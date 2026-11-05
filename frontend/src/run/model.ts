// Aufbereitung eines Runs für Verlauf, Kommunikationsgraph, Sequenzdiagramm und Wasserfall.
import type { Agent, Graph, GraphEdge, GraphNode, LlmCall, LogEntry, Message, RunDetail, Span, ToolInvocation } from "../lib/api";

export type TimelineItem =
  | { kind: "agent_start"; key: string; ts: number; agentId: number | null; callerId: number | null; span: Span; depth: number }
  | { kind: "agent_end"; key: string; ts: number; agentId: number | null; callerId: number | null; span: Span; depth: number }
  | { kind: "llm"; key: string; ts: number; agentId: number | null; call: LlmCall; tools: ToolInvocation[]; depth: number }
  | { kind: "tool"; key: string; ts: number; agentId: number | null; span: Span; depth: number }
  | { kind: "step"; key: string; ts: number; agentId: number | null; span: Span; depth: number }
  | { kind: "message"; key: string; ts: number; agentId: number | null; msg: Message; depth: number }
  | { kind: "log"; key: string; ts: number; agentId: number | null; log: LogEntry; depth: number };

export type TimelineKind = "agent" | "llm" | "tool" | "message" | "log";

export function kindGroup(item: TimelineItem): TimelineKind {
  switch (item.kind) {
    case "agent_start":
    case "agent_end":
    case "step":
      return "agent";
    case "llm":
      return "llm";
    case "tool":
      return "tool";
    case "message":
      return "message";
    case "log":
      return "log";
  }
}

/** Tiefe eines Spans = Anzahl der Agent-Vorfahren (für die Einrückung im Verlauf). */
export function spanDepths(spans: Span[]): Map<string, number> {
  const byId = new Map(spans.map((s) => [s.id, s]));
  const memo = new Map<string, number>();
  const depth = (s: Span | undefined, guard = 0): number => {
    if (!s || guard > 50) return 0;
    if (memo.has(s.id)) return memo.get(s.id)!;
    const parent = s.parent_id ? byId.get(s.parent_id) : undefined;
    const d = depth(parent, guard + 1) + (parent && parent.kind === "agent" ? 1 : 0);
    memo.set(s.id, d);
    return d;
  };
  spans.forEach((s) => depth(s));
  return memo;
}

/** Aufrufer eines Agent-Spans (Agent des nächsten Agent-Vorfahren). */
function callerOf(span: Span, byId: Map<string, Span>): number | null {
  let p = span.parent_id ? byId.get(span.parent_id) : undefined;
  let guard = 0;
  while (p && guard++ < 50) {
    if (p.kind === "agent") return p.agent_id;
    p = p.parent_id ? byId.get(p.parent_id) : undefined;
  }
  return null;
}

export function buildTimeline(d: RunDetail, opts: { logLevels?: string[] } = {}): TimelineItem[] {
  const levels = opts.logLevels ?? ["warn", "error"];
  const byId = new Map(d.spans.map((s) => [s.id, s]));
  const depths = spanDepths(d.spans);
  const depthOf = (spanId: string | null | undefined, self = false) => {
    if (!spanId) return 0;
    const s = byId.get(spanId);
    if (!s) return 0;
    return (depths.get(spanId) ?? 0) + (!self && s.kind === "agent" ? 1 : 0);
  };
  const items: TimelineItem[] = [];
  const agentSpanIds = new Set<string>();

  for (const s of d.spans) {
    if (s.kind === "run") continue;
    if (s.kind === "agent") {
      agentSpanIds.add(s.id);
      const callerId = callerOf(s, byId);
      const depth = depthOf(s.id, true);
      items.push({ kind: "agent_start", key: `as-${s.id}`, ts: s.started_at, agentId: s.agent_id, callerId, span: s, depth });
      if (s.ended_at) items.push({ kind: "agent_end", key: `ae-${s.id}`, ts: s.ended_at, agentId: s.agent_id, callerId, span: s, depth });
    } else if (s.kind === "tool") {
      items.push({ kind: "tool", key: `t-${s.id}`, ts: s.started_at, agentId: s.agent_id, span: s, depth: depthOf(s.parent_id) });
    } else {
      items.push({ kind: "step", key: `s-${s.id}`, ts: s.started_at, agentId: s.agent_id, span: s, depth: depthOf(s.parent_id) });
    }
  }
  const toolsByCall = new Map<number, ToolInvocation[]>();
  for (const t of d.tools) {
    if (t.llm_call_id == null) continue;
    const list = toolsByCall.get(t.llm_call_id) ?? [];
    list.push(t);
    toolsByCall.set(t.llm_call_id, list);
  }
  for (const c of d.llm_calls) {
    items.push({ kind: "llm", key: `l-${c.id}`, ts: c.started_at, agentId: c.agent_id, call: c, tools: toolsByCall.get(c.id) ?? [], depth: depthOf(c.parent_span_id) });
  }
  for (const m of d.messages) {
    // Aufruf/Rückgabe eines Agenten wird bereits durch Start/Ende des Agent-Spans dargestellt
    if ((m.kind === "call" || m.kind === "return") && m.span_id && agentSpanIds.has(m.span_id)) continue;
    items.push({ kind: "message", key: `m-${m.id}`, ts: m.ts, agentId: m.from_agent_id, msg: m, depth: depthOf(m.span_id) });
  }
  for (const l of d.logs) {
    if (!levels.includes(l.level) || l.source === "proxy") continue;
    items.push({ kind: "log", key: `g-${l.id}`, ts: l.ts, agentId: l.agent_id, log: l, depth: depthOf(l.span_id) });
  }
  const order: Record<TimelineItem["kind"], number> = { agent_start: 0, message: 1, step: 2, tool: 3, llm: 4, log: 5, agent_end: 6 };
  return items.sort((a, b) => a.ts - b.ts || order[a.kind] - order[b.kind]);
}

