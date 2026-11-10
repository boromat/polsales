// Ustawienia - statusy konfiguracji integracji (bez edycji sekretów, decyzja #12) i prywatność AI.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";

import { api, type IntegrationsConfig, type PrivacyStatus } from "@/api/client";
import { Badge, Button, Card, Skeleton } from "@/components/ui";

const ITEMS: { key: keyof IntegrationsConfig; label: string; hint: string }[] = [
  { key: "imap", label: "Skrzynka e-mail (IMAP)", hint: "IMAP_* w .env - pobiera zamówienia z maili" },
  { key: "meta_ads", label: "Meta Ads", hint: "META_ACCESS_TOKEN + META_AD_ACCOUNT_ID" },
  { key: "meta_organic", label: "Meta organicznie", hint: "META_ACCESS_TOKEN + META_PAGE_ID" },
  { key: "google_ads", label: "Google Ads", hint: "GOOGLE_ADS_* (MCC + developer token)" },
  { key: "ga4", label: "Google Analytics 4", hint: "GA4_SERVICE_ACCOUNT_JSON + GA4_PROPERTY_ID" },
  { key: "anthropic", label: "Asystent AI", hint: "OPENROUTER_API_KEY (lub ANTHROPIC_API_KEY)" },
  { key: "smtp", label: "Powiadomienia e-mail", hint: "SMTP_* - nowe zamówienia, alerty, zestawienia" },
];

const PROVIDERS: Record<string, string> = {
  openrouter: "OpenRouter",
  anthropic: "Anthropic",
  custom: "Własny endpoint",
};

// Wyróżniony fragment kodu (nazwy plików / zmiennych) - kontrastuje z blokiem surface-2.
const code = "rounded-md border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-text";

