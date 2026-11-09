# Model danych PostgreSQL i formuły metryk - panel analityczno-sprzedażowy

## 1. Architektura schematów (separacja kanałów)

Jedna baza (`polsales`), separacja przez schematy Postgres. Surowe dane każdego kanału żyją we własnym schemacie i nigdy nie są modyfikowane przez logikę biznesową - tylko dopisywane przez synchronizatory (APScheduler). Warstwa wspólna (`core`) i warstwa odczytu (`analytics` - same widoki) są jedynymi miejscami, z których czyta UI i asystent AI.

| Schemat | Zawartość | Zapis |
|---|---|---|
| `channel_meta` | surowe dzienne dane Meta Ads (kampanie, zestawy, reklamy) | tylko sync Meta Marketing API |
| `channel_google` | surowe dzienne dane Google Ads | tylko sync Google Ads API |
| `channel_ga4` | surowe dzienne dane ruchu z GA4 (Data API) | tylko sync GA4 |
| `channel_organic` | posty FB/IG i ich dzienne statystyki (Graph API) | tylko sync organic |
| `mail` | log przetworzonych maili IMAP + wyniki parsowania | tylko pipeline mailowy |
| `core` | zamówienia, pozycje, produkty, firmy, osoby, słownik kanałów, mapowanie źródeł, log scaleń | backend aplikacji |
| `analytics` | wyłącznie widoki (`v_*`) agregujące ponad schematami | brak (read-only) |

Rola aplikacyjna asystenta AI (`app_ai_readonly`) dostaje `GRANT USAGE` + `SELECT` wyłącznie na `analytics` i `core` - tool use Claude'a nigdy nie pisze do bazy bezpośrednio, mutacje idą przez endpointy FastAPI.

Typy wspólne (w schemacie `core`):

```sql
CREATE TYPE core.order_source   AS ENUM ('email_formularz','email_wolny','telefon','stacjonarnie','inne');
CREATE TYPE core.order_status   AS ENUM ('nowe','potwierdzone','w_realizacji','zrealizowane','anulowane');
CREATE TYPE core.customer_type  AS ENUM ('b2b','b2c');
CREATE TYPE core.attribution_method AS ENUM ('utm_formularz','heurystyka_ga4','reczna','brak');
CREATE TYPE core.mail_status    AS ENUM ('nowy','sparsowany','zamowienie_utworzone','odrzucony','blad');
```

## 2. Schemat `core` - DDL

### 2.1. Słownik kanałów i mapowanie źródeł

```sql
CREATE TABLE core.channels (
    id          smallint PRIMARY KEY,
    code        text NOT NULL UNIQUE,        -- 'meta_ads','google_ads','organic_fb_ig','direct_seo','inny'
    name_pl     text NOT NULL,
    is_paid     boolean NOT NULL DEFAULT false
);

-- Mapowanie source/medium z GA4 na wewnętrzny kanał (klucz do spójnego lejka i atrybucji)
CREATE TABLE core.channel_mapping (
    id          serial PRIMARY KEY,
    ga4_source  text NOT NULL,               -- np. 'facebook', 'google'
    ga4_medium  text NOT NULL,               -- np. 'cpc', 'paid', 'organic', '(none)'
    channel_id  smallint NOT NULL REFERENCES core.channels(id),
    UNIQUE (ga4_source, ga4_medium)
);
```

### 2.2. Firmy (klucz biznesowy: znormalizowany NIP), osoby, klienci B2C

```sql
CREATE TABLE core.companies (
    id              bigserial PRIMARY KEY,
    nip             char(10) NOT NULL UNIQUE,          -- zawsze znormalizowany, 10 cyfr
    name            text NOT NULL,
    email_domain    text,                              -- pomocniczo do dopinania osób po domenie maila
    first_seen_at   timestamptz NOT NULL DEFAULT now(),
    acq_channel_id  smallint REFERENCES core.channels(id),  -- kanał pozyskania (z 1. zamówienia)
    notes           text,
    merged_into_id  bigint REFERENCES core.companies(id),   -- NULL = profil aktywny
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT nip_digits CHECK (nip ~ '^[0-9]{10}$')
);

-- Osoby: kontakty B2B (company_id NOT NULL) oraz klienci B2C (company_id NULL)
CREATE TABLE core.contacts (
    id           bigserial PRIMARY KEY,
    company_id   bigint REFERENCES core.companies(id) ON DELETE SET NULL,
    full_name    text,
    email        citext,                                -- rozszerzenie citext; klucz dopasowania maili
    phone        text,
    customer_type core.customer_type NOT NULL DEFAULT 'b2c',
    acq_channel_id smallint REFERENCES core.channels(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (email)
);
```

