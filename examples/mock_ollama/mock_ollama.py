"""Mock-Ollama-Server für Tests und Demos ohne GPU.

Imitiert die wichtigsten Endpunkte von Ollama (native API und OpenAI-kompatibel):
- Mit Tools und einer neuen Benutzernachricht antwortet er mit einem Tool-Aufruf.
- Nach einem Tool-Ergebnis antwortet er mit Text.
- Mit ``think: true`` liefert er zusätzlich einen "thinking"-Text.

Start: ``uvicorn mock_ollama:app --port 11434``
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from datetime import UTC, datetime

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

DELAY = float(os.environ.get("MOCK_OLLAMA_DELAY", "0.05"))
MODELS = ["llama3.2:3b", "qwen2.5:7b"]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def _decide(messages: list[dict], tools: list[dict] | None) -> dict:
    """Erzeugt eine plausible Antwort: Tool-Aufruf oder Text."""
    last = messages[-1] if messages else {"role": "user", "content": ""}
    system = next((_text(m.get("content")) for m in messages if m.get("role") == "system"), "")
    if tools and last.get("role") == "user":
        fn = tools[0].get("function", tools[0])
        params = (fn.get("parameters") or {}).get("properties") or {}
        args = {k: _text(last.get("content"))[:60] or "test" for k in params} or {"query": "test"}
        return {"content": "", "tool_calls": [{"function": {"name": fn.get("name", "tool"), "arguments": args}}]}
    if last.get("role") == "tool":
        return {"content": f"Auf Basis des Tool-Ergebnisses: {_text(last.get('content'))[:200]}"}
    if "FEHLER" in _text(last.get("content")):
        raise RuntimeError("Simulierter Modellfehler")
    prompt = _text(last.get("content"))
    role = system.split(".")[0] if system else "Assistent"
    return {"content": f"[{role}] Antwort auf: {prompt[:160]}"}


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def chat(request: Request):
    body = await request.json()
    model = body.get("model", MODELS[0])
    messages = body.get("messages", [])
    try:
        answer = _decide(messages, body.get("tools"))
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    thinking = "Ich überlege, wie ich die Aufgabe löse …" if body.get("think") else None
    prompt_tokens = sum(_tokens(_text(m.get("content"))) for m in messages)
    out_tokens = _tokens(answer["content"]) + 5 * len(answer.get("tool_calls", []))
    await asyncio.sleep(DELAY + random.random() * DELAY)
    final = {
        "model": model,
        "created_at": _now(),
        "done": True,
        "done_reason": "stop",
        "total_duration": 1_000_000,
        "prompt_eval_count": prompt_tokens,
        "eval_count": out_tokens,
    }
    if body.get("stream", True) is False:
        msg = {"role": "assistant", "content": answer["content"]}
        if thinking:
            msg["thinking"] = thinking
        if answer.get("tool_calls"):
            msg["tool_calls"] = answer["tool_calls"]
        return JSONResponse({**final, "message": msg})

    async def gen():
        if thinking:
            yield json.dumps({"model": model, "created_at": _now(), "done": False,
                              "message": {"role": "assistant", "content": "", "thinking": thinking}}) + "\n"
        if answer.get("tool_calls"):
            yield json.dumps({"model": model, "created_at": _now(), "done": False,
                              "message": {"role": "assistant", "content": "",
                                          "tool_calls": answer["tool_calls"]}}) + "\n"
        words = answer["content"].split(" ")
        for i, w in enumerate(words):
            await asyncio.sleep(DELAY / 5)
            yield json.dumps({"model": model, "created_at": _now(), "done": False,
                              "message": {"role": "assistant", "content": w + (" " if i < len(words) - 1 else "")}}) + "\n"
        yield json.dumps({**final, "message": {"role": "assistant", "content": ""}}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


async def generate(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    answer = f"Antwort auf: {prompt[:160]}"
    await asyncio.sleep(DELAY)
    final = {"model": body.get("model", MODELS[0]), "created_at": _now(), "done": True,
             "prompt_eval_count": _tokens(prompt), "eval_count": _tokens(answer)}
    if body.get("stream", True) is False:
        return JSONResponse({**final, "response": answer})

    async def gen():
        yield json.dumps({"model": final["model"], "created_at": _now(), "done": False, "response": answer}) + "\n"
        yield json.dumps({**final, "response": ""}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


async def openai_chat(request: Request):
    body = await request.json()
    model = body.get("model", MODELS[0])
    messages = body.get("messages", [])
    answer = _decide(messages, body.get("tools"))
    tool_calls = [
        {"id": f"call_{i}_{int(time.time() * 1000)}", "type": "function",
         "function": {"name": tc["function"]["name"], "arguments": json.dumps(tc["function"]["arguments"])}}
        for i, tc in enumerate(answer.get("tool_calls", []))
    ]
    usage = {"prompt_tokens": sum(_tokens(_text(m.get("content"))) for m in messages),
             "completion_tokens": _tokens(answer["content"])}
    await asyncio.sleep(DELAY)
    if not body.get("stream"):
        msg = {"role": "assistant", "content": answer["content"]}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return JSONResponse({"id": "chatcmpl-mock", "object": "chat.completion", "model": model,
                             "choices": [{"index": 0, "message": msg,
                                          "finish_reason": "tool_calls" if tool_calls else "stop"}],
                             "usage": usage})

    async def gen():
        base = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "model": model}
        for i, tc in enumerate(tool_calls):
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": i, "id": tc["id"], "type": "function", "function": {"name": tc["function"]["name"],
                                                                              "arguments": ""}}]}}]}) + "\n\n"
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": i, "function": {"arguments": tc["function"]["arguments"]}}]}}]}) + "\n\n"
        for w in answer["content"].split(" "):
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {"content": w + " "}}]}) + "\n\n"
        yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {},
                                     "finish_reason": "tool_calls" if tool_calls else "stop"}],
                                     "usage": usage}) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


async def embed(request: Request):
    body = await request.json()
    inputs = body.get("input") or body.get("prompt") or ""
    n = len(inputs) if isinstance(inputs, list) else 1
    return JSONResponse({"model": body.get("model"), "embeddings": [[0.1, 0.2, 0.3]] * n})


async def tags(_: Request):
    return JSONResponse({"models": [{"name": m, "model": m, "size": 2_000_000_000,
                                     "details": {"parameter_size": m.split(":")[1].upper(), "family": "mock"}}
                                    for m in MODELS]})


async def ps(_: Request):
    return JSONResponse({"models": [{"name": MODELS[0], "model": MODELS[0], "size": 2_400_000_000,
                                     "size_vram": 2_400_000_000, "expires_at": _now(),
                                     "details": {"parameter_size": "3.2B", "quantization_level": "Q4_K_M"}}]})


async def version(_: Request):
    return JSONResponse({"version": "0.0.0-mock"})


app = Starlette(routes=[
    Route("/api/chat", chat, methods=["POST"]),
    Route("/api/generate", generate, methods=["POST"]),
    Route("/api/embed", embed, methods=["POST"]),
    Route("/v1/chat/completions", openai_chat, methods=["POST"]),
    Route("/api/tags", tags),
    Route("/api/ps", ps),
    Route("/api/version", version),
    Route("/", lambda _: JSONResponse("Ollama is running (mock)")),
])
