"""Minimaler, asynchroner Docker-Engine-Client (nur lesend) auf Basis von httpx."""

from __future__ import annotations

import json
import struct
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

STREAMS = {0: "stdin", 1: "stdout", 2: "stderr"}


def parse_docker_ts(value: str) -> float | None:
    """RFC3339Nano (``2026-11-05T07:36:42.734313372Z``) -> Unix-Sekunden."""
    if not value or value.startswith("0001-01-01"):
        return None
    value = value.strip()
    tz_offset = 0.0
    if value.endswith("Z"):
        value = value[:-1]
    elif len(value) > 6 and value[-6] in "+-" and value[-3] == ":":
        sign = 1 if value[-6] == "+" else -1
        tz_offset = sign * (int(value[-5:-3]) * 3600 + int(value[-2:]) * 60)
        value = value[:-6]
    base, _, frac = value.partition(".")
    try:
        dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    fraction = float("0." + frac) if frac.isdigit() else 0.0
    return dt.timestamp() + fraction - tz_offset


class LogDecoder:
    """Zerlegt den Log-Stream der Docker-API in Zeilen.

    Ohne TTY ist der Stream gemultiplext (8-Byte-Header je Frame: Stream-Typ, 3x 0, Länge big-endian).
    Mit TTY kommt der Rohtext ohne Header.
    """

    def __init__(self, tty: bool = False) -> None:
        self.tty = tty
        self._buf = b""
        self._partial: dict[str, bytes] = {}

    def feed(self, data: bytes) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        if self.tty:
            self._emit("stdout", data, out)
            return out
        self._buf += data
        while len(self._buf) >= 8:
            stream_type, size = struct.unpack(">BxxxL", self._buf[:8])
            if len(self._buf) < 8 + size:
                break
            payload = self._buf[8 : 8 + size]
            self._buf = self._buf[8 + size :]
            self._emit(STREAMS.get(stream_type, "stdout"), payload, out)
        return out

    def flush(self) -> list[tuple[str, str]]:
        out = []
        for stream, rest in self._partial.items():
            if rest:
                out.append((stream, rest.decode("utf-8", "replace").rstrip("\r")))
        self._partial.clear()
        return out

    def _emit(self, stream: str, payload: bytes, out: list[tuple[str, str]]) -> None:
        data = self._partial.get(stream, b"") + payload
        *lines, rest = data.split(b"\n")
        self._partial[stream] = rest
        for line in lines:
            out.append((stream, line.decode("utf-8", "replace").rstrip("\r")))


def split_timestamp(line: str) -> tuple[float | None, str]:
    """Trennt den von ``timestamps=1`` vorangestellten Zeitstempel ab."""
    ts_str, sep, rest = line.partition(" ")
    if sep and len(ts_str) >= 20 and ts_str[4] == "-" and ts_str[10] == "T":
        ts = parse_docker_ts(ts_str)
        if ts is not None:
            return ts, rest
    return None, line


class DockerClient:
    def __init__(self, docker_host: str) -> None:
        parsed = urlparse(docker_host)
        if parsed.scheme == "unix":
            transport = httpx.AsyncHTTPTransport(uds=parsed.path)
            base_url = "http://docker"
        else:
            scheme = "https" if parsed.scheme == "https" else "http"
            transport = httpx.AsyncHTTPTransport()
            base_url = f"{scheme}://{parsed.netloc}"
        self._client = httpx.AsyncClient(transport=transport, base_url=base_url, timeout=httpx.Timeout(10.0))

    @classmethod
    def from_client(cls, client: httpx.AsyncClient) -> DockerClient:
        inst = cls.__new__(cls)
        inst._client = client
        return inst

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        r = await self._client.get("/_ping")
        return r.status_code == 200

    async def list_containers(self, all_: bool = True) -> list[dict[str, Any]]:
        r = await self._client.get("/containers/json", params={"all": "1" if all_ else "0"})
        r.raise_for_status()
        return r.json()

    async def inspect(self, container_id: str) -> dict[str, Any] | None:
        r = await self._client.get(f"/containers/{container_id}/json")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        params = {"filters": json.dumps({"type": ["container"]})}
        async with self._client.stream("GET", "/events", params=params, timeout=None) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.strip():
                    yield json.loads(line)

    async def logs(
        self, container_id: str, *, tty: bool, since: float | None = None, tail: int | None = None
    ) -> AsyncIterator[tuple[str, float | None, str]]:
        """Folgt den Logs eines Containers. Liefert (stream, zeitstempel, zeile)."""
        params: dict[str, str] = {"stdout": "1", "stderr": "1", "follow": "1", "timestamps": "1"}
        if since is not None:
            params["since"] = f"{since:.9f}"
        elif tail is not None:
            params["tail"] = str(tail)
        decoder = LogDecoder(tty=tty)
        async with self._client.stream("GET", f"/containers/{container_id}/logs", params=params, timeout=None) as r:
            r.raise_for_status()
            async for chunk in r.aiter_bytes():
                for stream, line in decoder.feed(chunk):
                    ts, text = split_timestamp(line)
                    yield stream, ts, text
        for stream, line in decoder.flush():
            ts, text = split_timestamp(line)
            yield stream, ts, text
