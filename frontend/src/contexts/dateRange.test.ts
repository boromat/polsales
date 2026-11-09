import { describe, expect, it } from "vitest";

import { iso, przesunDni, zakresPresetu } from "./dateRange";

describe("zakres dat", () => {
  it("iso zwraca dzień LOKALNY, nie UTC", () => {
    // 22 lipca 00:30 czasu polskiego to 21 lipca 22:30 UTC - toISOString() dałby "2026-07-21"
    // i zakres „do dziś" kończyłby się wczoraj, ukrywając zamówienie złożone po północy.
    const poPolnocy = new Date(2026, 6, 22, 0, 30);
    expect(iso(poPolnocy)).toBe("2026-07-22");

    const przedPolnoca = new Date(2026, 6, 22, 23, 59);
    expect(iso(przedPolnoca)).toBe("2026-07-22");
  });

  it("iso dopełnia zerami miesiąc i dzień", () => {
    expect(iso(new Date(2026, 0, 5))).toBe("2026-01-05");
  });

  it("przesunDni liczy po kalendarzu, także przez zmianę czasu", () => {
    // Zmiana czasu na letni w Polsce: 29.03.2026. Odejmowanie milisekund gubi tu godzinę.
    expect(iso(przesunDni(new Date(2026, 2, 30, 1, 0), 1))).toBe("2026-03-29");
    expect(iso(przesunDni(new Date(2026, 2, 30, 1, 0), 2))).toBe("2026-03-28");
    // Przejście przez granicę miesiąca i roku.
    expect(iso(przesunDni(new Date(2026, 0, 1), 1))).toBe("2025-12-31");
  });

  it("preset „ostatnie N dni” liczy WŁĄCZNIE z dniem dzisiejszym", () => {
    const teraz = new Date(2026, 6, 22, 10, 0);
    expect(zakresPresetu(7, teraz)).toEqual({ from: "2026-07-16", to: "2026-07-22" });
    expect(zakresPresetu(1, teraz)).toEqual({ from: "2026-07-22", to: "2026-07-22" });
    expect(zakresPresetu(30, teraz)).toEqual({ from: "2026-06-23", to: "2026-07-22" });
  });

  it("preset „cały okres” zaczyna się w 2000 roku", () => {
    const teraz = new Date(2026, 6, 22, 10, 0);
    expect(zakresPresetu("all", teraz)).toEqual({ from: "2000-01-01", to: "2026-07-22" });
  });
});
