# Kanoniczne definicje metryk

**Jedno źródło prawdy.** Te same definicje są wpisane do system promptu asystenta AI oraz do tooltipów
„i" przy kartach KPI w UI. Nigdzie w systemie nie wolno liczyć tych metryk inaczej.

Wszystkie kwoty są **netto w PLN**, chyba że jawnie oznaczono „brutto".

## Kwoty netto i VAT

Liczone **na poziomie pozycji zamówienia** (`core.order_items`) z **zamrożoną** stawką VAT - stawka
jest kopiowana z produktu w chwili sprzedaży i nie zmienia się później (kolumny generowane):

```
line_gross = round(quantity * unit_price_gross, 2)
line_net   = round(quantity * unit_price_gross / (1 + vat_rate/100), 2)
line_vat   = line_gross - line_net
```

Sumy zamówienia (`total_gross`, `total_net`, `total_vat`) to sumy pozycji (utrzymywane triggerem).
Domyślna stawka VAT: **23%**, konfigurowalna per produkt (`core.products.vat_rate_id` → `core.vat_rates`).
Zmiana domyślnej stawki = nowy wiersz w `core.vat_rates`; historia zamówień nietknięta.

## LTV firmy (Lifetime Value)

Historyczne (nie predykcyjne). Suma netto wszystkich zamówień firmy o statusie **`potwierdzone`
LUB `zrealizowane`**, przypisanych do jej NIP (po scaleniach duplikatów):

```sql
ltv_net = SUM(total_net) WHERE company_id = :id AND status IN ('potwierdzone','zrealizowane')
```

Zamówienia `nowe` (jeszcze niepotwierdzone) i `anulowane` **nie** wchodzą do LTV.

## Średnia wartość zamówienia (AOV)

```
aov_net = ltv_net / liczba_zamowien_liczonych_do_ltv
```

## Częstotliwość zakupów firmy

Średni odstęp w dniach między kolejnymi zamówieniami. Liczona **tylko dla firm z ≥2 zamówieniami**;
dla firm z 1 zamówieniem wartość to `-`:

```
czestotliwosc_dni = (last_order_date - first_order_date) / (liczba_zamowien - 1)
```

W profilu firmy pokazujemy też trend („przyspiesza / zwalnia") - porównanie średniej z ostatnich
3 odstępów do średniej ogólnej.

## CAC per kanał (Customer Acquisition Cost)

Miesięcznie, per kanał:

```
CAC = wydatki_reklamowe_kanalu_w_miesiacu / liczba_nowych_klientow_z_tego_kanalu_w_miesiacu
```

- **Nowy klient** = pierwsze w historii zamówienie danego klienta (dla B2B: pierwszy raz dany NIP).
- **Kto jest tym samym klientem** (decyzja #18a): firma po scaleniu duplikatów → klasa kontaktów
  dzielących znormalizowany e-mail lub telefon → samo zamówienie (anonimowe). Powracający klient
  B2C liczy się **raz**, także wtedy, gdy raz zostawił mail, a raz tylko numer - mimo że każde
  jego zamówienie zakłada nowy rekord kontaktu (decyzja #18 zabrania automatycznego scalania
  rekordów; grupujemy dopiero na poziomie metryki). Grupowanie ma świadomą granicę (długie
  łańcuchy naprzemiennego maila/telefonu) - opisaną w decyzji **#18a**.
- **Atrybucja first-touch**: klient jest przypisany do kanału atrybucji swojego **pierwszego** zamówienia
  (`companies.acq_channel_id` / `contacts.acq_channel_id`).
- Gdy liczba nowych klientów = 0 → CAC = `NULL` (nie zero); asystent raportuje „brak nowych klientów
  przypisanych do kanału".
- Klienci z `attribution_method = 'brak'` liczeni **osobno** jako „nieprzypisani" i jawnie pokazywani,
  żeby suma CAC-ów nie sugerowała pełnej atrybucji.

## Lejek konwersji

Cztery etapy, per kanał, dla dowolnego zakresu dat:

```
Wyświetlenia → Kliknięcia → Sesje → Zamówienia
```

Wskaźniki przejścia:

```
CTR                   = clicks / impressions
click_to_session      = sessions / clicks          # może być >1 (powroty) lub <1 (odbicia) - raportować bez „naprawiania"
CR (sesja→zamówienie) = orders / sessions
CPC                   = spend_platny / clicks_platny
CPO (koszt/zamówienie)= spend_platny / orders_platny
ROAS                  = revenue_net_platny / spend_platny
```

**Wskaźniki kosztowe (CPC, CPO, ROAS) liczymy wyłącznie na kanałach płatnych** (`meta_ads`,
`google_ads`). Wydatki ponoszą tylko one, więc wciągnięcie do mianownika kliknięć, zamówień
i przychodu z kanałów bezpłatnych zaniżałoby koszt i zawyżało ROAS - im lepiej szedłby profil
organiczny, tym „tańsza" wyglądałaby reklama. Wolumeny lejka (wyświetlenia, kliknięcia, sesje,
zamówienia) pozostają zbiorcze dla wszystkich kanałów, zgodnie z decyzją #16.

**Uwaga metodologiczna** (asystent ma ją komunikować): etapy pochodzą z różnych systemów pomiarowych
- kliknięcia z platform reklamowych, sesje z GA4, zamówienia z `core`. Proporcje są matematycznie
poprawne per kanał i zakres, ale przejście kliknięcia→sesje łączy źródła o różnej metodologii.

Lejek zawiera też wiersz **„bezpośredni / nieprzypisane"** (kanały `seo_direct`, `brak`), aby suma
zamówień w lejku równała się sumie zamówień w systemie.

## ROAS (Return on Ad Spend)

```
ROAS = przychod_netto_przypisany_kampanii / wydatki_kampanii
```

Przychód przypisany kampanii to dolne oszacowanie (atrybucja niepełna przy zamówieniach mailowych/
telefonicznych) - asystent zawsze o tym uprzedza.

## Konkurencja (decyzja #22)

Miary liczone **osobno per grupa** (`europejska` / `polska` / `lokalna`), wyłącznie z danych
publicznych. Nie mieszamy ich z metrykami własnymi w jednym wskaźniku - patrz asymetria danych
w decyzji #22.

```
zaangazowanie_posta   = lajki + komentarze
zaangazowanie_grupy   = MEDIANA(zaangazowanie_posta) po wszystkich postach grupy w oknie
rytm_publikacji       = liczba_postow / liczba_tygodni_w_oknie      # postów na tydzień
udzial_formatu        = liczba_postow_formatu / liczba_postow_grupy # rolka/karuzela/zdjęcie/wideo
```

**Mediana, nie średnia** - jeden viral przesuwa średnią o rząd wielkości i sugeruje trend,
którego nie ma. Średnią wolno pokazać obok mediany, nigdy zamiast niej.

**Co jest porównywalne z własnym profilem:** rozkład formatów i rytm publikacji (obie strony
liczone tak samo, własne dane z `channel_organic.post_stats_daily`). Zaangażowanie porównujemy
tylko jako lajki + komentarze - bo zasięgu i wyświetleń konkurencji nie widać w ogóle.

**Czego NIE liczymy konkurencji:** zasięgu, wyświetleń, wydatków, ROAS-u, CAC. Brakuje mianownika,
więc każda taka liczba byłaby zmyślona.
