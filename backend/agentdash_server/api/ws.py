"""WebSocket für Live-Updates. Protokoll:

Client -> Server: {"op": "subscribe" | "unsubscribe", "topics": ["overview", "app:1", "run:<id>", ...]}
Server -> Client: {"type": "log" | "llm_call" | "span" | "message" | "tool" | "run" | "app" | "agent" | "ollama",
                   "topic": "...", "data": {...}}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.auth import COOKIE_NAME
from ..core.state import AppState

router = APIRouter()

TOPIC_RE = re.compile(r"^(overview|logs|app:\d+|agent:\d+|run:[\w-]{1,64})$")


@router.websocket("/api/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    state: AppState = ws.app.state.agentdash
    if not state.auth.verify(ws.cookies.get(COOKIE_NAME)):
        await ws.close(code=4401)
        return
    await ws.accept()
    sub = state.bus.subscribe()

    async def reader() -> None:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            topics = [t for t in msg.get("topics", []) if isinstance(t, str) and TOPIC_RE.match(t)]
            if msg.get("op") == "subscribe":
                for t in topics:
                    sub.add(t)
            elif msg.get("op") == "unsubscribe":
                for t in topics:
                    sub.remove(t)
            elif msg.get("op") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

    async def writer() -> None:
        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=25)
            except TimeoutError:
                await ws.send_text(json.dumps({"type": "ping"}))
                continue
            batch = [event]
            while not sub.queue.empty() and len(batch) < 500:
                batch.append(sub.queue.get_nowait())
            await ws.send_text(json.dumps({"type": "batch", "events": batch}, default=str))

    tasks = [asyncio.create_task(reader()), asyncio.create_task(writer())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(BaseException):
                await t
        sub.close()
