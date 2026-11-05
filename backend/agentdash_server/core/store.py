"""Schreibschicht: Anwendungen, Agenten, Runs und Logs anlegen/aktualisieren und Live-Events auslösen."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.models import Agent, Application, LogEntry, Run
from .bus import Bus

log = logging.getLogger(__name__)


def row_dict(obj: Any) -> dict[str, Any]:
    """ORM-Objekt oder Core-Row in ein JSON-fähiges Dict umwandeln."""
    if hasattr(obj, "__table__"):
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    return dict(obj._mapping)


def app_topics(app_id: int, agent_id: int | None = None, run_id: str | None = None) -> list[str]:
    topics = [f"app:{app_id}"]
    if agent_id is not None:
        topics.append(f"agent:{agent_id}")
    if run_id is not None:
        topics.append(f"run:{run_id}")
    return topics


class Store:
    LOG_FLUSH_INTERVAL = 0.25
    LOG_BATCH_MAX = 1000

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], bus: Bus) -> None:
        self.sm = sessionmaker
        self.bus = bus
        self._app_ids: dict[str, int] = {}
        self._agent_ids: dict[tuple[int, str], int] = {}
        self._agent_touch: dict[int, float] = {}
        self._known_runs: set[str] = set()
        self._log_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50_000)
        self._flusher: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ Lifecycle
    def start(self) -> None:
        self._flusher = asyncio.create_task(self._flush_loop(), name="log-flusher")

    async def stop(self) -> None:
        if self._flusher:
            self._flusher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flusher
        await self.flush_logs()

    # ------------------------------------------------------------------ Anwendungen
    async def upsert_app(self, key: str, *, name: str | None = None, source: str = "docker", **fields: Any) -> int:
        now = time.time()
        async with self._lock, self.sm() as s:
            app = (await s.execute(select(Application).where(Application.key == key))).scalar_one_or_none()
            if app is None:
                app = Application(key=key, name=name or key, source=source, first_seen=now, last_seen=now, **fields)
                s.add(app)
            else:
                if name:
                    app.name = name
                app.last_seen = now
                for k, v in fields.items():
                    setattr(app, k, v)
            await s.commit()
            data = row_dict(app)
        self._app_ids[key] = data["id"]
        self.bus.publish(["overview", f"app:{data['id']}"], "app", data)
        return data["id"]

    async def app_id_for_key(self, key: str) -> int | None:
        if key in self._app_ids:
            return self._app_ids[key]
        async with self.sm() as s:
            app_id = (await s.execute(select(Application.id).where(Application.key == key))).scalar_one_or_none()
        if app_id is not None:
            self._app_ids[key] = app_id
        return app_id

    async def ensure_app(self, key: str, *, name: str | None = None, source: str) -> int:
        app_id = await self.app_id_for_key(key)
        if app_id is None:
            app_id = await self.upsert_app(key, name=name, source=source, status="active")
        return app_id

    async def set_app_fields(self, app_id: int, **fields: Any) -> None:
        """Stilles Update ohne Live-Event (z. B. interne Lesemarken)."""
        async with self.sm() as s:
            await s.execute(update(Application).where(Application.id == app_id).values(**fields))
            await s.commit()

    async def get_app(self, app_id: int) -> dict[str, Any] | None:
        async with self.sm() as s:
            app = await s.get(Application, app_id)
            return row_dict(app) if app else None

    # ------------------------------------------------------------------ Agenten
    async def agent_id(self, app_id: int, name: str, *, model: str | None = None, role: str | None = None) -> int:
        key = (app_id, name)
        now = time.time()
        agent_id = self._agent_ids.get(key)
        if agent_id is not None:
            if now - self._agent_touch.get(agent_id, 0) > 10 or model:
                self._agent_touch[agent_id] = now
                values: dict[str, Any] = {"last_seen": now}
                if model:
                    values["model"] = model
                if role:
                    values["role"] = role
                async with self.sm() as s:
                    await s.execute(update(Agent).where(Agent.id == agent_id).values(**values))
                    await s.commit()
            return agent_id
        async with self._lock, self.sm() as s:
            stmt = (
                sqlite_insert(Agent)
                .values(app_id=app_id, name=name, model=model, role=role, first_seen=now, last_seen=now)
                .on_conflict_do_nothing(index_elements=["app_id", "name"])
            )
            res = await s.execute(stmt)
            created = res.rowcount == 1
            agent = (await s.execute(select(Agent).where(Agent.app_id == app_id, Agent.name == name))).scalar_one()
            if not created:
                agent.last_seen = now
                if model:
                    agent.model = model
                if role:
                    agent.role = role
            await s.commit()
            data = row_dict(agent)
        self._agent_ids[key] = data["id"]
        self._agent_touch[data["id"]] = now
        if created:
            self.bus.publish(["overview", f"app:{app_id}"], "agent", data)
        return data["id"]

    # ------------------------------------------------------------------ Runs
    async def ensure_run(
        self, run_id: str, app_id: int, *, started_at: float, source: str = "sdk", title: str | None = None
    ) -> bool:
        """Legt den Run an, falls er noch nicht existiert. Gibt True zurück, wenn er neu ist."""
        if run_id in self._known_runs:
            return False
        async with self.sm() as s:
            stmt = (
                sqlite_insert(Run)
                .values(
                    id=run_id,
                    app_id=app_id,
                    title=title,
                    source=source,
                    status="running",
                    started_at=started_at,
                    last_activity=started_at,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            res = await s.execute(stmt)
            await s.commit()
        self._known_runs.add(run_id)
        if len(self._known_runs) > 20_000:
            self._known_runs.clear()
        created = res.rowcount == 1
        if created:
            await self.publish_run(run_id)
        return created

    async def update_run(
        self,
        run_id: str,
        *,
        activity: float | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        llm_calls: int = 0,
        errors: int = 0,
        default_title: str | None = None,
        **fields: Any,
    ) -> None:
        """Atomares Update (Zähler werden in SQL addiert, damit parallele Aufrufe nichts verlieren)."""
        values: dict[str, Any] = {}
        if tokens_in:
            values["tokens_in"] = Run.tokens_in + tokens_in
        if tokens_out:
            values["tokens_out"] = Run.tokens_out + tokens_out
        if llm_calls:
            values["llm_calls"] = Run.llm_calls + llm_calls
        if errors:
            values["errors"] = Run.errors + errors
            values["status"] = case((Run.status == "ok", "error"), else_=Run.status)
        if activity is not None:
            values["last_activity"] = func.max(func.coalesce(Run.last_activity, activity), activity)
            values["started_at"] = func.min(Run.started_at, activity)
        if default_title:
            values["title"] = func.coalesce(Run.title, default_title)
        values.update({k: v for k, v in fields.items() if v is not None})
        async with self.sm() as s:
            if values:
                await s.execute(update(Run).where(Run.id == run_id).values(**values))
                await s.commit()
            run = await s.get(Run, run_id)
            if run is None:
                return
            data = row_dict(run)
        self.bus.publish(["overview", f"app:{data['app_id']}", f"run:{run_id}"], "run", data)

    async def publish_run(self, run_id: str) -> None:
        async with self.sm() as s:
            run = await s.get(Run, run_id)
            if run is None:
                return
            data = row_dict(run)
        self.bus.publish(["overview", f"app:{data['app_id']}", f"run:{run_id}"], "run", data)

    # ------------------------------------------------------------------ Logs
    def add_log(
        self,
        *,
        app_id: int,
        message: str,
        ts: float | None = None,
        level: str = "info",
        source: str,
        stream: str | None = None,
        agent_id: int | None = None,
        run_id: str | None = None,
        span_id: str | None = None,
        attributes: dict | None = None,
    ) -> None:
        entry = {
            "ts": ts or time.time(),
            "app_id": app_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "span_id": span_id,
            "level": level,
            "source": source,
            "stream": stream,
            "message": message,
            "attributes": attributes,
        }
        try:
            self._log_queue.put_nowait(entry)
        except asyncio.QueueFull:
            log.warning("Log-Queue voll, Eintrag verworfen")

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.LOG_FLUSH_INTERVAL)
            try:
                await self.flush_logs()
            except Exception:  # pragma: no cover - darf den Loop nie beenden
                log.exception("Fehler beim Schreiben der Logs")

    async def flush_logs(self) -> int:
        total = 0
        while not self._log_queue.empty():
            batch: list[dict[str, Any]] = []
            while not self._log_queue.empty() and len(batch) < self.LOG_BATCH_MAX:
                batch.append(self._log_queue.get_nowait())
            async with self.sm() as s:
                stmt = sqlite_insert(LogEntry).returning(LogEntry.id, sort_by_parameter_order=True)
                ids = [r[0] for r in (await s.execute(stmt, batch)).all()]
                await s.commit()
            for entry, entry_id in zip(batch, ids, strict=True):
                entry["id"] = entry_id
                topics = ["logs", *app_topics(entry["app_id"], entry["agent_id"], entry["run_id"])]
                if entry["level"] == "error":
                    topics.append("overview")
                self.bus.publish(topics, "log", entry)
            total += len(batch)
        return total