Uwaga projektowa: jedna encja `contacts` obsługuje oba przypadki - osoba z firmą to kontakt B2B, osoba bez firmy to klient B2C. Gdy do maila B2C dojdzie później NIP, wystarczy uzupełnić `company_id` i `customer_type`, historia zamówień zostaje.

### 2.3. Produkty i VAT

```sql
CREATE TABLE core.vat_rates (
    id      smallserial PRIMARY KEY,
    rate    numeric(5,2) NOT NULL UNIQUE,   -- 23.00, 8.00, 5.00, 0.00
    is_default boolean NOT NULL DEFAULT false
);
INSERT INTO core.vat_rates(rate, is_default) VALUES (23.00, true),(8.00,false),(5.00,false),(0.00,false);

CREATE TABLE core.products (
    id           bigserial PRIMARY KEY,
    sku          text UNIQUE,
    name         text NOT NULL,
    vat_rate_id  smallint NOT NULL REFERENCES core.vat_rates(id),  -- stawka per produkt, domyślnie 23%
    default_price_gross numeric(12,2),
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now()
);
```

### 2.4. Zamówienia i pozycje

```sql
CREATE TABLE core.orders (
    id              bigserial PRIMARY KEY,
    order_no        text NOT NULL UNIQUE,          -- np. 'ZAM-2026-000123', generowany w aplikacji
    company_id      bigint REFERENCES core.companies(id),   -- NULL dla B2C
    contact_id      bigint REFERENCES core.contacts(id),
    source          core.order_source NOT NULL,
    status          core.order_status NOT NULL DEFAULT 'nowe',
    ordered_at      timestamptz NOT NULL,          -- moment złożenia (z maila lub wpisu)
    -- kwoty: brutto wpisywane/parsowane; netto i VAT przeliczane z pozycji triggerem
    total_gross     numeric(12,2) NOT NULL DEFAULT 0,
    total_net       numeric(12,2) NOT NULL DEFAULT 0,
    total_vat       numeric(12,2) NOT NULL DEFAULT 0,
    currency        char(3) NOT NULL DEFAULT 'PLN',
    -- atrybucja marketingowa
    attribution_channel_id smallint REFERENCES core.channels(id),
    attribution_method     core.attribution_method NOT NULL DEFAULT 'brak',
    utm_source      text, utm_medium text, utm_campaign text,   -- surowe UTM-y jeśli dotarły
    source_email_id bigint,                        -- FK dopięty niżej po utworzeniu mail.emails
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT totals_consistent CHECK (total_gross = total_net + total_vat)
);

CREATE TABLE core.order_items (
    id           bigserial PRIMARY KEY,
    order_id     bigint NOT NULL REFERENCES core.orders(id) ON DELETE CASCADE,
    product_id   bigint REFERENCES core.products(id),
    description  text,                              -- gdy pozycja spoza katalogu (mail wolnym tekstem)
    quantity     numeric(10,3) NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price_gross numeric(12,2) NOT NULL,
    vat_rate     numeric(5,2) NOT NULL,             -- ZAMROŻONA stawka z chwili sprzedaży (kopiowana z produktu)
    line_gross   numeric(12,2) GENERATED ALWAYS AS (round(quantity * unit_price_gross, 2)) STORED,
    line_net     numeric(12,2) GENERATED ALWAYS AS (round(quantity * unit_price_gross / (1 + vat_rate/100), 2)) STORED,
    line_vat     numeric(12,2) GENERATED ALWAYS AS (round(quantity * unit_price_gross - quantity * unit_price_gross / (1 + vat_rate/100), 2)) STORED
);
```

Trigger `AFTER INSERT/UPDATE/DELETE ON core.order_items` sumuje `line_*` do `orders.total_*`. Zamrożenie `vat_rate` w pozycji gwarantuje, że zmiana stawki produktu nie przepisze historii.

### 2.5. Log scaleń firm

