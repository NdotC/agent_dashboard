"""Kern des SDK: Runs, Agenten, Tools, Nachrichten auf Basis von OpenTelemetry."""

from __future__ import annotations

import atexit
import contextvars
import functools
import inspect
import json
import logging
import os
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

F = TypeVar("F", bound=Callable[..., Any])

MAX_TEXT = 32_000
DEFAULT_ENDPOINT = "http://agentdash:4318"

_agent_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("agentdash_agent", default=None)
_lock = threading.Lock()
_state: dict[str, Any] = {"tracer": None, "provider": None, "logger_provider": None, "app": None}
_propagator = TraceContextTextMapPropagator()


# ---------------------------------------------------------------------- Initialisierung


def init(
    app: str | None = None,
    endpoint: str | None = None,
    *,
    headers: dict[str, str] | None = None,
    capture_logging: bool = True,
    instrument: bool = True,
    span_processor: SpanProcessor | None = None,
) -> None:
    """Initialisiert das SDK.

    :param app: Name der Anwendung. Im Docker-Betrieb optional – das Dashboard erkennt den Container.
    :param endpoint: OTLP/HTTP-Basis-URL des Dashboards (Standard: ``$AGENTDASH_ENDPOINT`` oder
        ``http://agentdash:4318``).
    :param capture_logging: Python-``logging`` mit Agent-/Run-Kontext an das Dashboard senden.
    :param instrument: Ausgehende httpx-Requests (z. B. ollama-python) mit ``X-Agent-Name`` und
        ``traceparent`` versehen, damit der Ollama-Proxy LLM-Aufrufe zuordnen kann.
    :param span_processor: Eigener Span-Processor (für Tests).
    """
    with _lock:
        if _state["tracer"] is not None:
            return
        app = app or os.environ.get("AGENTDASH_APP")
        endpoint = (endpoint or os.environ.get("AGENTDASH_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")
        key = os.environ.get("AGENTDASH_KEY")
        headers = dict(headers or {})
        if key:
            headers.setdefault("X-Agentdash-Key", key)

        attrs = {"service.name": app or os.environ.get("OTEL_SERVICE_NAME") or "agent-app"}
        if app:
            attrs["agentdash.app"] = app
        resource = Resource.create(attrs)
        provider = TracerProvider(resource=resource)
        if span_processor is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            span_processor = BatchSpanProcessor(
                OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers), schedule_delay_millis=500
            )
        provider.add_span_processor(span_processor)
        _state.update(tracer=provider.get_tracer("agentdash", "0.1.0"), provider=provider, app=app)

        if capture_logging:
            _setup_logging(resource, endpoint, headers)
        if instrument:
            from ._instrument import instrument_httpx

            instrument_httpx()
        atexit.register(shutdown)


