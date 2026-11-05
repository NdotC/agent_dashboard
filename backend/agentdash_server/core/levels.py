"""Erkennung des Log-Levels aus einer Textzeile."""

from __future__ import annotations

import json
import re

_LEVEL_ALIASES = {
    "trace": "debug",
    "debug": "debug",
    "info": "info",
    "information": "info",
    "notice": "info",
    "warn": "warn",
    "warning": "warn",
    "error": "error",
    "err": "error",
    "critical": "error",
    "fatal": "error",
    "panic": "error",
    "exception": "error",
}

_ERROR_RE = re.compile(
    r"\b(CRITICAL|FATAL|ERROR|ERR|PANIC)\b|Traceback \(most recent call last\)|\w+(Error|Exception):"
)
_WARN_RE = re.compile(r"\b(WARN|WARNING)\b")
_DEBUG_RE = re.compile(r"\b(DEBUG|TRACE)\b")
_INFO_RE = re.compile(r"\bINFO\b")
_LOGFMT_RE = re.compile(r"\b(?:level|lvl|severity)=\"?(\w+)", re.IGNORECASE)


def normalize_level(value: str | int | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        # Python-logging-Zahlen bzw. OTel-SeverityNumber (1-24)
        if value >= 40 or 17 <= value <= 24:
            return "error"
        if value >= 30 or 13 <= value <= 16:
            return "warn"
        if value >= 20 or 9 <= value <= 12:
            return "info"
        return "debug"
    return _LEVEL_ALIASES.get(str(value).strip().lower())


def detect_level(line: str, default: str = "info") -> str:
    stripped = line.lstrip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            for key in ("level", "levelname", "severity", "lvl", "log.level"):
                if key in obj:
                    lvl = normalize_level(obj[key])
                    if lvl:
                        return lvl
    m = _LOGFMT_RE.search(line)
    if m:
        lvl = normalize_level(m.group(1))
        if lvl:
            return lvl
    head = line[:200]
    if _ERROR_RE.search(head):
        return "error"
    if _WARN_RE.search(head):
        return "warn"
    if _DEBUG_RE.search(head):
        return "debug"
    if _INFO_RE.search(head):
        return "info"
    return default
