import json

import httpx
from sqlalchemy import select

from agentdash_server.db.models import Agent, Application, LlmCall, LogEntry, Run, ToolInvocation

from .conftest import proxy_client, settle

TOOLS = [{"type": "function", "function": {"name": "get_weather", "parameters": {"properties": {"city": {}}}}}]


async def _all(state, model):
    async with state.sm() as s:
        return list((await s.execute(select(model))).scalars())


async def test_chat_stream_with_tool_roundtrip(state):
    async with proxy_client(state) as c:
        msgs = [{"role": "system", "content": "Wetter-Agent. Hilft."}, {"role": "user", "content": "Berlin"}]
        r = await c.post(
            "/api/chat",
            json={"model": "llama3.2:3b", "messages": msgs, "tools": TOOLS, "think": True},
            headers={"X-Agent-Name": "wetter", "X-Agent-App": "demo"},
        )
        assert r.status_code == 200
        lines = [json.loads(line) for line in r.text.splitlines()]
        tool_calls = next(x["message"]["tool_calls"] for x in lines if x["message"].get("tool_calls"))
        await settle(state)

        # Agent schickt Tool-Ergebnis zurück (so wie es ollama-python macht)
        msgs2 = msgs + [
            {"role": "assistant", "content": "", "tool_calls": tool_calls},
            {"role": "tool", "content": "12 Grad, sonnig", "tool_name": "get_weather"},
        ]
        r2 = await c.post(
            "/api/chat",
            json={"model": "llama3.2:3b", "messages": msgs2, "stream": False},
            headers={"X-Agent-Name": "wetter", "X-Agent-App": "demo"},
        )
        assert r2.status_code == 200 and "12 Grad" in r2.json()["message"]["content"]
    await settle(state)

    apps = await _all(state, Application)
    assert [a.key for a in apps] == ["demo"]
    agents = await _all(state, Agent)
    assert [(a.name, a.model) for a in agents] == [("wetter", "llama3.2:3b")]
    calls = sorted(await _all(state, LlmCall), key=lambda c: c.started_at)
    assert len(calls) == 2
    first, second = calls
    assert first.thinking and first.tool_calls[0]["name"] == "get_weather"
    assert first.tokens_in and first.tokens_out
    assert second.run_id == first.run_id and second.parent_call_id == first.id
    tools = await _all(state, ToolInvocation)
    assert len(tools) == 1
    assert tools[0].arguments == {"city": "Berlin"}
    assert tools[0].result == "12 Grad, sonnig" and tools[0].result_llm_call_id == second.id
    runs = await _all(state, Run)
    assert len(runs) == 1 and runs[0].source == "auto" and runs[0].llm_calls == 2 and runs[0].title == "Berlin"
    logs = await _all(state, LogEntry)
    assert len(logs) == 2 and all(log.source == "proxy" for log in logs)


async def test_traceparent_assigns_run(state):
    trace = "4bf92f3577b34da6a3ce929d0e0e4736"
    async with proxy_client(state) as c:
        r = await c.post(
            "/api/chat",
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": False},
            headers={"traceparent": f"00-{trace}-00f067aa0ba902b7-01", "X-Agent-Name": "planner"},
        )
        assert r.status_code == 200
    await settle(state)
    calls = await _all(state, LlmCall)
    assert calls[0].run_id == trace and calls[0].parent_span_id == "00f067aa0ba902b7"
    runs = await _all(state, Run)
    assert runs[0].id == trace and runs[0].source == "sdk"
    # ohne Docker und ohne Header -> Host-Anwendung
    apps = await _all(state, Application)
    assert apps[0].key == "host-10.0.0.5"


async def test_openai_streaming(state):
    async with proxy_client(state) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "m", "stream": True, "tools": TOOLS, "messages": [{"role": "user", "content": "Paris"}]},
        )
        assert r.status_code == 200 and "data: [DONE]" in r.text
    await settle(state)
    call = (await _all(state, LlmCall))[0]
    assert call.endpoint == "openai_chat"
    assert call.tool_calls[0]["name"] == "get_weather" and call.tool_calls[0]["id"].startswith("call_")
    assert call.tokens_in is not None


async def test_upstream_error_and_unreachable(state):
    async with proxy_client(state) as c:
        r = await c.post(
            "/api/chat", json={"model": "m", "stream": False, "messages": [{"role": "user", "content": "FEHLER bitte"}]}
        )
        assert r.status_code == 500
    await state.proxy.client.aclose()
    state.proxy.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    )
    async with proxy_client(state) as c:
        r = await c.post("/api/chat", json={"model": "m", "messages": [{"role": "user", "content": "x"}]})
        assert r.status_code == 502 and "nicht erreichbar" in r.json()["error"]
    await settle(state)
    calls = sorted(await _all(state, LlmCall), key=lambda c: c.started_at)
    assert [c.status for c in calls] == ["error", "error"]
    assert "Simulierter Modellfehler" in calls[0].error
    logs = await _all(state, LogEntry)
    assert all(log.level == "error" for log in logs)


async def test_passthrough_not_recorded(state):
    async with proxy_client(state) as c:
        r = await c.get("/api/tags")
        assert r.status_code == 200 and r.json()["models"]
    await settle(state)
    assert await _all(state, LlmCall) == []


async def test_store_prompts_none(state):
    await state.runtime.update({"store_prompts": "none"})
    async with proxy_client(state) as c:
        await c.post(
            "/api/chat", json={"model": "m", "stream": False, "messages": [{"role": "user", "content": "geheim"}]}
        )
    await settle(state)
    call = (await _all(state, LlmCall))[0]
    assert "geheim" not in json.dumps(call.request) and "geheim" not in (call.response or "")