def _setup_logging(resource: Resource, endpoint: str, headers: dict[str, str]) -> None:
    try:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    except ImportError:  # pragma: no cover - ältere OTel-Versionen
        return
    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=f"{endpoint}/v1/logs", headers=headers), schedule_delay_millis=500
        )
    )
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=lp)
    handler.addFilter(_AgentFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.WARNING:  # Python-Standard -> INFO-Logs der Agenten mitnehmen
        root.setLevel(logging.INFO)
    _state["logger_provider"] = lp
    _state["log_handler"] = handler


_IGNORED_LOGGERS = ("opentelemetry", "httpx", "httpcore", "urllib3")


class _AgentFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        agent = _agent_var.get()
        if agent and not hasattr(record, "agentdash.agent"):
            setattr(record, "agentdash.agent", agent)
        # Eigene Exporter-Logs nicht erneut exportieren (Endlosschleife vermeiden) und
        # Request-Logs der HTTP-Bibliotheken weglassen (LLM-Aufrufe erfasst bereits der Proxy)
        return not record.name.startswith(_IGNORED_LOGGERS)


def shutdown() -> None:
    """Sendet ausstehende Daten und beendet das SDK."""
    provider = _state.get("provider")
    if provider is not None:
        provider.force_flush()
        provider.shutdown()
    lp = _state.get("logger_provider")
    if lp is not None:
        lp.force_flush()
        lp.shutdown()
        handler = _state.get("log_handler")
        if handler:
            logging.getLogger().removeHandler(handler)
    _state.update(tracer=None, provider=None, logger_provider=None, log_handler=None, app=None)


def flush() -> None:
    for key in ("provider", "logger_provider"):
        p = _state.get(key)
        if p is not None:
            p.force_flush()


def _tracer() -> trace.Tracer:
    if _state["tracer"] is None:
        init()
    return _state["tracer"]


# ---------------------------------------------------------------------- Hilfen


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = repr(value)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + f" … [{len(text) - MAX_TEXT} Zeichen gekürzt]"
    return text


def _call_input(func: Callable[..., Any], args: tuple, kwargs: dict) -> str | None:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        data = {k: v for k, v in bound.arguments.items() if k not in ("self", "cls")}
    except (TypeError, ValueError):
        data = {"args": args, "kwargs": kwargs}
    if len(data) == 1:
        return _to_text(next(iter(data.values())))
    return _to_text(data)


def current_agent() -> str | None:
    """Name des gerade aktiven Agenten (oder None)."""
    return _agent_var.get()


def trace_headers() -> dict[str, str]:
    """Header für ausgehende Requests: ``traceparent`` und ``X-Agent-Name``/``X-Agent-App``."""
    headers: dict[str, str] = {}
    _propagator.inject(headers)
    agent = _agent_var.get()
    if agent:
        headers["X-Agent-Name"] = agent
    if _state.get("app"):
        headers["X-Agent-App"] = _state["app"]
    return headers


# ---------------------------------------------------------------------- Spans


class _Span:
    """Kontextmanager (sync/async) und Dekorator für einen Dashboard-Span."""

    kind = "step"

    def __init__(self, name: str, *, input: Any = None, attributes: dict[str, Any] | None = None) -> None:
        self.name = name
        self.input = input
        self.output: Any = None
        self.attributes = dict(attributes or {})
        self._span: trace.Span | None = None
        self._ctx_token: object | None = None
        self._agent_token: contextvars.Token | None = None

    # -- Anpassungspunkte
    def _span_name(self) -> str:
        return self.name

    def _agent_name(self) -> str | None:
        return _agent_var.get()

    def _extra_attrs(self) -> dict[str, Any]:
        return {}

    def _sets_agent(self) -> bool:
        return False

    # -- Lebenszyklus
    def _start(self) -> _Span:
        tracer = _tracer()
        parent = trace.get_current_span()
        parent_id = parent.get_span_context().span_id if parent.get_span_context().is_valid else None
        agent = self._agent_name()
        attrs: dict[str, Any] = {"agentdash.kind": self.kind, **self._extra_attrs(), **self.attributes}
        if agent:
            attrs["agentdash.agent"] = agent
        input_text = _to_text(self.input)
        if input_text is not None:
            attrs["agentdash.input"] = input_text
        self._span = tracer.start_span(self._span_name(), attributes=attrs)
        ctx = trace.set_span_in_context(self._span)
        self._ctx_token = otel_context.attach(ctx)
        if self._sets_agent():
            self._agent_token = _agent_var.set(agent)
        # Start-Marker: kurzer Kind-Span, damit das Dashboard den Start sofort sieht
        marker_attrs = {
            "agentdash.marker": "start",
            "agentdash.target.kind": self.kind,
            "agentdash.target.name": self._span_name(),
            **{
                k: v
                for k, v in attrs.items()
                if k in ("agentdash.agent", "agentdash.caller", "agentdash.input", "agentdash.run.title")
            },
        }
        if parent_id:
            marker_attrs["agentdash.target.parent"] = format(parent_id, "016x")
        tracer.start_span("agentdash.start", context=ctx, attributes=marker_attrs).end()
        return self

    def _finish(self, exc: BaseException | None) -> None:
        span = self._span
        if span is None:
            return
        out = _to_text(self.output)
        if out is not None:
            span.set_attribute("agentdash.output", out)
        if exc is not None:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, f"{type(exc).__name__}: {exc}"))
        else:
            span.set_status(Status(StatusCode.OK))
        span.end()
        if self._agent_token is not None:
            _agent_var.reset(self._agent_token)
            self._agent_token = None
        if self._ctx_token is not None:
            otel_context.detach(self._ctx_token)
            self._ctx_token = None

    def set_output(self, value: Any) -> None:
        self.output = value

    def set_attribute(self, key: str, value: Any) -> None:
        if self._span is not None:
            self._span.set_attribute(key, value)

    def __enter__(self) -> _Span:
        return self._start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self._finish(exc)

    async def __aenter__(self) -> _Span:
        return self._start()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._finish(exc)

    # -- Dekorator
    def _clone(self, input: Any) -> _Span:
        clone = object.__new__(type(self))
        clone.__dict__.update(self.__dict__)
        clone.input = input if self.input is None else self.input
        clone.output = None
        clone._span = clone._ctx_token = clone._agent_token = None
        return clone

    def __call__(self, func: F) -> F:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                span = self._clone(_call_input(func, args, kwargs))
                async with span:
                    result = await func(*args, **kwargs)
                    if span.output is None:
                        span.output = result
                    return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            span = self._clone(_call_input(func, args, kwargs))
            with span:
                result = func(*args, **kwargs)
                if span.output is None:
                    span.output = result
                return result

        return wrapper  # type: ignore[return-value]


