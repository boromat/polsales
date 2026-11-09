// Dokowany panel czatu AI - streaming SSE, chipy kontekstowe, historia. Etap 4.
import { useQuery } from "@tanstack/react-query";
import { Plus, Send, ShieldCheck, Sparkles } from "lucide-react";
import * as React from "react";

import { api, czytelnyBlad } from "@/api/client";
import { Badge, Button, EmptyState, Input, Spinner, Table, TBody, Td, Th, THead, Tr } from "@/components/ui";

interface ChatMsg {
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
  tools?: string[];
  /** Maskowanie polanon tej tury: ile wartości ukryto i jak pytanie wyglądało dla modelu. */
  privacy?: { masked: number; labels: Record<string, number>; modelView: string };
}

const QUICK: Record<string, string[]> = {
  Dashboard: ["Podsumuj ten tydzień", "Który kanał ma najlepszy ROAS?", "Porównaj z zeszłym miesiącem"],
  Zamówienia: ["Ile zamówień w tym tygodniu?", "Pokaż ostatnie 5 zamówień"],
  "Firmy B2B": ["Top 5 firm wg LTV", "Którzy klienci są zagrożeni odejściem?"],
  Marketing: ["Które kampanie najwięcej kosztują?", "Pokaż lejek konwersji"],
  Skrzynka: ["Streść maile czekające na weryfikację"],
};

const TOOL_LABELS: Record<string, string> = {
  query_metrics: "Pobieram metryki",
  get_orders: "Pobieram zamówienia",
  get_company_profile: "Pobieram profil firmy",
  get_funnel: "Liczę lejek",
  get_campaign_stats: "Pobieram statystyki kampanii",
  get_top_products: "Liczę top produkty",
  compare_periods: "Porównuję okresy",
  get_recommendations: "Pobieram rekomendacje",
  get_pending_drafts: "Sprawdzam szkice",
  get_ad_formats: "Porównuję formaty reklam",
  get_organic_engagement: "Sprawdzam zasięgi organiczne",
  get_email_product_trends: "Analizuję trendy z maili",
  get_weekly_summary: "Pobieram zestawienie tygodniowe",
};

