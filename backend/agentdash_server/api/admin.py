"""Einstellungen, Systeminfos, Ollama-Status."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from ..core.retention import apply_retention
from ..core.state import AppState
from ..db.models import Agent, Application, LlmCall, LogEntry, Message, Run
from .deps import get_state

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/settings")
async def get_settings(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return state.runtime.all()


@router.put("/settings")
async def put_settings(body: dict[str, Any], state: AppState = Depends(get_state)) -> dict[str, Any]:
    try:
        return await state.runtime.update(body)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/settings/retention/run")
async def run_retention(state: AppState = Depends(get_state)) -> dict[str, int]:
    return await apply_retention(state.store, state.runtime)


@router.get("/system")
async def system(state: AppState = Depends(get_state)) -> dict[str, Any]:
    s_ = state.settings
    counts: dict[str, int] = {}
    async with state.sm() as s:
        for name, model in (
            ("applications", Application),
            ("agents", Agent),
            ("runs", Run),
            ("llm_calls", LlmCall),
            ("messages", Message),
            ("logs", LogEntry),
        ):
            counts[name] = (await s.execute(select(func.count()).select_from(model))).scalar_one()
    db_size = 0
    for suffix in ("", "-wal", "-shm"):
        p = s_.db_path.with_name(s_.db_path.name + suffix)
        if p.exists():
            db_size += p.stat().st_size
    return {
        "version": "0.1.0",
        "time": time.time(),
        "ports": {"ui": s_.port, "otlp": s_.otlp_port, "proxy": s_.proxy_port},
        "ollama_upstream": s_.ollama_upstream,
        "docker": {
            "enabled": s_.docker_enabled,
            "host": s_.docker_host,
            "connected": bool(state.watcher and state.watcher.connected),
            "containers_seen": len(state.watcher.containers) if state.watcher else 0,
            "label": s_.docker_label,
            "auto_discover": s_.docker_auto_discover,
        },
        "auth_enabled": state.auth.enabled,
        "ingest_key_enabled": bool(s_.ingest_key),
        "db_path": str(s_.db_path),
        "db_size": db_size,
        "counts": counts,
    }


@router.get("/ollama")
async def ollama_status(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return state.ollama.state


@router.post("/ollama/refresh")
async def ollama_refresh(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return await state.ollama.poll()
