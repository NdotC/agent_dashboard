import asyncio
import json
import struct

import httpx
from sqlalchemy import select

from agentdash_server.db.models import Agent, Application, LlmCall, LogEntry
from agentdash_server.ingest.docker_client import DockerClient
from agentdash_server.ingest.docker_watcher import DockerWatcher

from .conftest import proxy_client, settle

CID = "a" * 64
OTHER = "b" * 64


def frame(stream: int, data: bytes) -> bytes:
    return struct.pack(">BxxxL", stream, len(data)) + data


class FakeDocker:
    def __init__(self):
        self.events: asyncio.Queue = asyncio.Queue()

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/_ping":
            return httpx.Response(200, text="OK")
        if path == "/containers/json":
            return httpx.Response(
                200,
                json=[
                    {
                        "Id": CID,
                        "Names": ["/newsbot"],
                        "Labels": {"agentdash.enable": "true", "agentdash.agent": "writer"},
                        "NetworkSettings": {"Networks": {"agentdash": {"IPAddress": "172.20.0.5"}}},
                    },
                    {
                        "Id": OTHER,
                        "Names": ["/unlabeled"],
                        "Labels": {},
                        "NetworkSettings": {"Networks": {"agentdash": {"IPAddress": "172.20.0.9"}}},
                    },
                ],
            )
        if path.startswith("/containers/") and path.endswith("/json"):
            cid = path.split("/")[2]
            return httpx.Response(
                200,
                json={
                    "Id": cid,
                    "Name": "/newsbot" if cid == CID else "/unlabeled",
                    "RestartCount": 1,
                    "Config": {"Image": "newsbot:latest", "Tty": False, "Labels": {}},
                    "State": {"Status": "running", "StartedAt": "2026-11-05T07:00:00.000000000Z", "ExitCode": 0},
                },
            )
        if path.endswith("/logs"):
            body = frame(1, b"2026-11-05T07:00:01.000000000Z INFO starte Agent\n") + frame(
                2, b"2026-11-05T07:00:02.000000000Z ERROR kaputt\n"
            )
            return httpx.Response(200, content=body)
        if path == "/events":

            async def stream():
                while True:
                    ev = await self.events.get()
                    yield (json.dumps(ev) + "\n").encode()

            return httpx.Response(200, content=stream())
        return httpx.Response(404)


async def _wait_for(cond, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if await cond():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_watcher_discovers_labeled_containers_and_logs(state):
    fake = FakeDocker()
    client = DockerClient.from_client(
        httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://d")
    )
    watcher = DockerWatcher(state.settings, state.store, client)
    state.spans.resolver.watcher = watcher
    state.proxy.recorder.resolver.watcher = watcher
    watcher.start()
    try:

        async def has_logs():
            await state.store.flush_logs()
            async with state.sm() as s:
                return len((await s.execute(select(LogEntry))).scalars().all()) >= 2

        assert await _wait_for(has_logs)
        async with state.sm() as s:
            apps = (await s.execute(select(Application))).scalars().all()
            logs = (await s.execute(select(LogEntry).order_by(LogEntry.ts))).scalars().all()
        assert [a.key for a in apps] == ["newsbot"]  # unbeschrifteter Container wird ignoriert
        assert apps[0].status == "running" and apps[0].image == "newsbot:latest" and apps[0].restart_count == 1
        assert [(log.level, log.stream, log.message) for log in logs] == [
            ("info", "stdout", "INFO starte Agent"),
            ("error", "stderr", "ERROR kaputt"),
        ]

        # Proxy-Aufruf aus dem Container -> Anwendung per IP, Standard-Agent aus Label
        async with proxy_client(state, ip="172.20.0.5") as c:
            await c.post(
                "/api/chat", json={"model": "m", "stream": False, "messages": [{"role": "user", "content": "x"}]}
            )
        # Aufruf aus unbeschriftetem Container -> automatisch aufgenommen
        async with proxy_client(state, ip="172.20.0.9") as c:
            await c.post(
                "/api/chat", json={"model": "m", "stream": False, "messages": [{"role": "user", "content": "y"}]}
            )
        await settle(state)
        async with state.sm() as s:
            calls = (await s.execute(select(LlmCall).order_by(LlmCall.started_at))).scalars().all()
            agents = {a.id: a.name for a in (await s.execute(select(Agent))).scalars()}
            keys = sorted(a.key for a in (await s.execute(select(Application))).scalars())
        assert agents[calls[0].agent_id] == "writer"
        assert agents[calls[1].agent_id] == "unlabeled"
        assert keys == ["newsbot", "unlabeled"]
        assert watcher.connected
    finally:
        await watcher.stop()
