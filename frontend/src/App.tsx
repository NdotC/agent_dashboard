import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Empty, Loading } from "./components/ui";
import { api, UNAUTHORIZED_EVENT } from "./lib/api";
import { live } from "./lib/live";
import { AgentDetailPage } from "./pages/AgentDetail";
import { AppDetailPage } from "./pages/AppDetail";
import { LoginPage } from "./pages/Login";
import { LogsPage } from "./pages/Logs";
import { OverviewPage } from "./pages/Overview";
import { RunDetailPage } from "./pages/RunDetail";
import { RunsPage } from "./pages/Runs";
import { SettingsPage } from "./pages/Settings";

export function App() {
  const qc = useQueryClient();
  const auth = useQuery({
    queryKey: ["auth"],
    queryFn: () => api<{ auth_required: boolean; authenticated: boolean }>("/api/auth/status"),
    staleTime: Infinity,
  });
  useEffect(() => {
    const onUnauthorized = () => qc.invalidateQueries({ queryKey: ["auth"] });
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [qc]);

  if (auth.isLoading) return <Loading />;
  if (auth.data && !auth.data.authenticated) {
    return (
      <LoginPage
        onLogin={() => {
          qc.clear();
          live.reconnect();
        }}
      />
    );
  }
  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" });
    qc.clear();
  };
  return (
    <Layout authEnabled={!!auth.data?.auth_required} onLogout={logout}>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/apps/:appId" element={<AppDetailPage />} />
        <Route path="/agents/:agentId" element={<AgentDetailPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/logs" element={<LogsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Empty title="Seite nicht gefunden" />} />
      </Routes>
    </Layout>
  );
}
