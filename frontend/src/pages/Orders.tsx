import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  ChevronLeft,
  ChevronRight,
  Download,
  Plus,
  Search,
  ShoppingCart,
} from "lucide-react";
import * as React from "react";

import {
  api,
  ApiError,
  type Channel,
  type CompanyListItem,
  type Order,
  type OrderDetail,
} from "@/api/client";
import { useToast } from "@/components/toast";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  Input,
  PageHead,
  Select,
  Skeleton,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
} from "@/components/ui";
import { OrderDrawer } from "@/pages/OrderDrawer";
import { pl } from "@/i18n/pl";
import { dateStr, money } from "@/lib/format";

const SOURCE_LABEL: Record<string, string> = {
  email_formularz: "E-mail (formularz)",
  email_wolny: "E-mail",
  telefon: "Telefon",
  stacjonarnie: "Stacjonarnie",
};

const STATUS_LABEL: Record<string, string> = {
  nowe: "Nowe",
  potwierdzone: "Potwierdzone",
  zrealizowane: "Zrealizowane",
  anulowane: "Anulowane",
};

const STATUS_TONE: Record<string, "neutral" | "success" | "danger" | "primary"> = {
  nowe: "neutral",
  potwierdzone: "primary",
  zrealizowane: "success",
  anulowane: "danger",
};

// Statusy dostępne w szybkiej zmianie w wierszu (anulowanie idzie przez dialog).
const EDITABLE_STATUSES = ["nowe", "potwierdzone", "zrealizowane"] as const;

const PAGE_SIZE = 20;

