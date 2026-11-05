import asyncio

import httpx
import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentdash
from agentdash import agent, run, send_message, step, tool
from agentdash import _core

EXPORTER: InMemorySpanExporter


@pytest.fixture(autouse=True)
def sdk():
    global EXPORTER
    _core.shutdown()
    EXPORTER = InMemorySpanExporter()
    agentdash.init(app="testapp", span_processor=SimpleSpanProcessor(EXPORTER), capture_logging=False)
    yield
    _core.shutdown()


def spans():
    return [(s.name, dict(s.attributes or {}), s) for s in EXPORTER.get_finished_spans()]


def by_kind(kind):
    return [(n, a, s) for n, a, s in spans() if a.get("agentdash.kind") == kind and "agentdash.marker" not in a]


def test_run_with_nested_agents_tools_and_messages():
    @tool
    def search(query: str) -> str:
        return f"Ergebnisse für {query}"

    @agent("researcher")
    def research(topic: str) -> str:
        return search(topic)

    with run("Bericht erstellen") as r:
        with agent("planner", input="Thema KI") as p:
            facts = research("KI")
            send_message("writer", facts, kind="handoff")
            p.set_output("Plan fertig")
        r.set_output("ok")

    runs = by_kind("run")
    assert len(runs) == 1
    run_span = runs[0][2]
    trace_id = run_span.context.trace_id
    assert all(s.context.trace_id == trace_id for _, _, s in spans())
    assert run_span.parent is None and runs[0][1]["agentdash.run.title"] == "Bericht erstellen"

    agents = {a["agentdash.agent"]: (a, s) for _, a, s in by_kind("agent")}
    assert set(agents) == {"planner", "researcher"}
    assert "agentdash.caller" not in agents["planner"][0]
    assert agents["researcher"][0]["agentdash.caller"] == "planner"
    assert agents["researcher"][0]["agentdash.input"] == "KI"
    assert agents["researcher"][0]["agentdash.output"] == "Ergebnisse für KI"
    assert agents["planner"][0]["agentdash.output"] == "Plan fertig"

    tools = by_kind("tool")
    assert tools[0][1]["agentdash.tool.name"] == "search" and tools[0][1]["agentdash.agent"] == "researcher"
    assert tools[0][2].parent.span_id == agents["researcher"][1].context.span_id

    msgs = by_kind("message")
    assert msgs[0][1]["agentdash.message.from"] == "planner" and msgs[0][1]["agentdash.message.to"] == "writer"
    assert msgs[0][1]["agentdash.message.kind"] == "handoff"

    markers = [a for _, a, _ in spans() if a.get("agentdash.marker") == "start"]
    assert {m["agentdash.target.kind"] for m in markers} == {"run", "agent", "tool"}
    assert agentdash.current_agent() is None


def test_exception_marks_error():
    with pytest.raises(ValueError):
        with run("kaputt"):
            with agent("a"):
                raise ValueError("böse")
    a = by_kind("agent")[0][2]
    assert a.status.status_code.name == "ERROR" and "böse" in a.status.description
    assert any(e.name == "exception" for e in a.events)
    # äußerer Run ist fehlerhaft, trägt die Exception aber nicht noch einmal
    r = by_kind("run")[0][2]
    assert r.status.status_code.name == "ERROR" and not any(e.name == "exception" for e in r.events)


async def test_async_agents_keep_context():
    @agent("worker")
    async def work(n: int) -> int:
        await asyncio.sleep(0.01)
        assert agentdash.current_agent() == "worker"
        return n * 2

    async with run("parallel"):
        async with agent("boss"):
            results = await asyncio.gather(work(1), work(2))
    assert results == [2, 4]
    workers = [a for _, a, _ in by_kind("agent") if a["agentdash.agent"] == "worker"]
    assert len(workers) == 2 and all(w["agentdash.caller"] == "boss" for w in workers)


def test_httpx_requests_get_agent_and_trace_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with run("r"):
        with agent("caller"):
            with step("llm"):
                client.post("http://ollama/api/chat", json={})
    assert seen["x-agent-name"] == "caller" and seen["x-agent-app"] == "testapp"
    step_span = by_kind("step")[0][2]
    assert seen["traceparent"].split("-")[1] == format(step_span.context.trace_id, "032x")
    assert seen["traceparent"].split("-")[2] == format(step_span.context.span_id, "016x")
