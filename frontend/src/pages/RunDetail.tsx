import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Radio, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { LlmCallDetail } from "../components/LlmCallView";
import { LogView } from "../components/LogView";
import { AgentChip, Badge, Button, Card, CodeBlock, ErrorBox, Loading, PageHeader, StatusBadge, Tabs } from "../components/ui";
import { api, type RunDetail as RunDetailT } from "../lib/api";
import { fmtDateTime, fmtDuration, fmtMs, fmtNum, prettyJson, shortId } from "../lib/format";
import { useLive } from "../lib/live";
import { CommGraph } from "../run/CommGraph";
import { activeAgents, applyRunEvent, buildRunGraph, runBounds, type SeqRow } from "../run/model";
import { SequenceDiagram } from "../run/Sequence";
import { Timeline } from "../run/Timeline";
import { Waterfall } from "../run/Waterfall";

type Tab = "timeline" | "graph" | "sequence" | "waterfall" | "logs";

function Replay({ bounds, value, onChange, live }: {
  bounds: [number, number]; value: number | null; onChange: (v: number | null) => void; live: boolean;
}) {
  const [playing, setPlaying] = useState(false);
  const [start, end] = bounds;
  const span = end - start;
  useEffect(() => {
    if (!playing) return;
    const step = Math.max(span / 150, 0.05);
    const id = window.setInterval(() => {
      onChange(((value ?? start) + step) >= end ? null : (value ?? start) + step);
      if ((value ?? start) + step >= end) setPlaying(false);
    }, 80);
    return () => window.clearInterval(id);
  }, [playing, value, span, start, end, onChange]);
  const pos = value == null ? span : value - start;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface-2/50 px-3 py-2">
      <Button
        variant="secondary"
        onClick={() => {
          if (!playing && (value == null || value >= end)) onChange(start);
          setPlaying(!playing);
        }}
        title={playing ? "Anhalten" : "Abspielen"}
      >
        {playing ? <Pause size={14} /> : <Play size={14} />} {playing ? "Pause" : "Abspielen"}
      </Button>
      <input
        type="range"
        min={0}
        max={span}
        step={span / 500}
        value={pos}
        onChange={(e) => {
          setPlaying(false);
          const v = Number(e.target.value);
          onChange(v >= span ? null : start + v);
        }}
        className="min-w-[160px] flex-1 accent-[var(--accent)]"
        aria-label="Zeitpunkt im Run"
      />
      <span className="whitespace-nowrap text-right text-[12px] text-fg-2 tabular">{fmtMs(pos * 1000)} / {fmtMs(span * 1000)}</span>
      {value != null ? (
        <Button variant="ghost" onClick={() => { setPlaying(false); onChange(null); }} title="Gesamten Run zeigen">
          <RotateCcw size={14} /> Alles
        </Button>
      ) : live ? (
        <span className="flex items-center gap-1 text-[12px] font-medium text-accent"><Radio size={13} className="pulse" /> live</span>
      ) : null}
    </div>
  );
}

function SeqDetail({ row }: { row: SeqRow }) {
  if (row.kind === "llm") return <LlmCallDetail id={row.call.id} />;
  if (row.kind === "tool")
    return (
      <div className="flex flex-col gap-2">
        <div className="text-[12px] font-medium text-fg-2">Argumente</div>
        <CodeBlock>{prettyJson(row.span.input) || "–"}</CodeBlock>
        <div className="text-[12px] font-medium text-fg-2">Ergebnis</div>
        <CodeBlock>{row.span.status === "error" ? row.span.status_message : prettyJson(row.span.output) || "–"}</CodeBlock>
      </div>
    );
  return <CodeBlock>{prettyJson(row.msg.content) || "(kein Inhalt)"}</CodeBlock>;
}

