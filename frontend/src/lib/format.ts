// Formatowanie w konwencji polskiej (spacja jako separator tysięcy, przecinek dziesiętny).

const plNumber = new Intl.NumberFormat("pl-PL", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const plInt = new Intl.NumberFormat("pl-PL");

export function money(v: number | null | undefined, suffix = " zł"): string {
  if (v === null || v === undefined) return "-";
  return plNumber.format(v) + suffix;
}

export function moneyNet(v: number | null | undefined): string {
  if (v === null || v === undefined) return "-";
  return plNumber.format(v) + " zł netto";
}

export function int(v: number | null | undefined): string {
  if (v === null || v === undefined) return "-";
  return plInt.format(v);
}

export function percent(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "-";
  return v.toFixed(digits).replace(".", ",") + "%";
}

/** ROAS i inne krotności - 2 miejsca, przecinek dziesiętny, sufiks „×" (np. „0,64×"). */
export function ratio(v: number | null | undefined, suffix = "×"): string {
  if (v === null || v === undefined) return "-";
  return v.toFixed(2).replace(".", ",") + suffix;
}

/** Liczba dni z przecinkiem dziesiętnym (np. „3,5 dni"). */
export function days(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "-";
  return v.toFixed(digits).replace(".", ",") + " dni";
}

/**
 * Polonizuje kropkę dziesiętną w gotowym tekście (narracja AI z backendu,
 * np. „707.31 zł" → „707,31 zł").
 *
 * Daty w formacie polskim (13.07.2026) są chronione - kropka jest tam poprawna
 * i zamiana zrobiłaby z nich „13,07,2026". Daty ISO (2026-07-13) nie zawierają
 * kropek, więc pozostają nietknięte same z siebie.
 */
export function polonizeDecimals(s: string | null | undefined): string {
  if (!s) return "";
  // Alternatywa w regexie: najpierw proba dopasowania DATY (zwracamy bez zmian), dopiero
  // potem cyfra-kropka-cyfra. Bez podmiany na znaczniki - te moglyby uszkodzic tresc
  // zawierajaca liczby otoczone spacjami.
  return s.replace(/\d{1,2}\.\d{1,2}\.\d{4}|(\d)\.(\d)/g, (dopasowanie, a, b) =>
    a === undefined ? dopasowanie : `${a},${b}`,
  );
}

export function dateStr(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function dateTimeStr(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
