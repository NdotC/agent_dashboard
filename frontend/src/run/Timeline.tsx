import clsx from "clsx";
import { AlertTriangle, ArrowRightLeft, Bot, CheckCircle2, ChevronDown, ChevronRight, CornerDownLeft, Cpu, Footprints, Wrench, XCircle } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { AgentChip, Badge, CodeBlock, Empty } from "../components/ui";
import { LlmCallDetail, ToolCallBox } from "../components/LlmCallView";
import type { Agent, RunDetail } from "../lib/api";
import { agentColor, agentLabel } from "../lib/colors";
import { fmtMs, fmtNum, fmtTime, prettyJson } from "../lib/format";
import { buildTimeline, kindGroup, type TimelineItem, type TimelineKind } from "./model";

const KIND_FILTERS: { value: TimelineKind; label: string }[] = [
  { value: "agent", label: "Agenten" },
  { value: "llm", label: "LLM-Aufrufe" },
  { value: "tool", label: "Tools" },
  { value: "message", label: "Nachrichten" },
  { value: "log", label: "Warnungen & Fehler" },
];
const MSG_KIND: Record<string, string> = { handoff: "übergibt an", feedback: "gibt Feedback an", message: "schreibt an", broadcast: "sendet an", request: "fragt", response: "antwortet" };

function preview(text: string | null | undefined, n = 140) {
  if (!text) return null;
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n) + "…" : t;
}

