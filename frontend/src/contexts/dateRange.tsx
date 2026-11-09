// Globalny zakres dat - współdzielony między Dashboard / Marketing / Raporty (persist w localStorage).
import * as React from "react";

import { Select } from "@/components/ui";

/** Data jako RRRR-MM-DD w czasie LOKALNYM.
 *
 * `toISOString()` przelicza na UTC, a Polska to UTC+1/+2 - miedzy polnoca a 2:00
 * zwracal WCZORAJSZY dzien. Zakres "do dzis" konczyl sie wtedy na wczoraj i zamowienie
 * zlozone po polnocy nie pokazywalo sie w panelu. Backend bucketuje po Europe/Warsaw
 * (decyzja #17), wiec front musi liczyc dni tak samo.
 */
export function iso(d: Date): string {
  const dwie = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${dwie(d.getMonth() + 1)}-${dwie(d.getDate())}`;
}

/** Przesuniecie o cale dni po kalendarzu lokalnym (odporne na zmiane czasu).
 *
 * Odejmowanie milisekund gubi godzine przy przejsciu zima/lato i potrafi cofnac
 * date o jeden dzien za duzo.
 */
export function przesunDni(d: Date, dni: number): Date {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() - dni);
  return x;
}

/** Zakres dla presetu ("ostatnie N dni" liczone WLACZNIE z dniem dzisiejszym). */
export function zakresPresetu(days: number | "all", teraz: Date = new Date()): DateRange {
  const to = iso(teraz);
  return { from: days === "all" ? "2000-01-01" : iso(przesunDni(teraz, days - 1)), to };
}

export interface DateRange {
  from: string;
  to: string;
}

interface Ctx extends DateRange {
  setRange: (r: DateRange) => void;
  setPreset: (days: number | "all") => void;
  query: string; // "?date_from=..&date_to=.."
}

const DateRangeContext = React.createContext<Ctx | null>(null);

function initial(): DateRange {
  const saved = localStorage.getItem("dateRange");
  if (saved) {
    try {
      const r = JSON.parse(saved);
      if (r?.from && r?.to) return r;
    } catch {
      /* ignore */
    }
  }
  return zakresPresetu(30);
}

export function DateRangeProvider({ children }: { children: React.ReactNode }) {
  const [range, setRangeState] = React.useState<DateRange>(initial);
  const setRange = React.useCallback((r: DateRange) => {
    setRangeState(r);
    localStorage.setItem("dateRange", JSON.stringify(r));
  }, []);
  const setPreset = React.useCallback(
    (days: number | "all") => setRange(zakresPresetu(days)),
    [setRange],
  );
  const query = `?date_from=${range.from}&date_to=${range.to}`;
  return (
    <DateRangeContext.Provider value={{ ...range, setRange, setPreset, query }}>
      {children}
    </DateRangeContext.Provider>
  );
}

export function useDateRange(): Ctx {
  const ctx = React.useContext(DateRangeContext);
  if (!ctx) throw new Error("useDateRange poza DateRangeProvider");
  return ctx;
}

const PRESETS: { label: string; days: number | "all" }[] = [
  { label: "7 dni", days: 7 },
  { label: "30 dni", days: 30 },
  { label: "90 dni", days: 90 },
  { label: "12 mies.", days: 365 },
  { label: "Cały okres", days: "all" },
];

export function DateRangePicker() {
  const dr = useDateRange();
  const currentPreset = React.useMemo(() => {
    const today = iso(new Date());
    if (dr.to !== today) return "";
    if (dr.from === "2000-01-01") return "all";
    for (const p of PRESETS) {
      if (p.days !== "all") {
        if (zakresPresetu(p.days).from === dr.from) return String(p.days);
      }
    }
    return "";
  }, [dr.from, dr.to]);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="w-36">
        <Select
          value={currentPreset}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "all") dr.setPreset("all");
            else if (v) dr.setPreset(Number(v));
          }}
        >
          <option value="">Zakres własny…</option>
          {PRESETS.map((p) => (
            <option key={String(p.days)} value={String(p.days)}>
              {p.label}
            </option>
          ))}
        </Select>
      </div>
      <input
        type="date"
        aria-label="Data od"
        value={dr.from}
        max={dr.to}
        onChange={(e) => dr.setRange({ from: e.target.value, to: dr.to })}
        className="h-10 rounded-lg border border-border bg-surface px-2 text-sm text-text hover:border-border-strong focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25"
      />
      <span className="text-text-subtle">-</span>
      <input
        type="date"
        aria-label="Data do"
        value={dr.to}
        min={dr.from}
        onChange={(e) => dr.setRange({ from: dr.from, to: e.target.value })}
        className="h-10 rounded-lg border border-border bg-surface px-2 text-sm text-text hover:border-border-strong focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25"
      />
    </div>
  );
}
