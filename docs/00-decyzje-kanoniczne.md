# Decyzje kanoniczne

> Dokument z etapu projektowania, zostawiony jako zapis decyzji i ich uzasadnień. Część pozycji
> nie została wdrożona albo zmieniła się w trakcie (np. Batches API, adaptive thinking, tytuły
> rozmów generowane przez AI, tryb ciemny poza zakresem). Stan faktyczny opisuje `README.md`.

Ten dokument ma **pierwszeństwo** nad wszystkimi plikami w `zrodla/`. Rozstrzyga sprzeczności
i braki wykryte przez agenta-krytyka (patrz `zrodla/recenzja-krytyka.md`). Każda decyzja jest
wiążąca dla implementacji.

## Kontekst i skala

- System **wewnętrzny jednej firmy**, **1 użytkownik** (właściciel), **≤100 zamówień/miesiąc**.
- Sprzedaż B2B i B2C. Strona firmowa to **wizytówka z formularzem** (bez sklepu online).
- Zamówienia: mailem (skrzynka IMAP na własnej domenie; maile mieszane - formularz + wolny tekst)
  oraz telefonicznie/stacjonarnie (wpis ręczny).
- Kanały marketingowe: Meta Ads, Facebook/Instagram organicznie, Google Ads, Google Analytics 4.
- Hosting: tani VPS + Docker Compose. Język UI: polski.
- Właściciel **ma kontrolę nad stroną www** (można dodać GA4 i ukryte pola UTM).

## Stack

| Warstwa | Wybór |
|---|---|
| Backend | Python 3.12 + FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2 |
| Baza | PostgreSQL 16 (rozszerzenia `citext`, `pg_trgm`) |
| Frontend | React 18 + Vite + TypeScript + Tailwind + shadcn/ui + Recharts (SPA) |
| Zadania cykliczne | APScheduler w osobnym procesie workera (ten sam obraz Dockera, inne CMD) |
| Reverse proxy | Caddy 2 (HTTPS + serwowanie statycznego frontendu) |
| AI | SDK `anthropic` (szczegóły niżej) |

### Modele Claude (zweryfikowane cenniki)

| Zastosowanie | Model | Cena wej./wyj. za 1M tok. |
|---|---|---|
| Czat asystenta-analityka | `claude-opus-4-8` | 5 / 25 USD |
| Parsowanie maili (structured outputs) | `claude-haiku-4-5` | 1 / 5 USD |
| Eskalacja parsowania (`confidence < 0.5`) | `claude-opus-4-8` | 5 / 25 USD |
| Rekomendacje nocne (Batches API, -50%) | `claude-opus-4-8` | 2,5 / 12,5 USD efektywnie |
| Tytuły rozmów | `claude-haiku-4-5` | 1 / 5 USD |

Czat: adaptive thinking, prompt caching (stały prefiks: narzędzia → system prompt → historia),
streaming SSE. Szacunek kosztu całości: **~130-210 zł/mies.** (VPS Hetzner CX22 ~4,6 € + API).

## Rozstrzygnięcia (numeracja zgodna z planem)

### 1. Układ bazy - schematy Postgres (nie prefiksy tabel)

| Schemat | Zawartość |
|---|---|
| `core` | zamówienia, pozycje, firmy, kontakty, produkty, VAT, słownik kanałów, szkice zamówień |
| `mail` | log maili IMAP + kursor UID |
| `channel_meta` / `channel_google` / `channel_ga4` / `channel_organic` | surowe dane dzienne per kanał |
| `analytics` | **wyłącznie widoki `v_*`** (jedyne źródło odczytu dla UI i asystenta) |
| `chat` | rozmowy, wiadomości, log wywołań narzędzi |
| `ops` | `sync_runs`, `sync_commands`, `sessions`, `users` |

### 2. Zamówienia mailowe - obowiązkowa ręczna weryfikacja

Każdy sparsowany mail → **szkic** w `core.orders_draft` (+ `order_draft_items`, `product_aliases`) →
człowiek zatwierdza w widoku „Skrzynka" → dopiero wtedy powstaje `core.orders`.
**Szkice nigdy nie wchodzą do metryk.** Wersja „auto-tworzenie zamówień" z `zrodla/model-danych.md` §3
- odrzucona.

