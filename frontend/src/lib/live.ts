// WebSocket-Verbindung für Live-Updates mit automatischem Reconnect und Topic-Abos.
import { useEffect, useRef, useSyncExternalStore } from "react";

export interface LiveEvent {
  type: string;
  topic: string;
  data: any; // eslint-disable-line @typescript-eslint/no-explicit-any
}
type Handler = (ev: LiveEvent) => void;

class LiveSocket {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private retry = 0;
  private timer: number | null = null;
  private listeners = new Set<() => void>();
  status: "connecting" | "open" | "closed" = "closed";

  private setStatus(s: LiveSocket["status"]) {
    this.status = s;
    this.listeners.forEach((l) => l());
  }

  onStatus(l: () => void) {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  }

  connect() {
    if (this.ws || typeof window === "undefined") return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.setStatus("connecting");
    const ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.setStatus("open");
      const topics = [...this.handlers.keys()];
      if (topics.length) ws.send(JSON.stringify({ op: "subscribe", topics }));
    };
    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      const events: LiveEvent[] = data.type === "batch" ? data.events : [data];
      for (const ev of events) {
        if (!ev.topic) continue;
        this.handlers.get(ev.topic)?.forEach((h) => h(ev));
      }
    };
    ws.onclose = () => {
      this.ws = null;
      this.setStatus("closed");
      const delay = Math.min(1000 * 2 ** this.retry++, 15000);
      this.timer = window.setTimeout(() => this.connect(), delay);
    };
  }

  reconnect() {
    if (this.timer) window.clearTimeout(this.timer);
    this.ws?.close();
    this.ws = null;
    this.retry = 0;
    this.connect();
  }

  subscribe(topics: string[], handler: Handler): () => void {
    const fresh: string[] = [];
    for (const t of topics) {
      let set = this.handlers.get(t);
      if (!set) {
        set = new Set();
        this.handlers.set(t, set);
        fresh.push(t);
      }
      set.add(handler);
    }
    if (fresh.length && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ op: "subscribe", topics: fresh }));
    }
    this.connect();
    return () => {
      const gone: string[] = [];
      for (const t of topics) {
        const set = this.handlers.get(t);
        set?.delete(handler);
        if (set && set.size === 0) {
          this.handlers.delete(t);
          gone.push(t);
        }
      }
      if (gone.length && this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ op: "unsubscribe", topics: gone }));
      }
    };
  }
}

export const live = new LiveSocket();

/** Abonniert Topics; der Handler darf sich zwischen Renderings ändern. */
export function useLive(topics: (string | null | undefined)[], handler: Handler) {
  const ref = useRef(handler);
  ref.current = handler;
  const key = topics.filter(Boolean).join("|");
  useEffect(() => {
    if (!key) return;
    return live.subscribe(key.split("|"), (ev) => ref.current(ev));
  }, [key]);
}

export function useLiveStatus() {
  return useSyncExternalStore(
    (cb) => live.onStatus(cb),
    () => live.status,
  );
}

/** Ruft fn höchstens alle `ms` Millisekunden auf (letzter Aufruf gewinnt). */
export function useThrottled(fn: () => void, ms: number) {
  const ref = useRef(fn);
  ref.current = fn;
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);
  return () => {
    if (timer.current) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      ref.current();
    }, ms);
  };
}
