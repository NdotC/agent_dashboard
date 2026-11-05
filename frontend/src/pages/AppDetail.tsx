import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { LlmCallsTable } from "../components/LlmCallsTable";
import { LogView } from "../components/LogView";
import { RunsTable, useRuns } from "../components/RunsTable";
import { AgentDot, Badge, Card, CodeBlock, ContainerStatus, Empty, ErrorBox, KeyValue, Kpi, Loading, PageHeader, Tabs } from "../components/ui";
import { api, type App, type Graph } from "../lib/api";
import { agentColor } from "../lib/colors";
import { fmtAgo, fmtCompact, fmtDateTime, fmtMs, fmtNum, prettyJson } from "../lib/format";
import { useLive, useThrottled } from "../lib/live";
import { CommGraph } from "../run/CommGraph";

type Tab = "overview" | "runs" | "logs" | "llm" | "container";

export function AppDetailPage() {
  const appId = Number(useParams().appId);
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "overview";
  const qc = useQueryClient();
  const app = useQuery({ queryKey: ["app", appId], queryFn: () => api<App>(`/api/apps/${appId}`) });
  const graph = useQuery({ queryKey: ["app-graph", appId], queryFn: () => api<Graph>(`/api/apps/${appId}/graph?days=7`) });
  const runs = useRuns({ app_id: appId, limit: 50 }, `app:${appId}`);
  const refresh = useThrottled(() => {
    qc.invalidateQueries({ queryKey: ["app", appId] });
    qc.invalidateQueries({ queryKey: ["app-graph", appId] });
  }, 3000);
  useLive([`app:${appId}`], (ev) => {
    if (ev.type !== "log") refresh();
  });

  if (app.isLoading) return <Loading />;
  if (app.error || !app.data) return <ErrorBox error={app.error ?? "Nicht gefunden"} />;
  const a = app.data;
  const setTab = (t: Tab) => setParams((p) => { p.set("tab", t); return p; }, { replace: true });

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        back={<Link to="/" className="hover:underline">Übersicht</Link>}
        title={<span className="flex items-center gap-3">{a.name} <ContainerStatus status={a.status} /></span>}
        subtitle={
          <span className="flex flex-wrap gap-x-3 gap-y-1">
            {a.image && <span>Image <b className="font-medium text-fg">{a.image}</b></span>}
            {a.started_at && a.status === "running" && <span>läuft seit {fmtAgo(a.started_at)}</span>}
            {a.restart_count > 0 && <Badge tone="warning">{a.restart_count} Neustarts</Badge>}
            {a.exit_code != null && a.status !== "running" && <Badge tone={a.exit_code ? "critical" : "neutral"}>Exit-Code {a.exit_code}</Badge>}
          </span>
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Agenten" value={fmtNum(a.agents.length)} />
        <Kpi label="Runs 24h" value={fmtNum(a.runs_24h)} sub={a.active_runs ? `${a.active_runs} laufen gerade` : undefined} />
        <Kpi label="LLM-Aufrufe 24h" value={fmtCompact(a.llm_calls_24h)} sub={`${fmtCompact(a.tokens_in_24h + a.tokens_out_24h)} Tokens`} />
        <Kpi label="Fehler 24h" value={fmtNum(a.errors_24h)} tone={a.errors_24h ? "critical" : undefined} />
      </div>
      <Card bodyClass="p-0">
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          items={[
            { value: "overview", label: "Agenten & Kommunikation" },
            { value: "runs", label: "Runs", count: runs.data?.runs.length },
            { value: "logs", label: "Logs" },
            { value: "llm", label: "LLM-Aufrufe" },
            { value: "container", label: "Container" },
          ]}
        />
        {tab === "overview" && (
          <div className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
            <div className="min-w-0">
              <h3 className="mb-2 text-[13px] font-semibold">Agenten</h3>
              {a.agents.length === 0 ? (
                <Empty title="Noch keine Agenten" icon={<Bot size={20} />}>Agenten erscheinen, sobald LLM-Aufrufe oder SDK-Daten eintreffen.</Empty>
              ) : (
                <ul className="flex flex-col divide-y divide-line rounded-lg border border-line">
                  {a.agents.map((ag) => (
                    <li key={ag.id}>
                      <Link to={`/agents/${ag.id}`} className="flex items-center gap-3 px-3 py-2.5 hover:bg-surface-2">
                        <AgentDot color={agentColor(ag, a.agents)} size={10} />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[13px] font-medium">{ag.display_name || ag.name}</div>
                          <div className="truncate text-[12px] text-fg-2">{[ag.role, ag.model].filter(Boolean).join(" · ") || "–"}</div>
                        </div>
                        <div className="text-right text-[12px] text-fg-2 tabular">
                          <div>{fmtNum(ag.llm_calls_24h ?? 0)} LLM · Ø {fmtMs(ag.avg_ms_24h)}</div>
                          <div>aktiv {fmtAgo(ag.last_seen)}</div>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="min-w-0">
              <h3 className="mb-2 text-[13px] font-semibold">Kommunikation (letzte 7 Tage)</h3>
              {graph.data && graph.data.nodes.length > 0 && graph.data.edges.length > 0 ? (
                <div className="overflow-hidden rounded-lg border border-line bg-surface-2/30">
                  <CommGraph graph={graph.data} agents={a.agents} height={420} vertical />
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-line px-4 py-10 text-center text-[13px] text-fg-2">
                  Noch keine Kommunikation zwischen Agenten. Mit dem agentdash-SDK (<code className="font-mono">agent()</code>-Blöcke) wird sichtbar, welcher Agent welchen beauftragt.
                </div>
              )}
            </div>
          </div>
        )}
        {tab === "runs" && <RunsTable runs={runs.data?.runs} agents={runs.data?.agents ?? {}} loading={runs.isLoading} />}
        {tab === "logs" && <LogView filter={{ app_id: appId }} agents={a.agents} height={600} />}
        {tab === "llm" && <LlmCallsTable filter={{ app_id: appId }} agents={a.agents} topic={`app:${appId}`} />}
        {tab === "container" && (
          <div className="flex flex-col gap-4 p-4">
            <KeyValue
              items={[
                ["Schlüssel", <code className="font-mono">{a.key}</code>],
                ["Quelle", a.source],
                ["Container", a.container_name ?? "–"],
                ["Container-ID", <code className="font-mono text-[12px]">{a.container_id?.slice(0, 12) ?? "–"}</code>],
                ["Image", a.image ?? "–"],
                ["Gestartet", fmtDateTime(a.started_at)],
                ["Zuerst gesehen", fmtDateTime(a.first_seen)],
                ["Neustarts", fmtNum(a.restart_count)],
              ]}
            />
            {a.labels && Object.keys(a.labels).length > 0 && (
              <div>
                <div className="mb-1 text-[12px] font-medium text-fg-2">Labels</div>
                <CodeBlock>{prettyJson(a.labels)}</CodeBlock>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
