# Plan etapów wdrożenia

> **Dokument archiwalny.** Plan i dziennik etapów z okresu budowy (do lipca 2026), sprzed
> wydania 1.0 - nie jest aktualizowany. Liczby i zakres opisują ówczesny stan (np. migracje
> 0001-0008, 102 testy backendu). Stan faktyczny: [README](../README.md) (sekcje "Testy
> i jakość" i "Znane ograniczenia") oraz [CHANGELOG](../CHANGELOG.md).

Status aktualny: **Etapy 0-9: pełny zakres + UI + audyt + raporty PDF + responsywność + usprawnienia (bezpieczeństwo/analityka/UX/ops/CI).** Zweryfikowane na żywej bazie (przenośny
Postgres, bez Dockera): migracje 0001-0008, 102 testy backendu + 5 frontendu, code-split, CI, pełny flow danych i API.
Dopracowanie UI (lipiec 2026): odświeżony system projektowy - self-hostowany font Inter Variable, tokeny cieni/elewacji,
rozszerzone prymitywy (`Card`, `Button`, `Input`, `Textarea`, `Select`, `Badge`, `Skeleton`, `EmptyState`,
`PageHead`, `StatCard`, `Table*`), pasek boczny z grupami i akcentem aktywnej pozycji, szkielety ładowania,
stany puste i spójne tabele we wszystkich widokach; oba motywy zweryfikowane w przeglądarce, build produkcyjny czysty.
Integracje zewnętrzne (Meta/Google/GA4/IMAP) i asystent AI zbudowane z bezpieczną degradacją - wymagają
realnych poświadczeń/klucza Anthropic do działania „na żywo" (nietestowane w środowisku dev; patrz uwagi
przy etapach). Pozostał tylko tryb ciemny w miejsce dawnego „poza MVP" (dodany na życzenie).

## Etap 0 - Szkielet (fundament)

- [x] Struktura monorepo (`backend/`, `frontend/`, `deploy/`, `docs/`)
- [x] `docker-compose.yml` (db + api + worker + caddy), `Caddyfile`, `.env.example`
- [x] Backend: FastAPI, konfiguracja (pydantic-settings), połączenie DB, Alembic
- [x] Schematy Postgres + rozszerzenia (`citext`, `pg_trgm`)
- [x] Auth: 1 użytkownik, hasło argon2id, sesje w cookie HTTP-only, rate-limit logowania
- [x] Frontend: Vite + React + TS + Tailwind, layout (sidebar + topbar + dokowany panel czatu placeholder),
      ekran logowania
- [x] README z instrukcją uruchomienia

## Etap 1 - Rdzeń sprzedażowy (`core`)

- [x] Model `core`: `channels`, `vat_rates`, `products`, `companies` (NIP), `contacts`, `orders`,
      `order_items` (kolumny generowane netto/VAT)
- [x] Funkcje NIP: `normalize_nip` (prefiks PL, separatory), `is_valid_nip` (suma kontrolna)
- [x] Logika dopięcia zamówienia do firmy po NIP (utworzenie/znalezienie profilu)
- [x] API: ręczne dodawanie zamówień, lista zamówień, lista i profil firm, KPI dashboardu
- [x] Widoki `analytics.v_orders_all`, `analytics.v_company_metrics`
- [x] Frontend: Dashboard (KPI + wykres + ostatnie zamówienia), Zamówienia (lista + drawer),
      Firmy (lista + profil)
- [x] Testy: NIP, matematyka netto/VAT, LTV/częstotliwość

**Kryterium ukończenia:** `docker compose up` + `alembic upgrade head`; logowanie działa; dodanie
zamówienia z NIP tworzy firmę i aktualizuje KPI; drugi wpis z tym samym NIP dopina się do tej firmy.

## Etap 2 - Pipeline maili ✅

- [x] IMAP polling (`imap-tools`), `mail.imap_state`, idempotencja (UID + Message-ID hash) - degradacja bez konfiguracji
- [x] Klasyfikacja regułowa (nagłówki, słowa kluczowe) - tani odsiew przed AI
- [x] Parser regułowy (maile z formularza, w tym pola UTM) + ekstrakcja Claude Haiku (degradacja bez klucza)
- [x] Szkice `core.orders_draft`, fuzzy-match produktów (`rapidfuzz` + aliasy uczące się)
- [x] Widok „Skrzynka": master-detail, weryfikacja i zatwierdzanie szkiców, pomocnik „Symuluj mail"
- [x] Zweryfikowane end-to-end: formularz → szkic → zatwierdzenie → zamówienie, aliasy się uczą

## Etap 3 - Integracje marketingowe + lejek ✅

- [x] Klienci integracji: GA4, Meta Ads, Meta organic (metryka `views`), Google Ads - degradacja bez poświadczeń
- [x] Schematy `channel_*` + widoki (`v_marketing_daily`, `v_sessions_daily`, `v_funnel_daily`, `v_cac_monthly`)
- [x] Import CSV (endpoint + UI), kolumna `source`
- [x] Widok „Marketing" (lejek, porównanie kanałów, import), Ustawienia (statusy), `ops.sync_commands` + worker
- [x] Metryki CAC/ROAS/lejek na dashboardzie - zweryfikowane end-to-end przez import CSV
- [ ] Atrybucja kaskadowa `heurystyka_ga4` - struktura gotowa; wymaga żywych danych GA4 do dopracowania

