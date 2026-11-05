import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Pencil, Wrench } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { HourlyBars, HourlyLine } from "../components/Charts";
import { LlmCallsTable } from "../components/LlmCallsTable";
import { LogView } from "../components/LogView";
import { RunsTable, useRuns } from "../components/RunsTable";
import { AgentChip, AgentDot, Button, Card, ErrorBox, inputClass, Kpi, Loading, PageHeader, Tabs } from "../components/ui";
import { api, type Agent, type AgentDetail, type App } from "../lib/api";
import { agentColor, SERIES } from "../lib/colors";
import { fmtAgo, fmtCompact, fmtMs, fmtNum } from "../lib/format";
import { useLive, useThrottled } from "../lib/live";

type Tab = "runs" | "llm" | "logs";

function EditAgent({ agent, onDone }: { agent: AgentDetail; onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(agent.display_name ?? "");
  const [color, setColor] = useState(agent.color ?? "");
  const m = useMutation({
    mutationFn: () => api<Agent>(`/api/agents/${agent.id}`, { method: "PATCH", body: JSON.stringify({ display_name: name, color }) }),
    onSuccess: () => {
      qc.invalidateQueries();
      onDone();
    },
  });
  return (
    <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
      <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder={agent.name} aria-label="Anzeigename" />
      <div className="flex items-center gap-1" role="radiogroup" aria-label="Farbe">
        <button type="button" onClick={() => setColor("")} aria-checked={!color} role="radio"
          className={`h-6 rounded-full border px-2 text-[11px] ${!color ? "border-accent text-fg" : "border-line text-fg-2"}`}>auto</button>
        {SERIES.map((c) => (
          <button key={c} type="button" role="radio" aria-checked={color === c} onClick={() => setColor(c)}
            className={`h-6 w-6 rounded-full border-2 ${color === c ? "border-fg" : "border-transparent"}`} style={{ background: c }} aria-label={c} />
        ))}
      </div>
      <Button type="submit" variant="primary" disabled={m.isPending}>Speichern</Button>
      <Button onClick={onDone} variant="ghost">Abbrechen</Button>
    </form>
  );
}

export function AgentDetailPage() {
  const agentId = Number(useParams().agentId);
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "runs";
  const [editing, setEditing] = useState(false);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["agent", agentId], queryFn: () => api<AgentDetail>(`/api/agents/${agentId}`) });
  const app = useQuery({
    queryKey: ["app", q.data?.app_id],
    queryFn: () => api<App>(`/api/apps/${q.data!.app_id}`),
    enabled: !!q.data,
  });
  const runs = useRuns({ agent_id: agentId, limit: 50 }, `agent:${agentId}`);
  const refresh = useThrottled(() => qc.invalidateQueries({ queryKey: ["agent", agentId] }), 3000);
  useLive([`agent:${agentId}`], (ev) => {
    if (ev.type === "llm_call") refresh();
  });

  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <ErrorBox error={q.error ?? "Nicht gefunden"} />;
  const a = q.data;
  const siblings = app.data?.agents ?? [a];
  const byId = new Map(siblings.map((x) => [x.id, x]));
  const peers = new Map<number | null, { out: number; in: number }>();
  for (const p of a.peers) {
    const other = p.from_agent_id === agentId ? p.to_agent_id : p.from_agent_id;
    const cur = peers.get(other) ?? { out: 0, in: 0 };
    if (p.from_agent_id === agentId) cur.out += p.n;
    else cur.in += p.n;
    peers.set(other, cur);
  }
  const s = a.stats_24h;
  const setTab = (t: Tab) => setParams((p) => { p.set("tab", t); return p; }, { replace: true });

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        back={<>{a.app && <Link to={`/apps/${a.app.id}`} className="hover:underline">{a.app.name}</Link>} · Agent</>}
        title={
          <span className="flex items-center gap-2.5">
            <AgentDot color={agentColor(a, siblings)} size={12} />
            {a.display_name || a.name}
            {a.display_name && <span className="text-[13px] font-normal text-fg-3">({a.name})</span>}
          </span>
        }
        subtitle={[a.role, a.model && `Modell ${a.model}`, `zuletzt aktiv ${fmtAgo(a.last_seen)}`].filter(Boolean).join(" · ")}
        actions={!editing && <Button onClick={() => setEditing(true)}><Pencil size={14} /> Anpassen</Button>}
      />
      {editing && <Card><EditAgent agent={a} onDone={() => setEditing(false)} /></Card>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="LLM-Aufrufe 24h" value={fmtNum(s.llm_calls)} />
        <Kpi label="Tokens 24h" value={fmtCompact((s.tokens_in ?? 0) + (s.tokens_out ?? 0))} sub={`${fmtCompact(s.tokens_in)} rein · ${fmtCompact(s.tokens_out)} raus`} />
        <Kpi label="Ø Antwortzeit" value={fmtMs(s.avg_ms)} />
        <Kpi label="Fehler 24h" value={fmtNum(s.errors ?? 0)} tone={s.errors ? "critical" : undefined} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <Card title="LLM-Aufrufe pro Stunde" className="xl:col-span-1"><HourlyBars data={a.hours} dataKey="llm_calls" unit="Aufrufe" color={agentColor(a, siblings)} height={150} /></Card>
        <Card title="Ø Antwortzeit pro Stunde" className="xl:col-span-1"><HourlyLine data={a.hours} dataKey="avg_ms" unit="ms" ms color={agentColor(a, siblings)} height={150} /></Card>
        <Card title={<span className="flex items-center gap-1.5"><Wrench size={14} /> Genutzte Tools</span>}>
          {a.tools.length ? (
            <ul className="flex flex-col gap-1.5 text-[13px]">
              {a.tools.map((t) => (
                <li key={t.name} className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-[12px]">{t.name}</span>
                  <span className="tabular text-fg-2">{fmtNum(t.n)}×</span>
                </li>
              ))}
            </ul>
          ) : <div className="text-[13px] text-fg-3">Keine Tool-Aufrufe</div>}
        </Card>
        <Card title={<span className="flex items-center gap-1.5"><ArrowLeftRight size={14} /> Kommunikationspartner</span>}>
          {peers.size ? (
            <ul className="flex flex-col gap-1.5 text-[13px]">
              {[...peers.entries()].map(([id, v]) => (
                <li key={String(id)} className="flex items-center justify-between gap-2">
                  {id == null ? <span className="text-fg-2">Start / Benutzer</span> : <AgentChip agent={byId.get(id)} agents={siblings} />}
                  <span className="tabular text-[12px] text-fg-2">{v.out} gesendet · {v.in} erhalten</span>
                </li>
              ))}
            </ul>
          ) : <div className="text-[13px] text-fg-3">Keine Nachrichten mit anderen Agenten</div>}
        </Card>
      </div>
      <Card bodyClass="p-0">
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          items={[
            { value: "runs", label: "Runs", count: runs.data?.runs.length },
            { value: "llm", label: "LLM-Aufrufe" },
            { value: "logs", label: "Logs" },
          ]}
        />
        {tab === "runs" && <RunsTable runs={runs.data?.runs} agents={runs.data?.agents ?? {}} loading={runs.isLoading} />}
        {tab === "llm" && <LlmCallsTable filter={{ agent_id: agentId }} agents={siblings} topic={`agent:${agentId}`} />}
        {tab === "logs" && <LogView filter={{ agent_id: agentId }} agents={siblings} height={560} />}
      </Card>
    </div>
  );
}
