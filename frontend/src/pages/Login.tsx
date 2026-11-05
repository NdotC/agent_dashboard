import { Activity } from "lucide-react";
import { useState } from "react";
import { Button, ErrorBox, inputClass } from "../components/ui";
import { api } from "../lib/api";

export function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="flex min-h-full items-center justify-center px-4">
      <form
        className="card flex w-full max-w-sm flex-col gap-4 p-6"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api("/api/auth/login", { method: "POST", body: JSON.stringify({ password }) });
            onLogin();
          } catch (err) {
            setError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-accent-fg"><Activity size={18} /></div>
          <h1 className="text-lg font-semibold">Agent Dashboard</h1>
        </div>
        <label className="flex flex-col gap-1 text-[13px]">
          <span className="font-medium">Passwort</span>
          <input type="password" autoFocus className={inputClass} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {error != null && <ErrorBox error={error} />}
        <Button type="submit" variant="primary" disabled={busy || !password}>Anmelden</Button>
      </form>
    </div>
  );
}
