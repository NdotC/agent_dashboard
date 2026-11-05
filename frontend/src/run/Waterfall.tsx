import clsx from "clsx";
import { useMemo, useState } from "react";
import { LlmCallDetail } from "../components/LlmCallView";
import { CodeBlock } from "../components/ui";
import type { RunDetail } from "../lib/api";
import { agentColor, agentLabel } from "../lib/colors";
import { fmtMs, prettyJson } from "../lib/format";
import { buildWaterfall, runBounds, type WaterfallRow } from "./model";

const KIND_LABEL: Record<string, string> = { run: "Run", agent: "Agent", tool: "Tool", step: "Schritt", llm: "LLM" };

export function Waterfall({ detail }: { detail: RunDetail }) {
  const rows = useMemo(() => buildWaterfall(detail), [detail]);
  const [start, end] = runBounds(detail);
  const total = end - start;
  const [selected, setSelected] = useState<WaterfallRow | null>(null);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  if (!rows.length) return <div className="py-10 text-center text-[13px] text-fg-2">Keine Spans in diesem Run.</div>;

  return (
    <div className="flex flex-col gap-4">
      <div className="scroll-thin overflow-x-auto">
        <div className="min-w-[640px]">
          <div className="flex border-b border-line pb-1 text-[11px] text-fg-3">
            <div className="w-[280px] shrink-0">Span</div>
            <div className="relative h-4 flex-1">
              {ticks.map((t) => (
                <span key={t} className="absolute whitespace-nowrap tabular" style={{ left: `${t * 100}%`, transform: `translateX(-${t * 100}%)` }}>
                  {fmtMs(t * total * 1000)}
                </span>
              ))}
            </div>
          </div>
          {rows.map((r) => {
            const left = ((r.start - start) / total) * 100;
            const width = Math.max((((r.end ?? end) - r.start) / total) * 100, 0.4);
            const agent = r.agentId != null ? detail.agents[String(r.agentId)] : null;
            const color = r.kind === "run" ? "var(--fg-3)" : agentColor(agent, detail.agents);
            return (
              <button
                key={r.key}
                onClick={() => setSelected(selected?.key === r.key ? null : r)}
                className={clsx("flex w-full items-center py-[3px] text-left hover:bg-surface-2", selected?.key === r.key && "bg-accent-soft")}
              >
                <div className="flex w-[280px] shrink-0 items-center gap-1.5 truncate pr-2 text-[12px]" style={{ paddingLeft: r.depth * 14 }}>
                  <span className="rounded bg-surface-2 px-1 text-[10px] font-medium text-fg-2">{KIND_LABEL[r.kind]}</span>
                  <span className={clsx("truncate", r.status === "error" ? "text-critical-text" : "text-fg")}>{r.label}</span>
                  {agent && r.kind !== "agent" && <span className="truncate text-fg-3">· {agentLabel(agent)}</span>}
                </div>
                <div className="relative h-5 flex-1">
                  {ticks.slice(1, -1).map((t) => <span key={t} className="absolute inset-y-0 w-px bg-line" style={{ left: `${t * 100}%` }} />)}
                  <div
                    className={clsx("absolute top-1 h-3 rounded-[4px]", r.end == null && "pulse")}
                    style={{
                      left: `${left}%`,
                      width: `${width}%`,
                      background: r.status === "error" ? "var(--critical)" : color,
                      opacity: r.kind === "llm" ? 0.7 : 1,
                    }}
                    title={`${r.label}: ${fmtMs(((r.end ?? end) - r.start) * 1000)}`}
                  />
                  <span
                    className="absolute top-0.5 whitespace-nowrap px-1.5 text-[11px] text-fg-2 tabular"
                    style={left + width > 82 ? { right: `${100 - left}%` } : { left: `${left + width}%` }}
                  >
                    {r.end == null ? "läuft" : fmtMs((r.end - r.start) * 1000)}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>
      {selected && (
        <div className="rounded-lg border border-line p-3">
          <div className="mb-2 text-[13px] font-semibold">{selected.label}</div>
          {selected.call ? (
            <LlmCallDetail id={selected.call.id} />
          ) : selected.span ? (
            <div className="flex flex-col gap-2 text-[12px]">
              {selected.span.status_message && <div className="text-critical-text">{selected.span.status_message}</div>}
              {selected.span.input && <><div className="font-medium text-fg-2">Eingabe</div><CodeBlock>{prettyJson(selected.span.input)}</CodeBlock></>}
              {selected.span.output && <><div className="font-medium text-fg-2">Ausgabe</div><CodeBlock>{prettyJson(selected.span.output)}</CodeBlock></>}
              {selected.span.attributes && <><div className="font-medium text-fg-2">Attribute</div><CodeBlock>{prettyJson(selected.span.attributes)}</CodeBlock></>}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
