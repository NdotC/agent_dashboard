import type { Agent } from "./api";

// Kategoriale Farben in fester Reihenfolge (validierte Palette, hell/dunkel über CSS-Variablen).
export const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);
export const NEUTRAL = "var(--neutral-series)";

/**
 * Farbe eines Agenten: eigene Farbe, sonst der Slot entsprechend seiner Position innerhalb
 * der Anwendung (nach ID sortiert). Ab dem 9. Agenten neutral grau statt Wiederholung.
 */
export function agentColor(agent: Pick<Agent, "id" | "app_id" | "color"> | null | undefined, all: Agent[] | Record<string, Agent>): string {
  if (!agent) return NEUTRAL;
  if (agent.color) return agent.color;
  const list = (Array.isArray(all) ? all : Object.values(all))
    .filter((a) => a.app_id === agent.app_id)
    .sort((a, b) => a.id - b.id);
  const idx = list.findIndex((a) => a.id === agent.id);
  return idx >= 0 && idx < SERIES.length ? SERIES[idx] : NEUTRAL;
}

export const agentLabel = (a: Pick<Agent, "name" | "display_name"> | null | undefined) =>
  a ? a.display_name || a.name : "Start";
