"""Zur Laufzeit änderbare Einstellungen (in der DB, Standardwerte aus der Umgebung)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings
from ..db.models import Setting

EDITABLE: dict[str, type] = {
    "log_retention_days": int,
    "run_retention_days": int,
    "store_prompts": str,
    "prompt_truncate_chars": int,
}
STORE_PROMPT_MODES = ("full", "truncate", "none")


class RuntimeSettings:
    def __init__(self, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sm = sessionmaker
        self._values: dict[str, Any] = {k: getattr(settings, k) for k in EDITABLE}

    async def load(self) -> None:
        async with self.sm() as s:
            for row in (await s.execute(select(Setting))).scalars():
                if row.key in EDITABLE:
                    self._values[row.key] = row.value

    def get(self, key: str) -> Any:
        return self._values[key]

    def all(self) -> dict[str, Any]:
        return dict(self._values)

    async def update(self, values: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for k, v in values.items():
            if k not in EDITABLE:
                raise ValueError(f"Unbekannte Einstellung: {k}")
            v = EDITABLE[k](v)
            if k == "store_prompts" and v not in STORE_PROMPT_MODES:
                raise ValueError(f"store_prompts muss einer von {STORE_PROMPT_MODES} sein")
            if EDITABLE[k] is int and v < 1:
                raise ValueError(f"{k} muss >= 1 sein")
            clean[k] = v
        async with self.sm() as s:
            for k, v in clean.items():
                stmt = sqlite_insert(Setting).values(key=k, value=v)
                await s.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": v}))
            await s.commit()
        self._values.update(clean)
        return self.all()
