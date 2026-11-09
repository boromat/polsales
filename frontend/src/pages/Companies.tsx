import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Building2, Search } from "lucide-react";
import { Link } from "react-router-dom";

import { api, type CompanyListItem } from "@/api/client";
import { Badge, Card, EmptyState, Input, Skeleton, Table, TBody, Td, Th, THead, Tr } from "@/components/ui";
import { pl } from "@/i18n/pl";
import { dateStr, money } from "@/lib/format";

export function Companies() {
  const [q, setQ] = useState("");
  const [onlyAtRisk, setOnlyAtRisk] = useState(false);

  const companies = useQuery({
    queryKey: ["companies", q],
    queryFn: () => api.get<CompanyListItem[]>("/companies" + (q ? "?q=" + encodeURIComponent(q) : "")),
  });

  const rows = onlyAtRisk ? (companies.data ?? []).filter((c) => c.at_risk) : companies.data ?? [];
  const hasData = rows.length > 0;
  const atRiskCount = (companies.data ?? []).filter((c) => c.at_risk).length;

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3.5">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold">{pl.companies.title}</h2>
            {companies.data && <Badge tone="neutral">{rows.length}</Badge>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex cursor-pointer select-none items-center gap-2 text-xs text-text-muted">
              <input
                type="checkbox"
                checked={onlyAtRisk}
                onChange={(e) => setOnlyAtRisk(e.target.checked)}
                className="h-3.5 w-3.5 accent-danger"
              />
              tylko zagrożone
              {atRiskCount > 0 && <Badge tone="danger">{atRiskCount}</Badge>}
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-subtle" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Szukaj po nazwie lub NIP…"
                className="h-9 w-56 pl-9"
                aria-label="Szukaj firmy po nazwie lub NIP"
              />
            </div>
          </div>
        </div>

        {companies.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : hasData ? (
          <Table>
            <THead>
              <Th>{pl.companies.name}</Th>
              <Th>{pl.companies.nip}</Th>
              <Th align="right">{pl.companies.orders}</Th>
              <Th align="right">{pl.companies.ltv}</Th>
              <Th>{pl.companies.frequency}</Th>
              <Th>{pl.companies.lastOrder}</Th>
            </THead>
            <TBody>
              {rows.map((c) => (
                <Tr key={c.company_id}>
                  <Td className="font-medium">
                    <div className="flex items-center gap-2">
                      <Link
                        to={`/firmy/${c.company_id}`}
                        className="text-primary transition-colors hover:text-primary-hover"
                      >
                        {c.company_name ?? "-"}
                      </Link>
                      {c.at_risk && (
                        <span
                          title={
                            "Brak zakupu > 2× typowa częstotliwość" +
                            (c.days_since_last_order != null
                              ? `; ${c.days_since_last_order} dni od ostatniego`
                              : "")
                          }
                        >
                          <Badge tone="danger" dot>
                            zagrożona
                          </Badge>
                        </span>
                      )}
                    </div>
                  </Td>
                  <Td className="tabnum text-text-muted">{c.nip ?? "-"}</Td>
                  <Td align="right">{c.orders_count ?? 0}</Td>
                  <Td align="right">{money(c.ltv_net)}</Td>
                  <Td className="text-text-muted">
                    {c.frequency_days ? pl.companies.everyDays(c.frequency_days) : "-"}
                  </Td>
                  <Td className="text-text-muted">{dateStr(c.last_order)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        ) : (
          <EmptyState
            icon={onlyAtRisk ? AlertTriangle : Building2}
            title={
              onlyAtRisk
                ? "Brak firm zagrożonych odejściem."
                : q
                  ? "Brak firm pasujących do wyszukiwania."
                  : pl.companies.empty
            }
          />
        )}
      </Card>
    </div>
  );
}
