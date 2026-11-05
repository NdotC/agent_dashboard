"""Auswertung von Ollama-Requests und -Responses (native API und OpenAI-kompatibel)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Pfade, die aufgezeichnet werden. Alles andere wird nur durchgereicht.
CHAT_PATHS = {"/api/chat": "chat", "/v1/chat/completions": "openai_chat"}
GENERATE_PATHS = {"/api/generate": "generate", "/v1/completions": "openai_completion"}
EMBED_PATHS = {"/api/embed": "embed", "/api/embeddings": "embed", "/v1/embeddings": "openai_embed"}
RECORDED_PATHS = {**CHAT_PATHS, **GENERATE_PATHS, **EMBED_PATHS}


@dataclass
class ParsedResponse:
    content: str = ""
    thinking: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int | None = None
    tokens_out: int | None = None
    model: str | None = None
    done_reason: str | None = None
    error: str | None = None


def _parse_args(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def normalize_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
    fn = tc.get("function") or {}
    return {
        "id": tc.get("id"),
        "name": fn.get("name") or tc.get("name") or "?",
        "arguments": _parse_args(fn.get("arguments", tc.get("arguments"))),
    }


def _content_text(content: Any) -> str:
    """OpenAI erlaubt Content als Liste von Teilen."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text", ""))
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts)
    return str(content)


def _apply_ollama_obj(obj: dict[str, Any], res: ParsedResponse) -> None:
    if "error" in obj and obj["error"]:
        res.error = str(obj["error"])
    res.model = obj.get("model") or res.model
    msg = obj.get("message")
    if isinstance(msg, dict):
        res.content += msg.get("content") or ""
        res.thinking += msg.get("thinking") or ""
        for tc in msg.get("tool_calls") or []:
            res.tool_calls.append(normalize_tool_call(tc))
    if "response" in obj:
        res.content += obj.get("response") or ""
        res.thinking += obj.get("thinking") or ""
    if obj.get("done"):
        res.tokens_in = obj.get("prompt_eval_count", res.tokens_in)
        res.tokens_out = obj.get("eval_count", res.tokens_out)
        res.done_reason = obj.get("done_reason")


def parse_ollama(body: bytes) -> ParsedResponse:
    """Native API: einzelnes JSON oder NDJSON-Stream."""
    res = ParsedResponse()
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            _apply_ollama_obj(obj, res)
    return res


def _apply_openai_usage(obj: dict[str, Any], res: ParsedResponse) -> None:
    usage = obj.get("usage") or {}
    if usage:
        res.tokens_in = usage.get("prompt_tokens", res.tokens_in)
        res.tokens_out = usage.get("completion_tokens", res.tokens_out)


def parse_openai(body: bytes, streamed: bool) -> ParsedResponse:
    res = ParsedResponse()
    if not streamed:
        try:
            obj = json.loads(body or b"{}")
        except ValueError:
            return res
        if not isinstance(obj, dict):
            return res
        if obj.get("error"):
            err = obj["error"]
            res.error = err.get("message") if isinstance(err, dict) else str(err)
        res.model = obj.get("model")
        for choice in obj.get("choices") or []:
            msg = choice.get("message") or {}
            res.content += _content_text(msg.get("content")) or choice.get("text") or ""
            res.thinking += msg.get("reasoning") or msg.get("reasoning_content") or ""
            for tc in msg.get("tool_calls") or []:
                res.tool_calls.append(normalize_tool_call(tc))
            res.done_reason = choice.get("finish_reason") or res.done_reason
        _apply_openai_usage(obj, res)
        return res

    partial_tools: dict[int, dict[str, Any]] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            break
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        if obj.get("error"):
            err = obj["error"]
            res.error = err.get("message") if isinstance(err, dict) else str(err)
        res.model = obj.get("model") or res.model
        for choice in obj.get("choices") or []:
            delta = choice.get("delta") or {}
            res.content += _content_text(delta.get("content")) or choice.get("text") or ""
            res.thinking += delta.get("reasoning") or delta.get("reasoning_content") or ""
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", len(partial_tools))
                cur = partial_tools.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                cur["id"] = tc.get("id") or cur["id"]
                fn = tc.get("function") or {}
                cur["name"] += fn.get("name") or ""
                args = fn.get("arguments")
                if isinstance(args, str):
                    cur["arguments"] += args
                elif args is not None:
                    cur["arguments"] = args
            res.done_reason = choice.get("finish_reason") or res.done_reason
        _apply_openai_usage(obj, res)
    for _, tc in sorted(partial_tools.items()):
        res.tool_calls.append({"id": tc["id"], "name": tc["name"] or "?", "arguments": _parse_args(tc["arguments"])})
    return res