## Etap 4 - Asystent AI ✅

- [x] Backend czatu: pętla tool-use, streaming SSE, historia w `chat.*`, prompt caching (degradacja bez klucza)
- [x] Komplet 9 narzędzi (`strict: true`), rola DB `assistant_ro`, walidacja parametrów (zakres ≤400 dni)
- [x] System prompt PL z definicjami metryk, obsługa polskich określeń czasu (kontekst czasowy + widoku)
- [x] Frontend: pełny panel czatu (SSE, chipy kontekstowe, tabele markdown, historia)
- [x] Narzędzia zweryfikowane na żywej bazie; pętla LLM wymaga klucza Anthropic (degradacja potwierdzona)

## Etap 5 - Rekomendacje i eksporty ✅

- [x] Job rekomendacji (agregaty SQL + AI z kluczem / baseline regułowy bez klucza + walidacja) o 5:00 i na żądanie
- [x] Tabela `core.recommendations` z feedbackiem, widok „Rekomendacje" (karty, 👍/👎, „Generuj teraz")
- [x] Eksport CSV zamówień, import CSV zamówień historycznych - zweryfikowane (backfill LTV Alfa 400→1400)

## Etap 6 - poprawki z audytu poprawności ✅

Audyt „bebechów" (10 podsystemów, weryfikacja adwersaryjna) wykazał 47 potwierdzonych błędów -
wszystkie naprawione. Kluczowe:

- [x] **VAT**: `line_vat` = brutto - netto na wartościach zaokrąglonych (kolumna GENERATED + `vat.py`) -
      naprawia łamanie CHECK `totals_consistent` dla ilości ułamkowych (było ~25% zamówień → 500). Regres w testach.
