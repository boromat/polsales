# Integracje - instrukcje konfiguracji dostępów

Kolejność wdrażania od najłatwiejszej do najtrudniejszej. Pełny research z linkami źródłowymi:
`zrodla/integracje-research.md`. Wszystkie API są **darmowe** (płaci się tylko za same reklamy).

> **Wymóg wspólny - strefy czasowe (decyzja kanoniczna #17):** ustaw konto reklamowe Meta, konto
> Google Ads i usługę GA4 na **Europe/Warsaw**. Bez tego dzienne dane z różnych kanałów byłyby
> przesunięte względem zamówień.

---

## 1. Google Analytics 4 (Data API) - najłatwiejsze, ~30 min

1. Google Cloud Console → utwórz projekt (lub użyj istniejącego) → włącz **Google Analytics Data API**.
2. Utwórz **konto usługi (service account)** → wygeneruj klucz **JSON**.
3. W GA4: Administracja → Zarządzanie dostępem do usługi → dodaj e-mail konta usługi z rolą **Przeglądający**.
4. Zapisz plik JSON na serwerze; ścieżkę wskaż w `.env` (`GA4_SERVICE_ACCOUNT_JSON`), `GA4_PROPERTY_ID`.

Bez OAuth, bez review, klucz nie wygasa. W GA4 ustaw retencję danych zdarzeń na **14 miesięcy**
(domyślnie 2) - i tak archiwizujemy do własnej bazy.

## 2. Meta Marketing API (płatne kampanie FB/IG)

1. developers.facebook.com → konto deweloperskie (darmowe).
2. Utwórz aplikację typu **Business** → dodaj produkt **Marketing API**.
3. Powiąż aplikację z **Business Managerem**, w którym jest konto reklamowe firmy.
4. Ustawienia firmowe → Użytkownicy → **Użytkownicy systemowi** → utwórz użytkownika systemowego,
   przypisz konto reklamowe, wygeneruj **token** z uprawnieniami `ads_read` + `business_management`.
   Token użytkownika systemowego **domyślnie nie wygasa**.
5. `.env`: `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`.

**App Review NIE jest wymagany** dla własnego konta reklamowego. Monitoruj błąd **190** (OAuthException,
„token się zepsuł") → alert w UI. Dane historyczne: 37 miesięcy (agregaty).

## 3. Meta Graph API - organiczne FB/IG (ta sama aplikacja)

1. Strona firmowa na FB; konto IG przełączone na **konto profesjonalne (Business/Creator)** i
   **połączone ze stroną FB** (w Meta Business Suite).
2. Uprawnienia: `pages_show_list`, `pages_read_engagement`, `read_insights`, `instagram_basic`,
   `instagram_manage_insights`. Token użytkownika systemowego jak wyżej.
3. `.env`: `META_PAGE_ID`, `META_IG_USER_ID` (pobierane też programowo).

**Budujemy od razu na metryce `views`** (Page Viewer), nie `impressions` - deprecjacja metryk
organicznych 15.11.2025 (strony) i 15.06.2026 (v25.0). **Retencja tylko ~2 lata, okna zapytań maks.
90 dni** - to najmocniejszy argument, żeby uruchomić tę integrację wcześnie i archiwizować od 1. dnia.

## 4. Google Ads API - najtrudniejsze

1. Utwórz **konto menedżerskie (MCC)** - darmowe. W API Center MCC pobierz **developer token**
   (jeden na firmę). Konto reklamowe podepnij jako podrzędne pod MCC.
2. Google Cloud → ekran zgody OAuth → **klient OAuth** → jednorazowo uzyskaj **refresh token**.
3. **Pułapka nr 1:** ekran zgody OAuth musi mieć status **„In production"**, inaczej refresh token
   wygasa po **7 dniach**. Dla własnego użytku nie trzeba pełnej weryfikacji Google.
4. Poziom dostępu: nowe tokeny startują z **Explorer Access** (2 880 operacji/dzień) - bez wniosku,
   w zupełności wystarcza przy 1 syncu dziennie. Nie ubiegaj się o Basic, dopóki niepotrzebny
   (Google ma zaległości w rozpatrywaniu wniosków - stan 2026).
5. `.env`: `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`,
   `GOOGLE_ADS_REFRESH_TOKEN`, `GOOGLE_ADS_CUSTOMER_ID`, `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (MCC).

**Do czasu konfiguracji: import CSV** (patrz niżej).

---

## Import CSV (fallback + backfill) - decyzja kanoniczna #14

Trwała funkcja panelu (widok „Marketing"), nie tymczasowa. Służy do:
- uruchomienia systemu, zanim skonfigurujesz dostępy API,
- backfillu historii sprzed integracji,
- planu B przy każdej awarii/deprecjacji API.

Format CSV (kolumny): `dzien, kanal, kampania, wyswietlenia, klikniecia, koszt`. Wiersze trafiają do
tych samych tabel co przyszła integracja API, z kolumną `source = 'csv'`. Eksporty:
- **Google Ads**: Raporty → eksport CSV lub cykliczny raport e-mail.
- **Meta Ads**: Menedżer reklam → raporty niestandardowe → eksport CSV.
- **Meta organiczne**: Meta Business Suite → Insights → eksportuj dane.

---

## Zadanie dla strony www (atrybucja `utm_formularz`) - decyzja kanoniczna #15

Właściciel ma kontrolę nad stroną - do wdrożenia (można zlecić wykonawcy):

1. **Skrypt GA4** (`gtag.js`) z ID pomiaru na wszystkich podstronach.
2. **Zdarzenie kluczowe (key event)** „wysłanie formularza" - wywoływane po sukcesie wysyłki formularza
   kontaktowego (`gtag('event', 'generate_lead')` lub własne zdarzenie oznaczone jako kluczowe w GA4).
3. **Ukryte pola w formularzu** wypełniane JS-em z parametrów URL i `sessionStorage` (żeby przetrwały
   nawigację): `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `gclid`, `fbclid`.
   Wartości mają trafić do **treści maila** generowanego przez formularz (np. w stopce), skąd
   parser regułowy je odczyta i zapisze w `core.orders.utm_*`.

Przykładowy snippet do wklejenia w formularz (do dostosowania przez wykonawcę):

```html
<script>
  (function () {
    var p = new URLSearchParams(location.search);
    var keys = ['utm_source','utm_medium','utm_campaign','utm_content','gclid','fbclid'];
    keys.forEach(function (k) {
      var v = p.get(k) || sessionStorage.getItem('attr_' + k) || '';
      if (p.get(k)) sessionStorage.setItem('attr_' + k, p.get(k));
      var el = document.querySelector('[name="attr_' + k + '"]');
      if (el) el.value = v;
    });
  })();
</script>
<!-- ukryte pola formularza: -->
<input type="hidden" name="attr_utm_source">
<input type="hidden" name="attr_utm_medium">
<input type="hidden" name="attr_utm_campaign">
<input type="hidden" name="attr_utm_content">
<input type="hidden" name="attr_gclid">
<input type="hidden" name="attr_fbclid">
```

Bez tych zmian atrybucja opiera się na słabszej `heurystyka_ga4` i ręcznym pytaniu „skąd Pan o nas wie?".

---

## Harmonogram synchronizacji (worker APScheduler)

| Zadanie | Częstotliwość | Uwagi |
|---|---|---|
| Polling IMAP + parsowanie | co 5 min | idempotentnie po UID |
| Meta Ads insights | co 6 h + pełny D-1 o 03:00 | Meta koryguje metryki do 72 h → refetch |
| Meta/IG organic | 1×/dobę 03:15 | metryka `views` |
| Google Ads | 1×/dobę 03:30 | za D-1 |
| GA4 Data API | 1×/dobę 03:45 | + refetch D-2/D-3 (opóźnienia GA4) |
| Przeliczanie metryk (refresh widoków) | 1×/dobę 04:30 | po wszystkich syncach |
| Rekomendacje AI (Batches) | 1×/dobę 05:00 | na świeżych danych |
| Backup bazy + `/data` | 1×/dobę 02:00 | pg_dump + rclone offsite |

Wszystkie synchronizacje idempotentne (UPSERT po kluczach naturalnych), log w `ops.sync_runs`,
alerty na dashboardzie: zielony (OK) / żółty (ostatni sync nieudany) / czerwony (brak udanego syncu
> 24 h lub błąd auth). Błędy auth wyróżnione osobnym komunikatem z instrukcją odnowienia tokena.
