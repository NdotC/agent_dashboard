// Typen und Fetch-Helfer für die Dashboard-API.

export type AppStatus = "running" | "exited" | "restarting" | "paused" | "created" | "dead" | "removed" | "active" | "unknown";
export type RunStatus = "running" | "ok" | "error" | "stale";
export type Level = "debug" | "info" | "warn" | "error";

export interface Agent {
  id: number;
  app_id: number;
  name: string;
  display_name: string | null;
  color: string | null;
  role: string | null;
  model: string | null;
  first_seen: number;
  last_seen: number;
  llm_calls_24h?: number;
  tokens_24h?: number;
  avg_ms_24h?: number | null;
  llm_errors_24h?: number;
}

export interface App {
  id: number;
  key: string;
  name: string;
  source: string;
  container_id: string | null;
  container_name: string | null;
  image: string | null;
  status: AppStatus;
  started_at: number | null;
  exit_code: number | null;
  restart_count: number;
  labels: Record<string, string> | null;
  first_seen: number;
  last_seen: number;
  agents: Agent[];
  llm_calls_24h: number;
  tokens_in_24h: number;
  tokens_out_24h: number;
  errors_24h: number;
  runs_24h: number;
  active_runs: number;
  last_activity: number | null;
  last_log: { message: string; level: Level; ts: number } | null;
}

export interface OllamaState {
  reachable: boolean;
  upstream: string;
  checked_at: number | null;
  version?: string | null;
  error?: string;
  loaded?: { name: string; size: number; size_vram: number; expires_at: string; parameter_size?: string; quantization?: string }[];
  available?: { name: string; size: number; parameter_size?: string; family?: string }[];
  vram_used?: number;
}

export interface Overview {
  apps: App[];
  kpis: {
    apps_total: number;
    apps_running: number;
    agents_total: number;
    active_runs: number;
    llm_calls_24h: number;
    tokens_24h: number;
    errors_24h: number;
  };
  hours: { ts: number; llm_calls: number; tokens: number; errors: number }[];
  ollama: OllamaState;
  docker_connected: boolean;
  now: number;
}

export interface Run {
  id: string;
  app_id: number;
  title: string | null;
  source: "sdk" | "auto";
  status: RunStatus;
  started_at: number;
  ended_at: number | null;
  last_activity: number;
  tokens_in: number;
  tokens_out: number;
  llm_calls: number;
  errors: number;
  agent_ids?: number[];
  app_name?: string;
}

export interface Span {
  id: string;
  run_id: string;
  parent_id: string | null;
  agent_id: number | null;
  kind: "run" | "agent" | "tool" | "step" | "llm";
  name: string;
  started_at: number;
  ended_at: number | null;
  status: "running" | "ok" | "error";
  status_message: string | null;
  input: string | null;
  output: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  attributes: Record<string, unknown> | null;
}

export interface Message {
  id: number;
  app_id: number;
  run_id: string;
  span_id: string | null;
  from_agent_id: number | null;
  to_agent_id: number | null;
  kind: string;
  content: string | null;
  ts: number;
}

export interface ToolCallInfo {
  id: string | null;
  name: string;
  arguments: unknown;
}

export interface LlmCall {
  id: number;
  app_id: number;
  agent_id: number | null;
  run_id: string | null;
  span_id: string | null;
  parent_span_id: string | null;
  parent_call_id: number | null;
  endpoint: string;
  model: string | null;
  request?: Record<string, unknown> | null;
  response?: string | null;
  thinking?: string | null;
  tool_calls: ToolCallInfo[] | null;
  tokens_in: number | null;
  tokens_out: number | null;
  duration_ms: number | null;
  started_at: number;
  status: "ok" | "error";
  error: string | null;
  prompt_preview?: string | null;
  response_preview?: string | null;
  tool_invocations?: ToolInvocation[];
}

export interface ToolInvocation {
  id: number;
  app_id: number;
  agent_id: number | null;
  run_id: string | null;
  llm_call_id: number | null;
  result_llm_call_id: number | null;
  call_ref: string | null;
  name: string;
  arguments: unknown;
  result: string | null;
  ts: number;
  result_ts: number | null;
}

export interface LogEntry {
  id: number;
  ts: number;
  app_id: number;
  agent_id: number | null;
  run_id: string | null;
  span_id: string | null;
  level: Level;
  source: "docker" | "sdk" | "proxy";
  stream: string | null;
  message: string;
  attributes: Record<string, unknown> | null;
}

export interface RunDetail {
  run: Run;
  app: App | null;
  spans: Span[];
  llm_calls: LlmCall[];
  messages: Message[];
  tools: ToolInvocation[];
  logs: LogEntry[];
  agents: Record<string, Agent>;
}

export interface GraphNode {
  id: string;
  kind: "start" | "agent";
  agent_id: number | null;
  name: string;
  color?: string | null;
  model?: string | null;
  llm_calls?: number;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  count: number;
  kinds: Record<string, number>;
  last_ts: number;
}
export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface AgentDetail extends Agent {
  app: App | null;
  stats_24h: { llm_calls: number; tokens_in: number; tokens_out: number; avg_ms: number | null; errors: number | null };
  hours: { ts: number; llm_calls: number; avg_ms: number | null; tokens_out: number }[];
  tools: { name: string; n: number }[];
  peers: { from_agent_id: number | null; to_agent_id: number | null; n: number }[];
}

export interface SearchResult {
  logs: LogEntry[];
  llm_calls: LlmCall[];
  messages: Message[];
  runs: Run[];
  tools: ToolInvocation[];
}

export interface RuntimeSettings {
  log_retention_days: number;
  run_retention_days: number;
  store_prompts: "full" | "truncate" | "none";
  prompt_truncate_chars: number;
}

export interface SystemInfo {
  version: string;
  ports: { ui: number; otlp: number; proxy: number };
  ollama_upstream: string;
  docker: { enabled: boolean; host: string; connected: boolean; containers_seen: number; label: string; auto_discover: boolean };
  auth_enabled: boolean;
  ingest_key_enabled: boolean;
  db_path: string;
  db_size: number;
  counts: Record<string, number>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const UNAUTHORIZED_EVENT = "agentdash:unauthorized";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (res.status === 401 && !path.startsWith("/api/auth")) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, String(detail));
  }
  return res.json() as Promise<T>;
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
