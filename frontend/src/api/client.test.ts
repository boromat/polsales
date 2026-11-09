import { describe, expect, it } from "vitest";

import { czytelnyBlad } from "./client";

describe("czytelnyBlad", () => {
  it("zwykły komunikat tekstowy przechodzi bez zmian", () => {
    expect(czytelnyBlad("Nie znaleziono szkicu")).toBe("Nie znaleziono szkicu");
  });

  it("błąd walidacji FastAPI (422) zamienia się w czytelne zdanie, nie [object Object]", () => {
    // Realny kształt odpowiedzi: {"detail": [{"loc": [...], "msg": "...", "type": "..."}]}
    const detail = [
      { loc: ["body", "items", 0, "unit_price_gross"], msg: "Input should be a valid number" },
      { loc: ["body", "nip"], msg: "Nieprawidłowy NIP" },
    ];
    const wynik = czytelnyBlad(detail)!;
    expect(wynik).toContain("items.0.unit_price_gross");
    expect(wynik).toContain("nip: Nieprawidłowy NIP");
    expect(wynik).not.toContain("[object Object]");
  });

  it("obiekt bez pola msg nie gubi treści", () => {
    expect(czytelnyBlad({ message: "Coś poszło nie tak" })).toBe("Coś poszło nie tak");
  });

  it("brak detalu daje null (wołający zostaje przy statusText)", () => {
    expect(czytelnyBlad(null)).toBeNull();
    expect(czytelnyBlad(undefined)).toBeNull();
    expect(czytelnyBlad([])).toBeNull();
  });
});