```sql
CREATE TABLE core.company_merge_log (
    id            bigserial PRIMARY KEY,
    src_company_id bigint NOT NULL REFERENCES core.companies(id),
    dst_company_id bigint NOT NULL REFERENCES core.companies(id),
    merged_at     timestamptz NOT NULL DEFAULT now(),
    merged_by     text NOT NULL DEFAULT 'auto',   -- 'auto' | 'manual'
    details       jsonb                            -- co przeniesiono (liczby zamówień, kontaktów)
);
```

## 3. Schemat `mail` - log przetworzonych maili

```sql
CREATE TABLE mail.emails (
    id             bigserial PRIMARY KEY,
    message_id     text NOT NULL UNIQUE,        -- nagłówek Message-ID → idempotencja IMAP
    imap_uid       bigint,
    from_email     citext NOT NULL,
    from_name      text,
    subject        text,
    received_at    timestamptz NOT NULL,
    is_form_email  boolean NOT NULL DEFAULT false,  -- rozpoznany szablon formularza ze strony
    raw_body       text,                         -- pełna treść (do ponownego parsowania i podglądu)
    parsed_payload jsonb,                        -- wynik parsera: {nip, pozycje[], kwoty, utm...}
    parse_status   core.mail_status NOT NULL DEFAULT 'nowy',
    parse_error    text,
    order_id       bigint REFERENCES core.orders(id),
    processed_at   timestamptz
);

ALTER TABLE core.orders
    ADD CONSTRAINT fk_orders_source_email FOREIGN KEY (source_email_id) REFERENCES mail.emails(id);
```

Przepływ: sync IMAP wstawia (`ON CONFLICT (message_id) DO NOTHING`) → parser (regex dla maili formularzowych, Claude API dla wolnego tekstu) wypełnia `parsed_payload` → aplikacja tworzy zamówienie i spina `order_id`. Statusy `odrzucony`/`blad` lądują w skrzynce "do ręcznej weryfikacji" na dashboardzie.

## 4. Schematy kanałów - surowe dane dzienne

Wspólna zasada: klucz naturalny `(date, id_obiektu)` z `UNIQUE`, sync robi UPSERT (dane platform korygują się wstecznie do ~28 dni), kwoty wydatków w PLN `numeric(12,2)`.

```sql
-- META ADS
CREATE TABLE channel_meta.campaigns (
    campaign_id   text PRIMARY KEY,       -- ID z API Meta
    name          text NOT NULL,
    objective     text,
    status        text,
    synced_at     timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE channel_meta.ads_daily (
    date          date NOT NULL,
    campaign_id   text NOT NULL REFERENCES channel_meta.campaigns(campaign_id),
    adset_id      text,
    ad_id         text NOT NULL,
    ad_name       text,
    creative_type text,                   -- 'image','video','carousel','reels' → dla rekomendacji AI
    impressions   bigint NOT NULL DEFAULT 0,
    reach         bigint,
    clicks        bigint NOT NULL DEFAULT 0,   -- link clicks
    spend         numeric(12,2) NOT NULL DEFAULT 0,
    conversions   int DEFAULT 0,               -- leady z pixela, jeśli skonfigurowany
    synced_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (date, ad_id)
);

-- GOOGLE ADS (struktura bliźniacza)
CREATE TABLE channel_google.campaigns (
    campaign_id   text PRIMARY KEY,
    name          text NOT NULL,
    campaign_type text,                   -- 'SEARCH','PMAX','DISPLAY'
    status        text,
    synced_at     timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE channel_google.ads_daily (
    date          date NOT NULL,
    campaign_id   text NOT NULL REFERENCES channel_google.campaigns(campaign_id),
    ad_group_id   text,
    impressions   bigint NOT NULL DEFAULT 0,
    clicks        bigint NOT NULL DEFAULT 0,
    spend         numeric(12,2) NOT NULL DEFAULT 0,
    conversions   numeric(10,2) DEFAULT 0,
    synced_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (date, campaign_id, ad_group_id)
);

-- GA4
CREATE TABLE channel_ga4.traffic_daily (
    date            date NOT NULL,
    source          text NOT NULL,
    medium          text NOT NULL,
    campaign        text NOT NULL DEFAULT '(not set)',
    sessions        int NOT NULL DEFAULT 0,
    engaged_sessions int NOT NULL DEFAULT 0,
    total_users     int NOT NULL DEFAULT 0,
    new_users       int NOT NULL DEFAULT 0,
    key_events      int NOT NULL DEFAULT 0,      -- np. wysłanie formularza jako key event
    synced_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (date, source, medium, campaign)
);

-- ORGANIC FB/IG
CREATE TABLE channel_organic.posts (
    post_id       text PRIMARY KEY,        -- ID z Graph API
    platform      text NOT NULL CHECK (platform IN ('facebook','instagram')),
    post_type     text,                    -- 'photo','video','reel','carousel','text','story'
    message_excerpt text,                  -- pierwsze ~300 znaków treści → dla rekomendacji AI
    permalink     text,
    published_at  timestamptz NOT NULL,
    synced_at     timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE channel_organic.post_stats_daily (
    date          date NOT NULL,
    post_id       text NOT NULL REFERENCES channel_organic.posts(post_id),
    impressions   bigint NOT NULL DEFAULT 0,
    reach         bigint NOT NULL DEFAULT 0,
    likes         int NOT NULL DEFAULT 0,
    comments      int NOT NULL DEFAULT 0,
    shares        int NOT NULL DEFAULT 0,
    saves         int NOT NULL DEFAULT 0,
    link_clicks   int NOT NULL DEFAULT 0,
    video_views   int DEFAULT 0,
    synced_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (date, post_id)
);
```

