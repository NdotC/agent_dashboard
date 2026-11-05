"""Transparenter Ollama-Proxy: leitet alles weiter und zeichnet LLM-Aufrufe auf.

Grundsatz: Der Proxy darf Agenten nie blockieren. Fehler bei der Aufzeichnung werden nur geloggt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .llm_parse import RECORDED_PATHS, is_streaming
from .llm_recorder import LlmRecorder, ProxiedCall

log = logging.getLogger(__name__)

HOP_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "proxy-authorization",
    "proxy-authenticate",
    "accept-encoding",
    "content-encoding",
}
PRIVATE_HEADERS = {"x-agent-name", "x-agent-app", "x-agentdash-key"}


class OllamaProxy:
    def __init__(self, upstream: str, recorder: LlmRecorder, ingest_key: str | None = None) -> None:
        self.upstream = upstream.rstrip("/")
        self.recorder = recorder
        self.ingest_key = ingest_key
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0))
        self._tasks: set[asyncio.Task] = set()
        self.app = Starlette(
            routes=[Route("/{path:path}", self.handle, methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"])]
        )

    async def close(self) -> None:
        await self.client.aclose()

    def _schedule_record(self, call: ProxiedCall) -> None:
        async def _run() -> None:
            try:
                await self.recorder.record(call)
            except Exception:
                log.exception("Aufzeichnung eines LLM-Aufrufs fehlgeschlagen (%s)", call.path)

        task = asyncio.create_task(_run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wartet auf ausstehende Aufzeichnungen (für Tests und Shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def handle(self, request: Request) -> Response:
        if self.ingest_key:
            key = request.headers.get("x-agentdash-key")
            if key != self.ingest_key:
                return JSONResponse({"error": "agentdash: ungültiger oder fehlender X-Agentdash-Key"}, 401)

        path = "/" + request.path_params["path"]
        body = await request.body()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS | PRIVATE_HEADERS}
        headers["accept-encoding"] = "identity"
        url = self.upstream + path
        if request.url.query:
            url += "?" + request.url.query

        endpoint = RECORDED_PATHS.get(path) if request.method == "POST" else None
        req_json: dict = {}
        if endpoint:
            try:
                parsed = json.loads(body or b"{}")
                req_json = parsed if isinstance(parsed, dict) else {}
            except ValueError:
                endpoint = None

        started = time.time()
        t0 = time.perf_counter()
        client_ip = request.client.host if request.client else None
        info_headers = {k.lower(): v for k, v in request.headers.items()}

        try:
            upstream_req = self.client.build_request(request.method, url, headers=headers, content=body)
            upstream_resp = await self.client.send(upstream_req, stream=True)
        except httpx.HTTPError as exc:
            msg = f"Ollama nicht erreichbar ({self.upstream}): {exc.__class__.__name__}: {exc}"
            if endpoint:
                self._schedule_record(
                    ProxiedCall(
                        path,
                        endpoint,
                        client_ip,
                        info_headers,
                        req_json,
                        started,
                        (time.perf_counter() - t0) * 1000,
                        502,
                        error=msg,
                    )
                )
            return JSONResponse({"error": msg}, status_code=502)

        resp_headers = {k: v for k, v in upstream_resp.headers.items() if k.lower() not in HOP_HEADERS}

        if not endpoint:
            return StreamingResponse(
                upstream_resp.aiter_raw(),
                status_code=upstream_resp.status_code,
                headers=resp_headers,
                background=BackgroundTask(upstream_resp.aclose),
            )

        streamed = is_streaming(endpoint, req_json)
        chunks: list[bytes] = []

        async def relay() -> AsyncIterator[bytes]:
            error: str | None = None
            try:
                async for chunk in upstream_resp.aiter_raw():
                    chunks.append(chunk)
                    yield chunk
            except BaseException as exc:  # Abbruch durch Client oder Upstream
                error = f"Stream abgebrochen: {exc.__class__.__name__}"
                raise
            finally:
                await upstream_resp.aclose()
                self._schedule_record(
                    ProxiedCall(
                        path,
                        endpoint,
                        client_ip,
                        info_headers,
                        req_json,
                        started,
                        (time.perf_counter() - t0) * 1000,
                        upstream_resp.status_code,
                        body=b"".join(chunks),
                        streamed=streamed,
                        error=error,
                    )
                )

        return StreamingResponse(relay(), status_code=upstream_resp.status_code, headers=resp_headers)
