"""Beobachtet Docker-Container: Status, Logs und IP-Zuordnung (für Proxy/OTLP)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..core.levels import detect_level
from ..core.store import Store
from .docker_client import DockerClient, parse_docker_ts

log = logging.getLogger(__name__)

TRUE_VALUES = {"1", "true", "yes", "on"}
STATUS_EVENTS = {
    "start",
    "die",
    "stop",
    "kill",
    "restart",
    "pause",
    "unpause",
    "destroy",
    "rename",
    "create",
    "oom",
}


@dataclass
class ContainerInfo:
    id: str
    name: str
    labels: dict[str, str]
    ips: set[str] = field(default_factory=set)

    @property
    def app_key(self) -> str:
        return self.labels.get("agentdash.app") or self.name

    @property
    def display_name(self) -> str:
        return self.labels.get("agentdash.name") or self.app_key

    @property
    def default_agent(self) -> str:
        return self.labels.get("agentdash.agent") or self.app_key


def _container_from_list(c: dict[str, Any]) -> ContainerInfo:
    names = c.get("Names") or [c["Id"][:12]]
    networks = (c.get("NetworkSettings") or {}).get("Networks") or {}
    ips = {n.get("IPAddress") for n in networks.values() if n.get("IPAddress")}
    return ContainerInfo(id=c["Id"], name=names[0].lstrip("/"), labels=c.get("Labels") or {}, ips=ips)


class DockerWatcher:
    def __init__(self, settings: Settings, store: Store, client: DockerClient) -> None:
        self.settings = settings
        self.store = store
        self.client = client
        self.connected = False
        self.containers: dict[str, ContainerInfo] = {}
        self.ip_map: dict[str, str] = {}
        self.app_of_container: dict[str, int] = {}
        self._followers: dict[str, asyncio.Task] = {}
        self._last_log_ts: dict[int, float] = {}
        self._task: asyncio.Task | None = None
        self._last_refresh = 0.0
        self._refresh_lock = asyncio.Lock()

    # ------------------------------------------------------------------ Lifecycle
    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="docker-watcher")

    async def stop(self) -> None:
        tasks = [t for t in (self._task, *self._followers.values()) if t]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        await self._persist_log_ts()
        await self.client.close()

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self.client.ping()
                self.connected = True
                backoff = 1.0
                await self.refresh()
                async for ev in self.client.events():
                    await self._handle_event(ev)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.connected:
                    log.warning("Docker-Verbindung verloren: %s", exc)
                else:
                    log.debug("Docker nicht erreichbar: %s", exc)
                self.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    # ------------------------------------------------------------------ Container-Liste
    async def refresh(self) -> None:
        async with self._refresh_lock:
            self._last_refresh = time.time()
            listed = await self.client.list_containers(all_=True)
            current = {c["Id"]: _container_from_list(c) for c in listed}
            self.containers = current
            self.ip_map = {ip: cid for cid, info in current.items() for ip in info.ips}
            for cid, info in current.items():
                if await self._is_enabled(info):
                    await self.sync_container(cid)
            await self._persist_log_ts()

    async def _is_enabled(self, info: ContainerInfo) -> bool:
        if info.labels.get(self.settings.docker_label, "").lower() in TRUE_VALUES:
            return True
        # bereits bekannte (z. B. automatisch erkannte) Anwendung weiter beobachten
        return await self.store.app_id_for_key(info.app_key) is not None

    async def sync_container(self, container_id: str) -> int | None:
        data = await self.client.inspect(container_id)
        if data is None:
            return None
        info = self.containers.get(container_id)
        if info is None:
            networks = (data.get("NetworkSettings") or {}).get("Networks") or {}
            info = ContainerInfo(
                id=container_id,
                name=data.get("Name", container_id[:12]).lstrip("/"),
                labels=(data.get("Config") or {}).get("Labels") or {},
                ips={n.get("IPAddress") for n in networks.values() if n.get("IPAddress")},
            )
            self.containers[container_id] = info
            for ip in info.ips:
                self.ip_map[ip] = container_id
        state = data.get("State") or {}
        status = state.get("Status", "unknown")
        if state.get("Restarting"):
            status = "restarting"
        app_id = await self.store.upsert_app(
            info.app_key,
            name=info.display_name,
            source="docker",
            container_id=container_id,
            container_name=info.name,
            image=(data.get("Config") or {}).get("Image"),
            status=status,
            started_at=parse_docker_ts(state.get("StartedAt", "")),
            exit_code=state.get("ExitCode") if status != "running" else None,
            restart_count=data.get("RestartCount", 0),
            labels=info.labels,
        )
        self.app_of_container[container_id] = app_id
        if status == "running":
            self._ensure_follower(container_id, app_id, tty=bool((data.get("Config") or {}).get("Tty")))
        return app_id

    async def _handle_event(self, ev: dict[str, Any]) -> None:
        action = (ev.get("Action") or ev.get("status") or "").split(":")[0]
        cid = ev.get("id") or (ev.get("Actor") or {}).get("ID")
        if not cid or action not in STATUS_EVENTS:
            return
        if action == "destroy":
            app_id = self.app_of_container.pop(cid, None)
            info = self.containers.pop(cid, None)
            if info:
                for ip in info.ips:
                    self.ip_map.pop(ip, None)
            if app_id is not None and info is not None:
                await self.store.upsert_app(info.app_key, status="removed")
            return
        if action in ("start", "create"):
            # IP-Adressen ändern sich beim Start -> Liste neu laden
            await self.refresh()
            return
        info = self.containers.get(cid)
        if info and await self._is_enabled(info):
            await self.sync_container(cid)

    # ------------------------------------------------------------------ IP-Auflösung
    async def resolve_ip(self, ip: str) -> tuple[int, str] | None:
        """IP eines Clients -> (app_id, Standard-Agentenname). Nimmt ggf. neue Container auf."""
        if not self.connected or not ip:
            return None
        cid = self.ip_map.get(ip)
        if cid is None and time.time() - self._last_refresh > 5:
            with contextlib.suppress(Exception):
                await self.refresh()
            cid = self.ip_map.get(ip)
        if cid is None:
            return None
        info = self.containers[cid]
        app_id = self.app_of_container.get(cid)
        if app_id is None:
            if not self.settings.docker_auto_discover:
                return None
            app_id = await self.sync_container(cid)
            if app_id is None:
                return None
        return app_id, info.default_agent

    # ------------------------------------------------------------------ Logs
    def _ensure_follower(self, cid: str, app_id: int, tty: bool) -> None:
        task = self._followers.get(cid)
        if task and not task.done():
            return
        self._followers[cid] = asyncio.create_task(self._follow(cid, app_id, tty), name=f"logs-{cid[:12]}")

    async def _follow(self, cid: str, app_id: int, tty: bool) -> None:
        app = await self.store.get_app(app_id)
        since = self._last_log_ts.get(app_id) or (app or {}).get("last_log_ts")
        last_persist = time.time()
        try:
            async for stream, ts, line in self.client.logs(
                cid, tty=tty, since=since, tail=None if since else self.settings.docker_log_tail
            ):
                if since is not None and ts is not None and ts <= since:
                    continue
                if not line.strip():
                    continue
                ts = ts or time.time()
                self._last_log_ts[app_id] = ts
                self.store.add_log(
                    app_id=app_id,
                    message=line,
                    ts=ts,
                    level=detect_level(line),
                    source="docker",
                    stream=stream,
                )
                if time.time() - last_persist > 5:
                    last_persist = time.time()
                    await self._persist_log_ts()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.info("Log-Stream für %s beendet: %s", cid[:12], exc)
        finally:
            self._followers.pop(cid, None)

    async def _persist_log_ts(self) -> None:
        for app_id, ts in list(self._last_log_ts.items()):
            app = await self.store.get_app(app_id)
            if app and (app.get("last_log_ts") or 0) < ts:
                await self.store.set_app_fields(app_id, last_log_ts=ts)
