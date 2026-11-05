import clsx from "clsx";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, CircleDashed, CircleSlash, Loader2, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Agent } from "../lib/api";
import { agentColor, agentLabel } from "../lib/colors";

export function Card({ title, actions, children, className, bodyClass }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={clsx("card min-w-0", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="truncate text-[13px] font-semibold text-fg">{title}</h2>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={clsx(bodyClass ?? "p-4")}>{children}</div>
    </section>
  );
}

type Tone = "good" | "warning" | "critical" | "neutral" | "accent" | "running";

const STATUS: Record<string, { tone: Tone; label: string; icon: ReactNode }> = {
  running: { tone: "running", label: "läuft", icon: <Loader2 size={12} className="animate-spin" /> },
  active: { tone: "good", label: "aktiv", icon: <CheckCircle2 size={12} /> },
  ok: { tone: "good", label: "ok", icon: <CheckCircle2 size={12} /> },
  error: { tone: "critical", label: "Fehler", icon: <XCircle size={12} /> },
  stale: { tone: "warning", label: "abgebrochen", icon: <AlertTriangle size={12} /> },
  exited: { tone: "neutral", label: "gestoppt", icon: <CircleSlash size={12} /> },
  dead: { tone: "critical", label: "tot", icon: <XCircle size={12} /> },
  restarting: { tone: "warning", label: "startet neu", icon: <Loader2 size={12} className="animate-spin" /> },
  paused: { tone: "warning", label: "pausiert", icon: <CircleDashed size={12} /> },
  created: { tone: "neutral", label: "erstellt", icon: <CircleDashed size={12} /> },
  removed: { tone: "neutral", label: "entfernt", icon: <CircleSlash size={12} /> },
  unknown: { tone: "neutral", label: "unbekannt", icon: <CircleDashed size={12} /> },
};

const TONE: Record<Tone, string> = {
  good: "bg-good-soft text-good-text",
  warning: "bg-warning-soft text-warning-text",
  critical: "bg-critical-soft text-critical-text",
  neutral: "bg-surface-2 text-fg-2",
  accent: "bg-accent-soft text-accent",
  running: "bg-accent-soft text-accent",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const s = STATUS[status] ?? STATUS.unknown;
  // Container im Zustand "running" sind "aktiv" (nicht "läuft" wie ein Run)
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium", TONE[s.tone], className)}>
      {s.icon}
      {s.label}
    </span>
  );
}

export function ContainerStatus({ status }: { status: string }) {
  return <StatusBadge status={status === "running" ? "active" : status} />;
}

export function Badge({ children, tone = "neutral", className, title }: { children: ReactNode; tone?: Tone; className?: string; title?: string }) {
  return (
    <span title={title} className={clsx("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium", TONE[tone], className)}>
      {children}
    </span>
  );
}

export function LevelBadge({ level }: { level: string }) {
  const tone: Tone = level === "error" ? "critical" : level === "warn" ? "warning" : level === "debug" ? "neutral" : "accent";
  const label = { error: "ERROR", warn: "WARN", info: "INFO", debug: "DEBUG" }[level] ?? level.toUpperCase();
  return <Badge tone={tone} className="w-14 justify-center font-mono text-[10px]">{label}</Badge>;
}

export function Kpi({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "critical" }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-[12px] text-fg-2">{label}</div>
      <div className={clsx("tabular mt-1 text-2xl font-semibold tracking-tight", tone === "critical" ? "text-critical-text" : "text-fg")}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[12px] text-fg-3">{sub}</div>}
    </div>
  );
}

export function AgentDot({ color, size = 8 }: { color: string; size?: number }) {
  return <span className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: color }} />;
}

export function AgentChip({ agent, agents, link = true }: { agent: Agent | null | undefined; agents: Agent[] | Record<string, Agent>; link?: boolean }) {
  const inner = (
    <span className="inline-flex max-w-full items-center gap-1.5 truncate text-[12px] font-medium text-fg">
      <AgentDot color={agentColor(agent, agents)} />
      <span className="truncate">{agentLabel(agent)}</span>
    </span>
  );
  if (!agent || !link) return inner;
  return <Link to={`/agents/${agent.id}`} className="hover:underline">{inner}</Link>;
}

export function Tabs<T extends string>({ value, onChange, items }: {
  value: T; onChange: (v: T) => void; items: { value: T; label: ReactNode; count?: number }[];
}) {
  return (
    <div role="tablist" className="scroll-thin flex gap-1 overflow-x-auto border-b border-line">
      {items.map((it) => (
        <button
          key={it.value}
          role="tab"
          aria-selected={value === it.value}
          onClick={() => onChange(it.value)}
          className={clsx(
            "-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] font-medium transition-colors",
            value === it.value ? "border-accent text-fg" : "border-transparent text-fg-2 hover:text-fg",
          )}
        >
          {it.label}
          {it.count != null && <span className="tabular rounded bg-surface-2 px-1.5 text-[11px] text-fg-2">{it.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      {icon && <div className="text-fg-3">{icon}</div>}
      <div className="text-[13px] font-medium text-fg">{title}</div>
      {children && <div className="max-w-md text-[13px] text-fg-2">{children}</div>}
    </div>
  );
}

export function Loading({ label = "Lade …" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-[13px] text-fg-2">
      <Loader2 size={16} className="animate-spin" /> {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="rounded-lg border border-critical/40 bg-critical-soft px-4 py-3 text-[13px] text-critical-text">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export function Button({ children, onClick, variant = "secondary", type = "button", disabled, className, title }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "ghost"; type?: "button" | "submit";
  disabled?: boolean; className?: string; title?: string;
}) {
  return (
    <button
      type={type}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={clsx(
        "inline-flex h-8 items-center justify-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-colors disabled:opacity-50",
        variant === "primary" && "bg-accent text-accent-fg hover:opacity-90",
        variant === "secondary" && "border border-line bg-surface text-fg hover:bg-surface-2",
        variant === "ghost" && "text-fg-2 hover:bg-surface-2 hover:text-fg",
        className,
      )}
    >
      {children}
    </button>
  );
}

export const inputClass =
  "h-8 rounded-md border border-line bg-surface px-2.5 text-[13px] text-fg placeholder:text-fg-3 focus:border-accent focus:outline-none";

export function Collapsible({ title, children, defaultOpen = false, right }: {
  title: ReactNode; children: ReactNode; defaultOpen?: boolean; right?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-md border border-line">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[12px] font-medium text-fg-2 hover:text-fg">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="min-w-0 flex-1 truncate">{title}</span>
        {right}
      </button>
      {open && <div className="border-t border-line p-3">{children}</div>}
    </div>
  );
}

export function CodeBlock({ children, className, maxHeight = 360 }: { children: ReactNode; className?: string; maxHeight?: number }) {
  return (
    <pre
      className={clsx("scroll-thin overflow-auto whitespace-pre-wrap break-words rounded-md bg-code p-3 text-[12px] leading-relaxed text-fg", className)}
      style={{ maxHeight }}
    >
      {children}
    </pre>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,max-content)_1fr] gap-x-4 gap-y-1.5 text-[13px]">
      {items.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-fg-2">{k}</dt>
          <dd className="min-w-0 break-words text-fg">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PageHeader({ title, subtitle, actions, back }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; back?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {back && <div className="mb-1 text-[12px] text-fg-2">{back}</div>}
        <h1 className="truncate text-xl font-semibold tracking-tight text-fg">{title}</h1>
        {subtitle && <div className="mt-1 text-[13px] text-fg-2">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
