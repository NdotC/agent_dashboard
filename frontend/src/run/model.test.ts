import { describe, expect, it } from "vitest";
import type { RunDetail } from "../lib/api";
import { activeAgents, applyRunEvent, buildRunGraph, buildSequence, buildTimeline, buildWaterfall } from "./model";

const agent = (id: number, name: string) => ({ id, app_id: 1, name, display_name: null, color: null, role: null, model: "m", first_seen: 0, last_seen: 0 });
const span = (id: string, parent: string | null, kind: string, agentId: number | null, s: number, e: number | null) => ({
  id, run_id: "r", parent_id: parent, agent_id: agentId, kind, name: kind === "agent" ? `agent ${agentId}` : kind,
  started_at: s, ended_at: e, status: e ? "ok" : "running", status_message: null, input: "in", output: "out",
  tokens_in: null, tokens_out: null, attributes: null,
});

function fixture(): RunDetail {
  return {
    run: { id: "r", app_id: 1, title: "T", source: "sdk", status: "running", started_at: 0, ended_at: null, last_activity: 9, tokens_in: 0, tokens_out: 0, llm_calls: 2, errors: 0 },
    app: null,
    agents: { "1": agent(1, "planner"), "2": agent(2, "writer") },
    spans: [
      span("run", null, "run", null, 0, 10),
      span("p", "run", "agent", 1, 1, 9),
      span("w", "p", "agent", 2, 3, 6),
      span("t", "w", "tool", 2, 4, 4.5),
    ] as RunDetail["spans"],
    llm_calls: [
      { id: 1, app_id: 1, agent_id: 1, run_id: "r", span_id: "x", parent_span_id: "p", parent_call_id: null, endpoint: "chat", model: "m", tool_calls: null, tokens_in: 5, tokens_out: 5, duration_ms: 500, started_at: 2, status: "ok", error: null },
      { id: 2, app_id: 1, agent_id: 2, run_id: "r", span_id: "y", parent_span_id: "w", parent_call_id: null, endpoint: "chat", model: "m", tool_calls: null, tokens_in: 5, tokens_out: 5, duration_ms: 500, started_at: 5, status: "ok", error: null },
    ],
    messages: [
      { id: 1, app_id: 1, run_id: "r", span_id: "p", from_agent_id: null, to_agent_id: 1, kind: "call", content: "in", ts: 1 },
      { id: 2, app_id: 1, run_id: "r", span_id: "w", from_agent_id: 1, to_agent_id: 2, kind: "call", content: "in", ts: 3 },
      { id: 3, app_id: 1, run_id: "r", span_id: "w", from_agent_id: 2, to_agent_id: 1, kind: "return", content: "out", ts: 6 },
      { id: 4, app_id: 1, run_id: "r", span_id: "z", from_agent_id: 1, to_agent_id: 2, kind: "feedback", content: "besser", ts: 7 },
    ],
    tools: [],
    logs: [
      { id: 1, ts: 4.2, app_id: 1, agent_id: 2, run_id: "r", span_id: "w", level: "error", source: "sdk", stream: null, message: "kaputt", attributes: null },
      { id: 2, ts: 4.3, app_id: 1, agent_id: 2, run_id: "r", span_id: "w", level: "info", source: "sdk", stream: null, message: "info", attributes: null },
    ],
  };
}

describe("run model", () => {
  it("baut einen chronologischen Verlauf mit Einrückung", () => {
    const items = buildTimeline(fixture());
    expect(items.map((i) => i.kind)).toEqual(["agent_start", "llm", "agent_start", "tool", "log", "llm", "agent_end", "message", "agent_end"]);
    const writerStart = items[2];
    expect(writerStart.kind === "agent_start" && writerStart.callerId).toBe(1);
    expect(writerStart.depth).toBe(1);
    expect(items[3].depth).toBe(2); // Tool im writer
    expect(items[1].depth).toBe(1); // LLM-Aufruf im planner
  });

  it("aggregiert den Graphen und respektiert den Replay-Zeitpunkt", () => {
    const g = buildRunGraph(fixture());
    expect(g.nodes.map((n) => n.id)).toEqual(["start", "agent-1", "agent-2"]);
    const e = g.edges.find((x) => x.id === "agent-1->agent-2")!;
    expect(e.count).toBe(2);
    expect(e.kinds).toEqual({ call: 1, feedback: 1 });
    const early = buildRunGraph(fixture(), 2);
    expect(early.edges.map((x) => x.id)).toEqual(["start->agent-1"]);
    expect(early.nodes.find((n) => n.id === "agent-1")!.llm_calls).toBe(1);
  });

  it("erkennt aktive Agenten", () => {
    expect([...activeAgents(fixture(), 4)].sort()).toEqual([1, 2]);
    expect([...activeAgents(fixture(), 8)]).toEqual([1]);
  });

  it("baut Sequenz-Lanes in Reihenfolge des Auftretens", () => {
    const seq = buildSequence(fixture());
    expect(seq.lanes.map((l) => l.id)).toEqual(["start", "agent-1", "agent-2"]);
    expect(seq.rows[0].kind).toBe("message");
  });

  it("verschachtelt den Wasserfall", () => {
    const rows = buildWaterfall(fixture());
    expect(rows.map((r) => [r.key, r.depth])).toEqual([
      ["s-run", 0], ["s-p", 1], ["l-1", 2], ["s-w", 2], ["s-t", 3], ["l-2", 3],
    ]);
  });

  it("arbeitet Live-Events ein", () => {
    let d = fixture();
    d = applyRunEvent(d, "span", { ...d.spans[1], ended_at: 9.5, status: "ok" });
    d = applyRunEvent(d, "message", { id: 9, app_id: 1, run_id: "r", span_id: null, from_agent_id: 2, to_agent_id: 1, kind: "handoff", content: "x", ts: 9 });
    expect(d.spans[1].ended_at).toBe(9.5);
    expect(d.messages).toHaveLength(5);
  });
});
