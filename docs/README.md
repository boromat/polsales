# Dokumentacja projektu PolSales - panel analityczno-sprzedażowy z asystentem AI

Ten katalog zawiera pełną specyfikację systemu. Kolejność czytania:

1. **[00-decyzje-kanoniczne.md](00-decyzje-kanoniczne.md)** - nadrzędne rozstrzygnięcia. W razie
   sprzeczności między dokumentami źródłowymi ten plik ma pierwszeństwo.
2. **[08-plan-etapow.md](08-plan-etapow.md)** - archiwalny plan i dziennik etapów budowy (sprzed wydania 1.0).
3. **[06-metryki.md](06-metryki.md)** - kanoniczne definicje LTV, CAC, częstotliwości, netto, lejka.
4. **[05-integracje.md](05-integracje.md)** - instrukcje krok-po-kroku dostępów do API Meta/Google/GA4,
   zadanie dla strony www (GA4 + UTM), import CSV.
5. **[07-rodo.md](07-rodo.md)** - przetwarzanie danych osobowych, DPA Anthropic, retencja.
6. **[09-audyt-otwarte.md](09-audyt-otwarte.md)** - przebiegi audytu kodu: znaleziska, naprawy i odrzucone
   propozycje (z uzasadnieniem względem decyzji kanonicznych).

## Dokumenty źródłowe (`zrodla/`)

Szczegółowe projekty modułów przygotowane przez zespół agentów projektowych. Są to materiały
referencyjne - **gdziekolwiek są sprzeczne z `00-decyzje-kanoniczne.md`, obowiązuje decyzja kanoniczna.**

- `zrodla/architektura.md` - komponenty, stack, struktura katalogów, deployment, obsługa błędów
- `zrodla/model-danych.md` - pełny DDL PostgreSQL, formuły metryk, logika NIP
- `zrodla/pipeline-maili.md` - tor przetwarzania maili IMAP → parser → szkice
- `zrodla/asystent-ai.md` - architektura czatu, definicje narzędzi (tools), system prompt, rekomendacje
- `zrodla/ui-ux.md` - kompletny projekt interfejsu, wszystkie widoki, styl wizualny
- `zrodla/integracje-research.md` - research dostępów do API (stan 2026, z linkami źródłowymi)
- `zrodla/recenzja-krytyka.md` - lista problemów wykrytych w projekcie (rozstrzygniętych w decyzjach kanonicznych)

## Jak uruchomić

Zobacz `../README.md` w katalogu głównym repo.