### 3. Tabela maili - wg `zrodla/pipeline-maili.md`

`mail.emails`: `UNIQUE(uidvalidity, uid)` + `UNIQUE(message_id_hash)` (SHA-256; fallback z
`(from, date, sha256(body))` dla maili bez Message-ID). Tabela `mail.imap_state` (kursor `last_seen_uid`).
Statusy: `odebrany → sklasyfikowany → sparsowany → zamowienie_utworzone` |
`odrzucony_automatycznie` | `blad_parsowania` | `odpowiedz_w_watku` | `duplikat`.
Polling IMAP **co 5 min**, folder `Przetworzone`, **zero EXPUNGE** (nigdy nie kasujemy maili).
Wersja `mail.emails` z `zrodla/model-danych.md` §3 (bez `uidvalidity`/`imap_state`) - odrzucona.

### 4. Jeden słownik kanałów + osobny enum źródeł

`core.channels.code` ∈ **`meta_ads`, `google_ads`, `fb_ig_organic`, `seo_direct`, `polecenie`, `inny`**.
Źródło zamówienia to osobny enum `core.order_source` ∈ **`email_formularz`, `email_wolny`, `telefon`,
`stacjonarnie`**. Narzędzia asystenta, widoki, UI i formularze używają wyłącznie tych kodów.
Rozbieżne słowniki z `zrodla/model-danych.md` i `zrodla/asystent-ai.md` - ujednolicone do powyższego.

### 5. Statusy zamówień - 4 wartości

`core.order_status` ∈ **`nowe`, `potwierdzone`, `zrealizowane`, `anulowane`**. „Szkic" to osobna tabela
(`orders_draft`), nie status zamówienia. Wartość `w_realizacji` z `zrodla/model-danych.md` - usunięta.

### 6. Kanoniczne definicje metryk

Jedno źródło prawdy: **`06-metryki.md`** - te same definicje w system promptcie asystenta i tooltipach UI.
- **LTV firmy** = suma `total_net` zamówień o statusie `potwierdzone` LUB `zrealizowane`, przypisanych do NIP.
- **Częstotliwość** = średni odstęp w dniach między zamówieniami (tylko firmy z ≥2 zamówieniami).
- **CAC kanału** = wydatki kanału / liczba nowych klientów first-touch z tego kanału; klienci bez
  atrybucji raportowani **osobno** jako „nieprzypisani".
- **Netto** = liczone per pozycja z **zamrożoną** stawką VAT (kolumny generowane), domyślnie 23%, per produkt.

### 7. Granulacja godzinowa tylko dla zamówień

`core.orders.ordered_at` to `timestamptz` - obsługuje „raport od czwartku od 15:00". Dane marketingowe
są **dzienne**. Narzędzie `query_metrics` z `granularity: "hour"` działa tylko dla metryk zamówieniowych;
dla metryk marketingowych backend zwraca `tool_result` z `is_error: true` i komunikatem - model
przechodzi na granulację dzienną. Sprzeczność z `zrodla/asystent-ai.md` (godzinowa dla sesji/kliknięć)
- rozstrzygnięta na korzyść tej reguły.

### 8. Meta organiczne na nowym modelu metryk

Kolumna **`views`** (nie `impressions` - deprecjacja 15.11.2025 dla stron, 15.06.2026 dla v25.0),
model **Page Viewer**. Archiwizacja do własnej bazy **od pierwszego dnia** (retencja API ~2 lata,
okna zapytań maks. 90 dni). `zrodla/model-danych.md` §4 (`post_stats_daily.impressions`) - poprawiony na `views`.

### 9. Zero surowego SQL od modelu

Model **nie widzi SQL**. Każde narzędzie mapuje się na funkcję serwisową z zapytaniem parametryzowanym.
Rola DB **`assistant_ro`** z `SELECT` wyłącznie na `analytics.*`; `statement_timeout = 10s`;
zakres dat ≤ **400 dni**; limit **10 iteracji** tool-use na turę. Narzędzie `run_readonly_sql`
z `zrodla/architektura.md` §5 - odrzucone.