## 5. Logika NIP

### 5.1. Normalizacja i walidacja (funkcje w `core`)

```sql
CREATE OR REPLACE FUNCTION core.normalize_nip(raw text) RETURNS char(10)
LANGUAGE sql IMMUTABLE AS $$
    -- usuń wszystko poza cyframi, po uprzednim zdjęciu prefiksu PL/pl
    SELECT NULLIF(regexp_replace(regexp_replace(upper(coalesce(raw,'')), '^\s*PL', ''), '[^0-9]', '', 'g'), '')::char(10)
$$;

CREATE OR REPLACE FUNCTION core.is_valid_nip(nip char(10)) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    w int[] := ARRAY[6,5,7,2,3,4,5,6,7];   -- wagi NIP
    s int := 0; i int;
BEGIN
    IF nip IS NULL OR nip !~ '^[0-9]{10}$' THEN RETURN false; END IF;
    FOR i IN 1..9 LOOP
        s := s + w[i] * substr(nip, i, 1)::int;
    END LOOP;
    IF s % 11 = 10 THEN RETURN false; END IF;          -- cyfra kontrolna nie może wynosić 10
    RETURN (s % 11) = substr(nip, 10, 1)::int;
END $$;
```

Kolejność normalizacji: (1) trim, (2) zdjęcie prefiksu `PL`, (3) usunięcie kresek, spacji i wszystkich znaków niecyfrowych, (4) sprawdzenie długości = 10, (5) suma kontrolna. Odrzucone NIP-y nie blokują zamówienia - zamówienie zapisuje się jako B2C/`inne` z flagą do ręcznej weryfikacji (surowy NIP w `notes`/`parsed_payload`).

### 5.2. Automatyczne przypinanie zamówienia do firmy (pseudokod aplikacyjny)

```
przy tworzeniu zamówienia z NIP:
  nip_norm = normalize_nip(raw)
  jeśli !is_valid_nip(nip_norm): oznacz "NIP do weryfikacji", zapisz bez company_id, STOP
  firma = SELECT ... FROM core.companies WHERE nip = nip_norm
  jeśli firma istnieje:
      jeśli firma.merged_into_id NOT NULL: podążaj za łańcuchem do profilu aktywnego
      order.company_id = firma.id
  w przeciwnym razie:
      INSERT core.companies(nip, name, first_seen_at) ON CONFLICT (nip) DO NOTHING  -- wyścig dwóch maili
      firma = SELECT ponownie; order.company_id = firma.id
      firma.acq_channel_id = atrybucja tego (pierwszego) zamówienia
  kontakt: dopasuj po email (contacts.email); jeśli brak → INSERT contact z company_id = firma.id
  jeśli kontakt istniał jako B2C (company_id NULL), a teraz ma NIP → ustaw company_id, customer_type='b2b'
```

`UNIQUE` na `companies.nip` + `ON CONFLICT` daje twardą gwarancję jednego profilu na NIP nawet przy równoległym przetwarzaniu.

### 5.3. Scalanie duplikatów

