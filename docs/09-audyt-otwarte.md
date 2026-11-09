# Audyt - znaleziska i stan napraw

**Stan: wszystkie 39 znalezisk zamkniete.** Kazde ma przy wpisie `✔ NAPRAWIONE`
z krotka informacja, czym zostalo naprawione.

## Historia przebiegow

| Przebieg | Zgloszone | Potwierdzone | Uwagi |
|---|---|---|---|
| 1 (8 obiektywow) | 64 | 39 | pelny przeglad repo |
| 2 (regresje) | 20 | 4 | wykryl 2 REGRESJE z napraw przebiegu 1 |
| 3 (weryfikacja) | 14 | 6 | wykryl 1 REGRESJE (daty w PDF) - naprawy przebiegu 2 utrzymane |

Kazde znalezisko przechodzilo weryfikacje adwersarialna: niezalezny agent probowal je
OBALIC czytajac kod. Odrzucono odpowiednio 25 i 16 zgloszen.

## Naprawione (39 znalezisk + 2 regresje wlasne)

Przebieg 1: dane demo w migracjach (0009), cicha utrata importu CSV (SAVEPOINT),
kolizja klucza CSV/API, klamiace `get_orders(anulowane)`, limit listy zamowien,
obejscie rate-limitu, brak limitu tresci maila dla AI, klucz klienta w CAC (0010),
odpornosc pollingu IMAP, wyciek tokenu Meta, znacznik w nazwie produktu psujacy PDF.
Poza lista audytu: cicha utrata zamowien z maila (`/api/drafts/problems`),
niespojne formatowanie liczb (panel/PDF/mail/rekomendacje).

Przebieg 2 (regresje z wlasnych napraw): SAVEPOINT w IMAP gubil maile po cichu
zamiast blokowac; status 'blad_parsowania' nie mial sciezki wyjscia (migracja 0011
+ przycisk "Obsluzone").

Przebieg 3: `polonize_decimals` w PDF nie chronilo dat ("13.07.2026" -> "13,07,2026"),
podczas gdy blizniacza funkcja we frontendzie juz to robila - ta sama narracja
tygodniowa wygladala inaczej w panelu i w raporcie (test backendowy dopisany);
tytul rekomendacji nie przechodzil przez `polonizeDecimals` (lista + dialog archiwizacji).
Poza lista audytu: `connect_timeout=5` na silnikach SQLAlchemy - zgaszona baza
wieszala API i pytest na ~4 minuty zamiast dac czytelny blad.

Przebieg 4 (domkniecie listy): odpornosc na awarie (SAVEPOINT w imporcie historycznym,
rollback w petli polecen workera, timeout klienta AI, powiadomienia po commicie,
status 'nieskonfigurowane' zamiast 'error'), kaskada atrybucji #15 (nowy
`services/attribution.py` - UTM/gclid wyznaczaja KANAL, nie tylko metode), CPC liczone
na kanalach platnych, 401 wraca na ekran logowania, bledy 422 po polsku, pozycja bez
ceny blokuje zatwierdzenie szkicu, zakres dat liczony w czasie lokalnym (nie UTC),
wykres z dniami bez zamowien, powrot do baseline'u rekomendacji, indeks i retencja
`ops.sync_runs` (migracja 0013), trendy bez odrzuconych szkicow (migracja 0012),
limit rozmiaru zadania przed wczytaniem ciala, `res.ok` w czacie, zrodlo
`email_formularz` dla szkicow z formularza.

Testy dopisane w tym przebiegu: glowna sciezka mail -> szkic -> zatwierdzenie,
import historyczny z bledym wierszem, mapowanie UTM na kanal, `czytelnyBlad` (422),
zakres dat, tozsamosc klienta w CAC. Backend 141, frontend 17.

Przebieg 5: znalezisko [8] - decyzja #18a i `customer_key` (migracja 0014). Powracajacy
klient B2C przestal byc liczony jako kolejna nowa akwizycja w mianowniku CAC.

Przebieg 6 (jeden recenzent na caly diff sesji): 6 znalezisk, wszystkie naprawione.
Cztery byly REGRESJAMI z tej samej sesji - wykres przychodu rozwijal ~9700 pustych
punktow dla presetu „Caly okres”, `customer_key` z 0014 rozdzielal te sama osobe (raz
mail, raz sam telefon), `pytest` zostawial w bazie konto z haslem z repo i rosnaca liste
sesji (120 wpisow), a wygasniecie sesji dawalo osiem identycznych toastow. Do tego
zatwierdzenie szkicu z reczna korekta kanalu zapisywalo metode 'utm_formularz' zamiast
'reczna', a README mialo nieaktualna liczbe testow.

