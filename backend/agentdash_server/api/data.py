"""Lesende REST-Endpunkte für das Frontend."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Integer, String, and_, case, cast, func, or_, select, text, union
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.state import AppState
from ..core.store import row_dict
from ..db.models import Agent, Application, LlmCall, LogEntry, Message, Run, Span, ToolInvocation
from .deps import effective_run, get_state

router = APIRouter(prefix="/api", tags=["data"])

LLM_SUMMARY_COLS = [
    LlmCall.id,
    LlmCall.app_id,
    LlmCall.agent_id,
    LlmCall.run_id,
    LlmCall.span_id,
    LlmCall.parent_span_id,
    LlmCall.parent_call_id,
    LlmCall.endpoint,
    LlmCall.model,
    LlmCall.tokens_in,
    LlmCall.tokens_out,
    LlmCall.duration_ms,
    LlmCall.started_at,
    LlmCall.status,
    LlmCall.error,
    LlmCall.tool_calls,
    LlmCall.response,
    LlmCall.request,
]


def _preview(text_: str | None, n: int = 200) -> str | None:
    if not text_:
        return text_
    t = " ".join(text_.split())
    return t[:n] + ("…" if len(t) > n else "")


def llm_summary(row: dict[str, Any]) -> dict[str, Any]:
    req = row.pop("request", None) or {}
    msgs = req.get("messages") or []
    last_user = next((m for m in reversed(msgs) if isinstance(m, dict) and m.get("role") == "user"), None)
    prompt = (last_user or {}).get("content") if last_user else req.get("prompt")
    row["prompt_preview"] = _preview(prompt if isinstance(prompt, str) else None)
    row["response_preview"] = _preview(row.pop("response", None))
    return row


async def _rows(s: AsyncSession, stmt: Any) -> list[dict[str, Any]]:
    out = []
    for r in (await s.execute(stmt)).all():
        if len(r) == 1 and hasattr(r[0], "__table__"):
            out.append(row_dict(r[0]))
        else:
            out.append(dict(r._mapping))
    return out


def fts_query(q: str) -> str:
    terms = [t for t in q.split() if t]
    return " ".join('"' + t.replace('"', '""') + '"*' for t in terms)


# ---------------------------------------------------------------------- Übersicht / Anwendungen


async def app_summaries(s: AsyncSession, now: float) -> list[dict[str, Any]]:
    day = now - 86400
    apps = [row_dict(a) for a in (await s.execute(select(Application).order_by(Application.name))).scalars()]
    agents = defaultdict(list)
    for a in (await s.execute(select(Agent).order_by(Agent.name))).scalars():
        agents[a.app_id].append(row_dict(a))
    llm = {
        r["app_id"]: r
        for r in await _rows(
            s,
            select(
                LlmCall.app_id,
                func.count().label("llm_calls_24h"),
                func.coalesce(func.sum(LlmCall.tokens_in), 0).label("tokens_in_24h"),
                func.coalesce(func.sum(LlmCall.tokens_out), 0).label("tokens_out_24h"),
                func.max(LlmCall.started_at).label("last_llm"),
            )
            .where(LlmCall.started_at >= day)
            .group_by(LlmCall.app_id),
        )
    }
    errors = {
        r["app_id"]: r["n"]
        for r in await _rows(
            s,
            select(LogEntry.app_id, func.count().label("n"))
            .where(LogEntry.level == "error", LogEntry.ts >= day)
            .group_by(LogEntry.app_id),
        )
    }
    runs = {
        r["app_id"]: r
        for r in await _rows(
            s,
            select(
                Run.app_id,
                func.max(Run.last_activity).label("last_run_activity"),
                func.count().label("runs_24h"),
            )
            .where(Run.started_at >= day)
            .group_by(Run.app_id),
        )
    }
    active = defaultdict(int)
    for r in await _rows(s, select(Run).where(Run.status == "running")):
        if effective_run(r, now)["status"] == "running":
            active[r["app_id"]] += 1
    last_lines = {}
    for app in apps:
        line = (
            await s.execute(
                select(LogEntry.message, LogEntry.level, LogEntry.ts)
                .where(LogEntry.app_id == app["id"])
                .order_by(LogEntry.ts.desc())
                .limit(1)
            )
        ).first()
        if line:
            last_lines[app["id"]] = dict(line._mapping)
    out = []
    for app in apps:
        l_ = llm.get(app["id"], {})
        r_ = runs.get(app["id"], {})
        last_log = last_lines.get(app["id"])
        activity = max(
            [x for x in (l_.get("last_llm"), r_.get("last_run_activity"), (last_log or {}).get("ts")) if x] or [0]
        )
        out.append(
            {
                **app,
                "agents": agents.get(app["id"], []),
                "llm_calls_24h": l_.get("llm_calls_24h", 0),
                "tokens_in_24h": l_.get("tokens_in_24h", 0),
                "tokens_out_24h": l_.get("tokens_out_24h", 0),
                "errors_24h": errors.get(app["id"], 0),
                "runs_24h": r_.get("runs_24h", 0),
                "active_runs": active.get(app["id"], 0),
                "last_activity": activity or None,
                "last_log": last_log,
            }
        )
    return out


@router.get("/overview")
async def overview(state: AppState = Depends(get_state)) -> dict[str, Any]:
    now = time.time()
    start = now - 24 * 3600
    async with state.sm() as s:
        apps = await app_summaries(s, now)
        llm_hours = await _rows(
            s,
            select(
                cast((LlmCall.started_at - start) / 3600, Integer).label("h"),
                func.count().label("calls"),
                func.sum(case((LlmCall.status == "error", 1), else_=0)).label("errors"),
                func.coalesce(func.sum(LlmCall.tokens_in), 0).label("tokens_in"),
                func.coalesce(func.sum(LlmCall.tokens_out), 0).label("tokens_out"),
            )
            .where(LlmCall.started_at >= start)
            .group_by(text("h")),
        )
        err_hours = await _rows(
            s,
            select(
                cast((LogEntry.ts - start) / 3600, Integer).label("h"),
                func.count().label("n"),
            )
            .where(LogEntry.ts >= start, LogEntry.level == "error")
            .group_by(text("h")),
        )
    hours = []
    by_h = {r["h"]: r for r in llm_hours}
    err_by_h = {r["h"]: r["n"] for r in err_hours}
    for h in range(24):
        r = by_h.get(h, {})
        hours.append(
            {
                "ts": start + h * 3600,
                "llm_calls": r.get("calls", 0),
                "tokens": (r.get("tokens_in") or 0) + (r.get("tokens_out") or 0),
                "errors": err_by_h.get(h, 0),
            }
        )
    kpis = {
        "apps_total": len(apps),
        "apps_running": sum(1 for a in apps if a["status"] in ("running", "active")),
        "agents_total": sum(len(a["agents"]) for a in apps),
        "active_runs": sum(a["active_runs"] for a in apps),
        "llm_calls_24h": sum(a["llm_calls_24h"] for a in apps),
        "tokens_24h": sum(a["tokens_in_24h"] + a["tokens_out_24h"] for a in apps),
        "errors_24h": sum(a["errors_24h"] for a in apps),
    }
    return {
        "apps": apps,
        "kpis": kpis,
        "hours": hours,
        "ollama": state.ollama.state,
        "docker_connected": bool(state.watcher and state.watcher.connected),
        "now": now,
    }


@router.get("/apps")
async def list_apps(state: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    async with state.sm() as s:
        return await app_summaries(s, time.time())


@router.get("/apps/{app_id}")
async def get_app(app_id: int, state: AppState = Depends(get_state)) -> dict[str, Any]:
    now = time.time()
    async with state.sm() as s:
        summaries = [a for a in await app_summaries(s, now) if a["id"] == app_id]
        if not summaries:
            raise HTTPException(404, "Anwendung nicht gefunden")
        app = summaries[0]
        stats = {
            r["agent_id"]: r
            for r in await _rows(
                s,
                select(
                    LlmCall.agent_id,
                    func.count().label("llm_calls_24h"),
                    func.coalesce(
                        func.sum(func.coalesce(LlmCall.tokens_in, 0) + func.coalesce(LlmCall.tokens_out, 0)),
                        0,
                    ).label("tokens_24h"),
                    func.avg(LlmCall.duration_ms).label("avg_ms_24h"),
                    func.sum(case((LlmCall.status == "error", 1), else_=0)).label("llm_errors_24h"),
                )
                .where(LlmCall.app_id == app_id, LlmCall.started_at >= now - 86400)
                .group_by(LlmCall.agent_id),
            )
        }
    app["agents"] = [
        {**a, **{k: v for k, v in stats.get(a["id"], {}).items() if k != "agent_id"}} for a in app["agents"]
    ]
    return app


@router.delete("/apps/{app_id}")
async def delete_app(app_id: int, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Entfernt eine Anwendung mit allen Daten (z. B. veraltete Einträge). Läuft der Container noch,
    taucht er beim nächsten Abgleich wieder auf."""
    async with state.sm() as s:
        app = await s.get(Application, app_id)
        if app is None:
            raise HTTPException(404, "Anwendung nicht gefunden")
        key = app.key
        await s.delete(app)
        await s.commit()
    state.store.forget_app(key)
    if state.watcher is not None:
        state.watcher.forget_app(app_id)
    state.bus.publish(["overview"], "app_deleted", {"id": app_id})
    return {"ok": True}