class run(_Span):  # noqa: N801 - API-Name
    """Ein Durchlauf der Anwendung (z. B. eine Benutzeranfrage). Alles darin gehört zu diesem Run."""

    kind = "run"

    def _extra_attrs(self) -> dict[str, Any]:
        return {"agentdash.run.title": self.name}

    def _agent_name(self) -> str | None:
        return None

    def _sets_agent(self) -> bool:
        return True  # innerhalb eines neuen Runs ist zunächst kein Agent aktiv

    def _start(self) -> _Span:
        # Ein Run beginnt immer einen neuen Trace
        self._detached = otel_context.attach(otel_context.Context())
        return super()._start()

    def _finish(self, exc: BaseException | None) -> None:
        super()._finish(exc)
        token = getattr(self, "_detached", None)
        if token is not None:
            otel_context.detach(token)
            self._detached = None


class agent(_Span):  # noqa: N801
    """Ein Agent arbeitet. Ruft ein Agent einen anderen auf, wird das als Nachricht erfasst."""

    kind = "agent"

    def __init__(self, name: str, *, input: Any = None, role: str | None = None, **kw: Any) -> None:
        super().__init__(name, input=input, **kw)
        self.agent_name = name
        self.role = role

    def _span_name(self) -> str:
        return f"agent {self.agent_name}"

    def _agent_name(self) -> str | None:
        return self.agent_name

    def _sets_agent(self) -> bool:
        return True

    def _extra_attrs(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": self.agent_name}
        caller = _agent_var.get()
        if caller and caller != self.agent_name:
            attrs["agentdash.caller"] = caller
        if self.role:
            attrs["agentdash.agent.role"] = self.role
        return attrs


class tool(_Span):  # noqa: N801
    """Ausführung eines Tools. Als Dekorator: ``@tool`` oder ``@tool("name")``."""

    kind = "tool"

    def __new__(cls, name: Any = None, **kw: Any):  # type: ignore[no-untyped-def]
        if callable(name):  # @tool ohne Klammern
            inst = super().__new__(cls)
            inst.__init__(name.__name__, **kw)
            return inst(name)
        return super().__new__(cls)

    def __init__(self, name: str | None = None, *, input: Any = None, **kw: Any) -> None:
        if callable(name):
            return
        super().__init__(name or "tool", input=input, **kw)

    def __call__(self, func: F) -> F:
        if self.name == "tool":
            self.name = func.__name__
        return super().__call__(func)

    def _extra_attrs(self) -> dict[str, Any]:
        return {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": self.name,
            "agentdash.tool.name": self.name,
        }


class step(_Span):  # noqa: N801
    """Beliebiger Arbeitsschritt (z. B. "Daten laden")."""

    kind = "step"


def send_message(to: str, content: Any, *, kind: str = "message", sender: str | None = None) -> None:
    """Meldet eine Nachricht zwischen Agenten (z. B. eine Übergabe oder ein Broadcast).

    Aufrufe zwischen Agenten innerhalb von ``agent()``-Blöcken werden automatisch erfasst;
    diese Funktion braucht man für zusätzliche, explizite Nachrichten.
    """
    sender = sender or _agent_var.get()
    attrs: dict[str, Any] = {
        "agentdash.kind": "message",
        "agentdash.message.to": to,
        "agentdash.message.kind": kind,
    }
    if sender:
        attrs["agentdash.message.from"] = sender
        attrs["agentdash.agent"] = sender
    text = _to_text(content)
    if text is not None:
        attrs["agentdash.message.content"] = text
    _tracer().start_span(f"message {sender or 'start'} -> {to}", attributes=attrs).end()
