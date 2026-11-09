import { Download, ExternalLink, FileText, RefreshCw } from "lucide-react";
import * as React from "react";

import { Button, Card, Label, PageHead } from "@/components/ui";
import { DateRangePicker, useDateRange } from "@/contexts/dateRange";

export function Reports() {
  const dr = useDateRange();
  const from = dr.from;
  const to = dr.to;
  const [nonce, setNonce] = React.useState(0);

  const base = `/api/reports/pdf?date_from=${from}&date_to=${to}`;
  const viewUrl = `${base}&_=${nonce}`; // nonce wymusza przeładowanie podglądu
  const downloadUrl = `${base}&download=1`;

  const linkBtn =
    "inline-flex h-10 items-center gap-2 rounded-lg px-4 text-sm font-medium transition-all active:scale-[0.98]";

  return (
    <div className="space-y-4">
      <PageHead
        title="Raporty"
        subtitle="Raport analityczno-sprzedażowy w formacie PDF - podgląd i pobranie."
        actions={
          <a href={downloadUrl} className={`${linkBtn} bg-[#4F46E5] text-white shadow-sm hover:bg-[#4338CA]`}>
            <Download className="h-4 w-4" /> Pobierz PDF
          </a>
        }
      />

      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <Label>Zakres</Label>
            <DateRangePicker />
          </div>
          <Button variant="secondary" onClick={() => setNonce((n) => n + 1)}>
            <RefreshCw className="h-4 w-4" /> Odśwież podgląd
          </Button>
          <a href={viewUrl} target="_blank" rel="noreferrer" className={`${linkBtn} border border-border text-text-muted hover:bg-surface-2`}>
            <ExternalLink className="h-4 w-4" /> Otwórz w nowej karcie
          </a>
        </div>
      </Card>

      {/* Podgląd inline na desktopie; na telefonie iframe PDF bywa nieobsługiwany → CTA otwórz/pobierz. */}
      <Card className="overflow-hidden">
        <iframe
          key={`${from}|${to}|${nonce}`}
          title="Podgląd raportu PDF"
          src={viewUrl}
          className="hidden h-[75vh] w-full border-0 md:block"
        />
        <div className="flex flex-col items-center gap-3 px-6 py-12 text-center md:hidden">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-text-subtle">
            <FileText className="h-6 w-6" />
          </div>
          <p className="max-w-xs text-sm text-text-muted">
            Podgląd PDF działa najlepiej na większym ekranie. Na telefonie otwórz lub pobierz raport:
          </p>
          <div className="flex gap-2">
            <a href={viewUrl} target="_blank" rel="noreferrer" className={`${linkBtn} border border-border text-text hover:bg-surface-2`}>
              <ExternalLink className="h-4 w-4" /> Otwórz
            </a>
            <a href={downloadUrl} className={`${linkBtn} bg-[#4F46E5] text-white hover:bg-[#4338CA]`}>
              <Download className="h-4 w-4" /> Pobierz
            </a>
          </div>
        </div>
      </Card>
    </div>
  );
}