### 10. Komplet narzędzi asystenta (nazwy ostateczne)

`query_metrics`, `get_orders`, `get_company_profile` (przyjmuje `nip` LUB `company_id`), `get_funnel`,
`get_campaign_stats`, `get_top_products`, `compare_periods`, `get_recommendations`,
**`get_pending_drafts`** (dla chipa „streść maile do weryfikacji"). Wszystkie `strict: true`.
Frontend przekazuje kontekst aktywnego widoku (nazwa + opcjonalny `company_id`) w bloku
`<kontekst_widoku>` na początku wiadomości użytkownika (obok `<kontekst_czasowy>`).
Rozbieżne nazwy z `zrodla/architektura.md` (`query_orders`, `get_metrics`…) - odrzucone na rzecz powyższych.

### 11. Rekomendacje - codziennie 05:00

Po nocnych syncach (03:00-04:30). Agregaty liczone **SQL-em** (nie modelem); generowanie przez
Opus 4.8 **Batches API**; walidacja anty-halucynacyjna: każda wartość w `supporting_metrics` musi
występować w danych wejściowych. Tabela `recommendations` **z kolumną `feedback`** (`trafna`/`nietrafna`/
`null`) - feedback trafia do promptu następnych generacji. Przycisk „Generuj teraz" w UI (przez `sync_commands`).
Rozbieżne harmonogramy (03:30 / 08:00 / codziennie) - ujednolicone do 05:00.

### 12. Sekrety wyłącznie w `.env`

Plik `deploy/.env` (chmod 600), poza repo. Widok „Ustawienia" pokazuje **statusy** integracji,
przycisk „Testuj połączenie" i instrukcje konfiguracji - **bez edycji sekretów z panelu**.
Edycja kluczy z UI (`zrodla/ui-ux.md` §11) - odrzucona.

### 13. Kanał sterowania workerem

Tabela `ops.sync_commands` (`type` ∈ `sync_now` / `generate_recs` / `test_imap`, `payload jsonb`,
`status`, `created_at`, `processed_at`). API wstawia polecenie, worker sprawdza co **10 s**.
Obsługuje przyciski „Synchronizuj teraz", „Generuj teraz", „Testuj połączenie IMAP".

### 14. Import CSV - pełnoprawna funkcja

Endpoint `POST /api/import/marketing-csv` + UI w widoku „Marketing". Kolumna `source` (`api`/`csv`)
we wszystkich tabelach kanałów. Fallback dla Google Ads/Meta na czas konfiguracji dostępów oraz
backfill historii sprzed uruchomienia integracji.

### 15. Atrybucja - kaskada

Zapisywana w `core.orders.attribution_method` ∈ `utm_formularz` / `heurystyka_ga4` / `reczna` / `brak`:
1. **`utm_formularz`** - ukryte pola UTM/`gclid`/`fbclid` w formularzu → treść maila → parser.
   **Pola UTM dodane do schematu ekstrakcji Claude i do parsera regułowego** (poprawka z recenzji -
   `zrodla/pipeline-maili.md` ich nie miał).
2. **`heurystyka_ga4`** - kanał o największym udziale w płatnych sesjach GA4 w oknie 7 dni przed zamówieniem.
3. **`reczna`** - pole „skąd Pan/Pani o nas wie?" przy wpisie ręcznym.
4. **`brak`** - zamówienie wchodzi do przychodu, ale nie do CAC/ROAS.

Wymaga zmian na stronie www (użytkownik ma kontrolę): skrypt GA4, key event „wysłanie formularza",
ukryte pola UTM w formularzu. Rozpisane w `05-integracje.md`.

### 16. Lejek zawiera wiersz „nieprzypisane"

Widok `analytics.v_funnel_daily` uwzględnia zamówienia kanałów bez danych marketingowych (`seo_direct`,
`brak`) tak, by **suma zamówień w lejku = suma zamówień w systemie**. `zrodla/model-danych.md` §7
(widok startujący od danych marketingowych) - poprawiony.

### 17. Strefy czasowe

Wymóg konfiguracyjny: konto reklamowe Meta, konto Google Ads i usługa GA4 ustawione na **Europe/Warsaw**.
Checklist w `05-integracje.md`. Bez tego joiny po `date` między kanałami a zamówieniami byłyby przesunięte.

### 18. `core.contacts.email` bez UNIQUE

Wspólny adres `biuro@firma.example` używany przez wielu pracowników oraz jedna osoba obsługująca dwie firmy
(dwa NIP-y) są legalne w polskim B2B. Dopasowanie kontaktu: para (email, firma), zawsze jako **sugestia**,
nigdy automat. `zrodla/model-danych.md` §2.2 (`UNIQUE(email)`) - poprawiony.

### 18a. Tożsamość klienta w metrykach (mianownik CAC)

Decyzja #18 zabrania **scalania rekordów** kontaktów automatem - i to zostaje bez zmian:
`create_order` nadal zapisuje nowy `core.contacts` dla każdego zamówienia, a dopasowanie kontaktu
w panelu pozostaje sugestią.

Rozstrzygnięcie dotyczy czegoś innego: **jak liczymy „nowego klienta" w metrykach**. Dotąd
tożsamością był rekord kontaktu, więc powracający klient B2C (Jan Kowalski zamawia telefonicznie
trzeci raz) liczył się jako trzech różnych nowych klientów. Mianownik CAC był zawyżony, a CAC
zaniżony - reklama wyglądała na tańszą, niż jest.

Kanoniczny klucz tożsamości (`analytics.v_orders_all.customer_key`), pierwsza pasująca reguła:

1. `company_id` po scaleniu duplikatów - B2B rozstrzyga NIP,
2. `'k'` + id reprezentanta **klasy kontaktów** (`analytics.v_tozsamosc_kontaktu`),
3. `'o'` + id zamówienia - zamówienie anonimowe, bez firmy i bez kontaktu (nie wiemy, czy to
   ta sama osoba, więc liczymy osobno).

**Klasa kontaktów:** dwa rekordy `core.contacts` to ta sama osoba, gdy dzielą znormalizowany
e-mail (`lower(btrim(...))`) **lub** telefon sprowadzony do 9 cyfr (bez spacji, `+48`, myślników).
Reprezentantem klasy jest najmniejsze `id` w niej. Numery krótsze niż 9 cyfr są ignorowane -
inaczej śmieciowy wpis w rodzaju `0` skleiłby wszystkich, którzy go mają.

Klucz **nie zawiera** e-maila ani telefonu, nawet w postaci skrótu: schemat `analytics` czyta rola
`assistant_ro`, a przez nią model AI (decyzja #9). Samo `id` kontaktu i tak jest już w widoku.

**Granica metody (świadoma):** klasy liczymy dwiema rundami propagacji etykiet, nie pełnym
domknięciem przechodnim. Pokrywa to realny przypadek („raz formularz z mailem i telefonem,
raz sam telefon") oraz łańcuch o dwóch ogniwach. Ta sama osoba w czterech rekordach, wpisywana
naprzemiennie raz mailem, raz telefonem, i nigdy dwa razy tak samo - rozpadnie się na dwie klasy.
Dokładna rekurencja jest odrzucona świadomie: przy jednym numerze współdzielonym przez tysiące
kontaktów zbiór par rośnie kwadratowo i pytanie o CAC przestaje wracać (zmierzone: 22 s już przy
10 tys. kontaktów, wersja liniowa - 32 ms). Gdyby skala urosła, właściwą drogą jest osobna tabela
tożsamości przeliczana przez workera (union-find), a nie cięższy widok.

**Drugi świadomy kompromis:** wspólny adres `biuro@firma.example` u klienta B2C bez NIP-u sklei kilka
osób w jednego klienta. Przy tej skali (≤100 zamówień/mies.) to błąd rzadszy i mniejszy niż
liczenie każdego powrotu jako nowej akwizycji. W B2B problem nie występuje, bo pierwsza reguła
to firma.

Klucz jest **jeden** dla wszystkich konsumentów: `analytics.v_cac_monthly`, `app/services/marketing.py`
i narzędzia asystenta (`app/ai/tools.py`) czytają tę samą kolumnę widoku.

### 19. Backfill

Przy pierwszym uruchomieniu pipeline maili importuje ostatnie **90 dni** skrzynki (konfigurowalne
przez `IMAP_BACKFILL_DAYS`). Historyczne zamówienia sprzed systemu - przez import CSV zamówień (Etap 5).

### 20. RODO

Treści maili (imiona, telefony, adresy, NIP-y) wysyłane do Anthropic API. Szczegóły, DPA, retencja
i rejestr czynności - w `07-rodo.md`. Do potwierdzenia z księgową/prawnikiem właściciela przed produkcją.

### 21. Poza zakresem MVP (świadomie wycięte)

Dark mode, TOTP (drugi składnik), parsowanie załączników PDF, mini-wykresy renderowane w czacie
(czat renderuje markdown + tabele; wykresy w v1.1), LTV predykcyjne, wybór/eskalacja modelu per-request z UI.

### 22. Obserwacja konkurencji - trzy grupy i granice tego, co widać

Konkurenci są przypisani do jednej z **trzech grup**: `europejska` (duzi gracze zagraniczni),
`polska` (krajowi), `lokalna` (z okolicy). Grupa jest cechą profilu, nie kategorią wyliczaną -
o przypisaniu decyduje właściciel, bo „lokalny" znaczy co innego dla każdej branży.

**Legalne źródła danych - i tylko one:**

| Źródło | Co daje | Uwaga |
|---|---|---|
| Instagram Business Discovery (Graph API) | obserwujący, liczba postów, a per post: typ, opis, lajki, komentarze, data, link | tylko publiczne konta Business/Creator; jedzie na własnym `META_ACCESS_TOKEN` + `META_IG_USER_ID` |
| Obserwacja ręczna | cokolwiek właściciel sam zobaczy i wpisze | zawsze dostępna, `source='reczne'` |
| Ad Library | jakie reklamy konkurent puszcza | tylko link do wyszukiwania + notatka; API za weryfikacją tożsamości |

**Scraping jest zakazany.** Łamie ToS Meta, a leciałby na tym samym tokenie, na którym stoją
własne reklamy i pipeline maili - blokada konta kosztowałaby więcej niż wartość tych danych.
Nie wolno tego obchodzić „przez przeglądarkę", nagłówki User-Agent ani zewnętrzne pośredniki.

**Asymetria danych (najważniejsza reguła tej sekcji).** O sobie znamy zasięg, wyświetlenia
i wydatki. O konkurencji widać **wyłącznie lajki i komentarze**. Dlatego:

1. Raport i panel **zawsze** pokazują, czego nie widać - sekcja „co widać / czego nie widać"
   jest obowiązkowym elementem każdej grupy, nie ozdobnikiem.
2. **Nigdy** nie zestawiamy własnego zasięgu z cudzym zaangażowaniem w jednym wskaźniku.
   Porównywalne są tylko: rozkład formatów postów, rytm publikacji i zaangażowanie liczone
   tą samą metodą po obu stronach.
3. Nie liczymy konkurentom „ROAS", „CAC" ani niczego z wydatkami - nie znamy mianownika.

**Zaangażowanie grupy liczymy MEDIANĄ, nie średnią.** Jeden viral w grupie trzech firm
przesuwa średnią o rząd wielkości i sugeruje trend, którego nie ma. Mediana pokazuje typowy
post. Średnia może być raportowana obok, nigdy zamiast.

**Minimalna próbka:** wskaźniki grupy pokazujemy dopiero od `MIN_POSTOW_GRUPY` postów
(patrz `app/services/competitors.py`). Poniżej tego progu raport pisze wprost „za mało danych",
zamiast podawać liczbę, która wygląda na pomiar, a jest przypadkiem.

**RODO:** profile firmowe nie są danymi osobowymi, ale konto jednoosobowego twórcy bywa nimi
w praktyce. Zapisujemy wyłącznie dane publiczne i wyłącznie o **kontach firmowych**; nie
budujemy profili osób, nie zapisujemy komentujących ani obserwujących.
