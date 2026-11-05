import json
import struct
from datetime import UTC, datetime

from agentdash_server.core.levels import detect_level, normalize_level
from agentdash_server.core.tracecontext import parse_traceparent
from agentdash_server.ingest.conversations import (
    ConversationState,
    ConversationTracker,
    PendingTool,
    assign_tool_results,
)
from agentdash_server.ingest.docker_client import LogDecoder, parse_docker_ts, split_timestamp
from agentdash_server.ingest.llm_parse import parse_ollama, parse_openai, sanitize_request


def frame(stream: int, data: bytes) -> bytes:
    return struct.pack(">BxxxL", stream, len(data)) + data


def test_detect_level():
    assert detect_level("2024-01-01 ERROR something broke") == "error"
    assert detect_level("Traceback (most recent call last):") == "error"
    assert detect_level("ValueError: bad") == "error"
    assert detect_level("WARNING: low memory") == "warn"
    assert detect_level('{"level": "debug", "msg": "x"}') == "debug"
    assert detect_level('time=1 level=warn msg="x"') == "warn"
    assert detect_level("hello world") == "info"
    assert normalize_level(17) == "error" and normalize_level(9) == "info" and normalize_level(30) == "warn"


def test_log_decoder_multiplexed_and_partial():
    dec = LogDecoder(tty=False)
    data = frame(1, b"hello\nwor") + frame(2, b"oops\n") + frame(1, b"ld\n")
    out = dec.feed(data[:5]) + dec.feed(data[5:])
    assert out == [("stdout", "hello"), ("stderr", "oops"), ("stdout", "world")]


def test_log_decoder_tty():
    dec = LogDecoder(tty=True)
    assert dec.feed(b"a\r\nb") == [("stdout", "a")]
    assert dec.flush() == [("stdout", "b")]


def test_docker_timestamps():
    base = datetime(2026, 11, 5, 7, 36, 42, tzinfo=UTC).timestamp()
    ts = parse_docker_ts("2026-11-05T07:36:42.734313372Z")
    assert abs(ts - (base + 0.734313372)) < 1e-5
    assert abs(parse_docker_ts("2026-11-05T09:36:42+02:00") - base) < 1e-6
    ts2, text = split_timestamp("2026-11-05T07:36:42.5Z hello world")
    assert text == "hello world" and abs(ts2 - (base + 0.5)) < 1e-6
    assert split_timestamp("no timestamp") == (None, "no timestamp")
    assert parse_docker_ts("0001-01-01T00:00:00Z") is None


def test_traceparent():
    tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    assert parse_traceparent(tp) == ("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331")
    assert parse_traceparent("garbage") is None
    assert parse_traceparent("00-" + "0" * 32 + "-b7ad6b7169203331-01") is None


def test_parse_ollama_stream_with_tools_and_thinking():
    lines = [
        {"model": "m", "message": {"role": "assistant", "content": "", "thinking": "hmm"}, "done": False},
        {
            "model": "m",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "search", "arguments": {"q": "x"}}}],
            },
            "done": False,
        },
        {"model": "m", "message": {"role": "assistant", "content": "Hallo"}, "done": False},
        {
            "model": "m",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 3,
        },
    ]
    res = parse_ollama("\n".join(json.dumps(x) for x in lines).encode())
    assert res.content == "Hallo" and res.thinking == "hmm"
    assert res.tool_calls == [{"id": None, "name": "search", "arguments": {"q": "x"}}]
    assert (res.tokens_in, res.tokens_out) == (10, 3)


def test_parse_openai_stream_tool_call_fragments():
    chunks = [
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "calc", "arguments": ""}}]}}
            ]
        },
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"a": '}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}}]},
        {
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        },
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    res = parse_openai(body.encode(), streamed=True)
    assert res.tool_calls == [{"id": "c1", "name": "calc", "arguments": {"a": 1}}]
    assert res.tokens_in == 5 and res.done_reason == "tool_calls"


def test_sanitize_request_modes():
    req = {"model": "m", "messages": [{"role": "user", "content": "x" * 50, "images": ["AAAA"]}]}
    full = sanitize_request(req, "full", 10)
    assert full["messages"][0]["content"] == "x" * 50
    assert full["messages"][0]["images"][0].startswith("<Bild")
    assert "gekürzt" in sanitize_request(req, "truncate", 10)["messages"][0]["content"]
    assert sanitize_request(req, "none", 10)["messages"][0]["content"] == "<50 Zeichen>"


def test_conversation_tracking_and_tool_results():
    tr = ConversationTracker()
    msgs = [{"role": "user", "content": "Wetter?"}]
    assistant = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "weather", "arguments": {"c": "B"}}}],
    }
    state = ConversationState(1, "run1", 7, 3, [PendingTool(11, "weather", None)])
    tr.remember(7, msgs, assistant, state)
    # Client schickt die Assistant-Nachricht mit JSON-String-Argumenten zurück (OpenAI-Stil)
    follow = msgs + [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "x", "function": {"name": "weather", "arguments": '{"c": "B"}'}}],
        },
        {"role": "tool", "content": "sonnig", "tool_name": "weather"},
    ]
    found = tr.match(7, follow)
    assert found is not None and found[0].run_id == "run1" and found[1] == 2
    assert tr.match(8, follow) is None  # andere Anwendung
    results = assign_tool_results(found[0].pending_tools, follow[found[1] :])
    assert [(p.invocation_id, r) for p, r in results] == [(11, "sonnig")]
