"""Parser für OTLP/HTTP (Protobuf und JSON) -> einfache Datenklassen."""

from __future__ import annotations

import base64
import binascii
import gzip
import json
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


@dataclass
class OtelEvent:
    name: str
    ts: float
    attrs: dict[str, Any]


@dataclass
class OtelSpan:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    start: float
    end: float | None
    status_code: int
    status_message: str | None
    attrs: dict[str, Any]
    resource: dict[str, Any]
    events: list[OtelEvent] = field(default_factory=list)


@dataclass
class OtelLog:
    ts: float
    severity_number: int
    severity_text: str | None
    body: str
    attrs: dict[str, Any]
    resource: dict[str, Any]
    trace_id: str | None
    span_id: str | None


def decode_body(body: bytes, content_encoding: str | None) -> bytes:
    if content_encoding and "gzip" in content_encoding.lower():
        return gzip.decompress(body)
    return body


# ---------------------------------------------------------------------- Protobuf


def _pb_any(v: Any) -> Any:
    kind = v.WhichOneof("value")
    if kind is None:
        return None
    if kind == "array_value":
        return [_pb_any(x) for x in v.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: _pb_any(kv.value) for kv in v.kvlist_value.values}
    if kind == "bytes_value":
        return v.bytes_value.hex()
    return getattr(v, kind)


def _pb_attrs(attrs: Any) -> dict[str, Any]:
    return {kv.key: _pb_any(kv.value) for kv in attrs}


def _hex(b: bytes) -> str | None:
    h = b.hex()
    return h if h and set(h) != {"0"} else None


def parse_traces_pb(data: bytes) -> list[OtelSpan]:
    req = ExportTraceServiceRequest()
    req.ParseFromString(data)
    out: list[OtelSpan] = []
    for rs in req.resource_spans:
        resource = _pb_attrs(rs.resource.attributes)
        for ss in rs.scope_spans:
            for sp in ss.spans:
                out.append(
                    OtelSpan(
                        trace_id=sp.trace_id.hex(),
                        span_id=sp.span_id.hex(),
                        parent_id=_hex(sp.parent_span_id),
                        name=sp.name,
                        start=sp.start_time_unix_nano / 1e9,
                        end=sp.end_time_unix_nano / 1e9 if sp.end_time_unix_nano else None,
                        status_code=sp.status.code,
                        status_message=sp.status.message or None,
                        attrs=_pb_attrs(sp.attributes),
                        resource=resource,
                        events=[OtelEvent(e.name, e.time_unix_nano / 1e9, _pb_attrs(e.attributes)) for e in sp.events],
                    )
                )
    return out


def parse_logs_pb(data: bytes) -> list[OtelLog]:
    req = ExportLogsServiceRequest()
    req.ParseFromString(data)
    out: list[OtelLog] = []
    for rl in req.resource_logs:
        resource = _pb_attrs(rl.resource.attributes)
        for sl in rl.scope_logs:
            for lr in sl.log_records:
                ts = lr.time_unix_nano or lr.observed_time_unix_nano
                body = _pb_any(lr.body)
                out.append(
                    OtelLog(
                        ts=ts / 1e9 if ts else 0.0,
                        severity_number=lr.severity_number,
                        severity_text=lr.severity_text or None,
                        body=body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, default=str),
                        attrs=_pb_attrs(lr.attributes),
                        resource=resource,
                        trace_id=_hex(lr.trace_id),
                        span_id=_hex(lr.span_id),
                    )
                )
    return out


# ---------------------------------------------------------------------- JSON


def _json_id(value: str | None) -> str | None:
    """OTLP/JSON nutzt Hex; manche Exporter senden Base64."""
    if not value:
        return None
    v = value.strip()
    try:
        int(v, 16)
        is_hex = len(v) in (16, 32)
    except ValueError:
        is_hex = False
    if not is_hex:
        try:
            v = base64.b64decode(v).hex()
        except (binascii.Error, ValueError):
            return None
    return v.lower() if set(v) != {"0"} else None


def _json_any(v: dict[str, Any] | None) -> Any:
    if not v:
        return None
    if "stringValue" in v:
        return v["stringValue"]
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "arrayValue" in v:
        return [_json_any(x) for x in (v["arrayValue"] or {}).get("values", [])]
    if "kvlistValue" in v:
        return {kv["key"]: _json_any(kv.get("value")) for kv in (v["kvlistValue"] or {}).get("values", [])}
    if "bytesValue" in v:
        return v["bytesValue"]
    return None


def _json_attrs(attrs: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {a["key"]: _json_any(a.get("value")) for a in attrs or []}


def _ns(value: Any) -> float | None:
    if value in (None, "", 0, "0"):
        return None
    return int(value) / 1e9


def parse_traces_json(data: bytes) -> list[OtelSpan]:
    doc = json.loads(data or b"{}")
    out: list[OtelSpan] = []
    for rs in doc.get("resourceSpans", []):
        resource = _json_attrs((rs.get("resource") or {}).get("attributes"))
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                status = sp.get("status") or {}
                code = status.get("code", 0)
                if isinstance(code, str):
                    code = {"STATUS_CODE_OK": 1, "STATUS_CODE_ERROR": 2}.get(code, 0)
                out.append(
                    OtelSpan(
                        trace_id=_json_id(sp.get("traceId")) or "",
                        span_id=_json_id(sp.get("spanId")) or "",
                        parent_id=_json_id(sp.get("parentSpanId")),
                        name=sp.get("name", ""),
                        start=_ns(sp.get("startTimeUnixNano")) or 0.0,
                        end=_ns(sp.get("endTimeUnixNano")),
                        status_code=int(code),
                        status_message=status.get("message") or None,
                        attrs=_json_attrs(sp.get("attributes")),
                        resource=resource,
                        events=[
                            OtelEvent(
                                e.get("name", ""),
                                _ns(e.get("timeUnixNano")) or 0.0,
                                _json_attrs(e.get("attributes")),
                            )
                            for e in sp.get("events", [])
                        ],
                    )
                )
    return out


def parse_logs_json(data: bytes) -> list[OtelLog]:
    doc = json.loads(data or b"{}")
    out: list[OtelLog] = []
    for rl in doc.get("resourceLogs", []):
        resource = _json_attrs((rl.get("resource") or {}).get("attributes"))
        for sl in rl.get("scopeLogs", []):
            for lr in sl.get("logRecords", []):
                body = _json_any(lr.get("body"))
                sev = lr.get("severityNumber", 0)
                if isinstance(sev, str):
                    sev = 0
                out.append(
                    OtelLog(
                        ts=_ns(lr.get("timeUnixNano")) or _ns(lr.get("observedTimeUnixNano")) or 0.0,
                        severity_number=int(sev),
                        severity_text=lr.get("severityText"),
                        body=body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, default=str),
                        attrs=_json_attrs(lr.get("attributes")),
                        resource=resource,
                        trace_id=_json_id(lr.get("traceId")),
                        span_id=_json_id(lr.get("spanId")),
                    )
                )
    return out


def parse_traces(data: bytes, content_type: str | None) -> list[OtelSpan]:
    if content_type and "json" in content_type:
        return parse_traces_json(data)
    return parse_traces_pb(data)


def parse_logs(data: bytes, content_type: str | None) -> list[OtelLog]:
    if content_type and "json" in content_type:
        return parse_logs_json(data)
    return parse_logs_pb(data)