/** Kommunikationsgraph eines Runs (optional nur bis zum Zeitpunkt `until`). */
export function buildRunGraph(d: RunDetail, until?: number | null): Graph {
  const agents = d.agents;
  const msgs = d.messages.filter((m) => until == null || m.ts <= until);
  const edges = new Map<string, GraphEdge>();
  const used = new Set<string>();
  const nid = (id: number | null) => (id == null ? "start" : `agent-${id}`);
  for (const m of msgs) {
    const src = nid(m.from_agent_id);
    const dst = nid(m.to_agent_id);
    used.add(src);
    used.add(dst);
    const key = `${src}->${dst}`;
    const e = edges.get(key) ?? { id: key, source: src, target: dst, count: 0, kinds: {}, last_ts: 0 };
    e.count += 1;
    e.kinds[m.kind] = (e.kinds[m.kind] ?? 0) + 1;
    e.last_ts = Math.max(e.last_ts, m.ts);
    edges.set(key, e);
  }
  const llmCounts = new Map<number, number>();
  for (const c of d.llm_calls) {
    if (c.agent_id == null || (until != null && c.started_at > until)) continue;
    llmCounts.set(c.agent_id, (llmCounts.get(c.agent_id) ?? 0) + 1);
    used.add(nid(c.agent_id));
  }
  for (const s of d.spans) if (s.agent_id != null && (until == null || s.started_at <= until)) used.add(nid(s.agent_id));
  const nodes: GraphNode[] = [];
  if (used.has("start")) nodes.push({ id: "start", kind: "start", agent_id: null, name: "Start" });
  const agentIds = [...used].filter((n) => n !== "start").map((n) => Number(n.split("-")[1])).sort((a, b) => a - b);
  for (const id of agentIds) {
    const a = agents[String(id)];
    if (!a) continue;
    nodes.push({ id: `agent-${id}`, kind: "agent", agent_id: id, name: a.display_name || a.name, color: a.color, model: a.model, llm_calls: llmCounts.get(id) ?? 0 });
  }
  return { nodes, edges: [...edges.values()] };
}

/** Agenten, die zum Zeitpunkt `at` gerade arbeiten (offener Agent-Span). */
export function activeAgents(d: RunDetail, at?: number | null): Set<number> {
  const out = new Set<number>();
  for (const s of d.spans) {
    if (s.kind !== "agent" || s.agent_id == null) continue;
    if (at == null ? s.status === "running" && !s.ended_at : s.started_at <= at && (s.ended_at == null || s.ended_at >= at)) out.add(s.agent_id);
  }
  if (at != null) {
    for (const c of d.llm_calls) {
      if (c.agent_id != null && c.started_at <= at && c.started_at + (c.duration_ms ?? 0) / 1000 >= at) out.add(c.agent_id);
    }
  }
  return out;
}

// ---------------------------------------------------------------------- Sequenzdiagramm

export type SeqRow =
  | { kind: "message"; key: string; ts: number; from: string; to: string; label: string; msg: Message }
  | { kind: "llm"; key: string; ts: number; from: string; to: string; label: string; call: LlmCall }
  | { kind: "tool"; key: string; ts: number; from: string; to: string; label: string; span: Span };

