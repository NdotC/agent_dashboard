"""Ende-zu-Ende: SDK erzeugt Spans -> OTLP-Receiver -> Datenbank/API, kombiniert mit dem Ollama-Proxy."""

import json

import agentdash
import httpx
import pytest
from agentdash import _core
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select

from agentdash_server.api.otlp import create_otlp_app
from agentdash_server.db.models import LlmCall, LogEntry, Message, Run, Span

from .conftest import proxy_client, settle


@pytest.fixture
def exporter():
    _core.shutdown()
    exp = InMemorySpanExporter()
    agentdash.init(app="newsbot", span_processor=SimpleSpanProcessor(exp), capture_logging=False)
    yield exp
    _core.shutdown()


async def post_spans(state, spans, *, as_json=False):
    app = create_otlp_app(state)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("10.1.1.1", 5000)), base_url="http://otlp"
    ) as c:
        body = encode_spans(spans).SerializeToString()
        r = await c.post("/v1/traces", content=body, headers={"content-type": "application/x-protobuf"})
        assert r.status_code == 200, r.text


async def test_multi_agent_run_end_to_end(state, api, exporter):
    async with proxy_client(state) as llm:

        async def ask(prompt):
            r = await llm.post(
                "/api/chat",
                json={"model": "llama3.2:3b", "stream": False, "messages": [{"role": "user", "content": prompt}]},
            )
            return r.json()["message"]["content"]

        async with agentdash.run("Tagesbericht") as r:
            async with agentdash.agent("planner", input="Schreibe einen Bericht") as planner:
                plan = await ask("Plane den Bericht")
                async with agentdash.agent("writer", input=plan) as writer:
                    writer.set_output(await ask("Schreibe"))
                agentdash.send_message("reviewer", "Bitte prüfen", kind="handoff")
                planner.set_output("fertig")
            r.set_output("ok")

    spans = exporter.get_finished_spans()
    markers = [s for s in spans if (s.attributes or {}).get("agentdash.marker")]
    others = [s for s in spans if s not in markers]
    # Live-Fall nachstellen: erst die Start-Marker, dann die vollständigen Spans
    await post_spans(state, markers)
    async with state.sm() as s:
        running = (await s.execute(select(Span))).scalars().all()
    assert {sp.status for sp in running} == {"running"}
    await post_spans(state, others)
    await settle(state)

    trace_id = format(spans[0].context.trace_id, "032x")
    async with state.sm() as s:
        run = await s.get(Run, trace_id)
        db_spans = {sp.id: sp for sp in (await s.execute(select(Span))).scalars()}
        calls = (await s.execute(select(LlmCall).order_by(LlmCall.started_at))).scalars().all()
        msgs = (await s.execute(select(Message).order_by(Message.ts, Message.id))).scalars().all()
    assert run.title == "Tagesbericht" and run.status == "ok" and run.ended_at and run.llm_calls == 2
    assert {sp.kind for sp in db_spans.values()} == {"run", "agent"}
    assert all(sp.status == "ok" and sp.ended_at for sp in db_spans.values())
    # LLM-Aufrufe hängen am richtigen Agenten-Span
    agent_span = {sp.name: sp for sp in db_spans.values()}
    assert calls[0].run_id == trace_id and calls[0].parent_span_id == agent_span["agent planner"].id
    assert calls[1].parent_span_id == agent_span["agent writer"].id

    detail = (await api.get(f"/api/runs/{trace_id}")).json()
    names = {a["id"]: a["name"] for a in detail["agents"].values()}
    flow = [
        (names.get(m["from_agent_id"], "Start"), names.get(m["to_agent_id"], "Start"), m["kind"])
        for m in detail["messages"]
    ]
    assert flow == [
        ("Start", "planner", "call"),
        ("planner", "writer", "call"),
        ("writer", "planner", "return"),
        ("planner", "reviewer", "handoff"),
        ("planner", "Start", "return"),
    ]
    assert len(msgs) == 5
    graph = (await api.get(f"/api/runs/{trace_id}/graph")).json()
    edges = {(e["source"], e["target"]) for e in graph["edges"]}
    assert ("start", f"agent-{calls[0].agent_id}") in edges
    assert {n["name"] for n in graph["nodes"]} == {"Start", "planner", "writer", "reviewer"}

    runs = (await api.get("/api/runs")).json()
    assert runs["runs"][0]["id"] == trace_id and len(runs["runs"][0]["agent_ids"]) == 3


async def test_otlp_json_logs_and_errors(state, api):
    app = create_otlp_app(state)
    trace_id = "5b8efff798038103d269b633813fc60c"
    span_id = "eee19b7ec3c1b174"
    logs_body = {
        "resourceLogs": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "jsonapp"}}]},
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": "1700000000000000000",
                                "severityNumber": 17,
                                "severityText": "ERROR",
                                "body": {"stringValue": "Datenbank nicht erreichbar"},
                                "traceId": trace_id,
                                "spanId": span_id,
                                "attributes": [{"key": "agentdash.agent", "value": {"stringValue": "loader"}}],
                            }
                        ]
                    }
                ],
            }
        ]
    }
    span_body = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "jsonapp"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": "lade daten",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "status": {"code": 2, "message": "kaputt"},
                                "attributes": [
                                    {"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}},
                                    {"key": "gen_ai.agent.name", "value": {"stringValue": "loader"}},
                                ],
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": "1700000000500000000",
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "IOError"}},
                                            {"key": "exception.message", "value": {"stringValue": "timeout"}},
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://otlp") as c:
        r1 = await c.post("/v1/logs", content=json.dumps(logs_body), headers={"content-type": "application/json"})
        r2 = await c.post("/v1/traces", content=json.dumps(span_body), headers={"content-type": "application/json"})
        assert r1.status_code == r2.status_code == 200
        assert (
            await c.post("/v1/traces", content=b"\x00garbage", headers={"content-type": "application/x-protobuf"})
        ).status_code == 400
    await settle(state)
    async with state.sm() as s:
        logs = (await s.execute(select(LogEntry).order_by(LogEntry.ts))).scalars().all()
        run = await s.get(Run, trace_id)
    assert logs[0].level == "error" and logs[0].run_id == trace_id and logs[0].agent_id is not None
    assert any("IOError: timeout" in log.message for log in logs)
    assert run.status == "error" and run.errors == 1 and run.title == "lade daten"

    found = (await api.get("/api/search", params={"q": "Datenbank"})).json()
    assert len(found["logs"]) == 1
    page = (await api.get("/api/logs", params={"level": "error", "q": "erreich"})).json()
    assert len(page) == 1