async def _agent_names(s: AsyncSession, app_ids: set[int] | None = None) -> dict[int, dict[str, Any]]:
    q = select(Agent)
    if app_ids:
        q = q.where(Agent.app_id.in_(app_ids))
    return {a.id: row_dict(a) for a in (await s.execute(q)).scalars()}


def build_graph(
    agents: dict[int, dict[str, Any]],
    messages: list[dict[str, Any]],
    llm_counts: dict[int, int],
    include_agents: set[int],
) -> dict[str, Any]:
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    used: set[str] = set()

    def node_id(agent_id: int | None) -> str:
        return f"agent-{agent_id}" if agent_id is not None else "start"

    for m in messages:
        src, dst = node_id(m["from_agent_id"]), node_id(m["to_agent_id"])
        used.update((src, dst))
        e = edges.setdefault(
            (src, dst),
            {"id": f"{src}->{dst}", "source": src, "target": dst, "count": 0, "kinds": {}, "last_ts": 0},
        )
        e["count"] += 1
        e["kinds"][m["kind"]] = e["kinds"].get(m["kind"], 0) + 1
        e["last_ts"] = max(e["last_ts"], m["ts"])
    nodes = []
    if "start" in used:
        nodes.append({"id": "start", "kind": "start", "name": "Start", "agent_id": None})
    for agent_id in sorted(include_agents | {int(n.split("-")[1]) for n in used if n != "start"}):
        a = agents.get(agent_id)
        if not a:
            continue
        nodes.append(
            {
                "id": f"agent-{agent_id}",
                "kind": "agent",
                "agent_id": agent_id,
                "name": a.get("display_name") or a["name"],
                "color": a.get("color"),
                "model": a.get("model"),
                "llm_calls": llm_counts.get(agent_id, 0),
            }
        )
    return {"nodes": nodes, "edges": list(edges.values())}