export function Orders() {
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState<string>("all");
  const [page, setPage] = React.useState(0);
  const [cancelTarget, setCancelTarget] = React.useState<Order | null>(null);
  const qc = useQueryClient();
  const toast = useToast();

  // Bez jawnego limitu backend zwraca tylko 50 najnowszych, a naglowek twierdzilby,
  // ze to calosc. 200 = gorna granica walidatora endpointu.
  const orders = useQuery({
    queryKey: ["orders"],
    queryFn: () => api.get<Order[]>("/orders?limit=200"),
  });
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api.get<Channel[]>("/channels") });

  const statusMut = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      api.patch<OrderDetail>(`/orders/${id}`, { status }),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["kpi"] });
      qc.invalidateQueries({ queryKey: ["revenue-series"] });
      qc.invalidateQueries({ queryKey: ["recent-orders"] });
      toast.success(
        updated.status === "anulowane"
          ? "Zamówienie anulowane"
          : "Status zamówienia zaktualizowany",
      );
    },
    onError: (e) => {
      toast.error(e instanceof ApiError ? e.message : "Nie udało się zmienić statusu");
    },
  });

  const onCreated = () => {
    setDrawerOpen(false);
    qc.invalidateQueries({ queryKey: ["orders"] });
    qc.invalidateQueries({ queryKey: ["kpi"] });
    qc.invalidateQueries({ queryKey: ["revenue-series"] });
    qc.invalidateQueries({ queryKey: ["recent-orders"] });
    qc.invalidateQueries({ queryKey: ["companies"] });
    toast.success("Zamówienie utworzone");
  };

  const all = orders.data ?? [];

  // Filtrowanie po stronie klienta: szukajka (nr / firma) + status.
  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter((o) => {
      if (statusFilter !== "all" && o.status !== statusFilter) return false;
      if (!q) return true;
      const no = o.order_no.toLowerCase();
      const company = (o.company_name ?? "").toLowerCase();
      return no.includes(q) || company.includes(q);
    });
  }, [all, search, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));

  // Reset strony po zmianie filtrów / rozmiaru wyników.
  React.useEffect(() => {
    setPage(0);
  }, [search, statusFilter]);

  const safePage = Math.min(page, totalPages - 1);
  const paged = React.useMemo(
    () => filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE),
    [filtered, safePage],
  );

  const confirmCancel = () => {
    if (!cancelTarget) return;
    statusMut.mutate(
      { id: cancelTarget.id, status: "anulowane" },
      { onSuccess: () => setCancelTarget(null) },
    );
  };

  return (
    <div className="space-y-6">
      <PageHead
        title={pl.orders.title}
        subtitle={orders.data ? `${orders.data.length} zamówień` : undefined}
        actions={
          <>
            <a
              href="/api/exports/orders.csv"
              className="inline-flex h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-border bg-surface px-4 text-sm font-medium text-text transition-all hover:border-border-strong hover:bg-surface-2 active:scale-[0.98]"
            >
              <Download className="h-4 w-4" /> Eksport CSV
            </a>
            <Button onClick={() => setDrawerOpen(true)}>
              <Plus className="h-4 w-4" />
              {pl.orders.add}
            </Button>
          </>
        }
      />

      <Card className="overflow-hidden">
        {/* Pasek narzędzi: szukajka + filtr statusu */}
        {orders.data && orders.data.length > 0 && (
          <div className="flex flex-col gap-3 border-b border-border px-5 py-3.5 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-subtle" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Szukaj (nr lub firma)"
                className="pl-9"
                aria-label="Szukaj zamówień"
              />
            </div>
            <div className="sm:w-56">
              <Select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="Filtr statusu"
              >
                <option value="all">Wszystkie statusy</option>
                {EDITABLE_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {STATUS_LABEL[s]}
                  </option>
                ))}
                <option value="anulowane">{STATUS_LABEL.anulowane}</option>
              </Select>
            </div>
          </div>
        )}

        {orders.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : orders.data && orders.data.length > 0 ? (
          filtered.length > 0 ? (
            <>
              <Table>
                <THead>
                  <Th>{pl.orders.number}</Th>
                  <Th>{pl.orders.date}</Th>
                  <Th>{pl.orders.client}</Th>
                  <Th>{pl.orders.source}</Th>
                  <Th align="right">{pl.orders.value}</Th>
                  <Th>{pl.orders.status}</Th>
                  <Th align="right">Akcje</Th>
                </THead>
                <TBody>
                  {paged.map((o) => {
                    const canceled = o.status === "anulowane";
                    return (
                      <Tr key={o.id}>
                        <Td className="font-medium">{o.order_no}</Td>
                        <Td>{dateStr(o.ordered_at)}</Td>
                        <Td>{o.company_name ?? "-"}</Td>
                        <Td className="text-text-muted">{SOURCE_LABEL[o.source] ?? o.source}</Td>
                        <Td align="right" className="tabular-nums">
                          {money(o.total_net)}
                        </Td>
                        <Td>
                          <Badge tone={STATUS_TONE[o.status] ?? "neutral"} dot>
                            {STATUS_LABEL[o.status] ?? o.status}
                          </Badge>
                        </Td>
                        <Td align="right">
                          {canceled ? (
                            <span className="text-text-subtle">-</span>
                          ) : (
                            <div className="flex items-center justify-end gap-2">
                              <div className="w-44">
                                <Select
                                  value={o.status}
                                  disabled={statusMut.isPending}
                                  onChange={(e) => {
                                    const next = e.target.value;
                                    if (next !== o.status) {
                                      statusMut.mutate({ id: o.id, status: next });
                                    }
                                  }}
                                  aria-label={`Zmień status zamówienia ${o.order_no}`}
                                >
                                  {EDITABLE_STATUSES.map((s) => (
                                    <option key={s} value={s}>
                                      {STATUS_LABEL[s]}
                                    </option>
                                  ))}
                                </Select>
                              </div>
                              <Button
                                variant="danger"
                                disabled={statusMut.isPending}
                                onClick={() => setCancelTarget(o)}
                                aria-label={`Anuluj zamówienie ${o.order_no}`}
                              >
                                <Ban className="h-4 w-4" />
                                Anuluj
                              </Button>
                            </div>
                          )}
                        </Td>
                      </Tr>
                    );
                  })}
                </TBody>
              </Table>

              {/* Paginacja kliencka */}
              {filtered.length > PAGE_SIZE && (
                <div className="flex items-center justify-between border-t border-border px-5 py-3 text-sm text-text-muted">
                  <span className="tabular-nums">
                    {safePage * PAGE_SIZE + 1}-{Math.min((safePage + 1) * PAGE_SIZE, filtered.length)} z{" "}
                    {filtered.length}
                  </span>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={safePage <= 0}
                      onClick={() => setPage((p) => Math.max(0, p - 1))}
                    >
                      <ChevronLeft className="h-4 w-4" /> Poprzednia
                    </Button>
                    <span className="tabular-nums text-text-subtle">
                      {safePage + 1} / {totalPages}
                    </span>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={safePage >= totalPages - 1}
                      onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                    >
                      Następna <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <EmptyState icon={Search} title="Brak wyników" description="Zmień zapytanie lub filtr statusu." />
          )
        ) : (
          <EmptyState icon={ShoppingCart} title={pl.orders.empty} />
        )}
      </Card>

      <ConfirmDialog
        open={cancelTarget !== null}
        title="Anulować zamówienie?"
        message={
          <>
            Zamówienie <span className="font-medium text-text">{cancelTarget?.order_no}</span>
            {cancelTarget?.company_name ? (
              <>
                {" "}dla <span className="font-medium text-text">{cancelTarget.company_name}</span>
              </>
            ) : null}{" "}
            zostanie oznaczone jako anulowane. Tej operacji nie można cofnąć z tego widoku.
          </>
        }
        confirmLabel="Anuluj zamówienie"
        cancelLabel="Wróć"
        danger
        busy={statusMut.isPending}
        onConfirm={confirmCancel}
        onCancel={() => setCancelTarget(null)}
      />

      {drawerOpen && (
        <OrderDrawer
          channels={channels.data ?? []}
          onClose={() => setDrawerOpen(false)}
          onCreated={onCreated}
        />
      )}
    </div>
  );
}

// Eksponujemy helper do drawera (lookup NIP) tu, żeby OrderDrawer był samodzielny.
export async function lookupNip(nip: string): Promise<CompanyListItem | null> {
  try {
    return await api.get<CompanyListItem | null>(`/companies/nip/${encodeURIComponent(nip)}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) return null;
    throw e;
  }
}
