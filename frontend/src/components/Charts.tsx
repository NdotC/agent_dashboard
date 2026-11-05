import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtHour, fmtMs, fmtNum } from "../lib/format";

interface Point { ts: number; [key: string]: number | null }

function ChartTooltip({ active, payload, label, unit, formatter }: {
  active?: boolean; payload?: { value: number }[]; label?: number; unit: string; formatter?: (v: number) => string;
}) {
  if (!active || !payload?.length || label == null) return null;
  const v = payload[0].value;
  return (
    <div className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12px] shadow">
      <div className="text-fg-2">{fmtHour(label)} – {fmtHour(label + 3600)}</div>
      <div className="tabular font-medium text-fg">{v == null ? "–" : formatter ? formatter(v) : fmtNum(v)} {unit}</div>
    </div>
  );
}

const axis = { stroke: "var(--fg-3)", fontSize: 11, tickLine: false, axisLine: false } as const;

/** Säulen pro Stunde (eine Serie, daher keine Legende – der Titel benennt sie). */
export function HourlyBars({ data, dataKey, unit, color = "var(--series-1)", height = 160 }: {
  data: Point[]; dataKey: string; unit: string; color?: string; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -18 }} barCategoryGap={2}>
        <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="2 4" />
        <XAxis dataKey="ts" tickFormatter={fmtHour} interval={5} {...axis} />
        <YAxis allowDecimals={false} width={44} {...axis} />
        <Tooltip cursor={{ fill: "var(--surface-2)" }} content={<ChartTooltip unit={unit} />} />
        <Bar dataKey={dataKey} fill={color} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function HourlyLine({ data, dataKey, unit, color = "var(--series-1)", height = 160, ms = false }: {
  data: Point[]; dataKey: string; unit: string; color?: string; height?: number; ms?: boolean;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -4 }}>
        <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="2 4" />
        <XAxis dataKey="ts" tickFormatter={fmtHour} interval={5} {...axis} />
        <YAxis width={64} tickFormatter={(v) => (ms ? fmtMs(v) : fmtNum(v))} {...axis} />
        <Tooltip
          cursor={{ stroke: "var(--line-strong)" }}
          content={<ChartTooltip unit={ms ? "" : unit} formatter={ms ? (v) => fmtMs(v) : undefined} />}
        />
        <Line dataKey={dataKey} stroke={color} strokeWidth={2}
          dot={data.filter((p) => p[dataKey] != null).length <= 3 ? { r: 4, fill: color, strokeWidth: 0 } : false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
          connectNulls isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
