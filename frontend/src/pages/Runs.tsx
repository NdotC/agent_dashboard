import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useState } from "react";
import { RunsTable, useRuns } from "../components/RunsTable";
import { Card, inputClass, PageHeader } from "../components/ui";
import { api, type App } from "../lib/api";

export function RunsPage() {
  const [status, setStatus] = useState<string>("");
  const [appId, setAppId] = useState<string>("");
  const [q, setQ] = useState("");
  const apps = useQuery({ queryKey: ["apps"], queryFn: () => api<App[]>("/api/apps") });
  const runs = useRuns({ status: status || undefined, app_id: appId ? Number(appId) : undefined, q: q || undefined, limit: 100 }, "overview");
  return (
    <div>
      <PageHeader title="Runs" subtitle="Jeder Durchlauf einer Anwendung – mit allen Aktionen, LLM-Aufrufen und Nachrichten zwischen den Agenten." />
      <Card
        bodyClass="p-0"
        title={
          <div className="flex flex-wrap items-center gap-2 font-normal">
            {[["", "Alle"], ["running", "Laufend"], ["error", "Mit Fehlern"]].map(([v, l]) => (
              <button
                key={v}
                onClick={() => setStatus(v)}
                aria-pressed={status === v}
                className={clsx("rounded-full px-2.5 py-1 text-[12px] font-medium", status === v ? "bg-surface-3 text-fg" : "text-fg-2 hover:text-fg")}
              >
                {l}
              </button>
            ))}
          </div>
        }
        actions={
          <>
            <select className={inputClass} value={appId} onChange={(e) => setAppId(e.target.value)} aria-label="Anwendung">
              <option value="">Alle Anwendungen</option>
              {(apps.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
            <input className={clsx(inputClass, "w-44")} placeholder="Titel suchen …" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Titel suchen" />
          </>
        }
      >
        <RunsTable runs={runs.data?.runs} agents={runs.data?.agents ?? {}} showApp loading={runs.isLoading} />
      </Card>
    </div>
  );
}
