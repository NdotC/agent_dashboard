from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from agentdash_server.config import Settings
from agentdash_server.main import build_state, create_api_app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples" / "mock_ollama"))

import mock_ollama  # noqa: E402

mock_ollama.DELAY = 0.0


def make_settings(tmp_path: Path, **kw) -> Settings:
    return Settings(
        data_dir=tmp_path,
        docker_enabled=False,
        ollama_upstream="http://ollama.test",
        **kw,
    )


@pytest.fixture
async def state(tmp_path):
    st = await build_state(make_settings(tmp_path))
    await st.proxy.client.aclose()
    st.proxy.client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_ollama.app), base_url="http://ollama.test"
    )
    st.store.start()
    yield st
    await st.proxy.drain()
    await st.store.stop()
    await st.engine.dispose()


@pytest.fixture
async def api(state):
    app = create_api_app(state)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ui.test") as client:
        yield client


def proxy_client(state, ip: str = "10.0.0.5") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.proxy.app, client=(ip, 40000)), base_url="http://proxy.test"
    )


async def settle(state) -> None:
    """Wartet, bis alle Aufzeichnungen und Logs geschrieben sind."""
    await state.proxy.drain()
    await state.store.flush_logs()