Duplikaty firm powstają praktycznie tylko przy ręcznych wpisach bez NIP-u albo literówce (poprawny checksum-owo inny NIP). Procedura `core.merge_companies(src_id, dst_id)`:

```
1. UPDATE core.orders   SET company_id = dst WHERE company_id = src;
2. UPDATE core.contacts SET company_id = dst WHERE company_id = src;
3. UPDATE core.companies SET merged_into_id = dst WHERE id = src;   -- soft delete, NIP zostaje w historii
4. INSERT INTO core.company_merge_log(src, dst, merged_by, details);
5. przelicz dst.first_seen_at = LEAST(src, dst); acq_channel_id = kanał najwcześniejszego zamówienia po scaleniu.
```

Wpis `merged_into_id` zamiast DELETE: unikamy łamania FK, a stary NIP dalej trafia we właściwy profil (aplikacja podąża za łańcuchem scaleń). Kandydatów do ręcznego scalenia podpowiada widok porównujący `similarity(name)` (rozszerzenie `pg_trgm`) dla firm bez NIP.

## 6. Atrybucja zamówień do kanałów (dla CAC/ROAS/lejka)

Atrybucja przy zamówieniach mailowych jest z natury niepełna - model kaskadowy, od najpewniejszej metody do najsłabszej, zapisany w `orders.attribution_method`:

1. **`utm_formularz`** - formularz na stronie dostaje ukryte pola wypełniane JS-em z parametrów UTM/`gclid`/`fbclid` (oraz z `sessionStorage`, by przetrwały nawigację po stronie); wartości trafiają do treści maila formularzowego → parser wpisuje je w `orders.utm_*` → mapowanie `core.channel_mapping` daje kanał. Jedyna metoda deterministyczna; wymaganie wobec strony-wizytówki opisać w specyfikacji integracji.
2. **`heurystyka_ga4`** - dla maili bez UTM (wolny tekst) i pierwszego zamówienia klienta: przypisz kanał o największym udziale w **płatnych** sesjach GA4 w oknie 7 dni przed `ordered_at`; jeśli w tym oknie nie było ruchu płatnego → kanał `direct_seo`. Heurystyka probabilistyczna - oznaczana jako taka w raportach (asystent AI ma obowiązek komunikować niepewność).
3. **`reczna`** - właściciel przy wpisie telefonicznym/stacjonarnym pyta "skąd Pan/Pani o nas wie?" i wybiera kanał z listy; nadpisuje 1-2.
4. **`brak`** - zamówienie wchodzi do przychodu, ale nie do CAC/ROAS (osobna pozycja "nieprzypisane" w raportach, żeby mianowniki nie kłamały).

Do CAC klienta przypisuje się **kanał atrybucji jego pierwszego zamówienia** (first-touch na poziomie klienta), zapisany w `companies.acq_channel_id` / `contacts.acq_channel_id`.

## 7. Widoki agregujące (schemat `analytics`)