@router.get("/apps/{app_id}/graph")
async def app_graph(app_id: int, days: float = 7, state: AppState = Depends(get_state)) -> dict[str, Any]:
    since = time.time() - days * 86400
    async with state.sm() as s:
        agents = await _agent_names(s, {app_id})
        msgs = await _rows(s, select(Message).where(Message.app_id == app_id, Message.ts >= since).order_by(Message.ts))
        llm_counts = {
            r["agent_id"]: r["n"]
            for r in await _rows(
                s,
                select(LlmCall.agent_id, func.count().label("n"))
                .where(LlmCall.app_id == app_id, LlmCall.started_at >= since)
                .group_by(LlmCall.agent_id),
            )
        }
    return build_graph(agents, msgs, llm_counts, set(agents))


# ---------------------------------------------------------------------- Agenten


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: int, state: AppState = Depends(get_state)) -> dict[str, Any]:
    now = time.time()
    start = now - 86400
    async with state.sm() as s:
        agent = await s.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(404, "Agent nicht gefunden")
        app = await s.get(Application, agent.app_id)
        totals = (
            await _rows(
                s,
                select(
                    func.count().label("llm_calls"),
                    func.coalesce(func.sum(LlmCall.tokens_in), 0).label("tokens_in"),
                    func.coalesce(func.sum(LlmCall.tokens_out), 0).label("tokens_out"),
                    func.avg(LlmCall.duration_ms).label("avg_ms"),
                    func.sum(case((LlmCall.status == "error", 1), else_=0)).label("errors"),
                ).where(LlmCall.agent_id == agent_id, LlmCall.started_at >= start),
            )
        )[0]
        hours_rows = await _rows(
            s,
            select(
                cast((LlmCall.started_at - start) / 3600, Integer).label("h"),
                func.count().label("calls"),
                func.avg(LlmCall.duration_ms).label("avg_ms"),
                func.coalesce(func.sum(LlmCall.tokens_out), 0).label("tokens_out"),
                func.sum(LlmCall.duration_ms).label("sum_ms"),
            )
            .where(LlmCall.agent_id == agent_id, LlmCall.started_at >= start)
            .group_by(text("h")),
        )
        tools = await _rows(
            s,
            select(ToolInvocation.name, func.count().label("n"))
            .where(ToolInvocation.agent_id == agent_id)
            .group_by(ToolInvocation.name)
            .order_by(func.count().desc())
            .limit(20),
        )
        peers = await _rows(
            s,
            select(Message.from_agent_id, Message.to_agent_id, func.count().label("n"))
            .where(or_(Message.from_agent_id == agent_id, Message.to_agent_id == agent_id))
            .group_by(Message.from_agent_id, Message.to_agent_id),
        )
    by_h = {r["h"]: r for r in hours_rows}
    hours = []
    for h in range(24):
        r = by_h.get(h, {})
        hours.append(
            {
                "ts": start + h * 3600,
                "llm_calls": r.get("calls", 0),
                "avg_ms": r.get("avg_ms"),
                "tokens_out": r.get("tokens_out", 0),
            }
        )
    return {
        **row_dict(agent),
        "app": row_dict(app) if app else None,
        "stats_24h": totals,
        "hours": hours,
        "tools": tools,
        "peers": peers,
    }