Migracja 0015 zamienia klucz na KLASY TOZSAMOSCI kontaktow (dzielony mail lub telefon).
Pierwsze podejscie - pelne domkniecie przechodnie rekurencyjnym CTE - zostalo odrzucone
po pomiarze: 22 s na pytanie o CAC przy 10 tys. kontaktow, a przy jednym numerze
wspoldzielonym przez 2 tys. kontaktow zapytanie przestawalo wracac. Wersja liniowa
(dwie rundy propagacji etykiet) to 32 ms w obu tych scenariuszach; jej granica jest
opisana wprost w decyzji #18a.

Testy: 145 backend, 17 frontend.

## Odrzucone jako sprzeczne z decyzjami kanonicznymi

**[8] Automatyczne scalanie kontaktow przy tworzeniu zamowienia - ODRZUCONE, problem u podstaw NAPRAWIONY inaczej.**
Audyt proponowal, by `create_order` wyszukiwal istniejacy kontakt po (email, firma) lub
telefonie i uzywal go zamiast tworzyc nowy. To **lamie decyzje kanoniczna #18**, ktora
mowi wprost: dopasowanie kontaktu „zawsze jako **sugestia**, nigdy automat" - bo wspolny
adres `biuro@firma.example` obsluguje wielu pracownikow, a jedna osoba moze obslugiwac dwie firmy.