```sql
-- Ujednolicone dzienne dane marketingowe ze wszystkich kanałów
CREATE VIEW analytics.v_marketing_daily AS
SELECT date, 'meta_ads'::text AS channel_code, campaign_id::text AS entity_id, 'campaign' AS entity_level,
       sum(impressions) impressions, sum(clicks) clicks, sum(spend) spend
FROM channel_meta.ads_daily GROUP BY 1,3
UNION ALL
SELECT date, 'google_ads', campaign_id, 'campaign', sum(impressions), sum(clicks), sum(spend)
FROM channel_google.ads_daily GROUP BY 1,3
UNION ALL
SELECT d.date, 'organic_fb_ig', d.post_id, 'post', sum(d.impressions), sum(d.link_clicks), 0
FROM channel_organic.post_stats_daily d GROUP BY 1,3;

-- Wszystkie zamówienia z rozstrzygniętą firmą (po scaleniach) i kanałem
CREATE VIEW analytics.v_orders_all AS
SELECT o.id, o.order_no, o.ordered_at, o.ordered_at::date AS order_date,
       o.source, o.status, o.total_gross, o.total_net, o.total_vat,
       COALESCE(c2.id, c.id)  AS company_id,          -- podążanie za merged_into (1 poziom; pełny łańcuch f. rekurencyjna)
       COALESCE(c2.nip, c.nip) AS nip,
       o.contact_id, ch.code AS attribution_channel, o.attribution_method
FROM core.orders o
LEFT JOIN core.companies c  ON c.id = o.company_id
LEFT JOIN core.companies c2 ON c2.id = c.merged_into_id
LEFT JOIN core.channels ch  ON ch.id = o.attribution_channel_id
WHERE o.status <> 'anulowane';

-- Sesje GA4 zmapowane na kanały wewnętrzne
CREATE VIEW analytics.v_sessions_daily AS
SELECT t.date, COALESCE(ch.code,'inny') AS channel_code,
       sum(t.sessions) sessions, sum(t.engaged_sessions) engaged_sessions, sum(t.key_events) key_events
FROM channel_ga4.traffic_daily t
LEFT JOIN core.channel_mapping m ON m.ga4_source = t.source AND m.ga4_medium = t.medium
LEFT JOIN core.channels ch ON ch.id = m.channel_id
GROUP BY 1,2;

-- Dzienny lejek per kanał (fundament raportów i asystenta)
CREATE VIEW analytics.v_funnel_daily AS
SELECT md.date, md.channel_code,
       sum(md.impressions) AS impressions,
       sum(md.clicks)      AS clicks,
       COALESCE(s.sessions,0) AS sessions,
       COALESCE(o.orders,0)   AS orders,
       COALESCE(o.revenue_net,0) AS revenue_net,
       sum(md.spend)       AS spend
FROM analytics.v_marketing_daily md
LEFT JOIN analytics.v_sessions_daily s ON s.date = md.date AND s.channel_code = md.channel_code
LEFT JOIN (SELECT order_date, attribution_channel, count(*) orders, sum(total_net) revenue_net
           FROM analytics.v_orders_all GROUP BY 1,2) o
       ON o.order_date = md.date AND o.attribution_channel = md.channel_code
GROUP BY md.date, md.channel_code, s.sessions, o.orders, o.revenue_net;
```

Dodatkowo: `analytics.v_company_metrics` (LTV, częstotliwość - §8), `analytics.v_content_performance` (posty + reklamy z `creative_type`/`post_type` i wskaźnikami - źródło dla rekomendacji AI), `analytics.v_cac_monthly`.

## 8. Formuły metryk

### 8.1. Netto z konfigurowalnym VAT
Liczone na poziomie pozycji (stawka per produkt, domyślnie 23%): `line_net = line_gross / (1 + vat_rate/100)` - kolumny generowane w `order_items`, sumowane do zamówienia. Zmiana domyślnej stawki = wpis w `core.vat_rates`; historia nietykalna dzięki zamrożonej stawce w pozycji.

### 8.2. LTV firmy (historyczne, na danych netto)
```sql
-- analytics.v_company_metrics
SELECT company_id,
       sum(total_net)                                   AS ltv_net,
       count(*)                                         AS orders_count,
       min(order_date)                                  AS first_order,
       max(order_date)                                  AS last_order,
       round(sum(total_net)/count(*), 2)                AS avg_order_value_net
FROM analytics.v_orders_all
WHERE company_id IS NOT NULL AND status = 'zrealizowane'
GROUP BY company_id;
```
Przy ~100 zam./mies. LTV predykcyjne to nadmiar - raportujemy historyczne; asystent AI może dodatkowo podawać `avg_order_value_net * częstotliwość * 12` jako prognozę roczną z zastrzeżeniem.

### 8.3. Średnia częstotliwość zakupów firmy
Dwie miary (obie w widoku):
```sql
-- (a) zamówienia/miesiąc życia klienta
orders_count / GREATEST( (last_order - first_order) / 30.44, 1.0 )        -- dni/30.44; min. 1 miesiąc
-- (b) średni odstęp między zakupami w dniach (tylko firmy z >=2 zamówieniami)
(last_order - first_order)::numeric / NULLIF(orders_count - 1, 0)
```

