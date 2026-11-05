import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { LogView } from "../components/LogView";
import { AgentChip, Badge, Button, Card, Empty, inputClass, LevelBadge, Loading, PageHeader, StatusBadge, Tabs } from "../components/ui";
import { api, qs, type Agent, type App, type SearchResult } from "../lib/api";
import { fmtDateTime, prettyJson, shortId } from "../lib/format";

function highlight(text: string, q: string) {
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return text.length > 220 ? text.slice(0, 220) + "…" : text;
  const start = Math.max(0, i - 80);
  const snippet = (start > 0 ? "…" : "") + text.slice(start, i + q.length + 140);
  const j = snippet.toLowerCase().indexOf(q.toLowerCase());
  return (
    <>
      {snippet.slice(0, j)}
      <mark className="rounded bg-warning-soft px-0.5 text-fg">{snippet.slice(j, j + q.length)}</mark>
      {snippet.slice(j + q.length)}
    </>
  );
}

function SearchSection({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  if (!count) return null;
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-2 text-[13px] font-semibold">{title} <Badge>{count}</Badge></h3>
      <ul className="flex flex-col divide-y divide-line rounded-lg border border-line">{children}</ul>
    </div>
  );
}

function GlobalSearch({ agents, apps }: { agents: Agent[]; apps: App[] }) {
  const [params, setParams] = useSearchParams();
  const [input, setInput] = useState(params.get("q") ?? "");
  const q = params.get("q") ?? "";
  const res = useQuery({
    queryKey: ["search", q],
    queryFn: () => api<SearchResult>(`/api/search${qs({ q, limit: 40 })}`),
    enabled: q.length > 0,
  });
  const byId = useMemo(() => new Map(agents.map((a) => [a.id, a])), [agents]);
  const appName = (id: number) => apps.find((a) => a.id === id)?.name;
  const r = res.data;
  const total = r ? r.logs.length + r.llm_calls.length + r.messages.length + r.runs.length + r.tools.length : 0;
  return (
    <div className="flex flex-col gap-4 p-4">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setParams((p) => { p.set("tab", "search"); p.set("q", input.trim()); return p; });
        }}
      >
        <div className="relative flex-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-3" />
          <input className={clsx(inputClass, "w-full pl-8")} value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="In Logs, Prompts, Antworten, Tool-Aufrufen und Nachrichten suchen …" aria-label="Suchbegriff" autoFocus />
        </div>
        <Button type="submit" variant="primary">Suchen</Button>
      </form>
      {!q && <Empty title="Alles durchsuchen" icon={<Search size={20} />}>Zum Beispiel: „Welcher Agent hat die Datei X erwähnt?“ – gesucht wird in Logs, Prompts, Antworten, Tool-Argumenten und -Ergebnissen sowie in Nachrichten zwischen Agenten.</Empty>}
      {res.isLoading && <Loading label="Suche …" />}
      {r && total === 0 && <Empty title="Keine Treffer">Für „{q}“ wurde nichts gefunden.</Empty>}
      {r && (
        <div className="flex flex-col gap-5">
          <SearchSection title="Runs" count={r.runs.length}>
            {r.runs.map((run) => (
              <li key={run.id}><Link to={`/runs/${run.id}`} className="flex items-center gap-3 px-3 py-2 hover:bg-surface-2">
                <StatusBadge status={run.status} /><span className="flex-1 truncate">{highlight(run.title ?? "", q)}</span>
                <span className="text-[12px] text-fg-3">{fmtDateTime(run.started_at)}</span></Link></li>
            ))}
          </SearchSection>
          <SearchSection title="Tool-Aufrufe" count={r.tools.length}>
            {r.tools.map((t) => (
              <li key={t.id}><Link to={t.run_id ? `/runs/${t.run_id}` : "#"} className="block px-3 py-2 hover:bg-surface-2">
                <div className="flex items-center gap-2 text-[13px]"><Badge>{t.name}</Badge>{t.agent_id != null && <AgentChip agent={byId.get(t.agent_id)} agents={agents} link={false} />}<span className="ml-auto text-[12px] text-fg-3">{fmtDateTime(t.ts)}</span></div>
                <div className="mt-1 truncate font-mono text-[12px] text-fg-2">{highlight(prettyJson(t.arguments) + " → " + (t.result ?? ""), q)}</div>
              </Link></li>
            ))}
          </SearchSection>
          <SearchSection title="LLM-Aufrufe" count={r.llm_calls.length}>
            {r.llm_calls.map((c) => (
              <li key={c.id}><Link to={c.run_id ? `/runs/${c.run_id}` : c.agent_id ? `/agents/${c.agent_id}?tab=llm` : "#"} className="block px-3 py-2 hover:bg-surface-2">
                <div className="flex items-center gap-2 text-[13px]">{c.agent_id != null && <AgentChip agent={byId.get(c.agent_id)} agents={agents} link={false} />}<Badge>{c.model}</Badge><span className="ml-auto text-[12px] text-fg-3">{fmtDateTime(c.started_at)}</span></div>
                <div className="mt-1 truncate text-[12px] text-fg-2">{c.prompt_preview} → {c.response_preview}</div>
              </Link></li>
            ))}
          </SearchSection>
          <SearchSection title="Nachrichten zwischen Agenten" count={r.messages.length}>
            {r.messages.map((m) => (
              <li key={m.id}><Link to={`/runs/${m.run_id}`} className="block px-3 py-2 hover:bg-surface-2">
                <div className="flex items-center gap-2 text-[13px]">
                  <AgentChip agent={m.from_agent_id != null ? byId.get(m.from_agent_id) : null} agents={agents} link={false} /> →
                  <AgentChip agent={m.to_agent_id != null ? byId.get(m.to_agent_id) : null} agents={agents} link={false} />
                  <Badge>{m.kind}</Badge><span className="ml-auto text-[12px] text-fg-3">{fmtDateTime(m.ts)}</span>
                </div>
                <div className="mt-1 text-[12px] text-fg-2">{highlight(m.content ?? "", q)}</div>
              </Link></li>
            ))}
          </SearchSection>
          <SearchSection title="Logs" count={r.logs.length}>
            {r.logs.map((l) => (
              <li key={l.id} className="flex items-start gap-2 px-3 py-2 font-mono text-[12px]">
                <span className="shrink-0 text-fg-3">{fmtDateTime(l.ts)}</span><LevelBadge level={l.level} />
                <span className="w-24 shrink-0 truncate font-sans text-fg-2">{appName(l.app_id)}</span>
                <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{highlight(l.message, q)}</span>
                {l.run_id && <Link to={`/runs/${l.run_id}`} className="shrink-0 font-sans text-accent hover:underline">Run {shortId(l.run_id, 6)}</Link>}
              </li>
            ))}
          </SearchSection>
        </div>
      )}
    </div>
  );
}