Problem u podstaw jest jednak realny: powracajacy klient B2C liczy sie jako NOWY klient
first-touch, wiec mianownik CAC rosnie, a CAC jest zanizony (wyglada lepiej niz jest).
Rozwiazanie zgodne z #18 nie scala rekordow, tylko grupuje tozsamosc **na poziomie metryki**.
Wdrozone: decyzja **#18a** w `00-decyzje-kanoniczne.md` (wpis przed kodem, zgodnie z zasada #4),
kolumna `customer_key` w `analytics.v_orders_all` (migracja 0014) i jeden wspolny klucz dla
`v_cac_monthly`, `services/marketing.py` i `ai/tools.py`. Kolejnosc: firma po scaleniu ->
md5 znormalizowanego maila -> md5 telefonu (9 cyfr) -> contact_id -> id zamowienia.
Skrot zamiast surowego adresu, bo schemat analytics czyta rola `assistant_ro` (decyzja #9).
Rekordy kontaktow NIE sa scalane - decyzja #18 zostaje nienaruszona.

---

[4] [✔ NAPRAWIONE (migracja 0010 + tools.py + marketing.py)] WYSOKI (dane_sql) Klucz klienta COALESCE(company_id, contact_id) jest NULL dla zamowien bez firmy i bez kontaktu - wszystkie takie zamowienia zlewaja sie w JEDNEGO klienta
    backend/app/ai/tools.py:221
    AWARIA: Ta sama konstrukcja wystepuje w trzech miejscach: tools.py:221 (_first_touch_cte), marketing.py:121 (mianownik CAC) i widoku analytics.v_cac_monthly (0006:146). `create_order` tworzy kontakt tylko gdy podano imie/mail/telefon (orders.py:106), a wszystkie te po
    NAPRAWA: Zmienic klucz na taki, ktory nigdy nie jest NULL i nie skleja roznych zamowien, np. COALESCE(company_id::text, 'c'||contact_id::text, 'o'||id::text) - anonimowe zamowienie liczy sie wtedy jako osobny 

[7] [✔ NAPRAWIONE (SAVEPOINT per wiadomosc, kursor UID przesuwany po bledzie)] WYSOKI (degradacja) Jeden wadliwy mail blokuje polling IMAP na zawsze i kasuje cały udany batch (kursor UID nie jest zapisywany)
    backend/app/integrations/imap_client.py:62
    AWARIA: Cała pętla fetch + ingest + aktualizacja kursora jest w jednej transakcji, commit dopiero w linii 77. Wystarczy jeden mail, na którym `ingest_email` rzuci wyjątek na poziomie bazy - realny przypadek: treść text/plain zawierająca bajt NUL (0x00), którego psycop
    NAPRAWA: Przetwarzać każdą wiadomość w osobnej, izolowanej jednostce pracy: dla każdego msg `try: ingest_email(...); db.commit() except Exception: db.rollback(); log + licznik failed` (ewentualnie SAVEPOINT pr

[8] [✔ NAPRAWIONE (decyzja #18a + customer_key, migracja 0014)] WYSOKI (zgodnosc) CAC/new_customers: każde zamówienie B2C tworzy nowy kontakt, więc każdy powrót klienta liczy się jako NOWY klient first-touch (decyzja #6)
    backend/app/services/orders.py:107
    AWARIA: Klient detaliczny Jan Kowalski (jan@x.example) dzwoni i zamawia 3 razy w lipcu; operator za każdym razem wpisuje jego imię/telefon w drawerze. create_order BEZWARUNKOWO tworzy nowy wiersz core.contacts (brak jakiegokolwiek SELECT po Contact w całym repo - grep 'Con
    NAPRAWA: Przed utworzeniem Contact wyszukać istniejący po (znormalizowany email, company_id) lub po znormalizowanym telefonie (decyzja #18 dopuszcza wspólny email, więc para email+firma). Gdy znaleziony - użyć

[9] [✔ NAPRAWIONE (zduplikowane z [4] - naprawione migracja 0010)] SREDNI (logika) CAC: wszystkie zamówienia bez firmy i bez kontaktu sklejają się w JEDNEGO klienta (NULL) w mianowniku
    backend/app/services/marketing.py:121
    AWARIA: Zamówienie utworzone przez POST /api/orders (albo szkic) bez poprawnego NIP i bez żadnego pola kontaktu (contact_name/email/phone) trafia do bazy z company_id = NULL i contact_id = NULL - create_order tworzy Contact tylko gdy podano którekolwiek pole kontaktow
    NAPRAWA: Wykluczyć wiersze bez tożsamości klienta z podzapytania albo nadać im tożsamość per-zamówienie, np. COALESCE(company_id::text, 'c'||contact_id::text, 'o'||id::text) - wtedy każde anonimowe zamówienie 

[10] [✔ NAPRAWIONE (services/attribution.py + create_order)] SREDNI (logika) Sygnały UTM/gclid ustawiają attribution_method='utm_formularz', ale nigdy nie wyznaczają kanału - zamówienie ląduje w 'brak'
    backend/app/services/orders.py:122
    AWARIA: Mail z formularza zawiera utm_source=google, utm_medium=cpc. create_draft ustawia attribution_method='utm_formularz' (drafts.py:28-30), approve_draft przekazuje ten method i kolumny UTM do create_order (drafts.py:142-145). Ale create_order ustawia attribution_
    NAPRAWA: W create_order (lub w approve_draft przed wywołaniem) - gdy attribution_channel_id jest None, a są utm_source/utm_medium - rozwiązać kanał przez istniejącą tabelę core.channel_mapping (ga4_source/ga4_

[11] [✔ NAPRAWIONE (CPC na kanalach platnych + wpis w docs/06-metryki.md)] SREDNI (logika) CPC w lejku: licznik tylko z kanałów płatnych, mianownik z kliknięć wszystkich kanałów (w tym organicznych)
    backend/app/services/marketing.py:58
    AWARIA: analytics.v_marketing_daily mapuje kanał organiczny jako impressions=sum(views), clicks=sum(link_clicks), spend=0 (0003_integracje.py:48). W funnel() suma spend pochodzi więc de facto tylko z kanałów płatnych, ale clicks zawiera też link_clicks z postów organi
    NAPRAWA: Dołożyć do zapytania agregaty clicks_paid i impressions_paid z FILTER (WHERE channel_code IN ({_PAID_IN_SQL})) i liczyć cpc = spend_paid/clicks_paid oraz ctr = clicks_paid/impressions_paid (albo rapor

[12] [✔ NAPRAWIONE (token w naglowku + _bez_sekretow)] SREDNI (bezpieczenstwo) Token dostępowy Meta Ads wycieka do bazy, logów i odpowiedzi /api/health/integrations
    backend/app/integrations/marketing_sync.py:130
    AWARIA: Token Meta jest przekazywany jako parametr QUERY (`params={"access_token": ...}`), a `resp.raise_for_status()` httpx buduje komunikat wyjątku ze wzorca "... for url '{0.url}'" (potwierdzone w .venv/Lib/site-packages/httpx/_models.py:810-816) - czyli z PEŁNYM U
    NAPRAWA: 1) Nie wysyłać tokenu w query stringu - Graph API akceptuje nagłówek: `hc.get(url, params={...bez access_token...}, headers={"Authorization": f"Bearer {settings.meta_access_token}"})` (analogicznie w 

[15] [✔ NAPRAWIONE (esc() na tekscie uzytkownika w report_pdf)] SREDNI (bezpieczenstwo) Wstrzyknięcie znaczników do generatora PDF - nazwa produktu z maila trwale psuje /api/reports/pdf
    backend/app/services/report_pdf.py:612
    AWARIA: `Paragraph` z reportlab parsuje mini-XML, a nazwy produktów (pochodzące z parsera AI maili, importu CSV i importu historycznego) są wstawiane BEZ escapowania. Zweryfikowałem na zainstalowanym reportlabie: `Paragraph('Rura <a>25')`, `Paragraph('profil <br')`, `
    NAPRAWA: Escapować każdy łańcuch pochodzący z danych przed przekazaniem do `Paragraph`: `from xml.sax.saxutils import escape` i `Paragraph(escape(str(p["product_name"])), S["cell"])`. Najbezpieczniej dodać hel

[16] [✔ NAPRAWIONE (SAVEPOINT na wiersz + test)] SREDNI (dane_sql) Import historycznych zamowien: jeden bledny wiersz CSV konczy sie HTTP 500 i utrata wszystkich poprawnie utworzonych wczesniej zamowien
    backend/app/api/exports.py:110
    AWARIA: CSV z backfillu LTV, w ktorym kolumna cena_brutto ma wartosc nieliczbowa ('brak', '-') -> `_num` zwraca None -> unit_price_gross=NULL -> NotNullViolation przy db.flush() w create_order (orders.py:168); albo ilosc '-2' -> naruszenie CHECK qty_positive; albo vat
    NAPRAWA: Owinac create_order per wiersz w `with db.begin_nested():` (SAVEPOINT), zeby blad jednego wiersza nie uniewaznial transakcji; alternatywnie walidowac wiersz przed create_order (unit_price_gross is not

[17] [✔ NAPRAWIONE (wygaslaSesja() + MutationCache w main.tsx)] SREDNI (frontend) Wygaśnięcie sesji (401) jest globalnie wyciszone - panel pokazuje pusty, „wyzerowany” biznes zamiast ekranu logowania
    frontend/src/main.tsx:22
    AWARIA: `QueryCache.onError` porzuca każdy błąd 401 bez toastu, a `AuthProvider` sprawdza `/auth/me` wyłącznie przy montowaniu i nigdzie nie czyści `user` po 401 z innego zapytania. Scenariusz: sesja wygasa (`settings.session_ttl_days`, backend/app/api/auth.py:91) alb
    NAPRAWA: W `QueryCache.onError` (i analogicznym `MutationCache.onError`) na 401 wywołać wyczyszczenie stanu auth: eksportować z `auth.tsx` funkcję `forceLogout()` (ustawia `user = null` + `queryClient.clear()`

[18] [✔ NAPRAWIONE (brak ceny blokuje zatwierdzenie + czerwona obwodka)] SREDNI (frontend) Zatwierdzenie szkicu po cichu wyrzuca pozycje bez ceny - zamówienie powstaje niekompletne, bez ostrzeżenia
    frontend/src/pages/Inbox.tsx:201
    AWARIA: Wszystkie pozycje szkicu startują z `unit_price_gross: ""` (Inbox.tsx:186). Mail zawiera 3 pozycje; operator wpisuje ceny dla 2 i klika „Zatwierdź zamówienie” (przycisk aktywny, bo `canApprove = items.some(...)`, linia 241). `items.filter((it) => it.unit_price
    NAPRAWA: Zablokować zatwierdzenie, gdy którakolwiek pozycja ma pustą cenę: `const missing = items.filter(it => !it.unit_price_gross)`, `disabled={items.length === 0 || missing.length > 0}` plus czerwona obwódk

[19] [✔ NAPRAWIONE (czytelnyBlad() + testy)] SREDNI (frontend) Błędy walidacji FastAPI (422) wyświetlają się użytkownikowi jako „[object Object]”
    frontend/src/api/client.ts:23
    AWARIA: Backend nie ma handlera `RequestValidationError`, więc FastAPI dla 422 zwraca `{"detail": [{"loc": [...], "msg": "..."}]}` - tablicę, nie string. `detail = data.detail ?? detail` przypisuje tablicę, a `new ApiError(status, detail)` robi z niej `Error.message =
    NAPRAWA: W `request()` znormalizować `detail`: jeśli `Array.isArray(data.detail)` - złożyć czytelny komunikat, np. `data.detail.map(d => `${d.loc?.slice(1).join('.')}: ${d.msg}`).join('; ')`; jeśli obiekt - `J

[20] [✔ NAPRAWIONE (status 'nieskonfigurowane' + mapowanie w health)] SREDNI (degradacja) Brak kluczy META/GOOGLE/GA4 zapisuje przebieg jako 'error' - panel na stałe pokazuje czerwone alerty integracji
    backend/app/integrations/marketing_sync.py:41
    AWARIA: Świeża instalacja bez META_ACCESS_TOKEN / GOOGLE_ADS_* / GA4_* (czyli scenariusz 'degradacja bez kluczy'). Scheduler odpala sync_marketing o 3:15/3:30/3:45 i co 6 h. Każdy syncer rzuca NotConfigured, a handler zapisuje do ops.sync_runs wiersz ze status='error'
    NAPRAWA: W gałęzi `except NotConfigured` nie tworzyć wiersza błędu: albo usunąć świeżo dodany SyncRun (db.rollback() i return bez merge), albo zapisać status='skipped'/'nieskonfigurowane' i rozszerzyć health.p

[21] [✔ NAPRAWIONE (rollback + ponowne pobranie polecenia)] SREDNI (degradacja) Pętla poleceń workera: zapis statusu 'error' na zatrutej sesji - polecenie zostaje 'pending' i jest wykonywane w kółko co 10 s
    backend/app/scheduler/runner.py:76
    AWARIA: Handler wyjątku ustawia `cmd.status='error'` i wywołuje `db.commit()` NIE robiąc wcześniej `db.rollback()`. Jeśli polecenie padło na błędzie bazodanowym, sesja jest w stanie 'needs rollback' i ten commit sam rzuca PendingRollbackError - łapie go zewnętrzny `ex
    NAPRAWA: W bloku `except` najpierw `db.rollback()`, potem ponownie pobrać/odświeżyć rekord polecenia (`cmd = db.get(SyncCommand, cmd_id)`) i dopiero wtedy ustawić status='error' + result i zrobić commit; całoś

[22] [✔ NAPRAWIONE (timeout 90 s, max_retries 1 (konfigurowalne))] SREDNI (degradacja) Klient AI bez timeoutu i limitu retry - zawieszone wywołanie blokuje otwartą transakcję DB i połączenie IMAP na kilkanaście minut
    backend/app/ai/client.py:78
    AWARIA: `anthropic.Anthropic(...)` jest tworzony bez `timeout=` i `max_retries=`, więc obowiązują domyślne wartości SDK (600 s na żądanie + 2 ponowienia ≈ 30 min w najgorszym razie). Scenariusz: OpenRouter ma incydent i przestaje odpowiadać (połączenie TCP wisi, brak 
    NAPRAWA: Ustawić jawny budżet czasu przy konstrukcji klienta, np. `anthropic.Anthropic(..., timeout=60.0, max_retries=1)` (osobno krótszy dla parsera maili, dłuższy dla streamingu asystenta), a wartość wystawi

[23] [✔ NAPRAWIONE (kolejka powiadomien wysylana po commicie)] SREDNI (degradacja) Powiadomienie o nowym szkicu wysyłane przed commitem - maile o zamówieniach, których nie ma w Skrzynce
    backend/app/services/email_pipeline.py:147
    AWARIA: `notify_new_draft` jest wołane po `db.flush()`, ale transakcję commituje dopiero wołający (`poll_and_ingest`, imap_client.py:77). W batchu 5 nowych maili: maile 1-2 tworzą szkice i natychmiast wysyłają SMTP-em 'Nowe zamówienie do weryfikacji - X, zweryfikuj w 
    NAPRAWA: Nie wysyłać powiadomienia wewnątrz transakcji. Zebrać dane do powiadomień na liście i wysłać je dopiero po udanym `db.commit()` w warstwie wołającej (albo skorzystać z hooka `after_commit` sesji SQLAl

[24] [✔ NAPRAWIONE (zduplikowane z [4] - naprawione migracja 0010)] SREDNI (zgodnosc) CAC first-touch: zamówienia bez firmy i bez kontaktu sklejają się w JEDNEGO klienta (klucz NULL) (decyzja #6)
    backend/app/ai/tools.py:221
    AWARIA: Import historyczny (backend/app/api/exports.py:98 przekazuje contact_name/email/phone = None) 40 zamówień B2C bez NIP -> company_id NULL i contact_id NULL. W Postgresie 'c'||NULL = NULL, więc COALESCE(NULL, NULL) = NULL i wszystkie 40 wierszy trafia do JEDNEJ 
    NAPRAWA: Zastąpić klucz wyrażeniem, które nigdy nie jest NULL, np. COALESCE(company_id::text, 'c'||contact_id::text, 'o'||id::text) - zamówienie anonimowe traktowane jako osobny klient jednorazowy. Poprawić w 

[25] [✔ NAPRAWIONE (services/attribution.py, takze gclid/fbclid ze szkicu)] SREDNI (zgodnosc) Kaskada atrybucji #15 nie przypisuje kanału: sygnał UTM ustawia tylko `attribution_method`, a `heurystyka_ga4` nie istnieje w kodzie
    backend/app/services/drafts.py:129
    AWARIA: Mail z formularza zawiera ukryte pola utm_source=facebook&utm_medium=paid. Parser zapisuje je do szkicu, _draft_attribution_method (drafts.py:89-90) zwraca AttributionMethod.utm_formularz. Ale approve_draft przekazuje attribution_channel_id=payload.get('attrib
    NAPRAWA: Dodać funkcję resolve_channel_from_utm(db, utm_source, utm_medium, gclid, fbclid) -> channel_id (gclid/utm_source=google+medium=cpc -> google_ads, fbclid/utm_source in facebook,instagram + medium płat

[26] [✔ NAPRAWIONE (kubelek 'brak' wykluczony + nazwa ze slownika)] SREDNI (zgodnosc) Zestawienie tygodniowe ogłasza 'brak' (kubełek nieprzypisanych) jako najlepszy KANAŁ - kod spoza słownika #4
    backend/app/services/weekly_summary.py:65
    AWARIA: _top_channel wybiera max(revenue_net) z analytics.v_funnel_daily grupując po channel_code, bez wykluczenia pseudo-kanału 'brak' (wprowadzonego przez COALESCE(ch.code,'brak') w v_orders_all na potrzeby decyzji #16). Na danych roboczych: brak=1000,00 z
    NAPRAWA: W SQL _top_channel dodać AND channel_code <> 'brak' (albo lepiej: JOIN core.channels ch ON ch.code=f.channel_code, co przepuszcza wyłącznie 6 kodów z decyzji #4) i raportować udział nieprzypisanych os

[27] [✔ NAPRAWIONE (generate_series - dni bez zamowien z zerem)] NISKI (logika) revenue_series pomija dni bez zamówień - wykres przychodu zniekształca oś czasu
    backend/app/services/metrics.py:101
    AWARIA: Zapytanie robi GROUP BY order_date po wierszach v_orders_all, więc zwraca wiersz tylko dla dni, w których w ogóle jest jakieś zamówienie. Przy skali <=100 zamówień/mies. większość dni jest pusta. Wejście: zamówienia 1 lipca (500 zł), 5 lipca (500 zł), 20 lipca
    NAPRAWA: Wygenerować pełną oś dat i dołączyć do niej agregaty, np. FROM generate_series(:df, :dt, interval '1 day') d(day) LEFT JOIN ... ON o.order_date = d.day, z COALESCE(...,0) - wtedy każdy dzień okna ma p

[28] [✔ NAPRAWIONE (powrot do baseline gdy walidacja wytnie wszystko)] NISKI (logika) Brak fallbacku na baseline, gdy walidacja anty-halucynacyjna odrzuci wszystkie rekomendacje AI
    backend/app/services/recommendations.py:313
    AWARIA: Przy skonfigurowanym kluczu API method='ai', więc _validate_recommendations skanuje też body i odrzuca CAŁĄ rekomendację, jeśli w treści jest dowolna liczba spoza agregatów. Regex _NUM_IN_TEXT łapie każdą liczbę, także taką, której nie da się ugruntować w dany
    NAPRAWA: Po walidacji: jeśli method=='ai' i recs jest puste, wygenerować _baseline_recommendations(agg) i ustawić method='baseline' (z ponowną walidacją). Dodatkowo zwracać w wyniku liczbę odrzuconych (np. {'r

[29] [✔ NAPRAWIONE (jak [26])] NISKI (logika) Zestawienie tygodniowe może ogłosić 'brak' (pseudo-kanał nieprzypisanych) najlepszym kanałem
    backend/app/services/weekly_summary.py:67
    AWARIA: analytics.v_funnel_daily zawiera wiersz o channel_code='brak' (COALESCE(ch.code,'brak') w v_orders_all, 0007_domkniecie_zakresu.py:41) - celowo, żeby suma zamówień lejka = suma w systemie (decyzja #16). _top_channel nie odfiltrowuje tego pseudo-kanału, tylko s
    NAPRAWA: Dodać do zapytania warunek AND channel_code <> 'brak' (ewentualnie też pominąć kanały bez wydatków i bez sesji), a gdy nie ma żadnego kanału z atrybucją, zwrócić None i pominąć zdanie w narracji.

[30] [✔ NAPRAWIONE (middleware 8 MB przed wczytaniem ciala)] NISKI (bezpieczenstwo) Limit rozmiaru CSV sprawdzany PO wczytaniu całego ciała żądania i PO stronie autoryzacji
    backend/app/api/marketing.py:89
    AWARIA: FastAPI czyta i parsuje ciało żądania ZANIM uruchomi zależności routera. W zainstalowanej wersji (backend/.venv/Lib/site-packages/fastapi/routing.py) linia 426 `body_bytes = await request.body()` i 432 `json_body = await request.json()` wykonują się przed `sol
    NAPRAWA: Odciąć rozmiar PRZED trasowaniem: (a) w deploy/Caddyfile w bloku `handle /api/*` dodać `request_body { max_size 6MB }`, oraz (b) dla obrony w głąb dodać w app/main.py middleware ASGI odrzucający żądan

[31] [✔ NAPRAWIONE (migracja 0012 - jak [38])] NISKI (dane_sql) Widok analytics.v_email_product_trends nie filtruje statusu szkicu - odrzucone szkice licza sie jako sygnal popytu
    backend/alembic/versions/0007_domkniecie_zakresu.py:130
    AWARIA: Widok robi JOIN core.order_draft_items -> core.orders_draft bez zadnego warunku na d.status, mimo ze CHECK ck_draft_status dopuszcza 'nowy','do_weryfikacji','zatwierdzone','odrzucone'. Scenariusz: do skrzynki wpada spam albo mail zle sparsowany przez model (np
    NAPRAWA: Dodac w nowej migracji CREATE OR REPLACE VIEW analytics.v_email_product_trends ... WHERE d.status <> 'odrzucone', a w dokumentacji metryki zaznaczyc, ze jest to sygnal zapytan mailowych, nie sprzedazy

[32] [✔ NAPRAWIONE (migracja 0013 (indeks) + retencja 90 dni w workerze)] NISKI (wydajnosc) ops.sync_runs rośnie bez ograniczeń i bez indeksu - DISTINCT ON robi pełny skan+sort przy każdym wejściu na Dashboard/Marketing
    backend/app/api/health.py:23
    AWARIA: IMAP jest skonfigurowany, więc scheduler (app/scheduler/runner.py:183, job co 5 min) wywołuje poll_and_ingest, które BEZWARUNKOWO wstawia wiersz do ops.sync_runs (app/integrations/imap_client.py:33-35) - 288 wierszy/dobę. Do tego _run() w marketing_sync wstawi
    NAPRAWA: 1) Dodać migrację z indeksem: CREATE INDEX idx_sync_runs_source_started ON ops.sync_runs (source, started_at DESC); - wtedy DISTINCT ON użyje Index Scan zamiast sortu. 2) Dorzucić do _retention_job ka

[33] [✔ NAPRAWIONE (is_form w API + email_formularz w Skrzynce)] NISKI (frontend) Martwy operator warunkowy: szkice z formularza WWW zawsze dostają źródło `email_wolny`
    frontend/src/pages/Inbox.tsx:180
    AWARIA: Obie gałęzie ternarnego wyrażenia zwracają tę samą wartość, więc pole „Źródło” jest inicjalizowane na `email_wolny` niezależnie od pochodzenia maila. Szkic wyekstrahowany regułami z formularza (`extraction_method === "reguly"`, co UI sam pokazuje jako badge „W
    NAPRAWA: `setSource(d.extraction_method === "reguly" ? "email_formularz" : "email_wolny")` - albo, lepiej, zwracać wyliczone źródło z backendu w `DraftDetail` i tylko je wyświetlać jako domyślne.

[34] [✔ NAPRAWIONE (sprawdzenie res.ok + komunikat po polsku)] NISKI (frontend) Czat AI nie sprawdza `res.ok` - błąd HTTP daje pusty dymek asystenta bez komunikatu
    frontend/src/components/ChatPanel.tsx:69
    AWARIA: `fetch` zwraca `res.body` również dla 401/500, więc warunek `if (!res.body)` nie łapie błędów. Przy wygasłej sesji lub wyjątku w `/chat/conversations/{id}/messages` treścią odpowiedzi jest JSON `{"detail": ...}`, który nie zawiera sekwencji `\n\n`, więc pętla 
    NAPRAWA: Po `await fetch(...)` dodać: `if (!res.ok) { const d = await res.json().catch(() => null); throw new Error(d?.detail ?? `Błąd ${res.status}`); }` - wtedy istniejący `catch` (linia 84) dopisze komunika

[35] [✔ NAPRAWIONE (iso/przesunDni/zakresPresetu w czasie lokalnym + testy)] NISKI (frontend) Zakres dat liczony w UTC - po północy czasu polskiego „dzisiaj” cofa się o dobę
    frontend/src/contexts/dateRange.tsx:7
    AWARIA: `iso()` bierze datę z `toISOString()`, czyli w UTC, podczas gdy użytkownik i backend operują na czasie polskim (UTC+2 latem). O 00:30 CEST 23 lipca `new Date().toISOString()` daje `2026-07-22T22:30Z`, więc preset „30 dni” ustawia `date_to=2026-07-22`. Zamówien
    NAPRAWA: Liczyć datę lokalnie: `const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}``, i tak samo w `previousRange` w Dashboard.tsx:87,

[36] [✔ NAPRAWIONE (tests/test_drafts_approve.py)] NISKI (testy) approve_draft - główna produkcyjna ścieżka powstawania zamówień - bez żadnego testu
    backend/app/services/drafts.py:109
    AWARIA: Zamówienia z maili powstają wyłącznie przez POST /api/drafts/{id}/approve → approve_draft → create_order, a testy dotykają wyłącznie ręcznego POST /api/orders. Nieosłonięte są trzy decyzje biznesowe zapisane w tej funkcji: data zamówienia = data maila (nie mom
    NAPRAWA: Dopisać backend/tests/test_drafts_approve.py oparte o istniejący hook POST /api/drafts/simulate (nie wymaga IMAP ani klucza AI dla maila formularzowego - idzie parserem regułowym): (a) test_approve_us

[37] [✔ NAPRAWIONE (tests/dateRange.test.ts + wymuszona strefa w vitest)] NISKI (testy) Frontend: wyliczanie zakresu dat (iso/setPreset) bez testu - toISOString gubi dzień w strefie UTC+1/+2
    frontend/src/contexts/dateRange.tsx:7
    AWARIA: Jedyny plik testowy frontendu to src/lib/format.test.ts (formatowanie liczb i dat). Kontekst dateRange, który wyznacza date_from/date_to dla WSZYSTKICH stron (Dashboard, Marketing, Raporty, Firmy), nie ma testu. iso() konwertuje czas lokalny na UTC, a Polska t
    NAPRAWA: Dodać frontend/src/contexts/dateRange.test.ts: wyeksportować iso i pomocniczą presetRange(days, now) z modułu, po czym asertować z wstrzykniętym 'now': dla now = new Date(2026, 6, 22, 0, 30) (czas lok

[38] [✔ NAPRAWIONE (migracja 0012 - filtr statusu szkicu)] NISKI (zgodnosc) Metryka trendów produktowych liczy szkice ODRZUCONE i już zatwierdzone - szkice wchodzą do metryki (decyzja #2)
    backend/alembic/versions/0007_domkniecie_zakresu.py:123
    AWARIA: Widok analytics.v_email_product_trends agreguje core.orders_draft BEZ filtra po statusie. Mail od dostawcy z ofertą ('Kawa ziarnista 50 kg, Filtry do ekspresu 200 szt.') zostaje sparsowany jako szkic, właściciel odrzuca go w Skrzynce (reject_draft ustawia stat
    NAPRAWA: W CREATE OR REPLACE VIEW analytics.v_email_product_trends dodać WHERE d.status <> 'odrzucone' (i rozważyć d.status = 'do_weryfikacji', by nie dublować popytu ze szkiców już zamienionych na zamówienia)

[39] [✔ NAPRAWIONE (etykieta 'Bez atrybucji')] NISKI (zgodnosc) Wiersz nieprzypisanych w tabeli kanałów wyświetla surowy kod 'brak' zamiast etykiety 'nieprzypisane' (decyzja #16)
    backend/app/services/marketing.py:73
    AWARIA: channel_summary robi LEFT JOIN core.channels ON ch.code = f.channel_code, ale w core.channels nie ma (i zgodnie z decyzją #4 nie może być) wiersza o kodzie 'brak' - sprawdzone: tabela zawiera dokładnie 6 kodów. Dla kubełka nieprzypisanego name_pl = NULL, więc 
    NAPRAWA: W channel_summary zwracać name_pl = COALESCE(ch.name_pl, CASE WHEN f.channel_code='brak' THEN 'Nieprzypisane' ELSE f.channel_code END) - lub użyć wspólnej mapy etykiet z report_pdf.py:109, żeby panel,
