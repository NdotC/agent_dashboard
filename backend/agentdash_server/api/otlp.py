"""OTLP/HTTP-Receiver (eigener Port, Standard 4318)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from ..core.state import AppState
from ..ingest.otlp import decode_body, parse_logs, parse_traces

log = logging.getLogger(__name__)


def _authorized(request: Request, state: AppState) -> bool:
    key = state.settings.ingest_key
    if not key:
        return True
    auth = request.headers.get("authorization", "")
    return request.headers.get("x-agentdash-key") == key or auth == f"Bearer {key}"


def _ok(content_type: str | None) -> Response:
    if content_type and "json" in content_type:
        return JSONResponse({"partialSuccess": {}})
    return Response(content=b"", media_type="application/x-protobuf")


def create_otlp_app(state: AppState) -> FastAPI:
    app = FastAPI(title="agentdash OTLP", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.agentdash = state

    @app.post("/v1/traces")
    async def traces(request: Request) -> Response:
        if not _authorized(request, state):
            return JSONResponse({"error": "unauthorized"}, 401)
        ctype = request.headers.get("content-type")
        try:
            data = decode_body(await request.body(), request.headers.get("content-encoding"))
            spans = parse_traces(data, ctype)
        except Exception as exc:
            log.warning("Ungültige OTLP-Traces: %s", exc)
            return JSONResponse({"error": f"Ungültige Daten: {exc}"}, 400)
        await state.spans.ingest_spans(spans, request.client.host if request.client else None)
        return _ok(ctype)

    @app.post("/v1/logs")
    async def logs(request: Request) -> Response:
        if not _authorized(request, state):
            return JSONResponse({"error": "unauthorized"}, 401)
        ctype = request.headers.get("content-type")
        try:
            data = decode_body(await request.body(), request.headers.get("content-encoding"))
            records = parse_logs(data, ctype)
        except Exception as exc:
            log.warning("Ungültige OTLP-Logs: %s", exc)
            return JSONResponse({"error": f"Ungültige Daten: {exc}"}, 400)
        await state.spans.ingest_logs(records, request.client.host if request.client else None)
        return _ok(ctype)

    @app.post("/v1/metrics")
    async def metrics() -> Response:
        # Metriken werden (noch) nicht ausgewertet, aber angenommen, damit Exporter nicht fehlschlagen.
        return Response(content=b"", media_type="application/x-protobuf")

    return app