export function Settings() {
  const config = useQuery({
    queryKey: ["settingsConfig"],
    queryFn: () => api.get<IntegrationsConfig>("/settings/config"),
  });
  const testImap = useMutation({
    mutationFn: () => api.post("/settings/commands/test_imap"),
  });
  const testEmail = useMutation({
    mutationFn: () => api.post("/settings/commands/test_email"),
  });

  if (config.isLoading || !config.data)
    return (
      <div className="max-w-2xl space-y-6">
        <Skeleton className="h-5 w-32" />
        <div className="grid gap-3 sm:grid-cols-2">
          {ITEMS.map((_, i) => (
            <Card key={i} className="p-4">
              <div className="flex items-start gap-3">
                <Skeleton className="h-9 w-9 rounded-lg" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3.5 w-28" />
                  <Skeleton className="h-3 w-40" />
                </div>
              </div>
            </Card>
          ))}
        </div>
        <Skeleton className="h-28 w-full rounded-xl" />
        <Skeleton className="h-24 w-full rounded-xl" />
      </div>
    );

  const cfg = config.data;

  return (
    <div className="max-w-2xl space-y-6">
      {/* Integracje - karta na integrację ze statusem konfiguracji */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight text-text">Integracje</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {ITEMS.map((it) => {
            const on = Boolean(cfg[it.key]);
            const missing = cfg.missing_packages?.[it.key as "ga4" | "google_ads"] ?? null;
            return (
              <Card key={it.key} className="animate-fade-in p-4">
                <div className="flex items-start gap-3">
                  <span
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                      on && !missing ? "bg-success-soft text-success" : "bg-surface-2 text-text-subtle"
                    }`}
                  >
                    {on && !missing ? <CheckCircle2 className="h-5 w-5" /> : <XCircle className="h-5 w-5" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="text-sm font-medium text-text">{it.label}</div>
                      <Badge tone={on ? (missing ? "warning" : "success") : "neutral"} dot className="shrink-0">
                        {on ? (missing ? "brak pakietu" : "skonfigurowane") : "brak"}
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-text-muted">{it.hint}</p>
                    {missing && (
                      <p className={`mt-1 text-xs ${on ? "text-warning" : "text-text-subtle"}`}>{missing}</p>
                    )}
                    {it.key === "imap" && (
                      <div className="mt-3 flex items-center gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => testImap.mutate()}
                          disabled={testImap.isPending}
                        >
                          {testImap.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                          Testuj
                        </Button>
                        {testImap.isSuccess && <CheckCircle2 className="h-4 w-4 text-success" />}
                        {testImap.isError && <XCircle className="h-4 w-4 text-danger" />}
                      </div>
                    )}
                    {it.key === "smtp" && (
                      <div className="mt-3 flex items-center gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => testEmail.mutate()}
                          disabled={testEmail.isPending}
                        >
                          {testEmail.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                          Wyślij testowy
                        </Button>
                        {testEmail.isSuccess && <CheckCircle2 className="h-4 w-4 text-success" />}
                        {testEmail.isError && <XCircle className="h-4 w-4 text-danger" />}
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      </section>

      {/* Modele AI */}
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <h2 className="text-sm font-semibold">Modele AI</h2>
          {cfg.ai_provider && (
            <Badge tone="primary" dot>
              {PROVIDERS[cfg.ai_provider] ?? cfg.ai_provider}
            </Badge>
          )}
        </div>
        <div className="space-y-2 px-5 py-4">
          <div className="flex items-center justify-between gap-3 rounded-lg bg-surface-2 px-3 py-2">
            <span className="text-sm text-text-muted">Czat</span>
            <code className={`${code} break-all text-right`}>{cfg.chat_model}</code>
          </div>
          <div className="flex items-center justify-between gap-3 rounded-lg bg-surface-2 px-3 py-2">
            <span className="text-sm text-text-muted">Parser maili</span>
            <code className={`${code} break-all text-right`}>{cfg.email_parser_model}</code>
          </div>
        </div>
      </Card>

      <PrivacyCard />

      {/* Konfiguracja */}
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <h2 className="text-sm font-semibold">Konfiguracja</h2>
        </div>
        <div className="px-5 py-4">
          <div className="rounded-lg bg-surface-2 p-3">
            <p className="text-sm leading-relaxed text-text-muted">
              Sekrety ustawia się wyłącznie w pliku <code className={code}>deploy/.env</code> na serwerze (nie z panelu -
              bezpieczeństwo). Instrukcje krok po kroku: <code className={code}>docs/05-integracje.md</code>.
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}

/** Przełącznik maskowania danych osobowych (polanon) przed wysłaniem czegokolwiek do modelu. */
function PrivacyCard() {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["settingsPrivacy"],
    queryFn: () => api.get<PrivacyStatus>("/settings/privacy"),
  });
  const save = useMutation({
    mutationFn: (body: { enabled: boolean; ner: boolean }) => api.put<PrivacyStatus>("/settings/privacy", body),
    onSuccess: (data) => {
      qc.setQueryData(["settingsPrivacy"], data);
      qc.invalidateQueries({ queryKey: ["settingsConfig"] });
    },
  });

  const st = status.data;
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
        <h2 className="text-sm font-semibold">Prywatność AI</h2>
        {st && (
          <Badge tone={st.polanon.installed ? "success" : "danger"} dot>
            {st.polanon.installed ? `polanon ${st.polanon.version ?? ""}`.trim() : "polanon niezainstalowany"}
          </Badge>
        )}
      </div>
      <div className="space-y-3 px-5 py-4">
        {!st ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          <>
            <Toggle
              label="Maskuj dane osobowe przed wysłaniem do AI"
              hint="Czat, parser maili, zestawienia i rekomendacje. Model widzi tokeny (<OSOBA_1>, <FIRMA_1>), prawdziwe wartości wracają lokalnie. Nazwy firm klientów i NIP-y z bazy są maskowane zawsze."
              checked={st.enabled}
              disabled={save.isPending}
              onChange={(enabled) => save.mutate({ enabled, ner: enabled && st.ner })}
            />
            <Toggle
              label="Tryb NER (spaCy)"
              hint={
                st.polanon.ner
                  ? "Dodatkowy model językowy: nazwy miejsc i nazwiska spoza reguł. Wolniejszy."
                  : 'Wymaga: pip install "polanon[ner]" i python -m spacy download pl_core_news_md'
              }
              checked={st.ner}
              disabled={save.isPending || !st.enabled || (!st.polanon.ner && !st.ner)}
              onChange={(ner) => save.mutate({ enabled: st.enabled, ner })}
            />
            {st.blocking ? (
              <div className="flex items-start gap-2 rounded-lg border border-danger/25 bg-danger-soft p-3 text-xs leading-relaxed text-danger">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                Maskowanie jest włączone, ale nie może działać. Funkcje AI są zablokowane i nic nie jest wysyłane
                do modelu, dopóki nie zainstalujesz polanon albo nie wyłączysz maskowania.
              </div>
            ) : (
              st.enabled && (
                <div className="flex items-center gap-2 text-xs text-success">
                  <ShieldCheck className="h-4 w-4" /> Rozpoznane dane osobowe oraz znani klienci z bazy trafiają do modelu jako tokeny.
                </div>
              )
            )}
            {save.isError && (
              <p className="text-xs text-danger">{(save.error as Error).message || "Nie udało się zapisać."}</p>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

function Toggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className={`flex items-start gap-3 rounded-lg bg-surface-2 px-3 py-2.5 ${disabled ? "opacity-60" : "cursor-pointer"}`}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
          checked ? "bg-primary" : "bg-border-strong"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
            checked ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
      <span className="min-w-0">
        <span className="block text-sm font-medium text-text">{label}</span>
        <span className="mt-0.5 block text-xs text-text-muted">{hint}</span>
      </span>
    </label>
  );
}
