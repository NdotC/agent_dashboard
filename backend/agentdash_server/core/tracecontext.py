"""W3C Trace Context (``traceparent``)."""

from __future__ import annotations

import re

_TP_RE = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


def parse_traceparent(value: str | None) -> tuple[str, str] | None:
    """Gibt (trace_id, parent_span_id) zurück oder None."""
    if not value:
        return None
    m = _TP_RE.match(value.strip().lower())
    if not m or set(m.group(1)) == {"0"} or set(m.group(2)) == {"0"}:
        return None
    return m.group(1), m.group(2)
