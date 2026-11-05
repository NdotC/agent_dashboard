"""Ordnet eingehende Daten (Proxy, OTLP) einer Anwendung und einem Standard-Agenten zu."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .store import Store

if TYPE_CHECKING:
    from ..ingest.docker_watcher import DockerWatcher


class IdentityResolver:
    def __init__(self, store: Store, watcher: DockerWatcher | None) -> None:
        self.store = store
        self.watcher = watcher

    async def resolve(self, ip: str | None, app_hint: str | None, *, source: str) -> tuple[int, str]:
        """Reihenfolge: Container per IP -> Hinweis (Header/Resource-Attribut) -> Host-IP."""
        if self.watcher is not None and ip:
            found = await self.watcher.resolve_ip(ip)
            if found is not None:
                return found
        if app_hint:
            return await self.store.ensure_app(app_hint, source=source), app_hint
        key = f"host-{ip or 'unbekannt'}"
        return await self.store.ensure_app(key, name=f"Host {ip or 'unbekannt'}", source=source), "agent"
