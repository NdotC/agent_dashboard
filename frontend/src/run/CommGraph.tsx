import dagre from "@dagrejs/dagre";
import {
  BaseEdge, Controls, EdgeLabelRenderer, Handle, MarkerType, Position, ReactFlow, getBezierPath,
  type Edge, type EdgeProps, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import clsx from "clsx";
import { Bot, Play } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import type { Agent, Graph } from "../lib/api";
import { agentColor } from "../lib/colors";
import { fmtNum } from "../lib/format";

const NODE_W = 190;
const NODE_H = 64;
const KIND_LABEL: Record<string, string> = {
  call: "Aufruf", return: "Rückgabe", handoff: "Übergabe", feedback: "Feedback", request: "Anfrage",
  response: "Antwort", broadcast: "Broadcast", message: "Nachricht",
};

type AgentNodeData = { vertical?: boolean; name: string; color: string; model?: string | null; llm?: number; active: boolean; start: boolean; agentId: number | null };

function AgentNode({ data }: NodeProps<Node<AgentNodeData>>) {
  return (
    <div
      className={clsx(
        "flex items-center gap-2.5 rounded-lg border bg-surface px-3 py-2 shadow-sm transition-shadow",
        data.active ? "border-accent ring-2 ring-accent/40" : "border-line-strong",
      )}
      style={{ width: NODE_W, height: NODE_H }}
    >
      <Handle type="target" position={data.vertical ? Position.Top : Position.Left} className="!h-2 !w-2 !border-0 !bg-line-strong" />
      <div
        className={clsx("flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white", data.active && "pulse")}
        style={{ background: data.start ? "var(--fg-3)" : data.color }}
      >
        {data.start ? <Play size={14} /> : <Bot size={15} />}
      </div>
      <div className="min-w-0">
        <div className="truncate text-[13px] font-semibold text-fg">{data.name}</div>
        <div className="truncate text-[11px] text-fg-2">
          {data.start ? "Auslöser" : [data.model, data.llm ? `${fmtNum(data.llm)} LLM` : null].filter(Boolean).join(" · ") || "Agent"}
        </div>
      </div>
      <Handle type="source" position={data.vertical ? Position.Bottom : Position.Right} className="!h-2 !w-2 !border-0 !bg-line-strong" />
    </div>
  );
}

type CountEdgeData = { count: number; back: number; kinds: Record<string, number>; backKinds: Record<string, number>; hot: boolean };

function CountEdge(props: EdgeProps<Edge<CountEdgeData>>) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd, id } = props;
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const describe = (k: Record<string, number>) => Object.entries(k).map(([kind, n]) => `${n}× ${KIND_LABEL[kind] ?? kind}`).join(", ");
  const kinds = `→ ${describe(data?.kinds ?? {})}${data?.back ? `\n← ${describe(data.backKinds)}` : ""}`;
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        markerStart={props.markerStart}
        style={{ stroke: data?.hot ? "var(--accent)" : "var(--line-strong)", strokeWidth: data?.hot ? 2.5 : 1.5 }}
        className={data?.hot ? "react-flow__edge-path animated" : undefined}
      />
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan pointer-events-auto absolute rounded-full border border-line bg-surface px-1.5 py-0.5 text-[11px] font-medium text-fg-2 tabular"
          style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          title={kinds}
        >
          {data?.back ? `${data.count} ⇄ ${data.back}` : data?.count}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

const nodeTypes = { agent: AgentNode };
const edgeTypes = { count: CountEdge };

interface MergedEdge {
  id: string;
  source: string;
  target: string;
  count: number;
  back: number;
  kinds: Record<string, number>;
  backKinds: Record<string, number>;
  last_ts: number;
}

