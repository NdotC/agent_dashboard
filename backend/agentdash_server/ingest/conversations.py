"""Erkennt, dass ein Chat-Request die Fortsetzung eines früheren ist.

Ein Agent schickt bei jedem Schritt den bisherigen Verlauf mit. Request N+1 enthält also die
Nachrichten von Request N plus die Antwort des Modells (und ggf. Tool-Ergebnisse). Über einen
Hash des normalisierten Präfixes finden wir den Vorgänger-Aufruf, ohne dass der Agent etwas
mitschicken muss.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from .llm_parse import message_text, normalize_tool_call


@dataclass
class PendingTool:
    invocation_id: int
    name: str
    call_ref: str | None


@dataclass
class ConversationState:
    call_id: int
    run_id: str
    app_id: int
    agent_id: int | None
    pending_tools: list[PendingTool] = field(default_factory=list)


def _norm_message(m: dict[str, Any]) -> list[Any]:
    role = m.get("role", "")
    text = message_text(m).strip()
    tools = []
    for tc in m.get("tool_calls") or []:
        n = normalize_tool_call(tc)
        tools.append([n["name"], json.dumps(n["arguments"], sort_keys=True, ensure_ascii=False, default=str)])
    return [role, text, tools]


def prefix_key(app_id: int, messages: list[dict[str, Any]]) -> str:
    h = hashlib.sha1(str(app_id).encode())
    for m in messages:
        h.update(json.dumps(_norm_message(m), ensure_ascii=False).encode())
        h.update(b"\x00")
    return h.hexdigest()


class ConversationTracker:
    def __init__(self, max_entries: int = 5000) -> None:
        self._states: OrderedDict[str, ConversationState] = OrderedDict()
        self._max = max_entries

    def match(self, app_id: int, messages: list[dict[str, Any]]) -> tuple[ConversationState, int] | None:
        """Sucht den längsten bekannten Präfix, der mit einer Assistant-Nachricht endet.

        Gibt (Zustand, Index der ersten neuen Nachricht) zurück.
        """
        for k in range(len(messages), 0, -1):
            if messages[k - 1].get("role") != "assistant":
                continue
            state = self._states.get(prefix_key(app_id, messages[:k]))
            if state is not None:
                self._states.move_to_end(prefix_key(app_id, messages[:k]))
                return state, k
        return None

    def remember(
        self, app_id: int, messages: list[dict[str, Any]], assistant: dict[str, Any], state: ConversationState
    ) -> None:
        key = prefix_key(app_id, [*messages, assistant])
        self._states[key] = state
        self._states.move_to_end(key)
        while len(self._states) > self._max:
            self._states.popitem(last=False)


def assign_tool_results(
    pending: list[PendingTool], new_messages: list[dict[str, Any]]
) -> list[tuple[PendingTool, str]]:
    """Ordnet ``role: tool``-Nachrichten den offenen Tool-Aufrufen zu (per ID, Name oder Reihenfolge)."""
    results: list[tuple[PendingTool, str]] = []
    open_tools = list(pending)
    for m in new_messages:
        if m.get("role") != "tool" or not open_tools:
            continue
        text = message_text(m)
        ref = m.get("tool_call_id")
        name = m.get("tool_name") or m.get("name")
        chosen = None
        if ref:
            chosen = next((p for p in open_tools if p.call_ref == ref), None)
        if chosen is None and name:
            chosen = next((p for p in open_tools if p.name == name), None)
        if chosen is None:
            chosen = open_tools[0]
        open_tools.remove(chosen)
        results.append((chosen, text))
    return results