def parse_response(endpoint: str, body: bytes, streamed: bool) -> ParsedResponse:
    if endpoint.startswith("openai"):
        return parse_openai(body, streamed)
    return parse_ollama(body)


def is_streaming(endpoint: str, req: dict[str, Any]) -> bool:
    if endpoint.startswith("openai"):
        return bool(req.get("stream", False))
    if endpoint == "embed":
        return False
    # Native API streamt standardmäßig
    return req.get("stream", True) is not False


# ---------------------------------------------------------------------- Request-Aufbereitung


def request_messages(endpoint: str, req: dict[str, Any]) -> list[dict[str, Any]]:
    """Einheitliche Nachrichtenliste eines Requests (für Konversationserkennung und Anzeige)."""
    if endpoint in ("chat", "openai_chat"):
        return [m for m in req.get("messages") or [] if isinstance(m, dict)]
    if endpoint in ("generate", "openai_completion"):
        msgs = []
        if req.get("system"):
            msgs.append({"role": "system", "content": req["system"]})
        prompt = req.get("prompt")
        if isinstance(prompt, list):
            prompt = "\n".join(str(p) for p in prompt)
        msgs.append({"role": "user", "content": prompt or ""})
        return msgs
    return []


def message_text(msg: dict[str, Any]) -> str:
    return _content_text(msg.get("content"))


def sanitize_request(req: dict[str, Any], mode: str, max_chars: int) -> dict[str, Any]:
    """Bilder entfernen und je nach Einstellung Inhalte kürzen/weglassen."""

    def clip(text: str) -> str:
        if mode == "truncate" and len(text) > max_chars:
            return text[:max_chars] + f" … [{len(text) - max_chars} Zeichen gekürzt]"
        return text

    out: dict[str, Any] = {}
    for k, v in req.items():
        if k == "images" and isinstance(v, list):
            out[k] = [f"<Bild, {len(str(i))} Zeichen base64>" for i in v]
        elif k == "messages" and isinstance(v, list):
            msgs = []
            for m in v:
                if not isinstance(m, dict):
                    continue
                m2 = dict(m)
                if "images" in m2 and isinstance(m2["images"], list):
                    m2["images"] = [f"<Bild, {len(str(i))} Zeichen base64>" for i in m2["images"]]
                if isinstance(m2.get("content"), list):
                    m2["content"] = _content_text(m2["content"])
                if mode == "none":
                    m2["content"] = f"<{len(message_text(m))} Zeichen>"
                elif isinstance(m2.get("content"), str):
                    m2["content"] = clip(m2["content"])
                msgs.append(m2)
            out[k] = msgs
        elif k in ("prompt", "system", "input") and isinstance(v, str):
            out[k] = f"<{len(v)} Zeichen>" if mode == "none" else clip(v)
        elif k == "input" and isinstance(v, list):
            out[k] = f"<{len(v)} Eingaben>"
        elif k == "context":
            out[k] = f"<Kontext, {len(v) if isinstance(v, list) else 0} Tokens>"
        else:
            out[k] = v
    return out
