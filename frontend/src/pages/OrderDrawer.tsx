// Drawer dodawania zamówienia ręcznego (telefon/stacjonarnie). Autouzupełnianie firmy po NIP,
// walidacja checksumy NIP, dynamiczne pozycje, sumy netto/VAT/brutto na żywo.
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Building2, CheckCircle2, Loader2, ShoppingCart, Trash2, X } from "lucide-react";
import * as React from "react";

import { api, type Channel, type CompanyListItem, type OrderDetail } from "@/api/client";
import { Button, Input, Label, Select, Textarea } from "@/components/ui";
import { lookupNip } from "@/pages/Orders";
import { pl } from "@/i18n/pl";
import { money } from "@/lib/format";

interface ItemRow {
  description: string;
  quantity: string;
  unit_price_gross: string;
  vat_rate: string;
}

const EMPTY_ITEM: ItemRow = { description: "", quantity: "1", unit_price_gross: "", vat_rate: "23" };

// Walidacja NIP po stronie klienta (spójna z backendem) - do natychmiastowego feedbacku.
function validNip(nip: string): boolean {
  const d = nip.replace(/[^0-9]/g, "");
  if (!/^[0-9]{10}$/.test(d)) return false;
  const w = [6, 5, 7, 2, 3, 4, 5, 6, 7];
  const sum = w.reduce((acc, wi, i) => acc + wi * Number(d[i]), 0);
  const ctrl = sum % 11;
  return ctrl !== 10 && ctrl === Number(d[9]);
}

function lineNet(it: ItemRow): number {
  const q = Number(it.quantity.replace(",", ".")) || 0;
  const up = Number(it.unit_price_gross.replace(",", ".")) || 0;
  const vat = Number(it.vat_rate.replace(",", ".")) || 0;
  return (q * up) / (1 + vat / 100);
}
function lineGross(it: ItemRow): number {
  const q = Number(it.quantity.replace(",", ".")) || 0;
  const up = Number(it.unit_price_gross.replace(",", ".")) || 0;
  return q * up;
}

