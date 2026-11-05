"""Gemeinsamer Anwendungszustand (eine Instanz pro Prozess)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ..config import Settings
from .auth import Auth
from .bus import Bus
from .runtime_settings import RuntimeSettings
from .store import Store

if TYPE_CHECKING:
    from ..ingest.docker_watcher import DockerWatcher
    from ..ingest.ollama_proxy import OllamaProxy
    from ..ingest.ollama_status import OllamaStatus
    from ..ingest.span_ingest import SpanIngestor


@dataclass
class AppState:
    settings: Settings
    engine: AsyncEngine
    sm: async_sessionmaker[AsyncSession]
    bus: Bus
    store: Store
    runtime: RuntimeSettings
    auth: Auth
    spans: SpanIngestor
    proxy: OllamaProxy
    ollama: OllamaStatus
    watcher: DockerWatcher | None
