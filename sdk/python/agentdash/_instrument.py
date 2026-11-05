"""Ergänzt ausgehende httpx-Requests um Agent- und Trace-Kontext.

Damit ordnet der Ollama-Proxy des Dashboards jeden LLM-Aufruf dem richtigen Agenten und Run zu –
ohne Änderungen am Code, der ollama-python, openai oder LangChain verwendet.
"""

from __future__ import annotations

from typing import Any

_patched = False


def _apply(request: Any) -> None:
    from ._core import trace_headers

    for key, value in trace_headers().items():
        if key not in request.headers:
            request.headers[key] = value


def instrument_httpx() -> bool:
    """Patcht ``httpx.Client.send`` und ``httpx.AsyncClient.send``. Gibt False zurück, wenn httpx fehlt."""
    global _patched
    if _patched:
        return True
    try:
        import httpx
    except ImportError:
        return False

    orig_send = httpx.Client.send
    orig_async_send = httpx.AsyncClient.send

    def send(self, request, *args, **kwargs):  # type: ignore[no-untyped-def]
        _apply(request)
        return orig_send(self, request, *args, **kwargs)

    async def async_send(self, request, *args, **kwargs):  # type: ignore[no-untyped-def]
        _apply(request)
        return await orig_async_send(self, request, *args, **kwargs)

    httpx.Client.send = send  # type: ignore[method-assign]
    httpx.AsyncClient.send = async_send  # type: ignore[method-assign]
    _patched = True
    return True