function Row({ item, agents, color, icon, title, meta, detail, error }: {
  item: TimelineItem; agents: Record<string, Agent>; color: string; icon: ReactNode; title: ReactNode; meta?: ReactNode;
  detail?: () => ReactNode; error?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const agent = item.agentId != null ? agents[String(item.agentId)] : null;
  return (
    <li className="relative flex gap-3">
      <div className="flex w-[52px] shrink-0 justify-end pt-2 text-[11px] text-fg-3 tabular">{fmtTime(item.ts)}</div>
      <div className="w-[calc(var(--d)*8px)] shrink-0 sm:w-[calc(var(--d)*22px)]" style={{ "--d": Math.min(item.depth, 6) } as React.CSSProperties} />
      <div className="relative flex flex-col items-center">
        <div className="absolute inset-y-0 w-0.5" style={{ background: color, opacity: 0.35 }} />
        <div
          className={clsx("relative z-10 mt-1.5 flex h-6 w-6 items-center justify-center rounded-full border-2 bg-surface", error && "!border-critical text-critical-text")}
          style={{ borderColor: error ? undefined : color, color: error ? undefined : color }}
        >
          {icon}
        </div>
      </div>
      <div className={clsx("min-w-0 flex-1 rounded-md py-1.5 pr-2", detail && "cursor-pointer")}>
        <button
          className="flex w-full min-w-0 items-start gap-1.5 text-left"
          onClick={() => detail && setOpen(!open)}
          aria-expanded={detail ? open : undefined}
          disabled={!detail}
        >
          <span className="mt-0.5 shrink-0 text-fg-3">{detail ? (open ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : <span className="inline-block w-3.5" />}</span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px] text-fg">
              {agent && <AgentChip agent={agent} agents={agents} link={false} />}
              <span className={clsx(error && "text-critical-text")}>{title}</span>
            </span>
            {meta && <span className="mt-0.5 block text-[12px] text-fg-2">{meta}</span>}
          </span>
        </button>
        {open && detail && <div className="ml-5 mt-2 cursor-auto">{detail()}</div>}
      </div>
    </li>
  );
}

export function Timeline({ detail, until }: { detail: RunDetail; until?: number | null }) {
  const [kinds, setKinds] = useState<TimelineKind[]>(["agent", "llm", "tool", "message", "log"]);
  const [hidden, setHidden] = useState<number[]>([]);
  const items = useMemo(() => buildTimeline(detail), [detail]);
  const agents = detail.agents;
  const involved = useMemo(() => [...new Set(items.map((i) => i.agentId).filter((x): x is number => x != null))], [items]);
  const visible = items.filter(
    (i) => kinds.includes(kindGroup(i)) && (i.agentId == null || !hidden.includes(i.agentId)) && (until == null || i.ts <= until),
  );
  const colorOf = (id: number | null) => agentColor(id != null ? agents[String(id)] : null, agents);
  const nameOf = (id: number | null) => agentLabel(id != null ? agents[String(id)] : null);

  const render = (item: TimelineItem) => {
    const color = colorOf(item.agentId);
    switch (item.kind) {
      case "agent_start":
        return (
          <Row key={item.key} item={item} agents={agents} color={color} icon={<Bot size={12} />}
            title={<>beginnt{item.callerId != null ? <> – beauftragt von <b className="font-medium">{nameOf(item.callerId)}</b></> : <> – gestartet</>}</>}
            meta={preview(item.span.input)}
            detail={item.span.input ? () => <CodeBlock>{prettyJson(item.span.input)}</CodeBlock> : undefined}
          />
        );
      case "agent_end": {
        const err = item.span.status === "error";
        return (
          <Row key={item.key} item={item} agents={agents} color={color} error={err}
            icon={err ? <XCircle size={12} /> : <CornerDownLeft size={12} />}
            title={err ? <>bricht mit Fehler ab</> : <>fertig{item.callerId != null ? <> – liefert an <b className="font-medium">{nameOf(item.callerId)}</b></> : null}</>}
            meta={<>{err ? item.span.status_message : preview(item.span.output)} <span className="text-fg-3">· Dauer {fmtMs(((item.span.ended_at ?? 0) - item.span.started_at) * 1000)}</span></>}
            detail={item.span.output || item.span.status_message ? () => (
              <CodeBlock>{err ? item.span.status_message : prettyJson(item.span.output)}</CodeBlock>
            ) : undefined}
          />
        );
      }
      case "llm": {
        const c = item.call;
        const err = c.status === "error";
        const decided = c.tool_calls?.map((t) => t.name).join(", ");
        return (
          <Row key={item.key} item={item} agents={agents} color={color} error={err} icon={<Cpu size={12} />}
            title={<>fragt das Modell <Badge>{c.model ?? "?"}</Badge>{decided && <> → entscheidet sich für <b className="font-medium">{decided}</b></>}</>}
            meta={err ? c.error : <>
              {preview(c.response_preview ?? c.response, 120) ?? (decided ? "Tool-Aufruf" : "")}
              <span className="text-fg-3"> · {fmtMs(c.duration_ms)} · {fmtNum(c.tokens_in)}→{fmtNum(c.tokens_out)} Tokens{c.thinking ? " · mit Denkprozess" : ""}</span>
            </>}
            detail={() => (
              <div className="flex flex-col gap-2">
                {item.tools.length > 0 && item.tools.map((t) => <ToolCallBox key={t.id} name={t.name} args={t.arguments} result={t.result} />)}
                <LlmCallDetail id={c.id} />
              </div>
            )}
          />
        );
      }
      case "tool": {
        const err = item.span.status === "error";
        return (
          <Row key={item.key} item={item} agents={agents} color={color} error={err} icon={<Wrench size={12} />}
            title={<>führt Tool <b className="font-medium">{item.span.name}</b> aus{err && " – Fehler"}</>}
            meta={<>{err ? item.span.status_message : preview(item.span.output, 120)} <span className="text-fg-3">· {fmtMs(((item.span.ended_at ?? item.span.started_at) - item.span.started_at) * 1000)}</span></>}
            detail={() => (
              <ToolCallBox name={item.span.name} args={item.span.input} result={err ? item.span.status_message : item.span.output} />
            )}
          />
        );
      }
      case "step":
        return (
          <Row key={item.key} item={item} agents={agents} color={color} icon={<Footprints size={12} />}
            title={<>Schritt <b className="font-medium">{item.span.name}</b></>}
            meta={preview(item.span.output)}
            detail={item.span.input || item.span.output ? () => (
              <div className="flex flex-col gap-2">
                {item.span.input && <CodeBlock>{prettyJson(item.span.input)}</CodeBlock>}
                {item.span.output && <CodeBlock>{prettyJson(item.span.output)}</CodeBlock>}
              </div>
            ) : undefined}
          />
        );
      case "message":
        return (
          <Row key={item.key} item={item} agents={agents} color={color} icon={<ArrowRightLeft size={12} />}
            title={<>{MSG_KIND[item.msg.kind] ?? item.msg.kind} <b className="font-medium">{nameOf(item.msg.to_agent_id)}</b></>}
            meta={preview(item.msg.content)}
            detail={item.msg.content ? () => <CodeBlock>{prettyJson(item.msg.content)}</CodeBlock> : undefined}
          />
        );
      case "log": {
        const err = item.log.level === "error";
        return (
          <Row key={item.key} item={item} agents={agents} color={color} error={err}
            icon={err ? <XCircle size={12} /> : <AlertTriangle size={12} />}
            title={<span className="font-mono text-[12px]">{preview(item.log.message, 200)}</span>}
            detail={item.log.message.length > 200 || item.log.message.includes("\n") ? () => <CodeBlock>{item.log.message}</CodeBlock> : undefined}
          />
        );
      }
    }
  };

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {KIND_FILTERS.map((k) => (
          <button
            key={k.value}
            onClick={() => setKinds(kinds.includes(k.value) ? kinds.filter((x) => x !== k.value) : [...kinds, k.value])}
            aria-pressed={kinds.includes(k.value)}
            className={clsx("rounded-full border px-2.5 py-1 text-[12px] font-medium", kinds.includes(k.value) ? "border-line-strong bg-surface-3 text-fg" : "border-line text-fg-3")}
          >
            {k.label}
          </button>
        ))}
        {involved.length > 1 && <span className="mx-1 h-4 w-px bg-line" />}
        {involved.length > 1 && involved.map((id) => (
          <button
            key={id}
            onClick={() => setHidden(hidden.includes(id) ? hidden.filter((x) => x !== id) : [...hidden, id])}
            aria-pressed={!hidden.includes(id)}
            className={clsx("flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-medium", hidden.includes(id) ? "border-line text-fg-3 line-through" : "border-line-strong text-fg")}
          >
            <span className="h-2 w-2 rounded-full" style={{ background: colorOf(id) }} />
            {nameOf(id)}
          </button>
        ))}
      </div>
      {visible.length === 0 ? (
        <Empty title="Keine Aktionen" icon={<CheckCircle2 size={20} />}>Für die gewählten Filter gibt es (noch) keine Einträge.</Empty>
      ) : (
        <ol className="flex flex-col">{visible.map(render)}</ol>
      )}
    </div>
  );
}
