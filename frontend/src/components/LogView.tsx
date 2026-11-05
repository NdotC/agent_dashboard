import clsx from "clsx";
import { ArrowDownToLine, ExternalLink, Pause, Play, Search } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, qs, type Agent, type App, type Level, type LogEntry } from "../lib/api";
import { fmtDateTime, fmtTime } from "../lib/format";
import { useLive } from "../lib/live";
import { AgentChip, Badge, Button, Empty, inputClass, LevelBadge } from "./ui";

const LEVELS: Level[] = ["debug", "info", "warn", "error"];
const SOURCES = [
  { value: "docker", label: "Container" },
  { value: "sdk", label: "SDK" },
  { value: "proxy", label: "LLM-Proxy" },
] as const;
const MAX_ROWS = 5000;

export interface LogFilter {
  app_id?: number;
  agent_id?: number;
  run_id?: string;
}

export function LogView({ filter, agents, apps, height = 520, showApp = false, initialLevels }: {
  filter: LogFilter;
  agents: Agent[] | Record<string, Agent>;
  apps?: App[];
  height?: number | string;
  showApp?: boolean;
  initialLevels?: Level[];
}) {
  const [rows, setRows] = useState<LogEntry[]>([]);
  const [levels, setLevels] = useState<Level[]>(initialLevels ?? ["debug", "info", "warn", "error"]);
  const [sources, setSources] = useState<string[]>(["docker", "sdk", "proxy"]);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [paused, setPaused] = useState(false);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [atBottom, setAtBottom] = useState(true);
  const [fresh, setFresh] = useState<Set<number>>(new Set());
  const buffer = useRef<LogEntry[]>([]);
  const scroller = useRef<HTMLDivElement>(null);

  const agentMap = useMemo(() => {
    const m = new Map<number, Agent>();
    (Array.isArray(agents) ? agents : Object.values(agents)).forEach((a) => m.set(a.id, a));
    return m;
  }, [agents]);
  const appMap = useMemo(() => new Map((apps ?? []).map((a) => [a.id, a])), [apps]);

  const params = useMemo(
    () => ({
      ...filter,
      level: levels.length === LEVELS.length ? undefined : levels.join(","),
      source: sources.length === SOURCES.length ? undefined : sources.join(","),
      q: appliedQuery || undefined,
    }),
    [filter, levels, sources, appliedQuery],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<LogEntry[]>(`/api/logs${qs({ ...params, limit: 300 })}`);
      setRows(data.reverse());
      setHasMore(data.length === 300);
      buffer.current = [];
      setAtBottom(true);
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    load();
  }, [load]);

  const loadOlder = async () => {
    if (!rows.length) return;
    const first = rows[0];
    const el = scroller.current;
    const prevHeight = el?.scrollHeight ?? 0;
    const data = await api<LogEntry[]>(`/api/logs${qs({ ...params, limit: 300, before_ts: first.ts, before_id: first.id })}`);
    setHasMore(data.length === 300);
    setRows((r) => [...data.reverse(), ...r]);
    requestAnimationFrame(() => {
      if (el) el.scrollTop = el.scrollHeight - prevHeight;
    });
  };

  const topic = filter.run_id ? `run:${filter.run_id}` : filter.agent_id ? `agent:${filter.agent_id}` : filter.app_id ? `app:${filter.app_id}` : "logs";
  const matches = useCallback(
    (e: LogEntry) =>
      levels.includes(e.level) &&
      sources.includes(e.source) &&
      (filter.agent_id == null || e.agent_id === filter.agent_id) &&
      (filter.run_id == null || e.run_id === filter.run_id) &&
      (filter.app_id == null || e.app_id === filter.app_id),
    [levels, sources, filter],
  );

  useLive([topic], (ev) => {
    if (ev.type !== "log" || appliedQuery) return;
    const entry = ev.data as LogEntry;
    if (!matches(entry)) return;
    if (paused) {
      buffer.current.push(entry);
      return;
    }
    append([entry]);
  });

  const append = (entries: LogEntry[]) => {
    setRows((r) => {
      const next = [...r, ...entries];
      return next.length > MAX_ROWS ? next.slice(next.length - MAX_ROWS) : next;
    });
    setFresh((f) => {
      const n = new Set(f);
      entries.forEach((e) => n.add(e.id));
      return n;
    });
    window.setTimeout(() => setFresh((f) => {
      const n = new Set(f);
      entries.forEach((e) => n.delete(e.id));
      return n;
    }), 1500);
  };

  const resume = () => {
    setPaused(false);
    if (buffer.current.length) append(buffer.current.splice(0));
  };

  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && atBottom) el.scrollTop = el.scrollHeight;
  }, [rows, atBottom]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };

  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <div className="flex min-w-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <form
          className="relative min-w-[180px] flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            setAppliedQuery(query.trim());
          }}
        >
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-3" />
          <input
            className={clsx(inputClass, "w-full pl-8")}
            placeholder="Logs durchsuchen (Enter) …"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (!e.target.value) setAppliedQuery("");
            }}
            aria-label="Logs durchsuchen"
          />
        </form>
        <div className="flex items-center gap-1" role="group" aria-label="Level">
          {LEVELS.map((l) => (
            <button
              key={l}
              onClick={() => setLevels(toggle(levels, l))}
              aria-pressed={levels.includes(l)}
              className={clsx("rounded px-2 py-1 text-[11px] font-medium uppercase", levels.includes(l) ? "bg-surface-3 text-fg" : "text-fg-3 line-through")}
            >
              {l}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1" role="group" aria-label="Quelle">
          {SOURCES.map((s) => (
            <button
              key={s.value}
              onClick={() => setSources(toggle(sources, s.value))}
              aria-pressed={sources.includes(s.value)}
              className={clsx("rounded px-2 py-1 text-[11px] font-medium", sources.includes(s.value) ? "bg-surface-3 text-fg" : "text-fg-3 line-through")}
            >
              {s.label}
            </button>
          ))}
        </div>
        <Button variant="ghost" onClick={paused ? resume : () => setPaused(true)} title={paused ? "Fortsetzen" : "Pausieren"}>
          {paused ? <Play size={14} /> : <Pause size={14} />}
          {paused ? `Fortsetzen${buffer.current.length ? ` (${buffer.current.length})` : ""}` : "Pause"}
        </Button>
      </div>
      <div ref={scroller} onScroll={onScroll} className="scroll-thin relative overflow-y-auto font-mono text-[12px]" style={{ height }}>
        {hasMore && rows.length > 0 && (
          <div className="flex justify-center py-2">
            <Button variant="ghost" onClick={loadOlder}>Ältere laden</Button>
          </div>
        )}
        {!loading && rows.length === 0 && (
          <Empty title={appliedQuery ? "Keine Treffer" : "Noch keine Logs"}>
            {appliedQuery ? "Andere Suchbegriffe oder Filter probieren." : "Sobald der Agent etwas ausgibt, erscheint es hier live."}
          </Empty>
        )}
        {rows.map((e) => (
          <div
            key={e.id}
            className={clsx(
              "group flex items-start gap-2 border-b border-line/60 px-3 py-1 hover:bg-surface-2",
              e.level === "error" && "bg-critical-soft/50",
              fresh.has(e.id) && "flash",
            )}
          >
            <span className="tabular shrink-0 pt-px text-fg-3" title={fmtDateTime(e.ts)}>{fmtTime(e.ts)}</span>
            <LevelBadge level={e.level} />
            <Badge className="hidden w-16 shrink-0 justify-center sm:inline-flex" title={e.stream ? `Stream: ${e.stream}` : undefined}>
              {e.source === "docker" ? "container" : e.source}
            </Badge>
            {showApp && <span className="hidden w-28 shrink-0 truncate pt-px font-sans text-fg-2 md:inline">{appMap.get(e.app_id)?.name}</span>}
            {e.agent_id != null && (
              <span className="hidden w-28 shrink-0 pt-px font-sans md:inline">
                <AgentChip agent={agentMap.get(e.agent_id)} agents={agents} />
              </span>
            )}
            <span className="min-w-0 flex-1 whitespace-pre-wrap break-words text-fg">{e.message}</span>
            {e.run_id && !filter.run_id && (
              <Link to={`/runs/${e.run_id}`} className="shrink-0 pt-px text-fg-3 opacity-0 hover:text-accent group-hover:opacity-100" title="Zum Run">
                <ExternalLink size={13} />
              </Link>
            )}
          </div>
        ))}
        {!atBottom && rows.length > 0 && (
          <button
            onClick={() => setAtBottom(true)}
            className="sticky bottom-3 left-full mr-3 flex items-center gap-1 rounded-full bg-accent px-3 py-1.5 font-sans text-[12px] font-medium text-accent-fg shadow"
            style={{ marginLeft: "auto" }}
          >
            <ArrowDownToLine size={13} /> Neueste
          </button>
        )}
      </div>
    </div>
  );
}
