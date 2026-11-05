import time

import httpx
from starlette.testclient import TestClient

from agentdash_server.core.retention import apply_retention
from agentdash_server.main import build_state, create_api_app

from .conftest import make_settings, proxy_client, settle

TOOLS = [{"type": "function", "function": {"name": "lookup", "parameters": {"properties": {"q": {}}}}}]


async def seed(state):
    async with proxy_client(state) as c:
        for prompt in ("eins", "zwei"):
            await c.post(
                "/api/chat",
                json={"model": "m", "stream": False, "tools": TOOLS, "messages": [{"role": "user", "content": prompt}]},
                headers={"X-Agent-App": "suite", "X-Agent-Name": "helper"},
            )
    await settle(state)


async def test_overview_apps_agents_runs(state, api):
    await seed(state)
    ov = (await api.get("/api/overview")).json()
    assert ov["kpis"]["apps_total"] == 1 and ov["kpis"]["llm_calls_24h"] == 2
    assert sum(h["llm_calls"] for h in ov["hours"]) == 2 and len(ov["hours"]) == 24
    app = ov["apps"][0]
    assert app["name"] == "suite" and app["agents"][0]["name"] == "helper" and app["last_log"]

    detail = (await api.get(f"/api/apps/{app['id']}")).json()
    agent = detail["agents"][0]
    assert agent["llm_calls_24h"] == 2

    a = (await api.get(f"/api/agents/{agent['id']}")).json()
    assert a["stats_24h"]["llm_calls"] == 2 and a["tools"] == [{"name": "lookup", "n": 2}]
    patched = (
        await api.patch(f"/api/agents/{agent['id']}", json={"display_name": "Helferlein", "color": "#ff0000"})
    ).json()
    assert patched["display_name"] == "Helferlein"

    runs = (await api.get("/api/runs", params={"app_id": app["id"]})).json()["runs"]
    assert len(runs) == 2 and all(r["source"] == "auto" for r in runs)
    calls = (await api.get("/api/llm-calls", params={"agent_id": agent["id"]})).json()
    assert len(calls) == 2 and calls[0]["prompt_preview"] in ("eins", "zwei") and "request" not in calls[0]
    full = (await api.get(f"/api/llm-calls/{calls[0]['id']}")).json()
    assert full["request"]["messages"] and full["tool_invocations"][0]["name"] == "lookup"

    found = (await api.get("/api/search", params={"q": "lookup"})).json()
    assert found["tools"] and found["llm_calls"]
    assert (await api.get("/api/apps/999")).status_code == 404


async def test_settings_and_retention(state, api):
    await seed(state)
    s = (await api.get("/api/settings")).json()
    assert s["store_prompts"] == "full"
    assert (await api.put("/api/settings", json={"store_prompts": "kaputt"})).status_code == 400
    assert (await api.put("/api/settings", json={"log_retention_days": 3})).json()["log_retention_days"] == 3
    sysinfo = (await api.get("/api/system")).json()
    assert sysinfo["counts"]["llm_calls"] == 2 and sysinfo["auth_enabled"] is False

    result = await apply_retention(state.store, state.runtime, now=time.time() + 400 * 86400)
    assert result["runs"] == 2 and result["logs"] == 2
    assert (await api.get("/api/llm-calls")).json() == []


async def test_auth_flow(tmp_path):
    st = await build_state(make_settings(tmp_path, password="geheim"))
    app = create_api_app(st)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ui.test") as c:
            assert (await c.get("/api/health")).status_code == 200
            assert (await c.get("/api/overview")).status_code == 401
            assert (await c.get("/api/auth/status")).json() == {"auth_required": True, "authenticated": False}
            assert (await c.post("/api/auth/login", json={"password": "falsch"})).status_code == 401
            assert (await c.post("/api/auth/login", json={"password": "geheim"})).status_code == 200
            assert (await c.get("/api/overview")).status_code == 200
            await c.post("/api/auth/logout")
            c.cookies.clear()
            assert (await c.get("/api/overview")).status_code == 401
    finally:
        await st.engine.dispose()


def test_websocket_live_events(tmp_path):
    import asyncio

    st = asyncio.run(build_state(make_settings(tmp_path)))
    app = create_api_app(st)
    with TestClient(app) as client, client.websocket_connect("/api/ws") as ws:
        ws.send_json({"op": "subscribe", "topics": ["overview", "app:1", "bogus topic"]})
        ws.send_json({"op": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        st.bus.publish(["app:1"], "log", {"message": "hallo"})
        msg = ws.receive_json()
        assert msg["type"] == "batch" and msg["events"][0]["data"]["message"] == "hallo"