/** Fasst A→B und B→A zu einer Kante zusammen. Vorwärts ist die Richtung mit Aufrufen/Übergaben. */
export function mergeEdges(edges: Graph["edges"]): MergedEdge[] {
  const byKey = new Map(edges.map((e) => [`${e.source}->${e.target}`, e]));
  const done = new Set<string>();
  const out: MergedEdge[] = [];
  const forwardScore = (e: Graph["edges"][number]) => e.count - 2 * (e.kinds.return ?? 0) + (e.source === "start" ? 100 : 0);
  for (const e of edges) {
    const key = `${e.source}->${e.target}`;
    const rev = byKey.get(`${e.target}->${e.source}`);
    if (done.has(key)) continue;
    done.add(key);
    if (rev) done.add(`${e.target}->${e.source}`);
    const [fwd, bwd] = rev && forwardScore(rev) > forwardScore(e) ? [rev, e] : [e, rev];
    out.push({
      id: `${fwd.source}->${fwd.target}`,
      source: fwd.source,
      target: fwd.target,
      count: fwd.count,
      back: bwd?.count ?? 0,
      kinds: fwd.kinds,
      backKinds: bwd?.kinds ?? {},
      last_ts: Math.max(fwd.last_ts, bwd?.last_ts ?? 0),
    });
  }
  return out;
}

function layout(graph: Graph, edges: MergedEdge[], vertical: boolean): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph();
  g.setGraph(vertical
    ? { rankdir: "TB", nodesep: 40, ranksep: 70, marginx: 20, marginy: 20 }
    : { rankdir: "LR", nodesep: 50, ranksep: 110, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  graph.nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  const pos = new Map<string, { x: number; y: number }>();
  graph.nodes.forEach((n) => {
    const p = g.node(n.id);
    pos.set(n.id, { x: (p?.x ?? 0) - NODE_W / 2, y: (p?.y ?? 0) - NODE_H / 2 });
  });
  return pos;
}

export function CommGraph({ graph, agents, active = new Set(), hotSince, height = 460, vertical = false }: {
  graph: Graph;
  agents: Agent[] | Record<string, Agent>;
  active?: Set<number>;
  /** Kanten mit Nachrichten nach diesem Zeitpunkt werden hervorgehoben */
  hotSince?: number | null;
  height?: number;
  /** Layout von oben nach unten (für schmale Container) */
  vertical?: boolean;
}) {
  const navigate = useNavigate();
  const agentById = useMemo(() => {
    const list = Array.isArray(agents) ? agents : Object.values(agents);
    return new Map(list.map((a) => [a.id, a]));
  }, [agents]);
  const structureKey = graph.nodes.map((n) => n.id).join(",") + "|" + graph.edges.map((e) => e.id).join(",");
  const merged = useMemo(() => mergeEdges(graph.edges), [graph.edges]);
  const positions = useMemo(() => layout(graph, merged, vertical), [structureKey, vertical]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodes: Node<AgentNodeData>[] = graph.nodes.map((n) => ({
    id: n.id,
    type: "agent",
    position: positions.get(n.id) ?? { x: 0, y: 0 },
    data: {
      vertical,
      name: n.name,
      color: agentColor(n.agent_id != null ? agentById.get(n.agent_id) : null, agents),
      model: n.model,
      llm: n.llm_calls,
      active: n.agent_id != null && active.has(n.agent_id),
      start: n.kind === "start",
      agentId: n.agent_id,
    },
  }));
  const edges: Edge<CountEdgeData>[] = merged.map((e) => {
    const hot = hotSince != null && e.last_ts >= hotSince;
    const marker = { type: MarkerType.ArrowClosed, width: 16, height: 16, color: hot ? "var(--accent)" : "var(--line-strong)" };
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      type: "count",
      markerEnd: marker,
      markerStart: e.back ? marker : undefined,
      data: { count: e.count, back: e.back, kinds: e.kinds, backKinds: e.backKinds, hot },
    };
  });

  return (
    <div style={{ height }} className="w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1.2 }}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          const id = (node.data as AgentNodeData).agentId;
          if (id != null) navigate(`/agents/${id}`);
        }}
        minZoom={0.3}
      >
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  );
}
