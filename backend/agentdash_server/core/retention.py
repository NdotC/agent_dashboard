"""Löscht alte Daten gemäß den Aufbewahrungsfristen."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from sqlalchemy import delete

from ..db.models import LlmCall, LogEntry, Message, Run, ToolInvocation
from .runtime_settings import RuntimeSettings
from .store import Store

log = logging.getLogger(__name__)


async def apply_retention(store: Store, runtime: RuntimeSettings, now: float | None = None) -> dict[str, int]:
    now = now or time.time()
    log_cutoff = now - runtime.get("log_retention_days") * 86400
    run_cutoff = now - runtime.get("run_retention_days") * 86400
    async with store.sm() as s:
        logs = (await s.execute(delete(LogEntry).where(LogEntry.ts < log_cutoff))).rowcount
        runs = (await s.execute(delete(Run).where(Run.last_activity < run_cutoff))).rowcount
        # Einträge ohne Run (z. B. Embeddings) separat
        llm = (
            await s.execute(delete(LlmCall).where(LlmCall.run_id.is_(None), LlmCall.started_at < run_cutoff))
        ).rowcount
        tools = (
            await s.execute(
                delete(ToolInvocation).where(ToolInvocation.run_id.is_(None), ToolInvocation.ts < run_cutoff)
            )
        ).rowcount
        msgs = (await s.execute(delete(Message).where(Message.ts < run_cutoff))).rowcount
        await s.commit()
    result = {"logs": logs, "runs": runs, "llm_calls": llm, "tools": tools, "messages": msgs}
    if any(result.values()):
        log.info("Aufbewahrung angewendet: %s", result)
    return result


class RetentionTask:
    def __init__(self, store: Store, runtime: RuntimeSettings, interval: float = 3600) -> None:
        self.store = store
        self.runtime = runtime
        self.interval = interval
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="retention")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while True:
            try:
                await apply_retention(self.store, self.runtime)
            except Exception:
                log.exception("Aufbewahrungs-Job fehlgeschlagen")
            await asyncio.sleep(self.interval)
