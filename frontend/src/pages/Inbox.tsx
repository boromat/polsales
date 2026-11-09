// Skrzynka - weryfikacja szkiców zamówień z maili (master-detail). Etap 2.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, AlertTriangle, Check, CheckCheck, Handshake, Loader2, Mail, Sparkles, X } from "lucide-react";
import * as React from "react";

import {
  api,
  type Channel,
  type DraftDetail,
  type DraftListItem,
  type PartnerEmail,
  type ProblemEmail,
  type Product,
} from "@/api/client";
import { Badge, Button, Card, EmptyState, Input, Label, Select, Skeleton } from "@/components/ui";
import { dateTimeStr } from "@/lib/format";

interface ReviewItem {
  raw_name: string | null;
  product_id: string;
  quantity: string;
  unit_price_gross: string;
  vat_rate: string;
}

function confidenceBadge(method: string, conf: number | null) {
  if (method === "reguly") return <Badge tone="success" dot>Wysoka (formularz)</Badge>;
  if (conf !== null && conf >= 0.7) return <Badge tone="warning" dot>Średnia (AI)</Badge>;
  return <Badge tone="danger" dot>Niska - sprawdź</Badge>;
}

export function Inbox() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<number | null>(null);

  const drafts = useQuery({
    queryKey: ["drafts"],
    queryFn: () => api.get<DraftListItem[]>("/drafts?status=do_weryfikacji"),
  });
  // Maile rozpoznane jako zamowienie, ktorych nie udalo sie sparsowac. Bez tej sekcji
  // znikaly z panelu bez sladu - wlasciciel nie wiedzial, ze klient probowal zamowic.
  const problemy = useQuery({
    queryKey: ["draft-problems"],
    queryFn: () => api.get<ProblemEmail[]>("/drafts/problems"),
  });

  const oznaczObsluzony = useMutation({
    mutationFn: (id: number) => api.post(`/drafts/problems/${id}/obsluzony`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["draft-problems"] });
      qc.invalidateQueries({ queryKey: ["draftsCount"] });
    },
  });
  const nieodczytane = problemy.data ?? [];

  // Zgłoszenia współpracy ze strony (klub sportowy / hurtownik). To nie zamówienia: nie mają
  // szkicu i nie wchodzą do sprzedaży. Są tu po to, żeby nie ginęły w skrzynce.
  const wspolpraca = useQuery({
    queryKey: ["draft-partners"],
    queryFn: () => api.get<PartnerEmail[]>("/drafts/partners"),
  });
  const zamknijWspolprace = useMutation({
    mutationFn: (id: number) => api.post(`/drafts/partners/${id}/obsluzony`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["draft-partners"] });
      qc.invalidateQueries({ queryKey: ["draftsCount"] });
    },
  });
  const zgloszenia = wspolpraca.data ?? [];

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Maile, ktorych nie udalo sie odczytac - bez tego znikaly z panelu bez sladu */}
      {nieodczytane.length > 0 && (
        <Card className="overflow-hidden border-warning/40">
          <div className="flex items-center gap-2 border-b border-border bg-warning-soft px-4 py-3">
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
            <h2 className="text-sm font-semibold text-warning">
              Nieodczytane zamówienia z maila ({nieodczytane.length})
            </h2>
          </div>
          <div className="px-4 py-3 text-xs text-text-muted">
            Te maile wyglądają na zamówienia, ale nie udało się z nich automatycznie odczytać danych.
            Wprowadź je ręcznie w „Zamówienia → Nowe zamówienie”.
          </div>
          <div className="divide-y divide-border">
            {nieodczytane.map((m) => (
              <div key={m.id} className="px-4 py-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">{m.subject || "(bez tematu)"}</span>
                  <span className="text-xs text-text-muted">{m.from_name || m.from_addr || "-"}</span>
                </div>
                {m.error_detail && (
                  <p className="mt-1 text-xs text-text-subtle">{m.error_detail}</p>
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  className="mt-2"
                  onClick={() => oznaczObsluzony.mutate(m.id)}
                  disabled={oznaczObsluzony.isPending}
                >
                  Obsłużone
                </Button>
                <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-2 text-xs text-text">
                  {m.body_preview}
                </pre>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Zgłoszenia współpracy - neutralny kolor, to informacja, nie ostrzeżenie */}
      {zgloszenia.length > 0 && (
        <Card className="overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border bg-surface-2 px-4 py-3">
            <Handshake className="h-4 w-4 shrink-0 text-text-muted" />
            <h2 className="text-sm font-semibold">Zgłoszenia współpracy ({zgloszenia.length})</h2>
          </div>
          <div className="px-4 py-3 text-xs text-text-muted">
            Kluby sportowe i hurtownie, które chcą nawiązać współpracę. To nie są zamówienia -
            nie powstaje z nich szkic i nie liczą się w sprzedaży.
          </div>
          <div className="divide-y divide-border">
            {zgloszenia.map((z) => (
              <div key={z.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <Badge tone="neutral">{z.kind || "Współpraca"}</Badge>
                    <span className="text-sm font-medium">{z.company_name || "(bez nazwy firmy)"}</span>
                    {z.nip && <span className="text-xs text-text-subtle">NIP {z.nip}</span>}
                  </div>
                  <span className="text-xs text-text-muted">
                    {z.date_received ? dateTimeStr(z.date_received) : "-"}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
                  {z.contact_person && <span>{z.contact_person}</span>}
                  {z.email && (
                    <a className="text-primary hover:underline" href={`mailto:${z.email}`}>
                      {z.email}
                    </a>
                  )}
                  {z.phone && (
                    <a className="text-primary hover:underline" href={`tel:${z.phone.replace(/[^+\d]/g, "")}`}>
                      {z.phone}
                    </a>
                  )}
                  {z.region && <span>Region: {z.region}</span>}
                  {z.utm_source && (
                    <span className="text-text-subtle">
                      Źródło: {[z.utm_source, z.utm_medium, z.utm_campaign].filter(Boolean).join(" / ")}
                    </span>
                  )}
                </div>
                {z.message && (
                  <p className="mt-2 whitespace-pre-wrap rounded-lg bg-surface-2 p-2 text-xs text-text">
                    {z.message}
                  </p>
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  className="mt-2"
                  onClick={() => zamknijWspolprace.mutate(z.id)}
                  disabled={zamknijWspolprace.isPending}
                >
                  Obsłużone
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

    <div className="grid grid-cols-1 gap-4 md:h-[calc(100vh-8rem)] md:grid-cols-[320px_1fr]">
      {/* Lista szkiców */}
      <Card className="flex flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">
            Do weryfikacji{" "}
            {drafts.data ? <span className="font-normal text-text-muted">({drafts.data.length})</span> : ""}
          </h2>
          <SimulateButton onDone={() => qc.invalidateQueries({ queryKey: ["drafts"] })} />
        </div>
        <div className="flex-1 overflow-auto">
          {drafts.isLoading ? (
            <div>
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex flex-col gap-2 border-b border-border px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-4 w-16 rounded-full" />
                  </div>
                  <Skeleton className="h-3 w-40" />
                  <Skeleton className="h-3 w-24" />
                </div>
              ))}
            </div>
          ) : drafts.data && drafts.data.length > 0 ? (
            drafts.data.map((d) => (
              <button
                key={d.id}
                onClick={() => setSelectedId(d.id)}
                className={`flex w-full flex-col gap-1 border-b border-border px-4 py-3 text-left transition-colors focus:outline-none ${
                  selectedId === d.id
                    ? "bg-primary-soft ring-1 ring-inset ring-primary/30"
                    : "hover:bg-surface-2"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">
                    {d.company_name ?? d.from_addr ?? "Nieznany nadawca"}
                  </span>
                  {confidenceBadge(d.extraction_method, d.extraction_confidence)}
                </div>
                <span className="truncate text-xs text-text-muted">{d.subject ?? "(bez tematu)"}</span>
                <span className="tabnum text-xs text-text-subtle">
                  {d.items_count} poz. · {dateTimeStr(d.created_at)}
                </span>
              </button>
            ))
          ) : (
            <EmptyState
              icon={CheckCheck}
              title="Wszystko zweryfikowane"
              description={`(Użyj „Symuluj mail”, aby wypróbować przepływ bez konfiguracji IMAP.)`}
            />
          )}
        </div>
      </Card>

      {/* Szczegóły / weryfikacja */}
      {selectedId ? (
        <DraftReview
          draftId={selectedId}
          onDone={() => {
            setSelectedId(null);
            qc.invalidateQueries({ queryKey: ["drafts"] });
            qc.invalidateQueries({ queryKey: ["draftsCount"] });
            qc.invalidateQueries({ queryKey: ["orders"] });
            qc.invalidateQueries({ queryKey: ["kpi"] });
          }}
        />
      ) : (
        <Card className="flex items-center justify-center">
          <EmptyState icon={Mail} title="Wybierz szkic z listy po lewej." />
        </Card>
      )}
    </div>
    </div>
  );
}

function SimulateButton({ onDone }: { onDone: () => void }) {
  const sample = `Firma: Beta Sport Sp. z o.o.
NIP: 123-123-12-37
Imię i nazwisko: Ewa Testowa
E-mail: ewa.testowa@beta-sport.example
Telefon: +48 500 000 008
utm_source: google
utm_medium: cpc
Zamawiane produkty:
Mata do jogi 6mm x 2 szt
Kask rowerowy - 3`;

  const mut = useMutation({
    mutationFn: () =>
      api.post("/drafts/simulate", {
        from_addr: "formularz@sportdemo.example",
        subject: "[Zamówienie ze strony] Beta Sport",
        body_text: sample,
        is_form: true,
      }),
    onSuccess: onDone,
  });

  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={() => mut.mutate()}
      disabled={mut.isPending}
      title="Wrzuca przykładowy mail w pipeline (dev)"
    >
      {mut.isPending ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <Sparkles className="h-3.5 w-3.5" />
      )}
      Symuluj mail
    </Button>
  );
}

function DraftReview({ draftId, onDone }: { draftId: number; onDone: () => void }) {
  const detail = useQuery({
    queryKey: ["draft", draftId],
    queryFn: () => api.get<DraftDetail>(`/drafts/${draftId}`),
  });
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.get<Product[]>("/products") });
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api.get<Channel[]>("/channels") });

  const [nip, setNip] = React.useState("");
  const [companyName, setCompanyName] = React.useState("");
  const [contactName, setContactName] = React.useState("");
  const [source, setSource] = React.useState("email_wolny");
  const [channelId, setChannelId] = React.useState("");
  const [items, setItems] = React.useState<ReviewItem[]>([]);

  React.useEffect(() => {
    if (!detail.data) return;
    const d = detail.data;
    setNip(d.nip ?? "");
    setCompanyName(d.company_name ?? "");
    setContactName(d.contact_name ?? "");
    // Mail z formularza WWW to inne zrodlo niz swobodna wiadomosc od klienta (decyzja #4).
    // Wczesniej oba ramiona warunku dawaly "email_wolny", wiec zamowienia z formularza
    // mialy zle zrodlo i mieszaly sie w raportach.
    setSource(d.email?.is_form ? "email_formularz" : "email_wolny");
    setItems(
      d.items.map((it) => ({
        raw_name: it.raw_name,
        product_id: it.matched_product_id ? String(it.matched_product_id) : "",
        quantity: it.quantity ? String(it.quantity) : "1",
        unit_price_gross: "",
        vat_rate: "23",
      })),
    );
  }, [detail.data]);

  const approve = useMutation({
    mutationFn: () =>
      api.post(`/drafts/${draftId}/approve`, {
        source,
        nip: nip || null,
        company_name: companyName || null,
        contact_name: contactName || null,
        attribution_channel_id: channelId ? Number(channelId) : null,
        items: items
          .filter((it) => it.unit_price_gross)
          .map((it) => ({
            raw_name: it.raw_name,
            product_id: it.product_id ? Number(it.product_id) : null,
            description: it.raw_name,
            quantity: Number(it.quantity.replace(",", ".")),
            unit_price_gross: Number(it.unit_price_gross.replace(",", ".")),
            vat_rate: Number(it.vat_rate.replace(",", ".")),
          })),
      }),
    onSuccess: onDone,
  });
  const reject = useMutation({
    mutationFn: () => api.post(`/drafts/${draftId}/reject`, { reason: "odrzucone ręcznie" }),
    onSuccess: onDone,
  });

  if (detail.isLoading || !detail.data) {
    return (
      <Card className="grid grid-cols-2 overflow-hidden">
        <div className="space-y-3 border-r border-border p-4">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-56" />
          <Skeleton className="h-3 w-44" />
          <Skeleton className="h-48 w-full rounded-lg" />
        </div>
        <div className="space-y-3 p-4">
          <Skeleton className="h-4 w-48" />
          <div className="grid grid-cols-2 gap-3">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      </Card>
    );
  }
  const d = detail.data;
  // Pozycje BEZ ceny byly po cichu odsiewane przez .filter() przy wysylce: zamowienie
  // powstawalo niekompletne (np. 2 z 3 produktow), a operator nie dostawal zadnego
  // ostrzezenia. Brakujaca cena musi blokowac zatwierdzenie.
  const bezCeny = items.filter((it) => !it.unit_price_gross.trim());
  const canApprove = items.length > 0 && bezCeny.length === 0;

  return (
    <Card className="grid grid-cols-2 overflow-hidden animate-fade-in">
      {/* Oryginalny mail */}
      <div className="flex flex-col overflow-hidden border-r border-border">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3 text-sm font-semibold">
          <Mail className="h-4 w-4 text-text-muted" /> Oryginalny mail
        </div>
        <div className="flex-1 space-y-3 overflow-auto p-4 text-sm">
          <div className="flex gap-2">
            <span className="w-14 shrink-0 text-text-subtle">Od:</span>
            <span className="min-w-0 break-words text-text">
              {d.email?.from_name ?? ""} &lt;{d.email?.from_addr ?? "-"}&gt;
            </span>
          </div>
          <div className="flex gap-2">
            <span className="w-14 shrink-0 text-text-subtle">Temat:</span>
            <span className="min-w-0 break-words text-text">{d.email?.subject ?? "-"}</span>
          </div>
          <div className="flex gap-2">
            <span className="w-14 shrink-0 text-text-subtle">Data:</span>
            <span className="tabnum text-text">{dateTimeStr(d.email?.date_received)}</span>
          </div>
          <pre className="mt-3 whitespace-pre-wrap rounded-lg border border-border bg-surface-2 p-3 font-mono text-xs leading-relaxed text-text-muted">
            {d.email?.body_text ?? "(brak treści)"}
          </pre>
        </div>
      </div>

      {/* Wyekstrahowane dane */}
      <div className="flex flex-col overflow-hidden">
        <div className="border-b border-border px-4 py-3 text-sm font-semibold">Wyekstrahowane zamówienie</div>
        <div className="flex-1 space-y-4 overflow-auto p-4">
          {d.ambiguities.length > 0 && (
            <div className="flex gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2.5 text-xs text-warning">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="space-y-1">
                {d.ambiguities.map((a, i) => (
                  <div key={i}>{a}</div>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>NIP</Label>
              <Input value={nip} onChange={(e) => setNip(e.target.value)} className="tabnum" />
            </div>
            <div>
              <Label>Nazwa firmy</Label>
              <Input value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
            </div>
          </div>
          <div>
            <Label>Osoba kontaktowa</Label>
            <Input value={contactName} onChange={(e) => setContactName(e.target.value)} />
          </div>

          <div className="space-y-2">
            <Label>Pozycje (uzupełnij ceny brutto)</Label>
            {items.map((it, idx) => (
              <div key={idx} className="grid grid-cols-[1fr_50px_80px_50px] gap-1.5">
                <Select
                  value={it.product_id}
                  onChange={(e) =>
                    setItems((r) => r.map((x, i) => (i === idx ? { ...x, product_id: e.target.value } : x)))
                  }
                  className="h-9 pr-8 text-xs"
                >
                  <option value="">{it.raw_name ?? "- wybierz -"}</option>
                  {(products.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
                <Input
                  className="tabnum h-9 text-center text-xs"
                  value={it.quantity}
                  onChange={(e) =>
                    setItems((r) => r.map((x, i) => (i === idx ? { ...x, quantity: e.target.value } : x)))
                  }
                />
                <Input
                  className={
                    it.unit_price_gross.trim()
                      ? "tabnum h-9 text-xs"
                      : "tabnum h-9 border-danger text-xs"
                  }
                  placeholder="brutto"
                  value={it.unit_price_gross}
                  onChange={(e) =>
                    setItems((r) =>
                      r.map((x, i) => (i === idx ? { ...x, unit_price_gross: e.target.value } : x)),
                    )
                  }
                />
                <Input
                  className="tabnum h-9 text-center text-xs"
                  value={it.vat_rate}
                  onChange={(e) =>
                    setItems((r) => r.map((x, i) => (i === idx ? { ...x, vat_rate: e.target.value } : x)))
                  }
                />
              </div>
            ))}
            {items.length === 0 && (
              <p className="text-xs text-text-muted">Brak pozycji - dodaj zamówienie ręcznie z widoku Zamówienia.</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Źródło</Label>
              <Select value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="email_formularz">E-mail (formularz)</option>
                <option value="email_wolny">E-mail (wolny tekst)</option>
              </Select>
            </div>
            <div>
              <Label>Kanał</Label>
              <Select value={channelId} onChange={(e) => setChannelId(e.target.value)}>
                <option value="">Nieznany</option>
                {(channels.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name_pl}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        </div>

        <div className="space-y-2 border-t border-border p-3">
          {bezCeny.length > 0 && (
            <p className="text-xs text-danger">
              Uzupełnij cenę brutto dla {bezCeny.length === 1 ? "pozycji" : "wszystkich pozycji"}:{" "}
              {bezCeny.map((it) => it.raw_name).join(", ")}. Bez ceny pozycja nie trafi do zamówienia.
            </p>
          )}
          <div className="flex gap-2">
          <Button onClick={() => approve.mutate()} disabled={!canApprove || approve.isPending}>
            {approve.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Zatwierdź zamówienie
          </Button>
          <Button variant="danger" onClick={() => reject.mutate()} disabled={reject.isPending}>
            {reject.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
            Odrzuć
          </Button>
          </div>
        </div>
        {approve.isError && (
          <div className="mx-3 mb-3 flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {approve.error instanceof Error ? approve.error.message : "Błąd"}
          </div>
        )}
      </div>
    </Card>
  );
}
