import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CodeBlock, ErrorBox, inputClass, KeyValue, Loading, PageHeader } from "../components/ui";
import { api, type RuntimeSettings, type SystemInfo } from "../lib/api";
import { fmtBytes, fmtNum } from "../lib/format";

const COMPOSE_SNIPPET = `services:
  mein-agent:
    image: mein-agent:latest
    labels:
      agentdash.enable: "true"        # Container im Dashboard anzeigen
      agentdash.app: "mein-agent"     # optional: Anwendungsname
    environment:
      OLLAMA_HOST: http://agentdash:11434         # LLM-Aufrufe über das Dashboard
      AGENTDASH_ENDPOINT: http://agentdash:4318   # nur mit SDK nötig
    networks: [agentdash]

networks:
  agentdash:
    external: true`;

const SDK_SNIPPET = `import agentdash
from agentdash import run, agent, tool

agentdash.init()

@tool
def suche(query: str) -> str: ...

with run("Anfrage bearbeiten"):
    with agent("planner") as planner:
        with agent("researcher"):
            ergebnis = suche("…")
        planner.set_output(ergebnis)`;

export function SettingsPage() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<RuntimeSettings>("/api/settings") });
  const system = useQuery({ queryKey: ["system"], queryFn: () => api<SystemInfo>("/api/system") });
  const [form, setForm] = useState<RuntimeSettings | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (settings.data) setForm(settings.data);
  }, [settings.data]);
  const save = useMutation({
    mutationFn: (v: RuntimeSettings) => api<RuntimeSettings>("/api/settings", { method: "PUT", body: JSON.stringify(v) }),
    onSuccess: (v) => {
      qc.setQueryData(["settings"], v);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2500);
    },
  });
  const cleanup = useMutation({
    mutationFn: () => api<Record<string, number>>("/api/settings/retention/run", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
  });

  if (settings.isLoading || !form) return <Loading />;
  const s = system.data;
  const set = <K extends keyof RuntimeSettings>(k: K, v: RuntimeSettings[K]) => setForm({ ...form, [k]: v });

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Einstellungen" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Speicherung & Aufbewahrung">
          <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); save.mutate(form); }}>
            <label className="flex flex-col gap-1 text-[13px]">
              <span className="font-medium">Logs aufbewahren (Tage)</span>
              <input type="number" min={1} className={inputClass} value={form.log_retention_days} onChange={(e) => set("log_retention_days", Number(e.target.value))} />
            </label>
            <label className="flex flex-col gap-1 text-[13px]">
              <span className="font-medium">Runs, LLM-Aufrufe & Nachrichten aufbewahren (Tage)</span>
              <input type="number" min={1} className={inputClass} value={form.run_retention_days} onChange={(e) => set("run_retention_days", Number(e.target.value))} />
            </label>
            <fieldset className="flex flex-col gap-1.5 text-[13px]">
              <legend className="mb-1 font-medium">Prompts & Antworten speichern</legend>
              {([
                ["full", "Vollständig", "Empfohlen, um Aktionen vollständig nachvollziehen zu können."],
                ["truncate", "Gekürzt", "Lange Inhalte werden nach der eingestellten Zeichenzahl abgeschnitten."],
                ["none", "Nicht speichern", "Nur Metadaten (Modell, Dauer, Tokens, Tool-Namen)."],
              ] as const).map(([v, l, hint]) => (
                <label key={v} className="flex cursor-pointer items-start gap-2">
                  <input type="radio" name="store" className="mt-1 accent-[var(--accent)]" checked={form.store_prompts === v} onChange={() => set("store_prompts", v)} />
                  <span><span className="font-medium">{l}</span><span className="block text-[12px] text-fg-2">{hint}</span></span>
                </label>
              ))}
            </fieldset>
            {form.store_prompts === "truncate" && (
              <label className="flex flex-col gap-1 text-[13px]">
                <span className="font-medium">Maximale Zeichen pro Inhalt</span>
                <input type="number" min={100} className={inputClass} value={form.prompt_truncate_chars} onChange={(e) => set("prompt_truncate_chars", Number(e.target.value))} />
              </label>
            )}
            {save.error && <ErrorBox error={save.error} />}
            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" variant="primary" disabled={save.isPending}>Speichern</Button>
              <Button onClick={() => cleanup.mutate()} disabled={cleanup.isPending} title="Alte Daten jetzt löschen">Jetzt aufräumen</Button>
              {saved && <span className="text-[12px] text-good-text">Gespeichert</span>}
              {cleanup.data && <span className="text-[12px] text-fg-2">Gelöscht: {fmtNum(cleanup.data.logs)} Logs, {fmtNum(cleanup.data.runs)} Runs</span>}
            </div>
          </form>
        </Card>
        <Card title="System">
          {s ? (
            <KeyValue
              items={[
                ["Version", s.version],
                ["Ports", <span className="tabular">UI {s.ports.ui} · OTLP {s.ports.otlp} · Ollama-Proxy {s.ports.proxy}</span>],
                ["Ollama", <code className="font-mono text-[12px]">{s.ollama_upstream}</code>],
                ["Docker", s.docker.enabled ? <span className="flex items-center gap-2">{s.docker.connected ? <Badge tone="good">verbunden</Badge> : <Badge tone="critical">nicht verbunden</Badge>}<code className="font-mono text-[12px]">{s.docker.host}</code></span> : "deaktiviert"],
                ["Erkennung", <>Label <code className="font-mono text-[12px]">{s.docker.label}=true</code>{s.docker.auto_discover && " + automatisch bei Proxy-/OTLP-Nutzung"}</>],
                ["Anmeldung", s.auth_enabled ? "Passwort aktiv" : <span className="text-warning-text">ohne Passwort (AGENTDASH_PASSWORD setzen)</span>],
                ["Ingest-Schlüssel", s.ingest_key_enabled ? "aktiv" : "aus"],
                ["Datenbank", <span>{fmtBytes(s.db_size)} · <code className="font-mono text-[12px]">{s.db_path}</code></span>],
                ["Einträge", <span className="tabular">{fmtNum(s.counts.applications)} Apps · {fmtNum(s.counts.agents)} Agenten · {fmtNum(s.counts.runs)} Runs · {fmtNum(s.counts.llm_calls)} LLM · {fmtNum(s.counts.logs)} Logs</span>],
              ]}
            />
          ) : <Loading />}
        </Card>
      </div>
      <Card title="Agenten anbinden">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="flex flex-col gap-2 text-[13px]">
            <p><b>1. Ohne Codeänderung:</b> Container ins Netzwerk <code className="font-mono">agentdash</code> hängen, Label setzen und <code className="font-mono">OLLAMA_HOST</code> auf das Dashboard zeigen lassen. Dann siehst du Container-Logs, alle LLM-Aufrufe, Denkprozesse und Tool-Aufrufe.</p>
            <CodeBlock>{COMPOSE_SNIPPET}</CodeBlock>
          </div>
          <div className="flex flex-col gap-2 text-[13px]">
            <p><b>2. Mehrere Agenten in einer Anwendung:</b> Mit dem Python-SDK <code className="font-mono">agentdash</code> werden die einzelnen Agenten, ihre Aufrufe untereinander und Tool-Ausführungen sichtbar.</p>
            <CodeBlock>{SDK_SNIPPET}</CodeBlock>
          </div>
        </div>
      </Card>
    </div>
  );
}
