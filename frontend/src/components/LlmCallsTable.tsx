import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronDown, ChevronRight, Cpu } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { api, qs, type Agent, type LlmCall } from "../lib/api";
import { fmtDateTime, fmtMs, fmtNum } from "../lib/format";
import { useLive, useThrottled } from "../lib/live";
import { LlmCallDetail } from "./LlmCallView";
import { AgentChip, Badge, Button, Empty, Loading } from "./ui";

export function LlmCallsTable({ filter, agents, topic }: { filter: { app_id?: number; agent_id?: number }; agents: Agent[]; topic: string }) {
  const qc = useQueryClient();
  const [limit, setLimit] = useState(50);
  const [open, setOpen] = useState<number | null>(null);
  const key = ["llm-calls", filter, limit];
  const q = useQuery({ queryKey: key, queryFn: () => api<LlmCall[]>(`/api/llm-calls${qs({ ...filter, limit })}`) });
  const refetch = useThrottled(() => qc.invalidateQueries({ queryKey: ["llm-calls", filter] }), 1500);
  useLive([topic], (ev) => {
    if (ev.type === "llm_call") refetch();
  });
  if (q.isLoading) return <Loading />;
  if (!q.data?.length)
    return (
      <Empty title="Noch keine LLM-Aufrufe" icon={<Cpu size={20} />}>
        LLM-Aufrufe werden erfasst, wenn der Agent Ollama über das Dashboard anspricht (<code className="font-mono">OLLAMA_HOST=http://agentdash:11434</code>).
      </Empty>
    );
  const byId = new Map(agents.map((a) => [a.id, a]));
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full min-w-[760px] text-[13px]">
        <thead>
          <tr className="border-b border-line text-left text-[12px] text-fg-2">
            <th className="w-8" />
            <th className="px-2 py-2 font-medium">Zeit</th>
            <th className="px-2 py-2 font-medium">Agent</th>
            <th className="px-2 py-2 font-medium">Modell</th>
            <th className="px-2 py-2 font-medium">Eingabe → Ausgabe</th>
            <th className="px-2 py-2 text-right font-medium">Dauer</th>
            <th className="px-4 py-2 text-right font-medium">Tokens</th>
          </tr>
        </thead>
        <tbody>
          {q.data.map((c) => (
            <Fragment key={c.id}>
              <tr onClick={() => setOpen(open === c.id ? null : c.id)} className={clsx("cursor-pointer border-b border-line/70 hover:bg-surface-2", open === c.id && "bg-surface-2")}>
                <td className="pl-3 text-fg-3">{open === c.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                <td className="whitespace-nowrap px-2 py-2 text-fg-2">{fmtDateTime(c.started_at)}</td>
                <td className="px-2 py-2">{c.agent_id != null && <AgentChip agent={byId.get(c.agent_id)} agents={agents} link={false} />}</td>
                <td className="px-2 py-2"><Badge>{c.model ?? "?"}</Badge></td>
                <td className="max-w-[420px] px-2 py-2">
                  <div className="truncate text-fg">{c.prompt_preview ?? "–"}</div>
                  <div className={clsx("truncate text-[12px]", c.status === "error" ? "text-critical-text" : "text-fg-2")}>
                    {c.status === "error" ? c.error : c.tool_calls?.length ? `→ Tool: ${c.tool_calls.map((t) => t.name).join(", ")}` : `→ ${c.response_preview ?? ""}`}
                  </div>
                </td>
                <td className="whitespace-nowrap px-2 py-2 text-right tabular">{fmtMs(c.duration_ms)}</td>
                <td className="whitespace-nowrap px-4 py-2 text-right tabular">{fmtNum(c.tokens_in)} → {fmtNum(c.tokens_out)}</td>
              </tr>
              {open === c.id && (
                <tr className="border-b border-line">
                  <td colSpan={7} className="bg-surface px-4 py-3">
                    {c.run_id && <div className="mb-2 text-[12px]"><Link className="text-accent hover:underline" to={`/runs/${c.run_id}`}>Zum Run →</Link></div>}
                    <LlmCallDetail id={c.id} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {q.data.length >= limit && <div className="flex justify-center p-3"><Button variant="ghost" onClick={() => setLimit(limit + 50)}>Mehr laden</Button></div>}
    </div>
  );
}
