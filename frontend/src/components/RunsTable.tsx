import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Workflow } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api, qs, type Agent, type Run } from "../lib/api";
import { fmtDateTime, fmtDuration, fmtNum, shortId } from "../lib/format";
import { useLive, useThrottled } from "../lib/live";
import { AgentChip, Badge, Empty, Loading, StatusBadge } from "./ui";

export function useRuns(params: { app_id?: number; agent_id?: number; status?: string; q?: string; limit?: number }, liveTopic: string) {
  const qc = useQueryClient();
  const key = ["runs", params];
  const query = useQuery({
    queryKey: key,
    queryFn: () => api<{ runs: Run[]; agents: Record<string, Agent> }>(`/api/runs${qs(params)}`),
  });
  const refetch = useThrottled(() => qc.invalidateQueries({ queryKey: ["runs"] }), 1500);
  useLive([liveTopic], (ev) => {
    if (ev.type === "run") refetch();
  });
  return query;
}

export function RunsTable({ runs, agents, showApp = false, loading }: {
  runs: Run[] | undefined; agents: Record<string, Agent>; showApp?: boolean; loading?: boolean;
}) {
  const navigate = useNavigate();
  if (loading) return <Loading />;
  if (!runs?.length)
    return (
      <Empty title="Noch keine Runs" icon={<Workflow size={20} />}>
        Ein Run entsteht automatisch aus LLM-Aufrufen über den Proxy oder explizit mit <code className="font-mono">agentdash.run()</code>.
      </Empty>
    );
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full min-w-[720px] text-[13px]">
        <thead>
          <tr className="border-b border-line text-left text-[12px] text-fg-2">
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-2 py-2 font-medium">Run</th>
            {showApp && <th className="px-2 py-2 font-medium">Anwendung</th>}
            <th className="px-2 py-2 font-medium">Agenten</th>
            <th className="px-2 py-2 font-medium">Start</th>
            <th className="px-2 py-2 text-right font-medium">Dauer</th>
            <th className="px-2 py-2 text-right font-medium">LLM</th>
            <th className="px-4 py-2 text-right font-medium">Tokens</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr
              key={r.id}
              onClick={() => navigate(`/runs/${r.id}`)}
              className="cursor-pointer border-b border-line/70 last:border-0 hover:bg-surface-2"
            >
              <td className="px-4 py-2"><StatusBadge status={r.status} /></td>
              <td className="max-w-[340px] px-2 py-2">
                <Link to={`/runs/${r.id}`} className="block truncate font-medium text-fg hover:underline" onClick={(e) => e.stopPropagation()}>
                  {r.title || `Run ${shortId(r.id)}`}
                </Link>
                <div className="flex items-center gap-1.5 text-[11px] text-fg-3">
                  <span className="font-mono">{shortId(r.id)}</span>
                  {r.source === "auto" && <Badge className="!py-0">auto</Badge>}
                  {r.errors > 0 && <Badge tone="critical" className="!py-0">{r.errors} Fehler</Badge>}
                </div>
              </td>
              {showApp && <td className="px-2 py-2 text-fg-2">{r.app_name}</td>}
              <td className="px-2 py-2">
                <div className="flex max-w-[260px] flex-wrap gap-x-2.5 gap-y-1">
                  {(r.agent_ids ?? []).slice(0, 5).map((id) => <AgentChip key={id} agent={agents[String(id)]} agents={agents} link={false} />)}
                  {(r.agent_ids?.length ?? 0) > 5 && <span className="text-[12px] text-fg-3">+{r.agent_ids!.length - 5}</span>}
                </div>
              </td>
              <td className="whitespace-nowrap px-2 py-2 text-fg-2">{fmtDateTime(r.started_at)}</td>
              <td className="whitespace-nowrap px-2 py-2 text-right tabular text-fg-2">
                {fmtDuration(r.started_at, r.status === "running" ? null : r.ended_at ?? r.last_activity)}
              </td>
              <td className="px-2 py-2 text-right tabular">{fmtNum(r.llm_calls)}</td>
              <td className="px-4 py-2 text-right tabular">{fmtNum(r.tokens_in + r.tokens_out)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