export function ChatPanel({ viewName }: { viewName: string }) {
  const status = useQuery({ queryKey: ["chatStatus"], queryFn: () => api.get<{ available: boolean }>("/chat/status") });
  const [convId, setConvId] = React.useState<string | null>(null);
  const [messages, setMessages] = React.useState<ChatMsg[]>([]);
  const [input, setInput] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function ensureConversation(): Promise<string> {
    if (convId) return convId;
    const conv = await api.post<{ id: string }>("/chat/conversations");
    setConvId(conv.id);
    return conv.id;
  }

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text }, { role: "assistant", text: "", streaming: true, tools: [] }]);

    try {
      const id = await ensureConversation();
      const res = await fetch(`/api/chat/conversations/${id}/messages`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, view_context: viewName }),
      });
      // Bez sprawdzenia res.ok blad HTTP (401 po wygasnieciu sesji, 500 z backendu)
      // konczyl sie PUSTYM dymkiem asystenta - wygladalo to jak zawieszenie panelu.
      if (!res.ok) {
        let opis = `HTTP ${res.status}`;
        try {
          const dane = await res.json();
          opis = czytelnyBlad(dane.detail) ?? opis;
        } catch {
          /* odpowiedz nie jest JSON-em - zostaje sam status */
        }
        if (res.status === 401) throw new Error("Sesja wygasła - zaloguj się ponownie.");
        throw new Error(opis);
      }
      if (!res.body) throw new Error("Brak strumienia");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const evt of events) {
          handleEvent(evt);
        }
      }
    } catch (e) {
      updateLast((m) => ({ ...m, text: m.text + `\n[błąd: ${e instanceof Error ? e.message : e}]`, streaming: false }));
    } finally {
      updateLast((m) => ({ ...m, streaming: false }));
      setBusy(false);
    }
  }

  function handleEvent(evt: string) {
    const lines = evt.split("\n");
    const typeLine = lines.find((l) => l.startsWith("event:"));
    const dataLine = lines.find((l) => l.startsWith("data:"));
    if (!dataLine) return;
    const type = typeLine?.slice(6).trim() ?? "message";
    let data: any = {};
    try {
      data = JSON.parse(dataLine.slice(5).trim());
    } catch {
      return;
    }
    if (type === "text_delta") {
      updateLast((m) => ({ ...m, text: m.text + (data.text ?? "") }));
    } else if (type === "privacy") {
      updateLast((m) => ({
        ...m,
        privacy: { masked: data.masked ?? 0, labels: data.labels ?? {}, modelView: data.model_view ?? "" },
      }));
    } else if (type === "done" && (data.masked ?? 0) > 0) {
      // Wyniki narzędzi też są maskowane - końcowy licznik przychodzi dopiero z "done".
      updateLast((m) => ({
        ...m,
        privacy: { masked: data.masked, labels: data.labels ?? {}, modelView: m.privacy?.modelView ?? "" },
      }));
    } else if (type === "tool_call") {
      updateLast((m) => ({ ...m, tools: [...(m.tools ?? []), data.name] }));
    } else if (type === "error") {
      updateLast((m) => ({ ...m, text: m.text + `\n⚠ ${data.message_pl ?? "Błąd"}`, streaming: false }));
    }
  }

  function updateLast(fn: (m: ChatMsg) => ChatMsg) {
    setMessages((msgs) => {
      const copy = [...msgs];
      const idx = copy.length - 1;
      if (idx >= 0 && copy[idx].role === "assistant") copy[idx] = fn(copy[idx]);
      return copy;
    });
  }

  function newConversation() {
    setConvId(null);
    setMessages([]);
  }

  const quick = QUICK[viewName] ?? QUICK.Dashboard;
  const available = status.data?.available;

  return (
    <div className="flex h-full flex-col bg-surface">
      <div className="flex h-12 shrink-0 items-center gap-2.5 border-b border-border px-4">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-soft text-primary">
          <Sparkles className="h-4 w-4" />
        </span>
        <span className="flex-1 text-sm font-semibold tracking-tight">Asystent AI</span>
        <Button variant="ghost" size="icon" onClick={newConversation} title="Nowa rozmowa" className="h-8 w-8">
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-auto p-4">
        {available === false && (
          <div className="rounded-lg border border-warning/25 bg-warning-soft p-3 text-xs leading-relaxed text-warning">
            Asystent niedostępny - ustaw OPENROUTER_API_KEY (lub ANTHROPIC_API_KEY) w pliku .env. Reszta panelu działa normalnie.
          </div>
        )}
        {messages.length === 0 && available !== false && (
          <EmptyState
            icon={Sparkles}
            title="Zapytaj o dane"
            description="Np. „pokaż raport od czwartku od 15:00”."
          />
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={m.role === "user" ? "flex animate-fade-in-up justify-end" : "flex animate-fade-in-up justify-start"}
          >
            <div
              className={
                m.role === "user"
                  ? "max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-sm text-white shadow-sm"
                  : "max-w-[90%] rounded-2xl rounded-bl-sm bg-surface-2 px-3.5 py-2 text-sm text-text shadow-sm"
              }
            >
              {m.role === "assistant" && m.tools && m.tools.length > 0 && (
                <div className="mb-1.5 flex flex-wrap gap-1">
                  {m.tools.map((t, ti) => (
                    <Badge key={ti} tone="primary" dot>
                      {TOOL_LABELS[t] ?? t}
                    </Badge>
                  ))}
                </div>
              )}
              {m.role === "assistant" && m.privacy && m.privacy.masked > 0 && <PrivacyNote privacy={m.privacy} />}
              <MessageContent text={m.text} />
              {m.streaming && !m.text && <Spinner label="Myślę…" />}
            </div>
          </div>
        ))}
      </div>

      <div className="shrink-0 border-t border-border p-3">
        <div className="mb-2 flex flex-wrap gap-1.5">
          {quick.map((q) => (
            <button
              key={q}
              onClick={() => send(q)}
              disabled={busy || available === false}
              className="rounded-full border border-border px-3 py-1 text-xs text-text-muted transition-colors hover:border-border-strong hover:bg-primary-soft hover:text-primary disabled:pointer-events-none disabled:opacity-50"
            >
              {q}
            </button>
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="flex items-center gap-2"
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy || available === false}
            placeholder="Zapytaj o dane…"
            className="flex-1"
          />
          <Button type="submit" size="icon" disabled={busy || available === false} title="Wyślij" className="shrink-0">
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </div>
  );
}

