# Research integracji marketingowych - stan na lipiec 2026

## 1. Meta Marketing API (statystyki płatnych kampanii FB/IG)

### a) Kroki dostępu dla właściciela małej firmy

1. Konto deweloperskie na developers.facebook.com (darmowe, wymaga zwykłego konta FB).
2. Utworzenie aplikacji typu „Business" w App Dashboard i dodanie produktu **Marketing API**.
3. Powiązanie aplikacji z **Business Managerem / portfolio biznesowym**, w którym jest konto reklamowe firmy.
4. Uprawnienia: `ads_read` (odczyt kampanii i insightów) + `business_management`; opcjonalnie `ads_management` (niepotrzebne - panel tylko czyta dane).
5. Token: najlepiej **token użytkownika systemowego (system user)** tworzony w Business Manager (Ustawienia firmowe → Użytkownicy → Użytkownicy systemowi) z przypisanym kontem reklamowym - **domyślnie nie wygasa** (chyba że zostanie ręcznie unieważniony lub jawnie utworzony jako wygasający 60-dniowy). To kluczowa różnica vs zwykły token użytkownika OAuth (60 dni). Źródła: https://developers.facebook.com/documentation/facebook-login/guides/access-tokens , https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/
6. **App Review NIE jest wymagany** dla dostępu do własnego konta reklamowego. Poziom podstawowy (dawniej „Development/Standard") działa od razu dla kont, do których użytkownik z rolą w aplikacji ma dostęp admina. Formalny review (Advanced Access + weryfikacja firmy) jest potrzebny wyłącznie, gdy aplikacja obsługuje **cudze** konta reklamowe - tu nie dotyczy. Źródła: https://developers.facebook.com/documentation/ads-commerce/marketing-api/get-started/authorization , https://adadvisor.ai/blog/meta-app-review-mcp
7. Zmiana od **4 maja 2026**: funkcja „Ads Management Standard Access" została przemianowana, a próg kwalifikacji do wyższego tieru obniżono z 1500 do **500 wywołań API w 15 dni**; zrzuty ekranu/nagrania nie są już wymagane, kryteria widoczne wprost w App Dashboard. Dla jednego użytkownika i ~100 zamówień/mies. wyższy tier prawdopodobnie nigdy nie będzie potrzebny. Źródło: https://developers.meta.com/blog/updates-to-ads-management-standard-access-feature/

### b) Limity i pułapki

- **Rate limity Ads Insights** (poziom standard): ~`600 + 400 × liczba aktywnych reklam` wywołań/godz. na konto; aplikacje w tierze deweloperskim mają limity znacznie niższe - przy jednej synchronizacji dziennie (APScheduler) to bez znaczenia. Nagłówek `x-business-use-case-usage` pozwala monitorować zużycie. Źródło: https://developers.facebook.com/docs/marketing-api/insights/best-practices/
- **Dane historyczne: 37 miesięcy** dla metryk zagregowanych; ale metryki unikalne (reach/unique) i podziały godzinowe tylko **13 miesięcy**, a `frequency_value` tylko **6 miesięcy**. Źródło: https://ppc.land/meta-restricts-attribution-windows-and-data-retention-in-ads-insights-api/
- **Wersjonowanie Graph API**: wersje żyją ~2 lata, kwartalne wydania; endpoint z przypiętą wersją przestaje działać po jej wygaśnięciu - trzeba planować coroczny przegląd integracji.
- Token systemowy „psuje się cicho" przy zmianie hasła/uprawnień admina lub weryfikacji biznesowej - warto w panelu monitorować błędy 190 (OAuthException) i alarmować w UI.

### c) Koszt: **darmowe** (brak opłat za API; płaci się tylko za same reklamy).

## 2. Meta Graph API - insighty organiczne strony FB i Instagrama

### a) Kroki dostępu

1. **Ta sama aplikacja** co dla Marketing API - nie trzeba drugiej.
2. Wymagania po stronie kont: strona firmowa na FB; konto IG przełączone na **konto profesjonalne (Business/Creator)** i **połączone ze stroną FB** (Ustawienia IG → Konto → Przełącz na konto profesjonalne; połączenie w Meta Business Suite).
3. Uprawnienia: `pages_show_list`, `pages_read_engagement`, `read_insights` (FB Page) oraz `instagram_basic`, `instagram_manage_insights` (IG). Bez `pages_show_list` + `pages_read_engagement` nie da się pobrać ID konta IG Business. Źródła: https://developers.facebook.com/docs/instagram-platform/insights/ , https://elfsight.com/blog/instagram-graph-api-complete-developer-guide-for-2026/
4. **Standard Access wystarcza** dla własnej strony/konta (osoby z rolą w aplikacji); Advanced Access i review tylko dla obsługi cudzych kont - nie dotyczy.
5. Token: token systemowy jak wyżej, albo długożyciowy **Page access token** (uzyskany z long-lived user tokena - Page token praktycznie nie wygasa).
6. Endpointy: `GET /{page-id}/insights`, `GET /{ig-user-id}/insights`, `GET /{media-id}/insights`.

### b) Limity i pułapki (tu jest najwięcej ruchomych piasków w 2026)

- **Wielka deprecjacja metryk organicznych**: od **15 listopada 2025** usunięto `impressions` i `page_fans` (zastąpione metryką `views`); od **15 czerwca 2026** (Graph API v25.0) usunięto masowo kolejne metryki organiczne stron - API zwraca „invalid metric". Nowy model opiera się na `views` i metryce **Page Viewer** (spójny pomiar FB+IG). System trzeba budować od razu na nowym modelu metryk, nie na starych poradnikach. Źródła: https://developers.facebook.com/blog/post/2025/08/15/page-insights-api-updates/ , https://windsor.ai/documentation/guide-for-deprecating-metrics-for-facebook-organic-connector-june-15-2026/ ; analogiczna czystka w IG Insights była 21 kwietnia 2025: https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights/
- **Retencja danych: tylko ~2 lata**, a pojedyncze zapytanie `since/until` obejmuje **maks. ~90/93 dni** - historię trzeba pobierać oknami i **archiwizować we własnej bazie od pierwszego dnia** (to mocny argument za wczesnym uruchomieniem tej integracji). Źródło: https://developers.facebook.com/docs/graph-api/reference/insights/
- Insighty IG na poziomie konta mają krótkie okna zapytań (do ~30 dni); insighty pojedynczych postów/mediów są dostępne przez cały cykl życia posta.
- Rate limity platformowe (~200 wywołań/godz./użytkownika lub limity BUC dla tokenów stron) - bez znaczenia przy dziennej synchronizacji.

### c) Koszt: **darmowe**.

## 3. Google Ads API

### a) Kroki dostępu

1. **Konto menedżerskie Google Ads (MCC)** - darmowe, zakładane obok zwykłego konta reklamowego; **developer token istnieje tylko w MCC** (API Center: https://ads.google.com/aw/apicenter ), jedno na firmę. Konto klienckie podpina się jako podrzędne pod MCC. Źródło: https://developers.google.com/google-ads/api/docs/api-policy/developer-token
2. Projekt Google Cloud → ekran zgody OAuth → klient OAuth (desktop/web) → jednorazowe uzyskanie **refresh tokena** dla konta właściciela.
3. Poziomy dostępu (stan 2026): **nowe tokeny startują domyślnie z poziomem „Explorer Access"** - od razu dostęp do kont produkcyjnych, limit **2 880 operacji/dzień**, bez wniosku i bez review (część aplikacji dostaje tylko Test Account Access). Wyżej: **Basic** (15 000 operacji/dzień, wniosek w API Center, cel ~2-5 dni roboczych) i **Standard** (bez limitu, ~10 dni). Źródła: https://developers.google.com/google-ads/api/docs/api-policy/access-levels , https://ads-developers.googleblog.com/2025/10/explorer-access-is-now-available-for.html
4. **Uwaga na 2026**: Google oficjalnie przyznał (6 lutego 2026) zaległości w rozpatrywaniu wniosków o Basic/Standard - terminy przekraczają cele; rekomendacja Google: pozostać na Explorer, dopóki Basic nie jest niezbędny. Dla tego systemu (odczyt raportów 1×/dzień, jedno konto) **Explorer w zupełności wystarcza** - 2 880 operacji/dzień to ogromny zapas. Źródła: https://ads-developers.googleblog.com/2026/02/an-update-on-google-ads-api-developer.html , https://ppc.land/google-faces-developer-token-application-backlog-as-new-api-tier-debuts/

### b) Limity i pułapki

- **Pułapka nr 1 - refresh token wygasa po 7 dniach**, jeśli ekran zgody OAuth ma status „Testing". Rozwiązanie: przełączyć publishing status na **„In production"** (dla własnego użytku nie trzeba przechodzić pełnej weryfikacji Google; token przestaje wygasać - unieważnia się tylko po 6 mies. nieużywania, zmianie hasła z pewnymi scope'ami lub ręcznym cofnięciu). Źródła: https://developers.google.com/google-ads/api/docs/get-started/common-errors , https://www.unipile.com/google-oauth-refresh-token/
- **Nowa retencja danych od 1 czerwca 2026**: dane godzinowe/dzienne/tygodniowe dostępne **37 miesięcy**; miesięczne/kwartalne/roczne **11 lat**; reach/frequency 3 lata. Źródło: https://calibrate-analytics.com/insights/2026/05/05/Google-Ads-Announces-37-Month-Limit-for-Historical-Data-Retention/
- Wersje API wygasają co ~12 miesięcy - biblioteka `google-ads` (Python) wymaga corocznej migracji wersji.
- Raportowanie przez GAQL (`GoogleAdsService.SearchStream`) - próg wejścia wyższy niż w GA4/Meta; developer token musi pochodzić z produkcyjnego (nie testowego) MCC.

### c) Koszt: **darmowe** - dokumentacja nie przewiduje żadnych opłat za token ani wywołania; płaci się wyłącznie za kampanie.

## 4. Google Analytics 4 Data API

### a) Kroki dostępu (najprostsze z całej czwórki)

1. Projekt Google Cloud → włączyć **Google Analytics Data API**.
2. Utworzyć **service account** + wygenerować klucz JSON.
3. W GA4: Administracja → Zarządzanie dostępem do usługi → dodać e-mail service accounta z rolą **Przeglądający (Viewer)**.
4. Koniec - **zero review, zero OAuth, zero wygasających tokenów** (klucz JSON działa bezterminowo). Całość ~30 minut. Źródła: https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart , https://www.contentful.com/help/apps/google-analytics-4/google-analytics-service-account-setup/

### b) Limity i pułapki

- Kwoty tokenowe (standardowa usługa GA4): **200 000 tokenów/dzień/usługę**, 40 000/godz., 14 000/godz. na parę projekt-usługa; koszt zapytania rośnie z liczbą wierszy/wymiarów/zakresem dat. Przy tej skali ruchu praktycznie nieosiągalne; monitorować przez `returnPropertyQuota: true`. Źródło: https://developers.google.com/analytics/devguides/reporting/data/v1/quotas
- Świeżość danych: standardowe raporty przetwarzają się do 24-48 h (jest osobny endpoint Realtime); nie porównywać „dzisiaj" z panelem reklamowym.
- Ustawić w GA4 retencję danych zdarzeń na **14 miesięcy** (domyślnie 2!) - dotyczy eksploracji; agregaty przez Data API sięgają dalej, ale i tak warto regularnie zrzucać dane do własnej bazy.
- Warunek sensownego lejka: **dyscyplina UTM** we wszystkich kampaniach i postach (utm_source/medium/campaign), inaczej sesji nie da się przypiąć do kanałów.

### c) Koszt: **darmowe** (standardowa własność GA4; kwoty zamiast opłat).

## Rekomendowana kolejność wdrażania (od najłatwiejszej)

1. **GA4 Data API** - service account, bez review, bez wygasających tokenów; działa w dzień 1. Brak potrzeby fallbacku.
2. **Meta Marketing API** - bez review dla własnego konta, token systemowy bez wygasania; głównie praca konfiguracyjna w Business Managerze.
3. **Meta Graph API (organiczne FB/IG)** - technicznie prosta (ta sama aplikacja), ale wymaga budowy na nowym modelu metryk `views`/Page Viewer (po deprecjacjach 2025/2026) i natychmiastowej archiwizacji (retencja 2 lata, okna 90 dni). Wdrożyć wcześnie właśnie z powodu retencji.
4. **Google Ads API** - najtrudniejsza: MCC, developer token, OAuth z pułapką 7 dni, GAQL, ewentualny wniosek o Basic w warunkach backlogu. Łagodząca okoliczność 2026: domyślny **Explorer Access** zwykle wystarcza bez żadnego wniosku.

### Fallbacki (system użyteczny od pierwszego dnia)

- **Google Ads**: ręczny import **CSV** z panelu Google Ads (Raporty → eksport lub cykliczny raport e-mail) - endpoint w panelu przyjmujący CSV z kolumnami dzień/kampania/wyświetlenia/kliknięcia/koszt; te same tabele co przyszła integracja API, kolumna `source='csv_import'`.
- **Meta Ads** (gdyby konfiguracja Business Managera się przeciągała): eksport CSV z Menedżera reklam (raporty niestandardowe, także cykliczne na e-mail) do tego samego mechanizmu importu.
- **Meta organiczne**: eksport CSV z **Meta Business Suite** (Insights → eksportuj dane) dla postów FB/IG.
- Mechanizm importu CSV warto zbudować jako trwałą funkcję panelu (nie tymczasową) - służy też do backfillu historii sprzed uruchomienia integracji i jako plan B przy każdej awarii/deprecjacji API.

Sources:
- [Meta: Updates to Ads Management Standard Access (zmiany od 4.05.2026)](https://developers.meta.com/blog/updates-to-ads-management-standard-access-feature/)
- [Meta Marketing API - Authorization](https://developers.facebook.com/documentation/ads-commerce/marketing-api/get-started/authorization)
- [Meta - Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens)
- [Meta - System Users: generowanie tokenów](https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/)
- [Meta - Insights Limits & Best Practices](https://developers.facebook.com/docs/marketing-api/insights/best-practices/)
- [PPC Land - Meta ogranicza retencję w Ads Insights API](https://ppc.land/meta-restricts-attribution-windows-and-data-retention-in-ads-insights-api/)
- [Meta - Page Insights API Updates (deprecjacje 2025/2026)](https://developers.facebook.com/blog/post/2025/08/15/page-insights-api-updates/)
- [Windsor.ai - deprecjacja metryk organicznych FB 15.06.2026](https://windsor.ai/documentation/guide-for-deprecating-metrics-for-facebook-organic-connector-june-15-2026/)
- [Meta - Page/insights (retencja 2 lata, okno 90 dni)](https://developers.facebook.com/docs/graph-api/reference/insights/)
- [Meta - Instagram Insights](https://developers.facebook.com/docs/instagram-platform/insights/)
- [Google Ads API - Access Levels](https://developers.google.com/google-ads/api/docs/api-policy/access-levels)
- [Google Ads API - Developer Token](https://developers.google.com/google-ads/api/docs/api-policy/developer-token)
- [Google Ads Developer Blog - Explorer Access (10.2025)](https://ads-developers.googleblog.com/2025/10/explorer-access-is-now-available-for.html)
- [Google Ads Developer Blog - backlog wniosków (02.2026)](https://ads-developers.googleblog.com/2026/02/an-update-on-google-ads-api-developer.html)
- [Google Ads API - Common Errors (7-dniowy refresh token)](https://developers.google.com/google-ads/api/docs/get-started/common-errors)
- [Calibrate Analytics - 37-miesięczna retencja Google Ads od 06.2026](https://calibrate-analytics.com/insights/2026/05/05/Google-Ads-Announces-37-Month-Limit-for-Historical-Data-Retention/)
- [GA4 Data API - Quickstart](https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart)
- [GA4 Data API - Limits and Quotas](https://developers.google.com/analytics/devguides/reporting/data/v1/quotas)