export function OrderDrawer({
  channels,
  onClose,
  onCreated,
}: {
  channels: Channel[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [segment, setSegment] = React.useState<"b2b" | "b2c">("b2b");
  const [nip, setNip] = React.useState("");
  const [companyName, setCompanyName] = React.useState("");
  const [contactName, setContactName] = React.useState("");
  const [contactPhone, setContactPhone] = React.useState("");
  const [contactEmail, setContactEmail] = React.useState("");
  const [source, setSource] = React.useState("telefon");
  const [channelId, setChannelId] = React.useState<string>("");
  const [notes, setNotes] = React.useState("");
  const [items, setItems] = React.useState<ItemRow[]>([{ ...EMPTY_ITEM }]);
  const [matched, setMatched] = React.useState<CompanyListItem | null>(null);
  const [nipError, setNipError] = React.useState<string | null>(null);

  const nipDigits = nip.replace(/[^0-9]/g, "");
  const nipOk = nipDigits.length === 0 || validNip(nipDigits);

  // Dostępność: zamykanie modala klawiszem Esc.
  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // Podpowiedź firmy po wpisaniu poprawnego NIP.
  React.useEffect(() => {
    setMatched(null);
    setNipError(null);
    if (nipDigits.length !== 10) return;
    if (!validNip(nipDigits)) {
      setNipError("Nieprawidłowy NIP - sprawdź cyfry");
      return;
    }
    let cancelled = false;
    lookupNip(nipDigits).then((c) => {
      if (cancelled) return;
      setMatched(c);
      if (c?.company_name) setCompanyName(c.company_name);
    });
    return () => {
      cancelled = true;
    };
  }, [nipDigits]);

  const totals = items.reduce(
    (acc, it) => {
      acc.net += lineNet(it);
      acc.gross += lineGross(it);
      return acc;
    },
    { net: 0, gross: 0 },
  );

  const mutation = useMutation({
    mutationFn: (payload: unknown) => api.post<OrderDetail>("/orders", payload),
    onSuccess: onCreated,
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!nipOk) return;
    mutation.mutate({
      source,
      status: "potwierdzone",
      nip: segment === "b2b" ? nipDigits || null : null,
      company_name: segment === "b2b" ? companyName || null : null,
      contact_name: contactName || null,
      contact_email: contactEmail || null,
      contact_phone: contactPhone || null,
      attribution_channel_id: channelId ? Number(channelId) : null,
      notes: notes || null,
      items: items
        .filter((it) => it.unit_price_gross)
        .map((it) => ({
          description: it.description || null,
          quantity: Number(it.quantity.replace(",", ".")),
          unit_price_gross: Number(it.unit_price_gross.replace(",", ".")),
          vat_rate: Number(it.vat_rate.replace(",", ".")),
        })),
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-label="Nowe zamówienie"
      onClick={onClose}
    >
      <div
        className="flex h-full w-[560px] max-w-full flex-col bg-surface shadow-pop animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Nagłówek */}
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-soft text-primary">
              <ShoppingCart className="h-4 w-4" />
            </span>
            <h2 className="text-base font-semibold text-text">Nowe zamówienie</h2>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Zamknij">
            <X className="h-5 w-5" />
          </Button>
        </div>

        {/* Treść */}
        <form onSubmit={submit} className="flex-1 space-y-6 overflow-auto p-5">
          {/* Klient */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-text">Klient</h3>
            <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5 text-sm">
              {(["b2b", "b2c"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSegment(s)}
                  className={
                    segment === s
                      ? "rounded-md bg-primary px-4 py-1.5 font-medium text-white shadow-sm transition-all"
                      : "rounded-md px-4 py-1.5 font-medium text-text-muted transition-colors hover:text-text"
                  }
                >
                  {s.toUpperCase()}
                </button>
              ))}
            </div>

            {segment === "b2b" && (
              <div>
                <Label>NIP</Label>
                <Input
                  value={nip}
                  onChange={(e) => setNip(e.target.value)}
                  placeholder="np. 5213..."
                  className={nipError ? "border-danger" : ""}
                />
                {nipError && <p className="mt-1.5 text-xs font-medium text-danger">{nipError}</p>}
                {matched && (
                  <div className="mt-2 flex items-start gap-2 rounded-lg bg-success-soft px-3 py-2 text-xs text-success">
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>
                      Rozpoznano: {matched.company_name} · {matched.orders_count ?? 0} wcześniejszych zamówień
                    </span>
                  </div>
                )}
                {!matched && nipDigits.length === 10 && !nipError && (
                  <div className="mt-2 flex items-start gap-2 rounded-lg bg-primary-soft px-3 py-2 text-xs text-primary">
                    <Building2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>Nowa firma - profil zostanie utworzony automatycznie</span>
                  </div>
                )}
                <div className="mt-3">
                  <Label>Nazwa firmy</Label>
                  <Input value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
                </div>
                <div className="mt-3">
                  <Label>Osoba zamawiająca</Label>
                  <Input value={contactName} onChange={(e) => setContactName(e.target.value)} />
                </div>
              </div>
            )}

            {segment === "b2c" && (
              <div className="space-y-3">
                <div>
                  <Label>Imię i nazwisko</Label>
                  <Input value={contactName} onChange={(e) => setContactName(e.target.value)} />
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Telefon</Label>
                <Input value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} />
              </div>
              <div>
                <Label>E-mail</Label>
                <Input value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
              </div>
            </div>
          </section>

          {/* Pozycje */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-text">Pozycje</h3>
            {items.map((it, idx) => (
              <div key={idx} className="grid grid-cols-[1fr_60px_104px_64px_40px] items-end gap-2">
                <div>
                  {idx === 0 && <Label>Produkt / opis</Label>}
                  <Input
                    value={it.description}
                    onChange={(e) =>
                      setItems((rows) => rows.map((r, i) => (i === idx ? { ...r, description: e.target.value } : r)))
                    }
                  />
                </div>
                <div>
                  {idx === 0 && <Label>Ilość</Label>}
                  <Input
                    className="tabnum"
                    value={it.quantity}
                    onChange={(e) =>
                      setItems((rows) => rows.map((r, i) => (i === idx ? { ...r, quantity: e.target.value } : r)))
                    }
                  />
                </div>
                <div>
                  {idx === 0 && <Label>Cena brutto</Label>}
                  <Input
                    className="tabnum"
                    value={it.unit_price_gross}
                    onChange={(e) =>
                      setItems((rows) =>
                        rows.map((r, i) => (i === idx ? { ...r, unit_price_gross: e.target.value } : r)),
                      )
                    }
                  />
                </div>
                <div>
                  {idx === 0 && <Label>VAT %</Label>}
                  <Input
                    className="tabnum"
                    value={it.vat_rate}
                    onChange={(e) =>
                      setItems((rows) => rows.map((r, i) => (i === idx ? { ...r, vat_rate: e.target.value } : r)))
                    }
                  />
                </div>
                <button
                  type="button"
                  onClick={() => setItems((rows) => rows.filter((_, i) => i !== idx))}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-text-subtle transition-colors hover:bg-danger-soft hover:text-danger disabled:pointer-events-none disabled:opacity-40"
                  disabled={items.length === 1}
                  aria-label="Usuń pozycję"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setItems((rows) => [...rows, { ...EMPTY_ITEM }])}
            >
              + Dodaj pozycję
            </Button>

            <div className="rounded-lg border border-border bg-surface-2/60 p-3.5 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-text-muted">Netto</span>
                <span className="tabnum font-medium text-text">{money(totals.net)}</span>
              </div>
              <div className="mt-2 flex items-center justify-between border-t border-border pt-2">
                <span className="font-medium text-text">Brutto</span>
                <span className="tabnum text-base font-semibold text-text">{money(totals.gross)}</span>
              </div>
            </div>
          </section>

          {/* Szczegóły */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-text">Szczegóły</h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Źródło</Label>
                <Select value={source} onChange={(e) => setSource(e.target.value)}>
                  <option value="telefon">Telefon</option>
                  <option value="stacjonarnie">Stacjonarnie</option>
                </Select>
              </div>
              <div>
                <Label>Kanał marketingowy (skąd klient?)</Label>
                <Select value={channelId} onChange={(e) => setChannelId(e.target.value)}>
                  <option value="">Nieznany</option>
                  {channels.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name_pl}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
            <div>
              <Label>Notatka</Label>
              <Textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Dodatkowe informacje o zamówieniu…"
              />
            </div>
          </section>

          {mutation.isError && (
            <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-soft px-4 py-2.5 text-sm text-danger">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{mutation.error instanceof Error ? mutation.error.message : "Błąd zapisu"}</span>
            </div>
          )}
        </form>

        {/* Stopka */}
        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border px-5 py-4">
          <Button variant="secondary" onClick={onClose}>
            {pl.common.cancel}
          </Button>
          <Button onClick={submit} disabled={mutation.isPending || !nipOk}>
            {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {mutation.isPending ? pl.common.loading : pl.common.save}
          </Button>
        </div>
      </div>
    </div>
  );
}
