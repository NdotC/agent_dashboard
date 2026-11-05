"""Einstiegspunkt: baut den Zustand auf und startet UI/API, OTLP-Receiver und Ollama-Proxy."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, auth, data, ws
from .api.deps import require_auth
from .api.otlp import create_otlp_app
from .config import Settings, get_settings
from .core.auth import Auth
from .core.bus import Bus
from .core.identity import IdentityResolver
from .core.retention import RetentionTask
from .core.runtime_settings import RuntimeSettings
from .core.state import AppState
from .core.store import Store
from .db.session import create_engine, make_sessionmaker, run_migrations
from .ingest.conversations import ConversationTracker
from .ingest.docker_client import DockerClient
from .ingest.docker_watcher import DockerWatcher
from .ingest.llm_recorder import LlmRecorder
from .ingest.ollama_proxy import OllamaProxy
from .ingest.ollama_status import OllamaStatus
from .ingest.span_ingest import SpanIngestor

log = logging.getLogger("agentdash")


async def build_state(settings: Settings, docker_client: DockerClient | None = None) -> AppState:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(run_migrations, settings.db_path)
    engine = create_engine(settings.db_url)
    sm = make_sessionmaker(engine)
    bus = Bus()
    store = Store(sm, bus)
    runtime = RuntimeSettings(settings, sm)
    await runtime.load()
    watcher = None
    if settings.docker_enabled:
        watcher = DockerWatcher(settings, store, docker_client or DockerClient(settings.docker_host))
    resolver = IdentityResolver(store, watcher)
    recorder = LlmRecorder(store, resolver, runtime, ConversationTracker())
    return AppState(
        settings=settings,
        engine=engine,
        sm=sm,
        bus=bus,
        store=store,
        runtime=runtime,
        auth=Auth(settings.password, settings.secret_key, settings.data_dir, settings.session_hours),
        spans=SpanIngestor(store, resolver),
        proxy=OllamaProxy(settings.ollama_upstream, recorder, settings.ingest_key),
        ollama=OllamaStatus(settings.ollama_upstream, bus, settings.ollama_status_interval),
        watcher=watcher,
    )


def create_api_app(state: AppState) -> FastAPI:
    app = FastAPI(title="agentdash", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.agentdash = state

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "docker": bool(state.watcher and state.watcher.connected),
            "ollama": bool(state.ollama.state.get("reachable")),
        }

    app.include_router(auth.router)
    protected = [Depends(require_auth)]
    app.include_router(data.router, dependencies=protected)
    app.include_router(admin.router, dependencies=protected)
    app.include_router(ws.router)

    static_dir = state.settings.static_dir
    if static_dir and Path(static_dir).is_dir():
        static_dir = Path(static_dir)
        if (static_dir / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
        index = static_dir / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):  # noqa: ANN202
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, 404)
            candidate = (static_dir / path).resolve()
            if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index)

    return app


@contextlib.asynccontextmanager
async def running(state: AppState) -> AsyncIterator[None]:
    """Startet alle Hintergrundaufgaben und beendet sie sauber."""
    retention = RetentionTask(state.store, state.runtime)
    state.store.start()
    state.ollama.start()
    retention.start()
    if state.watcher:
        state.watcher.start()
    try:
        yield
    finally:
        if state.watcher:
            await state.watcher.stop()
        await retention.stop()
        await state.ollama.stop()
        await state.proxy.drain()
        await state.proxy.close()
        await state.store.stop()
        await state.engine.dispose()


async def serve(settings: Settings) -> None:
    state = await build_state(settings)
    servers = [
        uvicorn.Server(
            uvicorn.Config(
                create_api_app(state),
                host=settings.host,
                port=settings.port,
                log_level="info",
                proxy_headers=True,
                ws="auto",
            )
        ),
        uvicorn.Server(
            uvicorn.Config(create_otlp_app(state), host=settings.host, port=settings.otlp_port, log_level="warning")
        ),
        uvicorn.Server(
            uvicorn.Config(state.proxy.app, host=settings.host, port=settings.proxy_port, log_level="warning")
        ),
    ]
    for srv in servers:
        srv.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    log.info(
        "agentdash startet: UI/API :%s, OTLP :%s, Ollama-Proxy :%s -> %s",
        settings.port,
        settings.otlp_port,
        settings.proxy_port,
        settings.ollama_upstream,
    )
    async with running(state):
        tasks = [asyncio.create_task(srv.serve()) for srv in servers]
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        import signal

        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)
        waiter = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait([*tasks, waiter], return_when=asyncio.FIRST_COMPLETED)
        for srv in servers:
            srv.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)
        waiter.cancel()
        for t in done:
            if t is not waiter and t.exception():
                raise t.exception()  # type: ignore[misc]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(serve(get_settings()))


if __name__ == "__main__":
    main()