- [x] **Atrybucja (#15)**: `create_order` ustawia `attribution_method` (auto „reczna" przy ręcznym kanale),
      `approve_draft` przekazuje metodę + UTM/gclid/fbclid; `ordered_at` = data maila, nie zatwierdzenia.
- [x] **Metryki**: częstotliwość liczona na datach filtrowanych statusem; ROAS/CPO lejka i CAC liczone na
      kanałach PŁATNYCH (zbiorczy ROAS 2,48 → 1,07); `v_cac_monthly` z FULL OUTER JOIN (kanały nieprzypisane).
- [x] **Asystent AI**: naprawiona pętla `tool_result` (rozmowy wielotUrowe), realna granulacja
      day/month/hour (raport „od 15:00"), brak `float(None)`; narzędzia czytają WYŁĄCZNIE `analytics.*`
      przez widoki-bramki, na sesji roli `assistant_ro` (statement_timeout 10 s) - decyzja #9 egzekwowana.
- [x] **Rekomendacje (#11)**: walidacja anty-halucynacyjna `supporting_metrics`, pętla feedbacku w promcie,
      stabilny dedupe (+ częściowy UNIQUE), brak sprzecznych rad przy ROAS<1.
- [x] **CSV/eksport**: `_num` parsuje polskie separatory tysięcy; eksport zawiera zamówienia anulowane (spójność z UI).
- [x] **Bezpieczeństwo/DB**: rate-limit logowania po (IP+login) z resetem i limitem; atomowa numeracja zamówień
      (`ops.order_no_seq`); CHECK na `vat_rate`/`unit_price_gross`; trigger sum przelicza stare i nowe zamówienie;
      funkcje NIP bez ucinania do 10 cyfr (parytet z Pythonem); strefa sesji Europe/Warsaw (#17).

Migracja `0006_poprawki_audytu`; 96 testów jednostkowych; zweryfikowane na żywej bazie (VAT, atrybucja,
metryki, wszystkie 9 narzędzi AI na roli read-only, eksport, endpointy HTTP).

## Etap 7 - domknięcie zakresu ✅

Cztery brakujące funkcje z pełnej listy wymagań (migracja `0007_domkniecie_zakresu` + dane demo):

- [x] **Czas kontakt → sprzedaż** (lead-time): kolumna `orders.first_contact_at` (dla maili = najwcześniejszy
      kontakt nadawcy), `lead_time_days` w `v_orders_all`, średnia w KPI dashboardu i profilu firmy, w narzędziach AI.
- [x] **Ranking formatów reklamowych**: widok `v_ad_format_stats` (Meta `creative_type` + Google `campaign_type`
      + organiczne `post_type`) - CTR dla płatnych, zaangażowanie/wyświetlenie dla organicznych; endpoint `/marketing/formats`,
      narzędzie `get_ad_formats`, sekcja UI. Zasila podpowiedzi formatów postów.
- [x] **Zestawienie tygodniowe AI**: serwis `weekly_summary` (WoW, top produkt/kanał/format; baseline bez klucza,
      Opus 4.8 z kluczem), tabela `core.weekly_summaries`, job poniedziałkowy 05:30, endpointy `/weekly` + `/weekly/generate`,
      narzędzie `get_weekly_summary`, sekcja na dashboardzie.
- [x] **Zaangażowanie organiczne + trendy produktów z maili**: `v_organic_engagement` (wyświetlenia/lajki/komentarze/
      udostępnienia wg typu posta) i `v_email_product_trends` (wzmianki produktów w szkicach w czasie); endpointy
      `/marketing/organic`, `/marketing/email-trends`; narzędzia AI; sekcje UI.

Narzędzia asystenta: 9 → **13**. Wszystkie nowe widoki są bramkami w `analytics.*` (rola `assistant_ro` bez dostępu do `core.*`).

**Poza repo (wymaga zewnętrznych integracji):** sam formularz kontaktowy na witrynie właściciela; wiadomości/DM
organiczne (Meta Messaging API); wychodzące powiadomienia e-mail (SMTP).

## Etap 8 - raporty PDF, KPI wydatków, responsywność ✅

- [x] **8. kafelek KPI**: „Wydatki reklamowe" (suma spend Meta+Google) na dashboardzie.
- [x] **Raporty PDF**: server-side `reportlab` (pure-Python, Windows-friendly, polska czcionka Arial/DejaVu),
      ładny layout (nagłówek marki, karty KPI, tabele kanałów/formatów/produktów, lejek, zestawienie tygodniowe);
      endpoint `/api/reports/pdf` (podgląd inline + `?download=1`); widok „Raporty" z podglądem w `<iframe>` na desktopie
      i CTA pobierz/otwórz na telefonie.
- [x] **Responsywność (PC + telefon)**: sidebar jako szuflada z hamburgerem na telefonie (statyczny 248px na desktopie),
      czat pełnoekranowy na telefonie (dokowany 420px na desktopie), Skrzynka (master-detail) stackuje się do jednej kolumny,
      drawer zamówienia `max-w-full`, tabele przewijane w kontenerze - **zero poziomego scrolla strony** na 375px.

Zweryfikowane w przeglądarce na 1280px i 375px (brak poziomego scrolla, drawer/overlay/nawigacja poprawne),
PDF generuje się (79 KB, nagłówek %PDF, polskie znaki), 96 testów przechodzi.

## Etap 9 - usprawnienia z przeglądu (bezpieczeństwo, analityka, UX, ops) ✅

Przegląd 6-wymiarowy wskazał 47 usprawnień - wdrożono wszystkie wartościowe (migracja `0008`):

- [x] **Bezpieczeństwo/RODO**: nocny job retencji surowych maili (`RAW_EMAIL_RETENTION_DAYS`) + czyszczenie
      wygasłych sesji; tokeny sesji trzymane jako HMAC (SESSION_SECRET realnie używany); fail-fast startu prod
      przy domyślnych sekretach; anty-formuła w eksporcie CSV; limity rozmiaru importu; globalny handler wyjątków + logowanie.
- [x] **Analityka**: koszt produktu (COGS) + marża brutto (KPI, raport PDF); segmentacja B2B/B2C w raporcie;
      lista firm „zagrożonych odejściem" (churn) + dni od ostatniego zakupu; **alerty progowe** (ROAS<1, CAC>LTV,
      spadek WoW, dużo nieprzypisanych, sprzedaż poniżej kosztu).
- [x] **UX**: globalny wybór zakresu dat (Dashboard/Marketing/Raporty), delty trendu na kartach KPI, wyszukiwarka
      + filtr statusu + paginacja (Zamówienia), **edycja/anulowanie zamówień** (PATCH + potwierdzenie), toasty,
      wykres porównania kanałów, dostępność (Esc/role w modalach), ErrorBoundary.
- [x] **Ops/DX**: worker w `run.bat` (+`run-worker.bat`), healthchecki i rotacja logów w compose, `.dockerignore`,
      CSP+Permissions-Policy w Caddy, harmonogram backupu + restore z załącznikami, ruff/ESLint, **GitHub Actions CI**,
      **code-splitting** frontendu (bundle 682 KB → wejście 45 KB + recharts/vendor lazy), testy API (FastAPI TestClient)
      i frontendu (Vitest).

Migracje 0001-0008; **102 testy backendu + 5 testów frontendu**; build produkcyjny czysty (code-split); zweryfikowane
w przeglądarce (PC + telefon) - zakres dat, alerty, delty, marża, filtry/anulowanie, churn, wykres kanałów.

**Świadomie odłożone** (przedwczesne przy tej skali lub wymagają zewnętrznych danych): atrybucja `heurystyka_ga4`
(wymaga żywych sesji GA4 powiązanych z zamówieniami), materializacja widoków, serwerowa paginacja firm, kohorty retencji.

## Weryfikacja end-to-end (docelowo)

- Test parsera na próbce prawdziwych maili (skrzynka testowa)
- Sync GA4/Meta/Google na żywych kontach
- Pytania kontrolne do asystenta z znanymi odpowiedziami („ile zamówień w tym tygodniu?", „raport
  od czwartku od 15:00", „które posty najlepiej konwertowały?")