### 8.4. CAC per kanał (miesięcznie)
```sql
WITH spend AS (
    SELECT date_trunc('month', date) m, channel_code, sum(spend) spend
    FROM analytics.v_marketing_daily GROUP BY 1,2
),
new_customers AS (   -- klient = firma (B2B) lub kontakt bez firmy (B2C); miesiąc pierwszego zamówienia
    SELECT date_trunc('month', first_order) m, acq_channel code, count(*) n
    FROM ( SELECT COALESCE(company_id::text, 'c'||contact_id::text) cust,
                  min(order_date) first_order,
                  (array_agg(attribution_channel ORDER BY ordered_at))[1] acq_channel
           FROM analytics.v_orders_all GROUP BY 1 ) f
    GROUP BY 1,2
)
SELECT s.m, s.channel_code, s.spend, COALESCE(nc.n,0) new_customers,
       CASE WHEN COALESCE(nc.n,0) > 0 THEN round(s.spend/nc.n, 2) END AS cac
FROM spend s LEFT JOIN new_customers nc ON nc.m = s.m AND nc.code = s.channel_code;
```
Gdy `new_customers = 0`, CAC = NULL (nie zero) - asystent raportuje "brak nowych klientów przypisanych do kanału". Klienci `attribution_method='brak'` liczeni osobno jako "nieprzypisani" i jawnie pokazywani, żeby suma CAC-ów nie sugerowała pełnej atrybucji.

### 8.5. Lejek i wskaźniki efektywności (na `v_funnel_daily`, dowolny zakres dat)
```
CTR                = clicks / NULLIF(impressions,0)
click_to_session   = sessions / NULLIF(clicks,0)          -- może być >1 (powroty) lub <1 (odrzucenia przed załadowaniem GA4) - to normalne, raportować bez "naprawiania"
CR (sesja→zamówienie) = orders / NULLIF(sessions,0)
CPC                = spend / NULLIF(clicks,0)
CPO (koszt/zamówienie) = spend / NULLIF(orders,0)
ROAS               = revenue_net / NULLIF(spend,0)
```
Etapy lejka pochodzą z różnych systemów pomiarowych (kliknięcia z platform reklamowych, sesje z GA4, zamówienia z core) - proporcje między etapami są matematycznie poprawne per kanał i per zakres dat, ale dokumentacja i asystent muszą oznaczać przejście kliknięcia→sesje jako łączenie źródeł o różnej metodologii.

## 9. Indeksy i klucze obce (poza już zadeklarowanymi PK/UNIQUE/FK)

```sql
-- core
CREATE INDEX idx_orders_company      ON core.orders (company_id) WHERE company_id IS NOT NULL;
CREATE INDEX idx_orders_contact      ON core.orders (contact_id);
CREATE INDEX idx_orders_ordered_at   ON core.orders (ordered_at);          -- zapytania "od czwartku 15:00"
CREATE INDEX idx_orders_status       ON core.orders (status);
CREATE INDEX idx_orders_attr_channel ON core.orders (attribution_channel_id, ordered_at);
CREATE INDEX idx_order_items_order   ON core.order_items (order_id);
CREATE INDEX idx_order_items_product ON core.order_items (product_id);
CREATE INDEX idx_contacts_company    ON core.contacts (company_id);
CREATE INDEX idx_companies_merged    ON core.companies (merged_into_id) WHERE merged_into_id IS NOT NULL;
CREATE INDEX idx_companies_name_trgm ON core.companies USING gin (name gin_trgm_ops);  -- wyszukiwarka + kandydaci do scaleń

-- mail
CREATE INDEX idx_emails_status       ON mail.emails (parse_status) WHERE parse_status IN ('nowy','odrzucony','blad');
CREATE INDEX idx_emails_from         ON mail.emails (from_email);
CREATE INDEX idx_emails_received     ON mail.emails (received_at);

-- kanały (PK złożone już pokrywają (date, id); dodatkowo odwrotny kierunek)
CREATE INDEX idx_meta_daily_campaign   ON channel_meta.ads_daily (campaign_id, date);
CREATE INDEX idx_google_daily_campaign ON channel_google.ads_daily (campaign_id, date);
CREATE INDEX idx_organic_stats_post    ON channel_organic.post_stats_daily (post_id, date);
CREATE INDEX idx_ga4_daily_sm          ON channel_ga4.traffic_daily (source, medium, date);
```

Rozszerzenia wymagane: `citext`, `pg_trgm`. Skala (≤100 zam./mies., pojedynczy użytkownik) nie wymaga partycjonowania ani materializacji widoków; jeśli `v_funnel_daily` kiedyś zwolni przy wieloletnich zakresach, pierwszym krokiem jest `MATERIALIZED VIEW` odświeżany nocnym jobem APScheduler - schemat tego nie wymusza, ale na to pozwala bez zmian DDL.