"""Speichert durch den Proxy gelaufene LLM-Aufrufe inkl. Tool-Entscheidungen und -Ergebnissen."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import update

from ..core.identity import IdentityResolver
from ..core.runtime_settings import RuntimeSettings
from ..core.store import Store, app_topics, row_dict
from ..core.tracecontext import parse_traceparent
from ..db.models import LlmCall, ToolInvocation
from .conversations import ConversationState, ConversationTracker, PendingTool, assign_tool_results
from .llm_parse import ParsedResponse, message_text, parse_response, request_messages, sanitize_request

log = logging.getLogger(__name__)


@dataclass
class ProxiedCall:
    path: str
    endpoint: str
    client_ip: str | None
    headers: dict[str, str]
    request: dict[str, Any]
    started_at: float
    duration_ms: float
    status_code: int
    body: bytes = b""
    streamed: bool = False
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _title_from(messages: list[dict[str, Any]]) -> str | None:
    for m in messages:
        if m.get("role") == "user":
            text = " ".join(message_text(m).split())
            if text:
                return text[:140] + ("…" if len(text) > 140 else "")
    return None


def _fmt_duration(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


class LlmRecorder:
    def __init__(
        self, store: Store, resolver: IdentityResolver, runtime: RuntimeSettings, tracker: ConversationTracker
    ) -> None:
        self.store = store
        self.resolver = resolver
        self.runtime = runtime
        self.tracker = tracker

    async def record(self, call: ProxiedCall) -> int:
        app_id, default_agent = await self.resolver.resolve(
            call.client_ip, call.headers.get("x-agent-app"), source="proxy"
        )
        model = call.request.get("model")
        agent_name = call.headers.get("x-agent-name") or default_agent
        agent_id = await self.store.agent_id(app_id, agent_name, model=model)

        parsed = parse_response(call.endpoint, call.body, call.streamed) if call.body else ParsedResponse()
        error = call.error or parsed.error
        if not error and call.status_code >= 400:
            error = f"HTTP {call.status_code}: {call.body[:500].decode('utf-8', 'replace')}"

        messages = request_messages(call.endpoint, call.request)
        is_chat = call.endpoint in ("chat", "openai_chat")
        is_embed = "embed" in call.endpoint
        continuation = self.tracker.match(app_id, messages) if is_chat else None

        trace = parse_traceparent(call.headers.get("traceparent"))
        parent_span_id = trace[1] if trace else None
        if trace:
            run_id: str | None = trace[0]
            await self.store.ensure_run(run_id, app_id, started_at=call.started_at, source="sdk")
        elif continuation is not None:
            run_id = continuation[0].run_id
        elif is_embed:
            run_id = None
        else:
            run_id = f"auto-{uuid.uuid4().hex[:20]}"
            await self.store.ensure_run(
                run_id, app_id, started_at=call.started_at, source="auto", title=_title_from(messages)
            )

        mode = self.runtime.get("store_prompts")
        max_chars = self.runtime.get("prompt_truncate_chars")
        stored_request = sanitize_request(call.request, mode, max_chars)
        if is_embed:
            stored_request = {k: v for k, v in stored_request.items() if k != "input"}
            inputs = call.request.get("input") or call.request.get("prompt")
            stored_request["input_count"] = len(inputs) if isinstance(inputs, list) else 1

        response_text = parsed.content
        thinking = parsed.thinking
        if mode == "none":
            response_text = f"<{len(response_text)} Zeichen>" if response_text else response_text
            thinking = f"<{len(thinking)} Zeichen>" if thinking else thinking
        elif mode == "truncate":
            if len(response_text) > max_chars:
                response_text = response_text[:max_chars] + " … [gekürzt]"
            if len(thinking) > max_chars:
                thinking = thinking[:max_chars] + " … [gekürzt]"

        tool_events: list[dict[str, Any]] = []
        async with self.store.sm() as s:
            llm = LlmCall(
                app_id=app_id,
                agent_id=agent_id,
                run_id=run_id,
                span_id=uuid.uuid4().hex[:16],
                parent_span_id=parent_span_id,
                parent_call_id=continuation[0].call_id if continuation else None,
                endpoint=call.endpoint,
                model=parsed.model or model,
                request=stored_request,
                response=response_text or None,
                thinking=thinking or None,
                tool_calls=parsed.tool_calls or None,
                tokens_in=parsed.tokens_in,
                tokens_out=parsed.tokens_out,
                duration_ms=round(call.duration_ms, 1),
                started_at=call.started_at,
                status="error" if error else "ok",
                error=error,
                client_ip=call.client_ip,
            )
            s.add(llm)
            await s.flush()

            # Tool-Ergebnisse, die in diesem Request an das Modell zurückgehen
            if continuation is not None:
                state, first_new = continuation
                for pending, result in assign_tool_results(state.pending_tools, messages[first_new:]):
                    await s.execute(
                        update(ToolInvocation)
                        .where(ToolInvocation.id == pending.invocation_id)
                        .values(result=result, result_ts=call.started_at, result_llm_call_id=llm.id)
                    )
                    tool_events.append(
                        {
                            "id": pending.invocation_id,
                            "result": result,
                            "result_ts": call.started_at,
                            "result_llm_call_id": llm.id,
                        }
                    )

            # Neue Tool-Entscheidungen des Modells
            pending_tools: list[PendingTool] = []
            for tc in parsed.tool_calls:
                inv = ToolInvocation(
                    app_id=app_id,
                    agent_id=agent_id,
                    run_id=run_id,
                    llm_call_id=llm.id,
                    call_ref=tc.get("id"),
                    name=tc["name"],
                    arguments=tc.get("arguments"),
                    ts=call.started_at + call.duration_ms / 1000,
                )
                s.add(inv)
                await s.flush()
                pending_tools.append(PendingTool(inv.id, inv.name, inv.call_ref))
                tool_events.append(row_dict(inv))
            await s.commit()
            llm_data = row_dict(llm)

        if is_chat and run_id is not None and not error:
            assistant = {"role": "assistant", "content": parsed.content, "tool_calls": parsed.tool_calls}
            self.tracker.remember(
                app_id,
                messages,
                assistant,
                ConversationState(llm_data["id"], run_id, app_id, agent_id, pending_tools),
            )

        if run_id is not None:
            await self.store.update_run(
                run_id,
                activity=call.started_at + call.duration_ms / 1000,
                tokens_in=parsed.tokens_in or 0,
                tokens_out=parsed.tokens_out or 0,
                llm_calls=1,
                errors=1 if error else 0,
            )

        topics = ["overview", *app_topics(app_id, agent_id, run_id)]
        self.store.bus.publish(topics, "llm_call", llm_data)
        for ev in tool_events:
            self.store.bus.publish(app_topics(app_id, agent_id, run_id), "tool", ev)

        tokens = ""
        if parsed.tokens_in is not None or parsed.tokens_out is not None:
            tokens = f", {parsed.tokens_in or 0}→{parsed.tokens_out or 0} Tokens"
        tools = f", Tools: {', '.join(t['name'] for t in parsed.tool_calls)}" if parsed.tool_calls else ""
        msg = (
            f"LLM-Aufruf {llm_data['model'] or '?'} ({call.endpoint}, {_fmt_duration(call.duration_ms)}{tokens}{tools})"
        )
        if error:
            msg += f" – Fehler: {error[:300]}"
        self.store.add_log(
            app_id=app_id,
            agent_id=agent_id,
            run_id=run_id,
            message=msg,
            ts=call.started_at,
            level="error" if error else "info",
            source="proxy",
            attributes={"llm_call_id": llm_data["id"]},
        )
        return llm_data["id"]