export function LogsPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "live" | "search") || "live";
  const [appId, setAppId] = useState("");
  const apps = useQuery({ queryKey: ["apps"], queryFn: () => api<App[]>("/api/apps") });
  const agents = useMemo(() => (apps.data ?? []).flatMap((a) => a.agents), [apps.data]);
  return (
    <div>
      <PageHeader title="Logs & Suche" subtitle="Alle Logs aller Anwendungen live – oder gezielt durchsuchen, was Agenten getan haben." />
      <Card bodyClass="p-0">
        <div className="flex flex-wrap items-center justify-between gap-2 pr-3">
          <Tabs value={tab} onChange={(t) => setParams((p) => { p.set("tab", t); return p; })} items={[{ value: "live", label: "Live-Logs" }, { value: "search", label: "Suche" }]} />
          {tab === "live" && (
            <select className={inputClass} value={appId} onChange={(e) => setAppId(e.target.value)} aria-label="Anwendung filtern">
              <option value="">Alle Anwendungen</option>
              {(apps.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          )}
        </div>
        {tab === "live" ? (
          <LogView key={appId} filter={appId ? { app_id: Number(appId) } : {}} agents={agents} apps={apps.data} showApp={!appId} height="calc(100vh - 230px)" />
        ) : (
          <GlobalSearch agents={agents} apps={apps.data ?? []} />
        )}
      </Card>
    </div>
  );
}
