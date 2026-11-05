import clsx from "clsx";
import { useMemo } from "react";
import type { RunDetail } from "../lib/api";
import { agentColor } from "../lib/colors";
import { fmtMs, fmtTime } from "../lib/format";
import { buildSequence, type SeqRow } from "./model";

const LANE_W = 165;
const GUTTER = 70;
const ROW_H = 34;
const HEAD_H = 46;
const KIND_LABEL: Record<string, string> = {
  call: "beauftragt", return: "liefert zurück", handoff: "übergibt", feedback: "Feedback", message: "Nachricht",
  request: "Anfrage", response: "Antwort", broadcast: "Broadcast",
};

function preview(text: string | null | undefined, n = 38) {
  if (!text) return "";
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n) + "…" : t;
}

function fit(text: string, px: number) {
  const max = Math.max(12, Math.floor(px / 6.3) - 2);
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

export function SequenceDiagram({ detail, until, selected, onSelect }: {
  detail: RunDetail;
  until?: number | null;
  selected?: string | null;
  onSelect?: (row: SeqRow) => void;
}) {
  const { lanes, rows } = useMemo(() => buildSequence(detail), [detail]);
  const laneX = new Map(lanes.map((l, i) => [l.id, GUTTER + i * LANE_W + LANE_W / 2]));
  const width = Math.max(GUTTER + lanes.length * LANE_W + 120, 320);
  const height = HEAD_H + rows.length * ROW_H + 20;
  const colorOf = (id: string) => {
    if (id === "start") return "var(--fg-3)";
    if (id === "llm") return "var(--fg-2)";
    const agentId = Number(id.split("-")[1]);
    return agentColor(detail.agents[String(agentId)], detail.agents);
  };

  if (!rows.length) return <div className="py-10 text-center text-[13px] text-fg-2">Noch keine Interaktionen in diesem Run.</div>;

  return (
    <div className="scroll-thin overflow-x-auto">
      <svg width={width} height={height} className="block text-fg" role="img" aria-label="Sequenzdiagramm der Kommunikation">
        <defs>
          <marker id="seq-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--fg-2)" />
          </marker>
        </defs>
        {lanes.map((l) => {
          const x = laneX.get(l.id)!;
          return (
            <g key={l.id}>
              <line x1={x} x2={x} y1={HEAD_H - 6} y2={height - 6} stroke="var(--line)" strokeDasharray="3 4" />
              <rect x={x - 70} y={6} width={140} height={28} rx={6} fill="var(--surface-2)" stroke="var(--line)" />
              <circle cx={x - 56} cy={20} r={4.5} fill={colorOf(l.id)} />
              <text x={x - 46} y={24} fontSize={12} fontWeight={600} fill="var(--fg)">
                {l.name.length > 16 ? l.name.slice(0, 15) + "…" : l.name}
              </text>
            </g>
          );
        })}
        {rows.map((r, i) => {
          const y = HEAD_H + i * ROW_H + ROW_H / 2;
          const x1 = laneX.get(r.from) ?? 0;
          const x2 = laneX.get(r.to) ?? 0;
          const future = until != null && r.ts > until;
          const isSel = selected === r.key;
          const label =
            r.kind === "message" ? `${KIND_LABEL[r.msg.kind] ?? r.msg.kind}${r.msg.content ? ": " + preview(r.msg.content) : ""}`
            : r.kind === "llm" ? `${r.call.model ?? "LLM"} · ${fmtMs(r.call.duration_ms)}${r.call.tool_calls?.length ? " · Tool-Wahl" : ""}`
            : `Tool ${r.label}`;
          const error = (r.kind === "llm" && r.call.status === "error") || (r.kind === "tool" && r.span.status === "error");
          return (
            <g
              key={r.key}
              className={clsx("cursor-pointer", future && "opacity-20")}
              onClick={() => onSelect?.(r)}
            >
              <rect x={0} y={y - ROW_H / 2} width={width} height={ROW_H} fill={isSel ? "var(--accent-soft)" : "transparent"} className="hover:fill-[var(--surface-2)]" />
              <text x={6} y={y + 4} fontSize={10} fill="var(--fg-3)" className="tabular">{fmtTime(r.ts)}</text>
              {r.kind !== "message" ? (
                <>
                  {r.kind === "tool" ? (
                    <rect x={x1 - 7} y={y - 8} width={14} height={16} rx={3} fill={error ? "var(--critical)" : colorOf(r.from)} />
                  ) : (
                    <circle cx={x1} cy={y} r={6} fill="var(--surface)" stroke={error ? "var(--critical)" : colorOf(r.from)} strokeWidth={2} />
                  )}
                  <text x={x1 + 13} y={y + 4} fontSize={11} fill={error ? "var(--critical-text)" : "var(--fg-2)"}>
                    {r.kind === "llm" ? "LLM " : ""}{label}
                  </text>
                </>
              ) : (
                <>
                  <line
                    x1={x1} y1={y} x2={x2 + (x2 > x1 ? -4 : 4)} y2={y}
                    stroke={colorOf(r.from)}
                    strokeWidth={2}
                    strokeDasharray={r.msg.kind === "return" ? "5 3" : undefined}
                    markerEnd="url(#seq-arrow)"
                  />
                  <text x={(x1 + x2) / 2} y={y - 6} fontSize={11} textAnchor="middle" fill="var(--fg-2)">
                    {fit(label, Math.abs(x2 - x1))}
                  </text>
                </>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