class AgentPatch(BaseModel):
    display_name: str | None = None
    color: str | None = None
    role: str | None = None


@router.patch("/agents/{agent_id}")
async def patch_agent(agent_id: int, body: AgentPatch, state: AppState = Depends(get_state)) -> dict[str, Any]:
    async with state.sm() as s:
        agent = await s.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(404, "Agent nicht gefunden")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(agent, k, v or None)
        await s.commit()
        data = row_dict(agent)
    state.bus.publish(["overview", f"app:{data['app_id']}", f"agent:{agent_id}"], "agent", data)
    return data


# ---------------------------------------------------------------------- Runs


async def _run_agents(s: AsyncSession, run_ids: list[str]) -> dict[str, list[int]]:
    if not run_ids:
        return {}
    q = union(
        select(Span.run_id, Span.agent_id).where(Span.run_id.in_(run_ids), Span.agent_id.is_not(None)),
        select(LlmCall.run_id, LlmCall.agent_id).where(LlmCall.run_id.in_(run_ids), LlmCall.agent_id.is_not(None)),
        select(Message.run_id, Message.to_agent_id).where(
            Message.run_id.in_(run_ids), Message.to_agent_id.is_not(None)
        ),
    )
    out: dict[str, list[int]] = defaultdict(list)
    for run_id, agent_id in (await s.execute(q)).all():
        if agent_id not in out[run_id]:
            out[run_id].append(agent_id)
    return out


