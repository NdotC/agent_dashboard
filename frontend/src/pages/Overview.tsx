import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Container, Cpu, HardDrive, Radio } from "lucide-react";
import { Link } from "react-router-dom";
import { HourlyBars } from "../components/Charts";
import { AgentChip, Badge, Card, ContainerStatus, Empty, ErrorBox, Kpi, Loading, PageHeader } from "../components/ui";
import { api, type App, type OllamaState, type Overview } from "../lib/api";
import { fmtAgo, fmtBytes, fmtCompact, fmtNum } from "../lib/format";
import { useLive, useThrottled } from "../lib/live";

function OllamaCard({ state }: { state: OllamaState }) {
  return (
    <Card title={<span className="flex items-center gap-2"><Cpu size={15} /> Ollama</span>}
      actions={state.reachable ? <Badge tone="good">erreichbar{state.version ? ` · ${state.version}` : ""}</Badge> : <Badge tone="critical">nicht erreichbar</Badge>}>
      {!state.reachable ? (
        <div className="text-[13px] text-fg-2">
          {state.upstream} antwortet nicht.{state.error && <div className="mt-1 font-mono text-[12px] text-critical-text">{state.error}</div>}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div>
            <div className="mb-1.5 text-[12px] text-fg-2">Geladene Modelle</div>
            {state.loaded?.length ? (
              <ul className="flex flex-col gap-1.5">
                {state.loaded.map((m) => (
                  <li key={m.name} className="flex items-center justify-between gap-2 text-[13px]">
                    <span className="truncate font-medium">{m.name}</span>
                    <span className="shrink-0 text-[12px] text-fg-2 tabular">
                      {m.parameter_size} {m.quantization && `· ${m.quantization}`} · <HardDrive size={11} className="inline" /> {fmtBytes(m.size_vram)} VRAM
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-[13px] text-fg-3">Kein Modell im Speicher</div>
            )}
          </div>
          <div className="text-[12px] text-fg-2">
            {state.available?.length ?? 0} Modelle installiert · {fmtBytes(state.vram_used)} VRAM belegt
          </div>
        </div>
      )}
    </Card>
  );
}

function AppCard({ app, now }: { app: App; now: number }) {
  return (
    <Link to={`/apps/${app.id}`} className="card flex min-w-0 flex-col gap-3 p-4 transition-colors hover:border-line-strong">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold">{app.name}</div>
          <div className="truncate text-[12px] text-fg-3">{app.image ?? (app.source === "docker" ? app.container_name : `Quelle: ${app.source}`)}</div>
        </div>
        <ContainerStatus status={app.status} />
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {app.agents.length ? app.agents.slice(0, 6).map((a) => <AgentChip key={a.id} agent={a} agents={app.agents} link={false} />) : <span className="text-[12px] text-fg-3">Noch keine Agenten erkannt</span>}
        {app.agents.length > 6 && <span className="text-[12px] text-fg-3">+{app.agents.length - 6}</span>}
      </div>
      <div className="grid grid-cols-3 gap-2 border-t border-line pt-3 text-[12px]">
        <div><div className="text-fg-2">LLM 24h</div><div className="tabular text-[15px] font-semibold">{fmtCompact(app.llm_calls_24h)}</div></div>
        <div><div className="text-fg-2">Runs 24h</div><div className="tabular text-[15px] font-semibold">{fmtCompact(app.runs_24h)}{app.active_runs > 0 && <span className="ml-1.5 inline-flex items-center gap-0.5 text-[11px] font-medium text-accent"><Radio size={11} className="pulse" />{app.active_runs}</span>}</div></div>
        <div><div className="text-fg-2">Fehler 24h</div><div className={`tabular text-[15px] font-semibold ${app.errors_24h ? "text-critical-text" : ""}`}>{fmtNum(app.errors_24h)}</div></div>
      </div>
      <div className="min-w-0 border-t border-line pt-2.5">
        <div className="mb-0.5 flex justify-between text-[11px] text-fg-3"><span>Letzte Aktivität</span><span>{fmtAgo(app.last_activity, now)}</span></div>
        <div className={`truncate font-mono text-[12px] ${app.last_log?.level === "error" ? "text-critical-text" : "text-fg-2"}`}>{app.last_log?.message ?? "–"}</div>
      </div>
    </Link>
  );
}

export function OverviewPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/api/overview"), refetchInterval: 30_000 });
  const refresh = useThrottled(() => qc.invalidateQueries({ queryKey: ["overview"] }), 2000);
  useLive(["overview"], (ev) => {
    if (ev.type === "ollama") qc.setQueryData<Overview>(["overview"], (d) => (d ? { ...d, ollama: ev.data } : d));
    else refresh();
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const k = d.kpis;
  const now = Date.now() / 1000;
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Übersicht"
        subtitle="Alle Anwendungen und Agenten auf dem Homeserver."
        actions={
          <Badge tone={d.docker_connected ? "good" : "warning"} title="Verbindung zur Docker-API">
            <Container size={12} /> Docker {d.docker_connected ? "verbunden" : "nicht verbunden"}
          </Badge>
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Anwendungen aktiv" value={<>{k.apps_running}<span className="text-base font-normal text-fg-3"> / {k.apps_total}</span></>} />
        <Kpi label="Agenten" value={fmtNum(k.agents_total)} />
        <Kpi label="Laufende Runs" value={fmtNum(k.active_runs)} />
        <Kpi label="LLM-Aufrufe 24h" value={fmtCompact(k.llm_calls_24h)} />
        <Kpi label="Tokens 24h" value={fmtCompact(k.tokens_24h)} />
        <Kpi label="Fehler 24h" value={fmtNum(k.errors_24h)} tone={k.errors_24h ? "critical" : undefined} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="LLM-Aufrufe pro Stunde (24 h)" className="lg:col-span-1"><HourlyBars data={d.hours} dataKey="llm_calls" unit="Aufrufe" /></Card>
        <Card title="Fehler pro Stunde (24 h)" className="lg:col-span-1"><HourlyBars data={d.hours} dataKey="errors" unit="Fehler" color="var(--critical)" /></Card>
        <OllamaCard state={d.ollama} />
      </div>
      <div>
        <h2 className="mb-3 flex items-center gap-2 text-[13px] font-semibold"><Boxes size={15} /> Anwendungen</h2>
        {d.apps.length === 0 ? (
          <Card>
            <Empty title="Noch keine Anwendungen" icon={<Boxes size={22} />}>
              Gib deinen Agent-Containern das Label <code className="font-mono">agentdash.enable=true</code> oder setze
              <code className="font-mono"> OLLAMA_HOST=http://agentdash:11434</code> – sie erscheinen dann automatisch hier.
            </Empty>
          </Card>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {d.apps.map((a) => <AppCard key={a.id} app={a} now={now} />)}
          </div>
        )}
      </div>
    </div>
  );
}
