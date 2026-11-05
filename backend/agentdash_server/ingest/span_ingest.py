"""Bildet OTel-Spans und -Logs auf Runs, Spans, Nachrichten und Logs ab.

Konventionen (vom SDK gesetzt, kompatibel zu den GenAI-Semantic-Conventions):

* ``agentdash.kind``: run | agent | tool | step | llm | message
* ``agentdash.agent``: Name des ausführenden Agenten
* ``agentdash.caller``: aufrufender Agent (bei Agent-Spans); fehlt = Start/Benutzer
* ``agentdash.input`` / ``agentdash.output``: Ein- und Ausgabe als Text
* ``agentdash.marker = "start"``: kurzer Kind-Span, der den Start des Eltern-Spans live meldet
* ``agentdash.message.*``: Nachricht zwischen Agenten (from, to, kind, content)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from ..core.identity import IdentityResolver
from ..core.levels import normalize_level
from ..core.store import Store, app_topics, row_dict
from ..db.models import Message, Span
from .otlp import OtelLog, OtelSpan

log = logging.getLogger(__name__)

GENAI_KIND = {
    "invoke_agent": "agent",
    "create_agent": "agent",
    "execute_tool": "tool",
    "chat": "llm",
    "text_completion": "llm",
    "generate_content": "llm",
    "embeddings": "llm",
}
VALID_KINDS = {"run", "agent", "tool", "step", "llm", "message"}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def span_kind(sp: OtelSpan) -> str:
    kind = sp.attrs.get("agentdash.kind")
    if kind in VALID_KINDS:
        return kind
    op = sp.attrs.get("gen_ai.operation.name")
    if op in GENAI_KIND:
        return GENAI_KIND[op]
    return "run" if sp.parent_id is None else "step"


def span_agent(sp: OtelSpan) -> str | None:
    return sp.attrs.get("agentdash.agent") or sp.attrs.get("gen_ai.agent.name")


def app_hint(resource: dict[str, Any]) -> str | None:
    hint = resource.get("agentdash.app") or resource.get("service.name")
    if hint and str(hint).startswith("unknown_service"):
        return None
    return hint


class SpanIngestor:
    def __init__(self, store: Store, resolver: IdentityResolver) -> None:
        self.store = store
        self.resolver = resolver

    async def _identity(self, resource: dict[str, Any], ip: str | None) -> tuple[int, str]:
        return await self.resolver.resolve(ip, app_hint(resource), source="otlp")

    async def _agent(self, app_id: int, name: str | None, attrs: dict[str, Any] | None = None) -> int | None:
        if not name:
            return None
        attrs = attrs or {}
        return await self.store.agent_id(
            app_id, name, model=attrs.get("gen_ai.request.model"), role=attrs.get("agentdash.agent.role")
        )

    # ------------------------------------------------------------------ Traces
    async def ingest_spans(self, spans: list[OtelSpan], client_ip: str | None) -> int:
        # Marker und Nachrichten zuerst (sie sind zeitlich früher), dann nach Startzeit
        spans = sorted(spans, key=lambda s: (s.start, 0 if s.attrs.get("agentdash.marker") else 1))
        count = 0
        for sp in spans:
            try:
                await self._ingest_span(sp, client_ip)
                count += 1
            except Exception:
                log.exception("Span %s konnte nicht verarbeitet werden", sp.span_id)
        return count

    async def _ingest_span(self, sp: OtelSpan, client_ip: str | None) -> None:
        if not sp.trace_id or not sp.span_id:
            return
        app_id, _default_agent = await self._identity(sp.resource, client_ip)
        run_id = sp.trace_id
        kind = span_kind(sp)
        title = sp.attrs.get("agentdash.run.title") if kind == "run" else None
        await self.store.ensure_run(run_id, app_id, started_at=sp.start, source="sdk", title=title or None)

        if sp.attrs.get("agentdash.marker") == "start":
            await self._ingest_start_marker(sp, app_id, run_id)
            return
        if kind == "message":
            await self._ingest_message(sp, app_id, run_id)
            return
        await self._ingest_full_span(sp, app_id, run_id, kind)

    async def _ingest_start_marker(self, sp: OtelSpan, app_id: int, run_id: str) -> None:
        target_id = sp.parent_id
        if not target_id:
            return
        a = sp.attrs
        target_kind = a.get("agentdash.target.kind", "step")
        agent_id = await self._agent(app_id, span_agent(sp), a)
        async with self.store.sm() as s:
            existing = await s.get(Span, target_id)
            if existing is not None:
                return
            span = Span(
                id=target_id,
                run_id=run_id,
                parent_id=a.get("agentdash.target.parent") or None,
                agent_id=agent_id,
                kind=target_kind,
                name=a.get("agentdash.target.name") or target_kind,
                started_at=sp.start,
                status="running",
                input=_text(a.get("agentdash.input")),
            )
            s.add(span)
            await s.commit()
            data = row_dict(span)
        self.store.bus.publish(app_topics(app_id, agent_id, run_id), "span", data)
        if target_kind == "agent":
            caller_id = await self._agent(app_id, a.get("agentdash.caller"))
            await self._add_message(
                app_id,
                run_id,
                target_id,
                caller_id,
                agent_id,
                "call",
                _text(a.get("agentdash.input")),
                sp.start,
            )
        if target_kind == "run" and a.get("agentdash.run.title"):
            await self.store.update_run(run_id, title=a.get("agentdash.run.title"))
        await self.store.update_run(run_id, activity=sp.start)

    async def _ingest_message(self, sp: OtelSpan, app_id: int, run_id: str) -> None:
        a = sp.attrs
        from_name = a.get("agentdash.message.from") or span_agent(sp)
        to_name = a.get("agentdash.message.to")
        from_id = await self._agent(app_id, from_name)
        to_id = await self._agent(app_id, to_name)
        await self._add_message(
            app_id,
            run_id,
            sp.parent_id,
            from_id,
            to_id,
            a.get("agentdash.message.kind", "message"),
            _text(a.get("agentdash.message.content")),
            sp.start,
            dedupe_kind=False,
            msg_span_id=sp.span_id,
        )
        await self.store.update_run(run_id, activity=sp.start)

    async def _add_message(
        self,
        app_id: int,
        run_id: str,
        span_id: str | None,
        from_id: int | None,
        to_id: int | None,
        kind: str,
        content: str | None,
        ts: float,
        *,
        dedupe_kind: bool = True,
        msg_span_id: str | None = None,
    ) -> None:
        async with self.store.sm() as s:
            ref = msg_span_id or span_id
            if ref is not None:
                q = select(Message.id).where(Message.span_id == ref)
                if dedupe_kind:
                    q = q.where(Message.kind == kind)
                if (await s.execute(q)).first() is not None:
                    return
            msg = Message(
                app_id=app_id,
                run_id=run_id,
                span_id=ref,
                from_agent_id=from_id,
                to_agent_id=to_id,
                kind=kind,
                content=content,
                ts=ts,
            )
            s.add(msg)
            await s.commit()
            data = row_dict(msg)
        data["parent_span_id"] = span_id if msg_span_id else None
        topics = app_topics(app_id, None, run_id)
        for agent_id in {from_id, to_id} - {None}:
            topics.append(f"agent:{agent_id}")
        self.store.bus.publish(topics, "message", data)

    async def _ingest_full_span(self, sp: OtelSpan, app_id: int, run_id: str, kind: str) -> None:
        a = sp.attrs
        agent_name = span_agent(sp)
        agent_id = await self._agent(app_id, agent_name, a)
        status = "error" if sp.status_code == 2 else "ok"
        status_message = sp.status_message
        error_events = [e for e in sp.events if e.name == "exception"]
        if error_events and not status_message:
            ev = error_events[0].attrs
            status_message = f"{ev.get('exception.type', 'Exception')}: {ev.get('exception.message', '')}"
        input_ = a.get("agentdash.input", a.get("gen_ai.input.messages", a.get("gen_ai.tool.call.arguments")))
        output = a.get("agentdash.output", a.get("gen_ai.output.messages", a.get("gen_ai.tool.call.result")))
        name = sp.name
        if kind == "tool":
            name = a.get("agentdash.tool.name") or a.get("gen_ai.tool.name") or sp.name
        attrs = {k: v for k, v in a.items() if not k.startswith("agentdash.") or k == "agentdash.caller"}

        async with self.store.sm() as s:
            span = await s.get(Span, sp.span_id)
            if span is not None and span.ended_at is not None:
                return  # Duplikat
            if span is None:
                span = Span(id=sp.span_id, run_id=run_id, started_at=sp.start)
                s.add(span)
            span.parent_id = sp.parent_id
            span.agent_id = agent_id
            span.kind = kind
            span.name = name
            span.started_at = sp.start
            span.ended_at = sp.end
            span.status = status
            span.status_message = status_message
            span.input = _text(input_) if input_ is not None else span.input
            span.output = _text(output)
            span.tokens_in = a.get("gen_ai.usage.input_tokens")
            span.tokens_out = a.get("gen_ai.usage.output_tokens")
            span.attributes = attrs or None
            await s.commit()
            data = row_dict(span)
        self.store.bus.publish(app_topics(app_id, agent_id, run_id), "span", data)

        if kind == "agent":
            caller_id = await self._agent(app_id, a.get("agentdash.caller"))
            await self._add_message(app_id, run_id, sp.span_id, caller_id, agent_id, "call", data["input"], sp.start)
            await self._add_message(
                app_id,
                run_id,
                sp.span_id,
                agent_id,
                caller_id,
                "return",
                data["output"] if status == "ok" else f"Fehler: {status_message}",
                sp.end or sp.start,
            )

        for ev in error_events:
            ev_a = ev.attrs
            text = f"{ev_a.get('exception.type', 'Exception')}: {ev_a.get('exception.message', '')}"
            if ev_a.get("exception.stacktrace"):
                text += "\n" + str(ev_a["exception.stacktrace"])
            self.store.add_log(
                app_id=app_id,
                agent_id=agent_id,
                run_id=run_id,
                span_id=sp.span_id,
                message=f"Fehler in {kind} '{name}': {text}",
                ts=ev.ts or sp.end or sp.start,
                level="error",
                source="sdk",
            )

        run_fields: dict[str, Any] = {}
        default_title = None
        if kind == "run":
            run_fields = {"title": a.get("agentdash.run.title") or sp.name, "ended_at": sp.end, "status": status}
        elif sp.parent_id is None:
            # Wurzel-Span ohne expliziten Run (z. B. andere OTel-Instrumentierung) beendet den Run
            run_fields = {"ended_at": sp.end, "status": status}
            default_title = sp.name
        await self.store.update_run(
            run_id,
            activity=sp.end or sp.start,
            errors=1 if status == "error" else 0,
            default_title=default_title,
            **run_fields,
        )

    # ------------------------------------------------------------------ Logs
    async def ingest_logs(self, records: list[OtelLog], client_ip: str | None) -> int:
        for rec in records:
            app_id, _ = await self._identity(rec.resource, client_ip)
            agent_id = await self._agent(app_id, rec.attrs.get("agentdash.agent"))
            level = normalize_level(rec.severity_text) or normalize_level(rec.severity_number or 9) or "info"
            attrs = {k: v for k, v in rec.attrs.items() if not k.startswith("agentdash.") and not k.startswith("otel")}
            self.store.add_log(
                app_id=app_id,
                agent_id=agent_id,
                run_id=rec.trace_id,
                span_id=rec.span_id,
                message=rec.body,
                ts=rec.ts or None,
                level=level,
                source="sdk",
                attributes=attrs or None,
            )
        return len(records)
