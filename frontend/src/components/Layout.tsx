import clsx from "clsx";
import { Activity, Boxes, LayoutDashboard, LogOut, Menu, Monitor, Moon, ScrollText, Settings, Sun, Workflow, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type App } from "../lib/api";
import { useLive, useLiveStatus } from "../lib/live";
import { ContainerStatus } from "./ui";

type Theme = "system" | "light" | "dark";

function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const t = localStorage.getItem("agentdash-theme");
      return t === "light" || t === "dark" ? t : "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("agentdash-theme", theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  return [theme, setTheme];
}

const NAV = [
  { to: "/", label: "Übersicht", icon: LayoutDashboard, end: true },
  { to: "/runs", label: "Runs", icon: Workflow },
  { to: "/logs", label: "Logs & Suche", icon: ScrollText },
  { to: "/settings", label: "Einstellungen", icon: Settings },
];

export function Layout({ children, authEnabled, onLogout }: { children: ReactNode; authEnabled: boolean; onLogout: () => void }) {
  const [theme, setTheme] = useTheme();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const liveStatus = useLiveStatus();
  const apps = useQuery({ queryKey: ["apps"], queryFn: () => api<App[]>("/api/apps") });
  useLive(["overview"], (ev) => {
    if (ev.type === "app" || ev.type === "agent" || ev.type === "app_deleted") apps.refetch();
  });
  useEffect(() => setOpen(false), [location.pathname]);

  const nextTheme: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  const ThemeIcon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;

  const sidebar = (
    <nav className="flex h-full flex-col gap-1 p-3">
      <div className="mb-3 flex items-center gap-2 px-2 pt-1">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-accent-fg">
          <Activity size={16} />
        </div>
        <div className="font-semibold tracking-tight">Agent Dashboard</div>
      </div>
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            clsx(
              "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium",
              isActive ? "bg-surface-3 text-fg" : "text-fg-2 hover:bg-surface-2 hover:text-fg",
            )
          }
        >
          <Icon size={16} /> {label}
        </NavLink>
      ))}
      <div className="mt-4 flex items-center gap-2 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-fg-3">
        <Boxes size={13} /> Anwendungen
      </div>
      <div className="scroll-thin -mx-1 flex-1 overflow-y-auto px-1">
        {(apps.data ?? []).map((app) => (
          <NavLink
            key={app.id}
            to={`/apps/${app.id}`}
            className={({ isActive }) =>
              clsx(
                "flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-[13px]",
                isActive ? "bg-surface-3 text-fg" : "text-fg-2 hover:bg-surface-2 hover:text-fg",
              )
            }
          >
            <span className="truncate">{app.name}</span>
            <ContainerStatus status={app.status} />
          </NavLink>
        ))}
        {apps.data?.length === 0 && <div className="px-2.5 py-1 text-[12px] text-fg-3">Noch keine Anwendungen</div>}
      </div>
      <div className="mt-2 flex items-center justify-between border-t border-line px-1 pt-3">
        <span className="flex items-center gap-1.5 text-[12px] text-fg-2" title="Live-Verbindung zum Server">
          <span
            className={clsx("h-2 w-2 rounded-full", liveStatus === "open" ? "bg-good" : liveStatus === "connecting" ? "pulse bg-warning" : "bg-critical")}
          />
          {liveStatus === "open" ? "Live" : liveStatus === "connecting" ? "Verbinde …" : "Getrennt"}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setTheme(nextTheme[theme])}
            className="rounded-md p-1.5 text-fg-2 hover:bg-surface-2 hover:text-fg"
            title={`Design: ${theme === "system" ? "System" : theme === "light" ? "Hell" : "Dunkel"}`}
            aria-label="Design wechseln"
          >
            <ThemeIcon size={16} />
          </button>
          {authEnabled && (
            <button onClick={onLogout} className="rounded-md p-1.5 text-fg-2 hover:bg-surface-2 hover:text-fg" title="Abmelden" aria-label="Abmelden">
              <LogOut size={16} />
            </button>
          )}
        </div>
      </div>
    </nav>
  );

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-line bg-surface lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-line bg-surface">{sidebar}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line bg-surface px-4 py-2.5 lg:hidden">
          <button onClick={() => setOpen(!open)} aria-label="Menü" className="rounded-md p-1 text-fg-2 hover:bg-surface-2">
            {open ? <X size={18} /> : <Menu size={18} />}
          </button>
          <span className="font-semibold">Agent Dashboard</span>
        </header>
        <main className="scroll-thin min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1500px] px-4 py-5 sm:px-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