@router.get("/runs")
async def list_runs(
    app_id: int | None = None,
    agent_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    before: float | None = None,
    limit: int = Query(50, le=500),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    now = time.time()
    async with state.sm() as s:
        stmt = select(Run).order_by(Run.started_at.desc()).limit(limit)
        if app_id is not None:
            stmt = stmt.where(Run.app_id == app_id)
        if agent_id is not None:
            sub = union(
                select(Span.run_id).where(Span.agent_id == agent_id),
                select(LlmCall.run_id).where(LlmCall.agent_id == agent_id),
                select(Message.run_id).where(or_(Message.to_agent_id == agent_id, Message.from_agent_id == agent_id)),
            )
            stmt = stmt.where(Run.id.in_(sub))
        if status == "error":
            stmt = stmt.where(or_(Run.status == "error", Run.errors > 0))
        elif status == "running":
            stmt = stmt.where(Run.status == "running")
        if q:
            stmt = stmt.where(Run.title.ilike(f"%{q}%"))
        if before is not None:
            stmt = stmt.where(Run.started_at < before)
        runs = [effective_run(row_dict(r), now) for r in (await s.execute(stmt)).scalars()]
        if status == "running":
            runs = [r for r in runs if r["status"] == "running"]
        involved = await _run_agents(s, [r["id"] for r in runs])
        app_ids = {r["app_id"] for r in runs}
        agents = await _agent_names(s, app_ids) if app_ids else {}
        apps = {a.id: a.name for a in (await s.execute(select(Application))).scalars()}
    for r in runs:
        r["agent_ids"] = involved.get(r["id"], [])
        r["app_name"] = apps.get(r["app_id"])
    return {"runs": runs, "agents": agents}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    async with state.sm() as s:
        run = await s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "Run nicht gefunden")
        run_d = effective_run(row_dict(run))
        app = await s.get(Application, run.app_id)
        spans = await _rows(s, select(Span).where(Span.run_id == run_id).order_by(Span.started_at))
        llm = await _rows(s, select(LlmCall).where(LlmCall.run_id == run_id).order_by(LlmCall.started_at))
        msgs = await _rows(s, select(Message).where(Message.run_id == run_id).order_by(Message.ts))
        tools = await _rows(
            s, select(ToolInvocation).where(ToolInvocation.run_id == run_id).order_by(ToolInvocation.ts)
        )
        logs = await _rows(
            s,
            select(LogEntry).where(LogEntry.run_id == run_id).order_by(LogEntry.ts, LogEntry.id).limit(5000),
        )
        agents = await _agent_names(s, {run.app_id})
    return {
        "run": run_d,
        "app": row_dict(app) if app else None,
        "spans": spans,
        "llm_calls": llm,
        "messages": msgs,
        "tools": tools,
        "logs": logs,
        "agents": agents,
    }


@router.get("/runs/{run_id}/graph")
async def run_graph(run_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    async with state.sm() as s:
        run = await s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "Run nicht gefunden")
        agents = await _agent_names(s, {run.app_id})
        msgs = await _rows(s, select(Message).where(Message.run_id == run_id).order_by(Message.ts))
        llm_counts = {
            r["agent_id"]: r["n"]
            for r in await _rows(
                s,
                select(LlmCall.agent_id, func.count().label("n"))
                .where(LlmCall.run_id == run_id)
                .group_by(LlmCall.agent_id),
            )
        }
        involved = set((await _run_agents(s, [run_id])).get(run_id, []))
    return build_graph(agents, msgs, llm_counts, involved)


# ---------------------------------------------------------------------- LLM-Aufrufe


@router.get("/llm-calls")
async def list_llm_calls(
    app_id: int | None = None,
    agent_id: int | None = None,
    run_id: str | None = None,
    status: str | None = None,
    before: float | None = None,
    limit: int = Query(50, le=500),
    state: AppState = Depends(get_state),
) -> list[dict[str, Any]]:
    stmt = select(*LLM_SUMMARY_COLS).order_by(LlmCall.started_at.desc()).limit(limit)
    if app_id is not None:
        stmt = stmt.where(LlmCall.app_id == app_id)
    if agent_id is not None:
        stmt = stmt.where(LlmCall.agent_id == agent_id)
    if run_id is not None:
        stmt = stmt.where(LlmCall.run_id == run_id)
    if status:
        stmt = stmt.where(LlmCall.status == status)
    if before is not None:
        stmt = stmt.where(LlmCall.started_at < before)
    async with state.sm() as s:
        return [llm_summary(r) for r in await _rows(s, stmt)]


@router.get("/llm-calls/{call_id}")
async def get_llm_call(call_id: int, state: AppState = Depends(get_state)) -> dict[str, Any]:
    async with state.sm() as s:
        call = await s.get(LlmCall, call_id)
        if call is None:
            raise HTTPException(404, "LLM-Aufruf nicht gefunden")
        tools = await _rows(
            s,
            select(ToolInvocation).where(
                or_(ToolInvocation.llm_call_id == call_id, ToolInvocation.result_llm_call_id == call_id)
            ),
        )
        return {**row_dict(call), "tool_invocations": tools}


