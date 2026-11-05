const nf = new Intl.NumberFormat("de-DE");
const compact = new Intl.NumberFormat("de-DE", { notation: "compact", maximumFractionDigits: 1 });
const timeFmt = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dateTimeFmt = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
});
const hourFmt = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" });

export const fmtNum = (n: number | null | undefined) => (n == null ? "–" : nf.format(n));
export const fmtCompact = (n: number | null | undefined) => (n == null ? "–" : compact.format(n));
export const fmtTime = (ts: number | null | undefined) => (ts ? timeFmt.format(ts * 1000) : "–");
export const fmtHour = (ts: number) => hourFmt.format(ts * 1000);
export function fmtDateTime(ts: number | null | undefined) {
  if (!ts) return "–";
  const d = new Date(ts * 1000);
  const today = new Date();
  return d.toDateString() === today.toDateString() ? `heute ${timeFmt.format(d)}` : dateTimeFmt.format(d);
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "–";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m} min ${s} s`;
}

export function fmtDuration(start: number | null | undefined, end: number | null | undefined): string {
  if (!start) return "–";
  return fmtMs(((end ?? Date.now() / 1000) - start) * 1000);
}

export function fmtAgo(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (!ts) return "nie";
  const d = Math.max(0, now - ts);
  if (d < 10) return "gerade eben";
  if (d < 60) return `vor ${Math.floor(d)} s`;
  if (d < 3600) return `vor ${Math.floor(d / 60)} min`;
  if (d < 86400) return `vor ${Math.floor(d / 3600)} h`;
  return `vor ${Math.floor(d / 86400)} d`;
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0).replace(".", ",")} ${units[i]}`;
}

export function shortId(id: string | null | undefined, n = 8) {
  if (!id) return "–";
  return id.replace(/^auto-/, "").slice(0, n);
}

export function prettyJson(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  return JSON.stringify(value, null, 2);
}