export function RunDetailPage() {
  const { runId } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "timeline";
  const qc = useQueryClient();
  const key = ["run", runId];
  const q = useQuery({ queryKey: key, queryFn: () => api<RunDetailT>(`/api/runs/${runId}`) });
  const [until, setUntil] = useState<number | null>(null);
  const [seqSel, setSeqSel] = useState<SeqRow | null>(null);
  const [, setTick] = useState(0);

  useLive([runId ? `run:${runId}` : null], (ev) => {
    qc.setQueryData<RunDetailT>(key, (d) => (d ? applyRunEvent(d, ev.type, ev.data) : d));
  });
  // "Hot"-Kanten und Laufzeiten regelmäßig neu berechnen
  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 2000);
    return () => window.clearInterval(id);
  }, []);

  const d = q.data;
  const graph = useMemo(() => (d ? buildRunGraph(d, until) : null), [d, until]);
  const active = useMemo(() => (d ? activeAgents(d, until) : new Set<number>()), [d, until]);
  if (q.isLoading) return <Loading />;
  if (q.error || !d) return <ErrorBox error={q.error ?? "Run nicht gefunden"} />;

  const run = d.run;
  const involved = [...new Set([...d.spans.map((s) => s.agent_id), ...d.llm_calls.map((c) => c.agent_id), ...d.messages.map((m) => m.to_agent_id)])]
    .filter((x): x is number => x != null)
    .map((id) => d.agents[String(id)])
    .filter(Boolean);
  const isLive = run.status === "running";
  const bounds = runBounds(d);
  const setTab = (t: Tab) => setParams((p) => { p.set("tab", t); return p; }, { replace: true });
  const now = Date.now() / 1000;

  return (
    <div>
      <PageHeader
        back={<><Link to="/runs" className="hover:underline">Runs</Link>{d.app && <> · <Link to={`/apps/${d.app.id}`} className="hover:underline">{d.app.name}</Link></>}</>}
        title={run.title || `Run ${shortId(run.id)}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <StatusBadge status={run.status} />
            <span>Start {fmtDateTime(run.started_at)}</span>
            <span>Dauer {fmtDuration(run.started_at, run.status === "running" ? null : run.ended_at ?? run.last_activity)}</span>
            <span className="tabular">{fmtNum(run.llm_calls)} LLM-Aufrufe</span>
            <span className="tabular">{fmtNum(run.tokens_in + run.tokens_out)} Tokens</span>
            {run.errors > 0 && <Badge tone="critical">{run.errors} Fehler</Badge>}
            {run.source === "auto" && <Badge title="Automatisch aus LLM-Aufrufen erkannt (ohne SDK)">automatisch erkannt</Badge>}
          </span>
        }
      />
      {involved.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3 text-[12px] text-fg-2">
          Beteiligte Agenten:
          {involved.map((a) => <AgentChip key={a.id} agent={a} agents={d.agents} />)}
        </div>
      )}
      <Card bodyClass="p-0">
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          items={[
            { value: "timeline", label: "Verlauf" },
            { value: "graph", label: "Kommunikation", count: d.messages.length },
            { value: "sequence", label: "Sequenz" },
            { value: "waterfall", label: "Wasserfall", count: d.spans.length + d.llm_calls.length },
            { value: "logs", label: "Logs", count: d.logs.length },
          ]}
        />
        <div className="p-4">
          {(tab === "graph" || tab === "sequence" || tab === "timeline") && (
            <div className="mb-4"><Replay bounds={bounds} value={until} onChange={setUntil} live={isLive} /></div>
          )}
          {tab === "timeline" && <Timeline detail={d} until={until} />}
          {tab === "graph" && graph && (
            graph.nodes.length ? (
              <>
                <div className="overflow-hidden rounded-lg border border-line bg-surface-2/30">
                  <CommGraph graph={graph} agents={d.agents} active={active} hotSince={until ?? (isLive ? now - 6 : null)} />
                </div>
                <p className="mt-2 text-[12px] text-fg-2">
                  Pfeile zeigen, wer wem Aufgaben oder Ergebnisse geschickt hat; die Zahl ist die Anzahl der Nachrichten. Aktive Agenten sind hervorgehoben. Klick auf einen Agenten öffnet seine Details.
                </p>
              </>
            ) : (
              <div className="py-10 text-center text-[13px] text-fg-2">
                Keine Kommunikation zwischen Agenten erfasst. Für Multi-Agent-Anwendungen das agentdash-SDK verwenden (siehe README).
              </div>
            )
          )}
          {tab === "sequence" && (
            <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_420px]">
              <div className="min-w-0 rounded-lg border border-line">
                <SequenceDiagram detail={d} until={until} selected={seqSel?.key} onSelect={setSeqSel} />
              </div>
              <div className="min-w-0">
                {seqSel ? <SeqDetail row={seqSel} /> : <div className="text-[13px] text-fg-2">Eine Zeile anklicken, um Inhalte zu sehen.</div>}
              </div>
            </div>
          )}
          {tab === "waterfall" && <Waterfall detail={d} />}
        </div>
        {tab === "logs" && <LogView filter={{ run_id: run.id }} agents={d.agents} height={560} />}
      </Card>
    </div>
  );
}