export function buildSequence(d: RunDetail): { lanes: { id: string; agentId: number | null; name: string }[]; rows: SeqRow[] } {
  const nid = (id: number | null) => (id == null ? "start" : `agent-${id}`);
  const rows: SeqRow[] = [];
  for (const m of d.messages) {
    rows.push({ kind: "message", key: `m-${m.id}`, ts: m.ts, from: nid(m.from_agent_id), to: nid(m.to_agent_id), label: m.kind, msg: m });
  }
  for (const c of d.llm_calls) {
    rows.push({ kind: "llm", key: `l-${c.id}`, ts: c.started_at, from: nid(c.agent_id), to: nid(c.agent_id), label: c.model ?? "LLM", call: c });
  }
  for (const s of d.spans) {
    if (s.kind === "tool") rows.push({ kind: "tool", key: `t-${s.id}`, ts: s.started_at, from: nid(s.agent_id), to: nid(s.agent_id), label: s.name, span: s });
  }
  const order = { message: 0, tool: 1, llm: 2 } as const;
  rows.sort((a, b) => a.ts - b.ts || order[a.kind] - order[b.kind]);
  const laneOrder: string[] = [];
  const add = (id: string) => {
    if (!laneOrder.includes(id)) laneOrder.push(id);
  };
  if (rows.some((r) => r.from === "start" || r.to === "start")) add("start");
  rows.forEach((r) => {
    add(r.from);
    add(r.to);
  });
  const lanes = laneOrder.map((id) => {
    const agentId = id === "start" ? null : Number(id.split("-")[1]);
    const a: Agent | undefined = agentId != null ? d.agents[String(agentId)] : undefined;
    return { id, agentId, name: id === "start" ? "Start" : a ? a.display_name || a.name : `#${agentId}` };
  });
  return { lanes, rows };
}

// ---------------------------------------------------------------------- Wasserfall

export interface WaterfallRow {
  key: string;
  depth: number;
  label: string;
  kind: Span["kind"];
  agentId: number | null;
  start: number;
  end: number | null;
  status: string;
  span?: Span;
  call?: LlmCall;
}

export function buildWaterfall(d: RunDetail): WaterfallRow[] {
  const children = new Map<string | null, (Span | LlmCall)[]>();
  const spanIds = new Set(d.spans.map((s) => s.id));
  const push = (parent: string | null, item: Span | LlmCall) => {
    const key = parent && (spanIds.has(parent)) ? parent : null;
    const list = children.get(key) ?? [];
    list.push(item);
    children.set(key, list);
  };
  d.spans.forEach((s) => push(s.parent_id, s));
  d.llm_calls.forEach((c) => push(c.parent_span_id, c));
  const startOf = (x: Span | LlmCall) => x.started_at;
  const rows: WaterfallRow[] = [];
  const walk = (parent: string | null, depth: number, guard = 0) => {
    if (guard > 50) return;
    for (const item of (children.get(parent) ?? []).sort((a, b) => startOf(a) - startOf(b))) {
      if ("kind" in item) {
        rows.push({
          key: `s-${item.id}`, depth, label: item.name, kind: item.kind, agentId: item.agent_id,
          start: item.started_at, end: item.ended_at, status: item.status, span: item,
        });
        walk(item.id, depth + 1, guard + 1);
      } else {
        rows.push({
          key: `l-${item.id}`, depth, label: `LLM ${item.model ?? ""}`.trim(), kind: "llm", agentId: item.agent_id,
          start: item.started_at, end: item.started_at + (item.duration_ms ?? 0) / 1000, status: item.status, call: item,
        });
      }
    }
  };
  walk(null, 0);
  return rows;
}

export function runBounds(d: RunDetail): [number, number] {
  let start = d.run.started_at;
  let end = d.run.ended_at ?? d.run.last_activity ?? start;
  for (const s of d.spans) {
    start = Math.min(start, s.started_at);
    end = Math.max(end, s.ended_at ?? s.started_at);
  }
  for (const c of d.llm_calls) end = Math.max(end, c.started_at + (c.duration_ms ?? 0) / 1000);
  for (const m of d.messages) end = Math.max(end, m.ts);
  return [start, Math.max(end, start + 0.001)];
}

/** Live-Event in einen geladenen Run einarbeiten (ersetzt nach ID oder hängt an). */
export function applyRunEvent(d: RunDetail, type: string, data: any): RunDetail { // eslint-disable-line @typescript-eslint/no-explicit-any
  const upsert = <T extends { id: unknown }>(list: T[], item: T): T[] => {
    const i = list.findIndex((x) => x.id === item.id);
    if (i < 0) return [...list, item];
    const copy = list.slice();
    copy[i] = { ...copy[i], ...item };
    return copy;
  };
  switch (type) {
    case "run":
      return { ...d, run: { ...d.run, ...data } };
    case "span":
      return { ...d, spans: upsert(d.spans, data) };
    case "llm_call":
      return { ...d, llm_calls: upsert(d.llm_calls, data) };
    case "message":
      return { ...d, messages: upsert(d.messages, data) };
    case "tool":
      return { ...d, tools: upsert(d.tools, data) };
    case "log":
      return d.logs.some((l) => l.id === data.id) ? d : { ...d, logs: [...d.logs, data] };
    case "agent":
      return { ...d, agents: { ...d.agents, [String(data.id)]: data } };
    default:
      return d;
  }
}
