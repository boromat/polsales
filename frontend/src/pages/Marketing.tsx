// Marketing - porównanie kanałów, lejek konwersji, import CSV, status synchronizacji. Etap 3.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Filter, Mail, Megaphone, RefreshCw, Share2, Upload } from "lucide-react";
import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  api,
  type AdFormat,
  type ChannelSummary,
  type EmailTrend,
  type Funnel,
  type IntegrationStatus,
  type OrganicEngagement,
} from "@/api/client";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Skeleton,
  Table,
  TBody,
  Td,
  Textarea,
  Th,
  THead,
  Tr,
} from "@/components/ui";
import { DateRangePicker, useDateRange } from "@/contexts/dateRange";
import { int, money, moneyNet, percent, ratio } from "@/lib/format";
import { useTheme } from "@/theme";

const SOURCE_LABELS: Record<string, string> = {
  imap: "Skrzynka e-mail",
  meta_ads: "Meta Ads",
  meta_organic: "Meta organicznie",
  google_ads: "Google Ads",
  ga4: "Google Analytics 4",
};

export function Marketing() {
  const dr = useDateRange();
  const channels = useQuery({
    queryKey: ["mkChannels", dr.from, dr.to],
    queryFn: () => api.get<ChannelSummary[]>(`/marketing/channels${dr.query}`),
  });
  const funnel = useQuery({
    queryKey: ["mkFunnel", dr.from, dr.to],
    queryFn: () => api.get<Funnel>(`/marketing/funnel${dr.query}&channel=all`),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">Marketing</h1>
        <DateRangePicker />
      </div>

      <SyncBar />

      {/* Lejek */}
      <Card className="p-5">
        <h2 className="mb-4 text-sm font-semibold">Lejek konwersji (wszystkie kanały)</h2>
        {funnel.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-9 flex-1" />
              </div>
            ))}
          </div>
        ) : funnel.data ? (
          <FunnelView f={funnel.data} />
        ) : (
          <EmptyState
            icon={Filter}
            title="Brak danych lejka"
            description="Podłącz integracje lub zaimportuj CSV, aby zobaczyć konwersję."
          />
        )}
      </Card>

      {/* Porównanie kanałów */}
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <h2 className="text-sm font-semibold">Porównanie kanałów</h2>
        </div>
        {channels.isLoading ? (
          <div className="space-y-3 p-4">
            <Skeleton className="h-64 w-full" />
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : channels.data && channels.data.length > 0 ? (
          <>
            <div className="border-b border-border px-5 py-4">
              <ChannelsBarChart data={channels.data} />
            </div>
            <Table>
            <THead>
              <Th>Kanał</Th>
              <Th align="right">Wydatki</Th>
              <Th align="right">Sesje</Th>
              <Th align="right">Zamówienia</Th>
              <Th align="right">Przychód netto</Th>
              <Th align="right">ROAS</Th>
            </THead>
            <TBody>
              {channels.data.map((c) => (
                <Tr key={c.channel_code}>
                  <Td className="font-medium">{c.name_pl}</Td>
                  <Td align="right">{money(c.spend)}</Td>
                  <Td align="right">{int(c.sessions)}</Td>
                  <Td align="right">{int(c.orders)}</Td>
                  <Td align="right">{money(c.revenue_net)}</Td>
                  <Td align="right">{ratio(c.roas)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
          </>
        ) : (
          <EmptyState
            icon={BarChart3}
            title="Brak danych marketingowych"
            description="Podłącz integracje lub zaimportuj CSV (poniżej)."
          />
        )}
      </Card>

      <AdFormatsRanking />

      <OrganicEngagementCard />

      <EmailTrendsCard />

      <CsvImport />
    </div>
  );
}

function AdFormatsRanking() {
  const dr = useDateRange();
  const formats = useQuery({
    queryKey: ["mkFormats", dr.from, dr.to],
    queryFn: () => api.get<AdFormat[]>(`/marketing/formats${dr.query}`),
  });

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
        <h2 className="text-sm font-semibold">Ranking formatów reklamowych</h2>
      </div>
      {formats.isLoading ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : formats.data && formats.data.length > 0 ? (
        <Table>
          <THead>
            <Th>Platforma</Th>
            <Th>Format</Th>
            <Th>Typ</Th>
            <Th align="right">Wyświetl.</Th>
            <Th align="right">Klik.</Th>
            <Th align="right">Wydatki</Th>
            <Th align="right">CTR</Th>
            <Th align="right">Zaangażowanie</Th>
          </THead>
          <TBody>
            {formats.data.map((f, i) => (
              <Tr key={`${f.platform}-${f.format}-${i}`}>
                <Td className="font-medium">{f.platform}</Td>
                <Td>{f.format}</Td>
                <Td>
                  <Badge tone={f.kind === "platny" ? "primary" : "neutral"} dot>
                    {f.kind}
                  </Badge>
                </Td>
                <Td align="right" className="tabnum">
                  {int(f.impressions)}
                </Td>
                <Td align="right" className="tabnum">
                  {int(f.clicks)}
                </Td>
                <Td align="right" className="tabnum">
                  {money(f.spend)}
                </Td>
                <Td align="right" className="tabnum">
                  {f.ctr === null ? "-" : percent(f.ctr * 100)}
                </Td>
                <Td align="right" className="tabnum">
                  {int(f.engagement)}
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      ) : (
        <EmptyState
          icon={Megaphone}
          title="Brak danych o formatach"
          description="Podłącz Meta Ads / Google Ads lub zaimportuj dane, aby zobaczyć ranking formatów."
        />
      )}
    </Card>
  );
}

function OrganicEngagementCard() {
  const dr = useDateRange();
  const organic = useQuery({
    queryKey: ["mkOrganic", dr.from, dr.to],
    queryFn: () => api.get<OrganicEngagement>(`/marketing/organic${dr.query}`),
  });

  const t = organic.data?.totals;

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
        <h2 className="text-sm font-semibold">Zaangażowanie organiczne</h2>
      </div>
      {organic.isLoading ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : organic.data && organic.data.by_type.length > 0 ? (
        <>
          {t && (
            <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-border px-5 py-3 text-xs text-text-muted">
              <span>
                Wyświetlenia: <span className="tabnum font-semibold text-text">{int(t.views)}</span>
              </span>
              <span>
                Zaangażowanie:{" "}
                <span className="tabnum font-semibold text-text">{int(t.engagement)}</span>
              </span>
              <span>
                Posty: <span className="tabnum font-semibold text-text">{int(t.posts)}</span>
              </span>
            </div>
          )}
          <Table>
            <THead>
              <Th>Typ posta</Th>
              <Th align="right">Posty</Th>
              <Th align="right">Wyświetlenia</Th>
              <Th align="right">Lajki</Th>
              <Th align="right">Komentarze</Th>
              <Th align="right">Udost.</Th>
              <Th align="right">Zaangażowanie</Th>
            </THead>
            <TBody>
              {organic.data.by_type.map((o, i) => (
                <Tr key={`${o.post_type}-${i}`}>
                  <Td className="font-medium">{o.post_type}</Td>
                  <Td align="right" className="tabnum">
                    {int(o.posts)}
                  </Td>
                  <Td align="right" className="tabnum">
                    {int(o.views)}
                  </Td>
                  <Td align="right" className="tabnum">
                    {int(o.likes)}
                  </Td>
                  <Td align="right" className="tabnum">
                    {int(o.comments)}
                  </Td>
                  <Td align="right" className="tabnum">
                    {int(o.shares)}
                  </Td>
                  <Td align="right" className="tabnum">
                    {int(o.engagement)}
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </>
      ) : (
        <EmptyState
          icon={Share2}
          title="Brak aktywności organicznej"
          description="Podłącz Meta organicznie, aby zobaczyć zaangażowanie postów."
        />
      )}
    </Card>
  );
}

function EmailTrendsCard() {
  const dr = useDateRange();
  const trends = useQuery({
    queryKey: ["mkEmailTrends", dr.from, dr.to],
    queryFn: () => api.get<EmailTrend[]>(`/marketing/email-trends${dr.query}`),
  });

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
        <h2 className="text-sm font-semibold">Trendy produktów z maili</h2>
      </div>
      {trends.isLoading ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : trends.data && trends.data.length > 0 ? (
        <Table>
          <THead>
            <Th>Produkt</Th>
            <Th align="right">Wzmianki</Th>
            <Th align="right">Ilość</Th>
            <Th align="right">Dni</Th>
          </THead>
          <TBody>
            {trends.data.map((e, i) => (
              <Tr key={`${e.product}-${i}`}>
                <Td className="font-medium">{e.product}</Td>
                <Td align="right" className="tabnum">
                  {int(e.mentions)}
                </Td>
                <Td align="right" className="tabnum">
                  {int(e.quantity)}
                </Td>
                <Td align="right" className="tabnum">
                  {int(e.days)}
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      ) : (
        <EmptyState
          icon={Mail}
          title="Brak wzmianek produktów w mailach"
          description="Gdy skrzynka e-mail zsynchronizuje zamówienia, pojawią się tu trendy produktów."
        />
      )}
    </Card>
  );
}

function ChannelsBarChart({ data }: { data: ChannelSummary[] }) {
  const { isDark } = useTheme();
  // Kolory zależne od motywu - przychód indygo (jak w Dashboard), wydatki pomarańczowe.
  const revenueColor = isDark ? "#818CF8" : "#4F46E5";
  const spendColor = isDark ? "#FB923C" : "#EA580C";
  const chartGrid = isDark ? "#27272A" : "#E4E4E7";
  const chartAxis = isDark ? "#A1A1AA" : "#64646E";
  const nfCompact = React.useMemo(
    () => new Intl.NumberFormat("pl-PL", { notation: "compact", maximumFractionDigits: 1 }),
    [],
  );

  return (
    <div className="h-[260px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }} barGap={4}>
          <CartesianGrid strokeDasharray="3 3" stroke={chartGrid} vertical={false} />
          <XAxis
            dataKey="name_pl"
            tick={{ fontSize: 11, fill: chartAxis }}
            axisLine={{ stroke: chartGrid }}
            tickLine={false}
            interval={0}
          />
          <YAxis
            tick={{ fontSize: 11, fill: chartAxis }}
            width={54}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => nfCompact.format(v)}
          />
          <Tooltip
            cursor={{ fill: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }}
            formatter={(value: number, name: string) => [
              name === "Przychód netto" ? moneyNet(value) : money(value),
              name,
            ]}
            contentStyle={{
              borderRadius: 12,
              border: `1px solid ${chartGrid}`,
              background: isDark ? "#18181B" : "#FFFFFF",
              boxShadow: "0 8px 30px -6px rgb(24 24 27 / 0.18)",
              fontSize: 12,
            }}
            labelStyle={{ color: chartAxis }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="spend" name="Wydatki" fill={spendColor} radius={[4, 4, 0, 0]} maxBarSize={48} />
          <Bar
            dataKey="revenue_net"
            name="Przychód netto"
            fill={revenueColor}
            radius={[4, 4, 0, 0]}
            maxBarSize={48}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function FunnelView({ f }: { f: Funnel }) {
  const stages = [
    { label: "Wyświetlenia", value: f.impressions },
    { label: "Kliknięcia", value: f.clicks },
    { label: "Sesje", value: f.sessions },
    { label: "Zamówienia", value: f.orders },
  ];
  const max = Math.max(...stages.map((s) => s.value), 1);
  const ratios = [
    f.ctr !== null ? `CTR ${percent(f.ctr * 100)}` : null,
    f.click_to_session !== null ? `${percent(f.click_to_session * 100)} klik.→sesja` : null,
    f.cr_session_order !== null ? `konwersja ${percent(f.cr_session_order * 100)}` : null,
  ];
  return (
    <div className="space-y-1.5">
      {stages.map((s, i) => (
        <React.Fragment key={s.label}>
          <div className="flex items-center gap-3">
            <div className="w-28 shrink-0 text-xs font-medium text-text-muted">{s.label}</div>
            <div className="flex-1">
              <div
                className="flex h-9 items-center rounded-lg bg-gradient-to-r from-primary to-primary-hover px-3 text-xs font-semibold text-white shadow-sm transition-all"
                style={{ width: `${Math.max((s.value / max) * 100, 6)}%` }}
              >
                <span className="tabnum truncate">{int(s.value)}</span>
              </div>
            </div>
          </div>
          {i < 3 && ratios[i] && (
            <div className="ml-28 pl-3 text-[11px] text-text-subtle">↓ {ratios[i]}</div>
          )}
        </React.Fragment>
      ))}
      <div className="mt-3 border-t border-border pt-3 text-xs text-text-muted">
        Wydatki: <span className="tabnum">{money(f.spend)}</span> · koszt/zamówienie:{" "}
        <span className="tabnum">{money(f.cpo)}</span> · ROAS:{" "}
        <span className="tabnum">{ratio(f.roas)}</span>
      </div>
    </div>
  );
}

function SyncBar() {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api.get<{ integrations: IntegrationStatus[] }>("/health/integrations"),
  });
  const sync = useMutation({
    mutationFn: () => api.post("/marketing/sync-now?source=all"),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ["integrations"] }), 1000),
  });

  const tone = (state: string): "success" | "danger" | "neutral" =>
    state === "ok" ? "success" : state === "blad" ? "danger" : "neutral";

  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        {status.isLoading
          ? Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-6 w-28 rounded-full" />
            ))
          : (status.data?.integrations ?? []).map((s) => (
              <Badge key={s.source} tone={tone(s.state)} dot>
                {SOURCE_LABELS[s.source] ?? s.source}
              </Badge>
            ))}
      </div>
      <Button variant="secondary" onClick={() => sync.mutate()} disabled={sync.isPending}>
        <RefreshCw className={`h-4 w-4 ${sync.isPending ? "animate-spin" : ""}`} /> Synchronizuj teraz
      </Button>
    </Card>
  );
}

function CsvImport() {
  const qc = useQueryClient();
  const [content, setContent] = React.useState("");
  const mut = useMutation({
    mutationFn: () => api.post<{ meta_ads: number; google_ads: number }>("/marketing/import-csv", { content }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mkChannels"] });
      qc.invalidateQueries({ queryKey: ["mkFunnel"] });
      qc.invalidateQueries({ queryKey: ["kpi"] });
    },
  });

  return (
    <Card className="p-5">
      <h2 className="mb-1 text-sm font-semibold">Import CSV (Meta Ads / Google Ads)</h2>
      <p className="mb-3 text-xs text-text-muted">
        Kolumny:{" "}
        <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-text">
          dzien, kanal, kampania, wyswietlenia, klikniecia, koszt
        </code>
        . Kanał: meta_ads lub google_ads. Fallback, zanim podłączysz API - patrz docs/05-integracje.md.
      </p>
      <Textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={5}
        placeholder={"dzien,kanal,kampania,wyswietlenia,klikniecia,koszt\n2026-07-19,meta_ads,Lipiec,12000,340,250.00"}
        className="font-mono text-xs"
      />
      <div className="mt-3 flex items-center gap-3">
        <Button onClick={() => mut.mutate()} disabled={!content || mut.isPending}>
          <Upload className="h-4 w-4" /> Importuj
        </Button>
        {mut.data && (
          <Badge tone="success" dot>
            Zaimportowano: Meta {mut.data.meta_ads}, Google {mut.data.google_ads}
          </Badge>
        )}
      </div>
    </Card>
  );
}
