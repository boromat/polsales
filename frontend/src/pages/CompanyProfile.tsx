import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Building2, Clock, Receipt, Repeat, ShoppingCart, TrendingUp } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { api, type CompanyProfile as CompanyProfileT } from "@/api/client";
import {
  Badge,
  Card,
  EmptyState,
  PageHead,
  Skeleton,
  StatCard,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
} from "@/components/ui";
import { pl } from "@/i18n/pl";
import { dateStr, int, money, moneyNet } from "@/lib/format";

const STATUS_TONE: Record<string, "neutral" | "success" | "warning" | "danger" | "primary"> = {
  nowe: "neutral",
  potwierdzone: "primary",
  zrealizowane: "success",
  anulowane: "danger",
};

const STATUS_LABEL: Record<string, string> = {
  nowe: "Nowe",
  potwierdzone: "Potwierdzone",
  zrealizowane: "Zrealizowane",
  anulowane: "Anulowane",
};

const BackLink = (
  <Link
    to="/firmy"
    className="inline-flex items-center gap-1.5 text-sm font-medium text-primary transition-colors hover:text-primary-hover"
  >
    <ArrowLeft className="h-4 w-4" /> Firmy B2B
  </Link>
);

export function CompanyProfile() {
  const { id } = useParams();
  const q = useQuery({
    queryKey: ["company", id],
    queryFn: () => api.get<CompanyProfileT>(`/companies/${id}`),
    enabled: !!id,
  });

  if (q.isLoading) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-6 w-64" />
          <Skeleton className="h-4 w-32" />
        </div>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="p-4">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-3 h-7 w-20" />
            </Card>
          ))}
        </div>
        <Card className="overflow-hidden">
          <div className="border-b border-border px-5 py-3.5">
            <Skeleton className="h-4 w-40" />
          </div>
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        </Card>
      </div>
    );
  }

  if (!q.data) return <EmptyState icon={Building2} title="Nie znaleziono firmy." />;

  const c = q.data;

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHead
        title={c.company_name}
        subtitle={
          <span className="inline-flex items-center gap-2">
            <span className="tabnum">NIP {c.nip}</span>
            {c.at_risk === true && (
              <span
                title={
                  c.days_since_last_order != null
                    ? `Brak zamówienia od ${c.days_since_last_order} dni`
                    : "Brak aktywności zakupowej"
                }
              >
                <Badge tone="danger" dot>
                  Zagrożona odejściem
                </Badge>
              </span>
            )}
          </span>
        }
        actions={BackLink}
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard label="LTV (netto)" value={moneyNet(c.ltv_net)} icon={TrendingUp} />
        <StatCard label="Liczba zamówień" value={int(c.orders_count)} icon={ShoppingCart} />
        <StatCard label="Śr. wartość" value={moneyNet(c.avg_order_value_net)} icon={Receipt} />
        <StatCard
          label="Częstotliwość"
          value={c.frequency_days ? pl.companies.everyDays(c.frequency_days) : "-"}
          icon={Repeat}
        />
        <StatCard
          label="Czas kontakt→sprzedaż"
          value={c.avg_lead_time_days == null ? "-" : `${c.avg_lead_time_days} dni`}
          icon={Clock}
        />
      </div>

      <p className="text-sm text-text-muted">
        Klient od: <span className="tabnum">{dateStr(c.first_order)}</span> · Ostatnie zamówienie:{" "}
        <span className="tabnum">{dateStr(c.last_order)}</span>
      </p>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <h2 className="text-sm font-semibold">Historia zamówień</h2>
        </div>
        {c.orders.length > 0 ? (
          <Table>
            <THead>
              <Th>{pl.orders.number}</Th>
              <Th>{pl.orders.date}</Th>
              <Th align="right">{pl.orders.value}</Th>
              <Th>{pl.orders.status}</Th>
            </THead>
            <TBody>
              {c.orders.map((o) => (
                <Tr key={o.id}>
                  <Td className="font-medium">{o.order_no}</Td>
                  <Td>{dateStr(o.ordered_at)}</Td>
                  <Td align="right">{money(o.total_net)}</Td>
                  <Td>
                    <Badge tone={STATUS_TONE[o.status] ?? "neutral"} dot>
                      {STATUS_LABEL[o.status]}
                    </Badge>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        ) : (
          <EmptyState icon={ShoppingCart} title="Brak zamówień." />
        )}
      </Card>
    </div>
  );
}