// Minimalny renderer: tabele markdown + pogrubienia + zawijanie linii.
function MessageContent({ text }: { text: string }) {
  if (!text) return null;
  const blocks: React.ReactNode[] = [];
  const lines = text.split("\n");
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    if (lines[i].includes("|") && i + 1 < lines.length && /^[\s|:-]+$/.test(lines[i + 1])) {
      const tableLines = [];
      while (i < lines.length && lines[i].includes("|")) {
        tableLines.push(lines[i]);
        i++;
      }
      blocks.push(<MarkdownTable key={key++} lines={tableLines} />);
    } else {
      blocks.push(
        <p key={key++} className="whitespace-pre-wrap leading-relaxed">
          {renderInline(lines[i])}
        </p>,
      );
      i++;
    }
  }
  return <div className="space-y-1">{blocks}</div>;
}

function MarkdownTable({ lines }: { lines: string[] }) {
  const rows = lines
    .filter((_l, idx) => idx !== 1)
    .map((l) => l.split("|").map((c) => c.trim()).filter((_, idx, arr) => idx !== 0 && idx !== arr.length - 1));
  const [head, ...body] = rows;
  return (
    <div className="my-1 overflow-hidden rounded-lg border border-border">
      <Table className="text-xs">
        <THead>
          {head?.map((h, i) => (
            <Th key={i} className="px-2.5 py-1.5">
              {h}
            </Th>
          ))}
        </THead>
        <TBody>
          {body.map((r, ri) => (
            <Tr key={ri}>
              {r.map((c, ci) => (
                <Td key={ci} className="tabnum px-2.5 py-1.5">
                  {c}
                </Td>
              ))}
            </Tr>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p,
  );
}


const LABEL_PL: Record<string, string> = {
  OSOBA: "osoby",
  FIRMA: "firmy",
  NIP: "NIP",
  EMAIL: "e-maile",
  TELEFON: "telefony",
  ADRES: "adresy",
  KOD_POCZTOWY: "kody pocztowe",
  IBAN: "konta",
  PESEL: "PESEL",
};

/** Odznaka maskowania: model dostał tokeny zamiast danych; po kliknięciu widać jego wersję pytania. */
function PrivacyNote({ privacy }: { privacy: NonNullable<ChatMsg["privacy"]> }) {
  const kinds = Object.entries(privacy.labels)
    .map(([k, n]) => `${LABEL_PL[k] ?? k.toLowerCase()}: ${n}`)
    .join(", ");
  return (
    <details className="mb-2 rounded-lg border border-success/25 bg-success-soft px-2.5 py-1.5 text-xs text-success">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-medium">
        <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
        polanon: zamaskowano {privacy.masked} {privacy.masked === 1 ? "wartość" : "wartości"} ({kinds})
      </summary>
      {privacy.modelView && (
        <div className="mt-1.5 border-t border-success/20 pt-1.5 text-text-muted">
          <span className="font-medium text-text">Pytanie widziane przez model:</span>{" "}
          <code className="break-words font-mono">{privacy.modelView}</code>
        </div>
      )}
    </details>
  );
}
