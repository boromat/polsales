import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarDays,
  Clock,
  Gauge,
  Info,
  Megaphone,
  Percent,
  Receipt,
  ShoppingCart,
  Target,
  TrendingUp,
  Wallet,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link } from "react-router-dom";

import {
  api,
  type BusinessAlert,
  type IntegrationStatus,
  type Kpi,
  type Order,
  type RevenuePoint,
  type WeeklySummary,
} from "@/api/client";
import {
  Badge,
  Button,
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
import { DateRangePicker, useDateRange } from "@/contexts/dateRange";
import { useTheme } from "@/theme";
import { pl } from "@/i18n/pl";
import { cn } from "@/lib/utils";
import { dateStr, days, int, money, moneyNet, polonizeDecimals, ratio } from "@/lib/format";

const SOURCE_LABELS: Record<string, string> = {
  imap: "Skrzynka e-mail",
  meta_ads: "Meta Ads",
  meta_organic: "Meta organicznie",
  google_ads: "Google Ads",
  ga4: "Google Analytics 4",
};

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

// Poprzedni okres o tej samej długości, kończący się dzień przed `from`.
function previousRange(from: string, to: string): { from: string; to: string } {
  const dayMs = 86_400_000;
  const fromMs = Date.parse(from);
  const toMs = Date.parse(to);
  const lengthDays = Math.round((toMs - fromMs) / dayMs) + 1;
  const prevToMs = fromMs - dayMs;
  const prevFromMs = prevToMs - (lengthDays - 1) * dayMs;
  const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  return { from: iso(prevFromMs), to: iso(prevToMs) };
}

// delta% względem poprzedniego okresu; null gdy brak bazy porównania.
function deltaPct(now: number | null | undefined, prev: number | null | undefined): number | null {
  if (now == null || prev == null || prev === 0) return null;
  return ((now - prev) / prev) * 100;
}

const ALERT_TONE: Record<BusinessAlert["level"], string> = {
  danger: "border-danger/30 bg-danger-soft text-danger",
  warning: "border-warning/30 bg-warning-soft text-warning",
  info: "border-border bg-surface text-text",
};

export function Dashboard() {
  const { isDark } = useTheme();
  const dr = useDateRange();
  const prev = previousRange(dr.from, dr.to);
  // Kolory wykresu zależne od motywu (indygo jaśniejsze na ciemnym, siatka z tokenu ramki).
  const chartPrimary = isDark ? "#818CF8" : "#4F46E5";
  const chartGrid = isDark ? "#27272A" : "#E4E4E7";
  const chartAxis = isDark ? "#A1A1AA" : "#64646E";
  const kpi = useQuery({
    queryKey: ["kpi", dr.from, dr.to],
    queryFn: () => api.get<Kpi>("/metrics/kpi" + dr.query),
  });
  const kpiPrev = useQuery({
    queryKey: ["kpi", "prev", prev.from, prev.to],
    queryFn: () => api.get<Kpi>(`/metrics/kpi?date_from=${prev.from}&date_to=${prev.to}`),
  });
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: () => api.get<BusinessAlert[]>("/alerts"),
  });
  const series = useQuery({
    queryKey: ["revenue-series", dr.from, dr.to],
    queryFn: () => api.get<RevenuePoint[]>("/metrics/revenue-series" + dr.query),
  });
  const orders = useQuery({
    queryKey: ["recent-orders"],
    queryFn: () => api.get<Order[]>("/orders?limit=8"),
  });
  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api.get<{ integrations: IntegrationStatus[] }>("/health/integrations"),
  });
  const weekly = useQuery({
    queryKey: ["weekly"],
    queryFn: () => api.get<WeeklySummary[]>("/weekly"),
  });

  const queryClient = useQueryClient();
  const generateWeekly = useMutation({
    mutationFn: () => api.post("/weekly/generate"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["weekly"] });
    },
  });
  const latestWeekly = weekly.data?.[0];

  const integrationAlerts = (integrations.data?.integrations ?? []).filter((i) => i.state === "blad");
  const businessAlerts = alerts.data ?? [];
  const hasAlerts = integrationAlerts.length > 0 || businessAlerts.length > 0;

  const now = kpi.data;
  const before = kpiPrev.data;
  const revenueDelta = deltaPct(now?.revenue_net, before?.revenue_net);
  const ordersDelta = deltaPct(now?.orders_count, before?.orders_count);
  const marginDelta = deltaPct(now?.gross_margin_net, before?.gross_margin_net);
  const cacDelta = deltaPct(now?.cac, before?.cac);

  return (
    <div className="space-y-6">
      {/* Nagłówek z zakresem dat */}
      <PageHead title="Pulpit" actions={<DateRangePicker />} />

      {/* Pasek alertów */}
      {hasAlerts && (
        <div className="space-y-2">
          {businessAlerts.map((a, i) => (
            <div
              key={`biz-${i}`}
              className={cn(
                "flex items-start gap-2 rounded-lg border px-4 py-2.5 text-sm",
                ALERT_TONE[a.level],
              )}
            >
              {a.level === "info" ? (
                <Info className="mt-0.5 h-4 w-4 shrink-0" />
              ) : (
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              )}
              <span>
                <span className="font-semibold">{a.title}</span>
                {a.detail ? <> - {a.detail}</> : null}
              </span>
            </div>
          ))}
          {integrationAlerts.map((a) => (
            <div
              key={a.source}
              className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-4 py-2.5 text-sm text-danger"
            >
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>
                Synchronizacja „{SOURCE_LABELS[a.source] ?? a.source}” nie działa
                {a.message ? `: ${a.message}` : "."}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Karty KPI - 9 kart w siatce 3×3 (bez osamotnionej karty w ostatnim rzędzie) */}
      {kpi.isLoading ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          {Array.from({ length: 9 }).map((_, i) => (
            <Card key={i} className="p-4">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-3 h-7 w-20" />
            </Card>
          ))}
        </div>
      ) : kpi.data ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <StatCard
            label={pl.kpi.revenue}
            value={moneyNet(kpi.data.revenue_net)}
            hint={pl.kpi.revenueTip}
            icon={Wallet}
            delta={revenueDelta}
          />
          <StatCard
            label={pl.kpi.orders}
            value={int(kpi.data.orders_count)}
            hint={pl.kpi.ordersTip}
            icon={ShoppingCart}
            delta={ordersDelta}
          />
          <StatCard label={pl.kpi.aov} value={moneyNet(kpi.data.avg_order_value_net)} hint={pl.kpi.aovTip} icon={Receipt} />
          <StatCard
            label={pl.kpi.cac}
            value={money(kpi.data.cac)}
            hint={pl.kpi.cacTip}
            icon={Target}
            delta={cacDelta}
            deltaGoodWhenUp={false}
          />
          <StatCard label={pl.kpi.ltv} value={moneyNet(kpi.data.avg_ltv_net)} hint={pl.kpi.ltvTip} icon={TrendingUp} />
          <StatCard
            label={pl.kpi.roas}
            value={ratio(kpi.data.roas)}
            hint={pl.kpi.roasTip}
            icon={Gauge}
          />
          <StatCard
            label="Czas kontakt→sprzedaż"
            value={days(kpi.data.avg_lead_time_days)}
            hint="Średni czas od pierwszego kontaktu klienta do zamówienia (dostępne dla zamówień z maila)."
            icon={Clock}
          />
          <StatCard
            label="Wydatki reklamowe"
            value={money(kpi.data.ad_spend)}
            hint="Suma wydatków na reklamy płatne (Meta Ads + Google Ads) w wybranym okresie."
            icon={Megaphone}
          />
          <StatCard
            label="Marża brutto"
            value={
              kpi.data.gross_margin_net == null ? (
                <span className="text-base font-medium text-text-muted">Brak danych</span>
              ) : (
                moneyNet(kpi.data.gross_margin_net)
              )
            }
            hint="Przychód netto pomniejszony o koszt własny sprzedaży (COGS) w wybranym okresie."
            icon={Percent}
            delta={kpi.data.gross_margin_net == null ? undefined : marginDelta}
            footer={
              kpi.data.gross_margin_net == null
                ? "Brak sprzedaży produktów z ustawionym kosztem w tym okresie"
                : kpi.data.margin_pct != null
                  ? `${kpi.data.margin_pct}% marży`
                  : undefined
            }
          />
        </div>
      ) : null}

      {/* Wykres przychodu */}
      <Card className="p-5">
        <h2 className="mb-4 text-sm font-semibold">
          Przychód netto w czasie ({dateStr(dr.from)}-{dateStr(dr.to)})
        </h2>
        <div className="h-72">
          {series.isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : series.data && series.data.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={series.data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={chartPrimary} stopOpacity={0.28} />
                    <stop offset="100%" stopColor={chartPrimary} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={chartGrid} vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: chartAxis }}
                  tickFormatter={(d) => dateStr(d)}
                  axisLine={{ stroke: chartGrid }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: chartAxis }}
                  width={70}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  formatter={(v: number) => [moneyNet(v), "Przychód"]}
                  labelFormatter={(d) => dateStr(String(d))}
                  contentStyle={{
                    borderRadius: 12,
                    border: `1px solid ${chartGrid}`,
                    background: isDark ? "#18181B" : "#FFFFFF",
                    boxShadow: "0 8px 30px -6px rgb(24 24 27 / 0.18)",
                    fontSize: 12,
                  }}
                  labelStyle={{ color: chartAxis }}
                />
                <Area
                  type="monotone"
                  dataKey="revenue_net"
                  stroke={chartPrimary}
                  fill="url(#rev)"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-text-muted">
              Brak danych za ten okres.
            </div>
          )}
        </div>
      </Card>

      {/* Zestawienie tygodniowe */}
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <h2 className="text-sm font-semibold">Zestawienie tygodniowe</h2>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => generateWeekly.mutate()}
            disabled={generateWeekly.isPending}
          >
            {generateWeekly.isPending ? "Generowanie…" : "Generuj teraz"}
          </Button>
        </div>
        {weekly.isLoading ? (
          <div className="space-y-2 p-5">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-40" />
            <Skeleton className="mt-3 h-24 w-full" />
          </div>
        ) : latestWeekly ? (
          <div className="space-y-2 p-5">
            <p className="font-medium">{polonizeDecimals(latestWeekly.headline)}</p>
            <p className="tabnum text-sm text-text-muted">
              {dateStr(latestWeekly.week_start)}-{dateStr(latestWeekly.week_end)}
            </p>
            <div className="whitespace-pre-line text-sm">{polonizeDecimals(latestWeekly.body)}</div>
          </div>
        ) : (
          <EmptyState
            icon={CalendarDays}
            title="Brak zestawień"
            description="Kliknij «Generuj teraz»"
            action={
              <Button
                variant="secondary"
                size="sm"
                onClick={() => generateWeekly.mutate()}
                disabled={generateWeekly.isPending}
              >
                {generateWeekly.isPending ? "Generowanie…" : "Generuj teraz"}
              </Button>
            }
          />
        )}
      </Card>

      {/* Ostatnie zamówienia */}
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <h2 className="text-sm font-semibold">Ostatnie zamówienia</h2>
          <Link
            to="/zamowienia"
            className="text-sm font-medium text-primary transition-colors hover:text-primary-hover"
          >
            Wszystkie zamówienia →
          </Link>
        </div>
        {orders.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : orders.data && orders.data.length > 0 ? (
          <Table>
            <THead>
              <Th>{pl.orders.number}</Th>
              <Th>{pl.orders.date}</Th>
              <Th>{pl.orders.client}</Th>
              <Th align="right">{pl.orders.value}</Th>
              <Th>{pl.orders.status}</Th>
            </THead>
            <TBody>
              {orders.data.map((o) => (
                <Tr key={o.id}>
                  <Td className="font-medium">{o.order_no}</Td>
                  <Td>{dateStr(o.ordered_at)}</Td>
                  <Td>{o.company_name ?? "-"}</Td>
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
          <EmptyState icon={ShoppingCart} title={pl.orders.empty} />
        )}
      </Card>
    </div>
  );
}
