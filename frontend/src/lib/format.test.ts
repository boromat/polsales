import { describe, expect, it } from "vitest";

import { dateStr, days, int, money, moneyNet, percent, polonizeDecimals, ratio } from "./format";

// Separator tysięcy (NBSP) i grupowanie zależą od ICU środowiska (node vs przeglądarka),
// więc porównujemy po usunięciu białych znaków - testujemy cyfry, przecinek dziesiętny i sufiks.
const n = (s: string) => s.replace(/\s/g, "");

describe("format", () => {
  it("money - przecinek dziesiętny + sufiks zł", () => {
    expect(n(money(1234.5))).toBe("1234,50zł");
    expect(n(money(0))).toBe("0,00zł");
    expect(money(null)).toBe("-");
    expect(money(undefined)).toBe("-");
  });

  it("moneyNet - sufiks 'zł netto'", () => {
    expect(n(moneyNet(100))).toBe("100,00złnetto");
    expect(moneyNet(null)).toBe("-");
  });

  it("int - liczba całkowita bez części dziesiętnej", () => {
    expect(n(int(12000))).toBe("12000");
    expect(int(5)).toBe("5");
    expect(int(null)).toBe("-");
  });

  it("percent - przecinek dziesiętny + znak %", () => {
    expect(percent(12.34)).toBe("12,3%");
    expect(percent(0)).toBe("0,0%");
    expect(percent(null)).toBe("-");
  });

  it("dateStr - format dd.mm.rrrr / - dla braku", () => {
    expect(dateStr("2026-07-20")).toBe("20.07.2026");
    expect(dateStr(null)).toBe("-");
    expect(dateStr(undefined)).toBe("-");
  });
});

describe("formatowanie polskie - spójność z raportem PDF", () => {
  it("ratio - ROAS z przecinkiem i znakiem ×", () => {
    expect(ratio(0.6388)).toBe("0,64×");
    expect(ratio(3)).toBe("3,00×");
    expect(ratio(null)).toBe("-");
    expect(ratio(1.5, "")).toBe("1,50");
  });

  it("days - czas kontakt→sprzedaż z przecinkiem", () => {
    expect(days(3.5)).toBe("3,5 dni");
    expect(days(0)).toBe("0,0 dni");
    expect(days(null)).toBe("-");
  });

  it("polonizeDecimals - kropka między cyframi na przecinek", () => {
    expect(polonizeDecimals("707.31 zł netto")).toBe("707,31 zł netto");
    expect(polonizeDecimals("ROAS: 0.64, CTR 2.4%")).toBe("ROAS: 0,64, CTR 2,4%");
    // Nie rusza dat ani zwykłych kropek zdaniowych
    expect(polonizeDecimals("Tydzień 2026-07-13. Koniec.")).toBe("Tydzień 2026-07-13. Koniec.");
    // Data polska MUSI zachowac kropki (regresja: "13.07.2026" -> "13,07,2026")
    expect(polonizeDecimals("Tydzień 13.07.2026-19.07.2026: 707.31 zł")).toBe(
      "Tydzień 13.07.2026-19.07.2026: 707,31 zł",
    );
    // Liczba otoczona spacjami nie moze zostac uszkodzona
    expect(polonizeDecimals("Zamówienia: 4 sztuki, wartość 12.50 zł")).toBe(
      "Zamówienia: 4 sztuki, wartość 12,50 zł",
    );
    expect(polonizeDecimals(null)).toBe("");
  });
});
