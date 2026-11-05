"""Fragt regelmäßig den Zustand von Ollama ab (geladene und verfügbare Modelle)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

import httpx

from ..core.bus import Bus

log = logging.getLogger(__name__)


class OllamaStatus:
    def __init__(self, upstream: str, bus: Bus, interval: float = 10.0) -> None:
        self.upstream = upstream.rstrip("/")
        self.bus = bus
        self.interval = interval
        self.state: dict[str, Any] = {"reachable": False, "upstream": self.upstream, "checked_at": None}
        self._task: asyncio.Task | None = None
        self._client = httpx.AsyncClient(timeout=5.0)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="ollama-status")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._client.aclose()

    async def _loop(self) -> None:
        while True:
            await self.poll()
            await asyncio.sleep(self.interval)

    async def poll(self) -> dict[str, Any]:
        state: dict[str, Any] = {"upstream": self.upstream, "checked_at": time.time()}
        try:
            version, ps, tags = await asyncio.gather(
                self._client.get(f"{self.upstream}/api/version"),
                self._client.get(f"{self.upstream}/api/ps"),
                self._client.get(f"{self.upstream}/api/tags"),
            )
            state["reachable"] = True
            state["version"] = version.json().get("version") if version.status_code == 200 else None
            loaded = ps.json().get("models", []) if ps.status_code == 200 else []
            state["loaded"] = [
                {
                    "name": m.get("name"),
                    "size": m.get("size"),
                    "size_vram": m.get("size_vram"),
                    "expires_at": m.get("expires_at"),
                    "parameter_size": (m.get("details") or {}).get("parameter_size"),
                    "quantization": (m.get("details") or {}).get("quantization_level"),
                }
                for m in loaded
            ]
            available = tags.json().get("models", []) if tags.status_code == 200 else []
            state["available"] = [
                {
                    "name": m.get("name"),
                    "size": m.get("size"),
                    "parameter_size": (m.get("details") or {}).get("parameter_size"),
                    "family": (m.get("details") or {}).get("family"),
                }
                for m in available
            ]
            state["vram_used"] = sum(m.get("size_vram") or 0 for m in loaded)
        except Exception as exc:
            state["reachable"] = False
            state["error"] = f"{exc.__class__.__name__}: {exc}"
        changed = {k: v for k, v in state.items() if k != "checked_at"} != {
            k: v for k, v in self.state.items() if k != "checked_at"
        }
        self.state = state
        if changed:
            self.bus.publish(["overview"], "ollama", state)
        return state
