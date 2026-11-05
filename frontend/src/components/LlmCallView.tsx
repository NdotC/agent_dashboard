import { useQuery } from "@tanstack/react-query";
import { Brain, Wrench } from "lucide-react";
import { api, type LlmCall } from "../lib/api";
import { fmtMs, fmtNum, prettyJson } from "../lib/format";
import { Badge, CodeBlock, Collapsible, ErrorBox, Loading } from "./ui";

interface ChatMessage {
  role?: string;
  content?: unknown;
  thinking?: string;
  tool_calls?: { id?: string; function?: { name?: string; arguments?: unknown }; name?: string; arguments?: unknown }[];
  tool_name?: string;
  name?: string;
  tool_call_id?: string;
  images?: string[];
}

const ROLE_LABEL: Record<string, string> = { system: "System", user: "Benutzer", assistant: "Modell", tool: "Tool-Ergebnis" };

function text(content: unknown): string {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map((p) => (typeof p === "string" ? p : p?.text ?? "")).join("");
  return JSON.stringify(content);
}

export function ToolCallBox({ name, args, result }: { name: string; args: unknown; result?: string | null }) {
  return (
    <div className="rounded-md border border-line bg-surface-2/60 p-2.5">
      <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-medium text-fg">
        <Wrench size={13} className="text-fg-2" /> {name}
      </div>
      <CodeBlock maxHeight={180}>{prettyJson(args) || "{}"}</CodeBlock>
      {result !== undefined && (
        <div className="mt-2">
          <div className="mb-1 text-[11px] font-medium text-fg-2">Ergebnis</div>
          <CodeBlock maxHeight={180}>{result ?? "(noch kein Ergebnis zurückgegeben)"}</CodeBlock>
        </div>
      )}
    </div>
  );
}

export function MessageList({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className="flex flex-col gap-2">
      {messages.map((m, i) => (
        <div key={i} className="rounded-md border border-line">
          <div className="flex items-center gap-2 border-b border-line bg-surface-2 px-2.5 py-1 text-[11px] font-medium text-fg-2">
            {ROLE_LABEL[m.role ?? ""] ?? m.role}
            {m.role === "tool" && (m.tool_name || m.name) && <Badge>{m.tool_name || m.name}</Badge>}
          </div>
          <div className="p-2.5">
            {text(m.content) && <div className="whitespace-pre-wrap break-words text-[13px] text-fg">{text(m.content)}</div>}
            {m.tool_calls?.map((tc, j) => (
              <div key={j} className="mt-1.5">
                <ToolCallBox name={tc.function?.name ?? tc.name ?? "?"} args={tc.function?.arguments ?? tc.arguments} />
              </div>
            ))}
            {!text(m.content) && !m.tool_calls?.length && <div className="text-[12px] italic text-fg-3">(leer)</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

export function LlmCallBody({ call }: { call: LlmCall }) {
  const req = call.request ?? {};
  const messages = (req.messages as ChatMessage[] | undefined) ??
    [...(req.system ? [{ role: "system", content: req.system }] : []), { role: "user", content: req.prompt }];
  const options = Object.fromEntries(Object.entries(req).filter(([k]) => !["messages", "prompt", "system", "tools"].includes(k)));
  const tools = req.tools as { function?: { name?: string } }[] | undefined;
  return (
    <div className="flex flex-col gap-3">
      {call.error && <ErrorBox error={call.error} />}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-fg-2">
        <span>Modell <b className="font-medium text-fg">{call.model ?? "?"}</b></span>
        <span>Endpunkt <b className="font-medium text-fg">{call.endpoint}</b></span>
        <span>Dauer <b className="tabular font-medium text-fg">{fmtMs(call.duration_ms)}</b></span>
        <span>Tokens <b className="tabular font-medium text-fg">{fmtNum(call.tokens_in)} → {fmtNum(call.tokens_out)}</b></span>
        {call.duration_ms && call.tokens_out ? (
          <span>Tempo <b className="tabular font-medium text-fg">{((call.tokens_out / call.duration_ms) * 1000).toFixed(1).replace(".", ",")} Tok/s</b></span>
        ) : null}
      </div>
      <Collapsible title={`Eingabe (${messages.length} Nachrichten)`} defaultOpen={messages.length <= 3}>
        <MessageList messages={messages} />
      </Collapsible>
      {tools?.length ? (
        <Collapsible title={`Verfügbare Tools (${tools.length})`}>
          <div className="flex flex-wrap gap-1.5">{tools.map((t, i) => <Badge key={i}>{t.function?.name ?? "?"}</Badge>)}</div>
          <CodeBlock className="mt-2">{prettyJson(tools)}</CodeBlock>
        </Collapsible>
      ) : null}
      {call.thinking && (
        <div>
          <div className="mb-1 flex items-center gap-1.5 text-[12px] font-medium text-fg-2"><Brain size={13} /> Denkprozess</div>
          <CodeBlock className="italic">{call.thinking}</CodeBlock>
        </div>
      )}
      {call.tool_calls?.length ? (
        <div>
          <div className="mb-1 text-[12px] font-medium text-fg-2">Entscheidung: Tool-Aufrufe</div>
          <div className="flex flex-col gap-2">
            {call.tool_calls.map((tc, i) => {
              const inv = call.tool_invocations?.find((t) => t.llm_call_id === call.id && t.name === tc.name && (!tc.id || t.call_ref === tc.id));
              return <ToolCallBox key={i} name={tc.name} args={tc.arguments} result={inv ? inv.result : undefined} />;
            })}
          </div>
        </div>
      ) : null}
      {call.response && (
        <div>
          <div className="mb-1 text-[12px] font-medium text-fg-2">Antwort</div>
          <CodeBlock>{call.response}</CodeBlock>
        </div>
      )}
      {Object.keys(options).length > 0 && (
        <Collapsible title="Parameter">
          <CodeBlock>{prettyJson(options)}</CodeBlock>
        </Collapsible>
      )}
    </div>
  );
}

/** Lädt einen LLM-Aufruf vollständig (inkl. Prompt) und zeigt ihn an. */
export function LlmCallDetail({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["llm-call", id], queryFn: () => api<LlmCall>(`/api/llm-calls/${id}`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  return <LlmCallBody call={q.data!} />;
}