# ---------------------------------------------------------------------- Logs & Suche


@router.get("/logs")
async def list_logs(
    app_id: int | None = None,
    agent_id: int | None = None,
    run_id: str | None = None,
    level: str | None = Query(None, description="Komma-getrennt: debug,info,warn,error"),
    source: str | None = Query(None, description="Komma-getrennt: docker,sdk,proxy"),
    q: str | None = None,
    since: float | None = None,
    until: float | None = None,
    before_ts: float | None = None,
    before_id: int | None = None,
    limit: int = Query(200, le=2000),
    state: AppState = Depends(get_state),
) -> list[dict[str, Any]]:
    stmt = select(LogEntry).order_by(LogEntry.ts.desc(), LogEntry.id.desc()).limit(limit)
    if app_id is not None:
        stmt = stmt.where(LogEntry.app_id == app_id)
    if agent_id is not None:
        stmt = stmt.where(LogEntry.agent_id == agent_id)
    if run_id is not None:
        stmt = stmt.where(LogEntry.run_id == run_id)
    if level:
        stmt = stmt.where(LogEntry.level.in_(level.split(",")))
    if source:
        stmt = stmt.where(LogEntry.source.in_(source.split(",")))
    if since is not None:
        stmt = stmt.where(LogEntry.ts >= since)
    if until is not None:
        stmt = stmt.where(LogEntry.ts <= until)
    if before_ts is not None:
        if before_id is not None:
            stmt = stmt.where(or_(LogEntry.ts < before_ts, and_(LogEntry.ts == before_ts, LogEntry.id < before_id)))
        else:
            stmt = stmt.where(LogEntry.ts < before_ts)
    if q and q.strip():
        stmt = stmt.where(
            LogEntry.id.in_(text("SELECT rowid FROM logs_fts WHERE logs_fts MATCH :fq").bindparams(fq=fts_query(q)))
        )
    async with state.sm() as s:
        return [row_dict(r) for r in (await s.execute(stmt)).scalars()]


@router.get("/search")
async def search(q: str, limit: int = Query(30, le=200), state: AppState = Depends(get_state)) -> dict[str, Any]:
    if not q.strip():
        return {"logs": [], "llm_calls": [], "messages": [], "runs": [], "tools": []}
    like = f"%{q}%"
    async with state.sm() as s:
        logs = [
            row_dict(r)
            for r in (
                await s.execute(
                    select(LogEntry)
                    .where(
                        LogEntry.id.in_(
                            text("SELECT rowid FROM logs_fts WHERE logs_fts MATCH :fq").bindparams(fq=fts_query(q))
                        )
                    )
                    .order_by(LogEntry.ts.desc())
                    .limit(limit)
                )
            ).scalars()
        ]
        llm = [
            llm_summary(r)
            for r in await _rows(
                s,
                select(*LLM_SUMMARY_COLS)
                .where(
                    or_(
                        LlmCall.response.ilike(like),
                        LlmCall.thinking.ilike(like),
                        cast(LlmCall.request, String).ilike(like),
                        cast(LlmCall.tool_calls, String).ilike(like),
                    )
                )
                .order_by(LlmCall.started_at.desc())
                .limit(limit),
            )
        ]
        msgs = await _rows(
            s, select(Message).where(Message.content.ilike(like)).order_by(Message.ts.desc()).limit(limit)
        )
        runs = [
            effective_run(row_dict(r))
            for r in (
                await s.execute(select(Run).where(Run.title.ilike(like)).order_by(Run.started_at.desc()).limit(limit))
            ).scalars()
        ]
        tools = await _rows(
            s,
            select(ToolInvocation)
            .where(
                or_(
                    ToolInvocation.name.ilike(like),
                    cast(ToolInvocation.arguments, String).ilike(like),
                    ToolInvocation.result.ilike(like),
                )
            )
            .order_by(ToolInvocation.ts.desc())
            .limit(limit),
        )
    return {"logs": logs, "llm_calls": llm, "messages": msgs, "runs": runs, "tools": tools}
