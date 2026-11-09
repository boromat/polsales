import { AlertCircle, BarChart3, Loader2 } from "lucide-react";
import * as React from "react";

import { useAuth } from "@/auth";
import { Button, Input, Label } from "@/components/ui";
import { pl } from "@/i18n/pl";

export function Login() {
  const { login } = useAuth();
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : pl.login.error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-bg p-4">
      {/* Delikatna poświata marki w tle. */}
      <div className="pointer-events-none absolute -top-40 left-1/2 h-[420px] w-[720px] -translate-x-1/2 rounded-full bg-primary/15 blur-[120px]" />

      <div className="relative w-full max-w-sm animate-fade-in-up">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-[#4F46E5] text-white shadow-lg shadow-primary/25">
            <BarChart3 className="h-6 w-6" />
          </span>
          <h1 className="text-lg font-semibold tracking-tight">{pl.appName}</h1>
          <p className="mt-1 text-sm text-text-muted">{pl.login.title}</p>
        </div>

        <div className="rounded-2xl border border-border bg-surface p-6 shadow-pop">
          <form onSubmit={onSubmit} className="space-y-4">
            <div>
              <Label>{pl.login.username}</Label>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                placeholder="wlasciciel"
              />
            </div>
            <div>
              <Label>{pl.login.password}</Label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="••••••••"
              />
            </div>
            {error && (
              <div className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error}
              </div>
            )}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {pl.common.loading}
                </>
              ) : (
                pl.login.submit
              )}
            </Button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-text-subtle">
          System wewnętrzny · dostęp tylko dla właściciela
        </p>
      </div>
    </div>
  );
}
