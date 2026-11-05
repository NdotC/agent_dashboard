from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException, Request

from ..core.auth import COOKIE_NAME
from ..core.state import AppState

AUTO_RUN_IDLE = 60  # Sekunden ohne Aktivität, nach denen ein automatisch erkannter Run als beendet gilt
SDK_RUN_STALE = 1800  # SDK-Run ohne Abschluss und ohne Aktivität -> "abgebrochen"


def get_state(request: Request) -> AppState:
    return request.app.state.agentdash


def require_auth(request: Request) -> None:
    state: AppState = request.app.state.agentdash
    if not state.auth.verify(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(status_code=401, detail="Nicht angemeldet")


def effective_run(run: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """Ergänzt den aus Sicht der Anzeige gültigen Status."""
    now = now or time.time()
    status = run["status"]
    idle = now - (run.get("last_activity") or run["started_at"])
    if status == "running":
        if run.get("source") == "auto" and idle > AUTO_RUN_IDLE:
            status = "error" if run.get("errors") else "ok"
            run = {**run, "ended_at": run.get("ended_at") or run.get("last_activity")}
        elif run.get("source") != "auto" and idle > SDK_RUN_STALE:
            status = "stale"
    return {**run, "status": status}
