# Projekt interfejsu (UI/UX) - panel analityczno-sprzedażowy z asystentem AI

## 0. Założenia projektowe

- Jeden użytkownik (właściciel), brak ról i uprawnień w UI - zero ekranów zarządzania użytkownikami.
- Desktop-first (praca biurowa na laptopie/monitorze), pełna używalność od 1280 px; na mniejszych ekranach degradacja kontrolowana (sekcja 2.3).
- Maks. ~100 zamówień/mies. → tabele bez wirtualizacji, prosta paginacja po 25 wierszy wystarcza; priorytetem jest czytelność, nie gęstość danych.
- Język UI wyłącznie polski; formaty: waluta `12 345,67 zł` (spacja jako separator tysięcy, przecinek dziesiętny), daty `19.07.2026`, data+czas `19.07.2026, 15:00`, procenty `4,2%`.
- Wszystkie kwoty w UI domyślnie **netto**; przy każdej kwocie brutto jawna etykieta „brutto". Przełącznik netto/brutto tylko w widoku szczegółów zamówienia.
- Jasny motyw jako domyślny i jedyny w MVP (jeden użytkownik, brak potrzeby utrzymywania dwóch motywów); tokeny kolorów projektowane tak, by dark mode dało się dodać później bez refaktoru.

---

## 1. Architektura informacji i nawigacja

### 1.1 Mapa widoków i routing

| Widok | Ścieżka | Ikona (lucide) | Badge w nawigacji |
|---|---|---|---|
| Dashboard | `/` | `layout-dashboard` | - |
| Skrzynka | `/skrzynka` | `inbox` | liczba szkiców do weryfikacji (np. `3`), czerwony |
| Zamówienia | `/zamowienia`, `/zamowienia/:id` | `shopping-cart` | - |
| Firmy B2B | `/firmy`, `/firmy/:id` | `building-2` | - |
| Marketing | `/marketing` (+ podzakładki `?kanal=meta|google|organic|ga4`) | `megaphone` | żółta kropka przy błędzie synchronizacji dowolnego kanału |
| Rekomendacje | `/rekomendacje` | `lightbulb` | liczba nieprzeczytanych rekomendacji, niebieski |
| Ustawienia | `/ustawienia` (+ zakładki) | `settings` | czerwona kropka przy błędnej konfiguracji (np. IMAP nie łączy) |

Kolejność w nawigacji jak wyżej - Skrzynka celowo tuż pod Dashboardem, bo to jedyny widok wymagający codziennej akcji użytkownika.

### 1.2 Nawigacja główna

- **Lewy sidebar stały**, szerokość 232 px, tło `#FFFFFF`, prawa krawędź `1px solid #E4E4E7`.
- Góra: logo/nazwa firmy (klik → Dashboard), pod spodem pionowa lista pozycji: ikona 20 px + etykieta, wysokość pozycji 40 px, zaokrąglenie 8 px, aktywna pozycja: tło `#EEF2FF`, tekst i ikona `#4F46E5`, pasek 3 px przy lewej krawędzi.
- Dół sidebaru (przyklejony): wskaźnik statusu synchronizacji zbiorczy - zielona kropka + „Synchronizacja OK, 15:32" lub czerwona + „Błąd: Meta Ads" (klik → `/ustawienia?tab=integracje`); pod nim pozycja „Ustawienia".
- Sidebar zwijany do 64 px (same ikony z tooltipami) przyciskiem chevron na dolnej krawędzi; stan zapamiętywany w `localStorage`.

### 1.3 Górny pasek (topbar)

Wysokość 56 px, obecny na każdym widoku:
- Lewa strona: tytuł bieżącego widoku (H1, 18 px/600) + breadcrumb przy widokach szczegółowych („Firmy B2B / Alfa Sp. z o.o.").
- Środek: **globalny selektor zakresu dat** (dotyczy Dashboardu i Marketingu; ukryty na pozostałych widokach) - dropdown z presetami: Dziś, Wczoraj, Ostatnie 7 dni, Ostatnie 30 dni (domyślny), Bieżący miesiąc, Poprzedni miesiąc, Bieżący kwartał, Bieżący rok, Zakres własny (dwukalendarzowy picker). Wybrany zakres widoczny zawsze, np. „Ostatnie 30 dni · 19.06-19.07.2026".
- Prawa strona: przycisk „+ Nowe zamówienie" (primary, otwiera formularz z sekcji 6), ikona dzwonka z listą alertów (te same co pasek alertów Dashboardu), przycisk przełączania panelu czatu AI (ikona `message-square`, ze skrótem widocznym w tooltipie: `Ctrl+K`).

---

## 2. Layout hybrydowy: dashboard + czat AI

### 2.1 Struktura strony

Trzy kolumny CSS grid: `[sidebar 232px] [treść 1fr, min 640px] [panel czatu 0 lub 420px]`.

- **Panel czatu AI: prawy, dokowany, zwijany.** Szerokość domyślna 420 px, zmienialna uchwytem (drag) w zakresie 360-560 px; szerokość zapamiętywana.
- Panel **dokuje się** (zwęża treść główną), a nie nakłada - użytkownik ma jednocześnie widzieć dashboard i rozmowę z AI (wymaganie hybrydowe: AI odwołuje się do danych, które użytkownik widzi obok).
- Otwieranie/zamykanie: przycisk w topbarze, skrót `Ctrl+K` (otwiera i ustawia fokus w polu wiadomości), `Esc` zamyka gdy fokus w panelu. Stan otwarcia zapamiętywany między sesjami.
- Panel utrzymuje **jedną ciągłą konwersację między widokami** - przełączenie widoku nie resetuje czatu.

### 2.2 Anatomia panelu czatu

Od góry:
1. Nagłówek 48 px: „Asystent AI" + ikona statusu (zielona: gotowy; animowana: odpowiada), przycisk „Nowa rozmowa" (ikona `plus`), menu `⋯` (Historia rozmów, Wyczyść), przycisk zwinięcia (chevron-right).
2. Obszar wiadomości (scroll, opis w sekcji 8).
3. Pasek szybkich pytań (chipy, sekcja 8.4).
4. Pole wprowadzania: textarea autorosnąca 1-6 linii, placeholder „Zapytaj o dane, np. »pokaż raport od czwartku od 15:00«", przycisk wyślij (ikona `send`), `Enter` wysyła, `Shift+Enter` nowa linia.

### 2.3 Zachowanie responsywne

- **≥ 1440 px:** pełny układ trzech kolumn.
- **1024-1439 px:** przy otwartym czacie sidebar automatycznie zwija się do 64 px; siatka dashboardu redukuje liczbę kolumn (sekcja 3.8).
- **768-1023 px (tablet):** czat przechodzi w tryb **overlay** - wysuwa się z prawej na 85% szerokości z półprzezroczystym scrimem `rgba(0,0,0,0.4)` nad treścią; sidebar tylko ikonowy.
- **< 768 px (telefon, użycie awaryjne):** sidebar zastąpiony dolnym paskiem 5 ikon (Dashboard, Skrzynka, Zamówienia, Czat, Więcej); czat jako pełnoekranowy widok; karty KPI w 2 kolumnach, tabele przewijane poziomo we własnym kontenerze. Pełna funkcjonalność edycyjna (weryfikacja maili, formularz zamówienia) dostępna, ale zoptymalizowana pod „podejrzeć i zatwierdzić", nie pod masową edycję.

---

## 3. Dashboard - dokładny układ

Siatka 12-kolumnowa, gutter 16 px, padding treści 24 px. Kolejność sekcji od góry:

### 3.1 Pasek alertów (wiersz 0, pełna szerokość)

Renderowany tylko gdy istnieją aktywne alerty; ułożone pionowo (maks. 3 widoczne + „pokaż wszystkie (n)").
- Struktura alertu: ikona ostrzeżenia, treść, przycisk akcji, przycisk „odłóż" (ukryj na 24 h), wysokość 44 px, zaokrąglenie 8 px.
- Poziomy: **błąd** (tło `#FEF2F2`, ramka `#FECACA`, ikona `#DC2626`) - np. „Synchronizacja Meta Ads nie działa od wczoraj, 14:20 - [Sprawdź połączenie]"; **ostrzeżenie** (tło `#FFFBEB`) - np. „3 maile czekają na weryfikację - [Przejdź do skrzynki]"; **informacja** (tło `#EFF6FF`) - np. „Nowa rekomendacja AI dot. kampanii - [Zobacz]".
- Przycisk akcji prowadzi zawsze do widoku rozwiązującego problem.

### 3.2 Karty KPI (wiersz 1)

Sześć kart, każda 2/12 szerokości (na węższych ekranach 3 kolumny × 2 rzędy, potem 2 × 3). Karta: wysokość 112 px, białe tło, ramka `1px #E4E4E7`, zaokrąglenie 12 px, padding 16 px. Zawartość karty:
- etykieta 12 px/500 `#71717A` z ikoną tooltipa „i" (definicja metryki, np. „CAC = wydatki na reklamy w okresie / liczba nowych klientów z tego okresu"),
- wartość 26 px/700 `#18181B`,
- delta vs poprzedni analogiczny okres: strzałka + procent, zielona `#16A34A` gdy korzystna, czerwona `#DC2626` gdy niekorzystna (uwaga: dla CAC spadek = zielony),
- mini-sparkline 40×24 px w prawym dolnym rogu.

Karty (dla zakresu z globalnego selektora): **1. Przychód netto**, **2. Liczba zamówień**, **3. Średnia wartość zamówienia (AOV netto)**, **4. CAC**, **5. LTV śr. (B2B)**, **6. ROAS** (łączny; w tooltipie rozbicie Meta/Google). Gdy metryki nie da się policzyć (np. brak wydatków reklamowych w okresie), wartość „-" z tooltipem wyjaśniającym.

### 3.3 Wykres przychodu w czasie (wiersz 2, kolumny 1-8)

- Karta wysokości 340 px. Nagłówek: „Przychód netto w czasie" + przełącznik granulacji (Dzień / Tydzień / Miesiąc - auto-dobór wg długości zakresu, ręcznie zmienialny) + przełącznik serii: checkboxy „Zamówienia (liczba)" (druga oś Y, linia przerywana) i „Podział na kanały" (stacked area zamiast pojedynczej linii: Meta Ads / Google Ads / Organiczny FB-IG / Wejścia bezpośrednie-inne / Telefon-stacjonarnie).
- Typ: wykres warstwowy (area) z gradientem pod linią; tooltip po najechaniu: data, wartość netto, liczba zamówień, rozbicie kanałów.
- Szara półprzezroczysta seria „poprzedni okres" do porównania (włączana checkboxem).

### 3.4 Lejek konwersji (wiersz 2, kolumny 9-12)

- Karta 340 px: „Lejek konwersji" + selektor kanału (Wszystkie / Meta Ads / Google Ads / Organiczny).
- Wizualizacja: **poziome pasy o malejącej szerokości** (nie klasyczny trójkąt - czytelniejsze etykiety), 4 poziomy: Wyświetlenia → Kliknięcia → Sesje → Zamówienia. Każdy pas: nazwa etapu, wartość bezwzględna (np. „41 200"), a **między pasami** strzałka z proporcją przejścia („CTR 2,4%", „78% kliknięć → sesja", „konwersja sesji 1,1%").
- Pod lejkiem wiersz podsumowania: „Konwersja całkowita: 0,021% · koszt zamówienia z reklam: 38,50 zł".
- Etap bez danych (np. brak wyświetleń dla kanału telefonicznego) - pas wyszarzony z etykietą „nie dotyczy".

### 3.5 Porównanie kanałów (wiersz 3, kolumny 1-7)

Karta z kompaktową tabelą, wiersz na kanał (Meta Ads, Google Ads, FB/IG organicznie, GA4-pozostały ruch, Telefon/stacjonarnie). Kolumny: Kanał (z kolorową kropką zgodną z serią wykresu), Wydatki, Sesje, Zamówienia, Przychód netto, ROAS, CAC. Sortowanie po kliknięciu nagłówka; najlepsza wartość w każdej kolumnie subtelnie podświetlona zielonym tłem `#F0FDF4`. Wiersz sumy na dole.

### 3.6 Top produkty (wiersz 3, kolumny 8-12)

Karta „Najlepsze produkty" - pozioma lista 5 pozycji: nazwa produktu, liczba sztuk, przychód netto, poziomy pasek proporcjonalny do przychodu (kolor `#4F46E5`, tło paska `#F4F4F5`). Przełącznik „wg przychodu / wg liczby sztuk". Link „Zobacz wszystkie" → Zamówienia z agregacją po produkcie.

### 3.7 Ostatnie zamówienia (wiersz 4, pełna szerokość)

Tabela 8 ostatnich zamówień (niezależnie od zakresu dat): Nr, Data, Klient (nazwa firmy z NIP-em w tooltipie lub imię i nazwisko B2C), Typ (badge `B2B`/`B2C`), Źródło (badge: `E-mail` / `Telefon` / `Stacjonarnie`), Kanał marketingowy (jeśli przypisany), Wartość netto, Status (Szkic / Potwierdzone / Zrealizowane / Anulowane - kolorowe kropki). Klik w wiersz → szczegóły zamówienia. Link „Wszystkie zamówienia →".

### 3.8 Redukcja na węższych ekranach

1024-1439 px: KPI 3×2; wykres przychodu pełna szerokość, lejek pod nim pełna szerokość; porównanie kanałów i top produkty jeden pod drugim. < 768 px: wszystko jednokolumnowo, KPI 2×3.

---

## 4. Skrzynka - weryfikacja maili

Najważniejszy widok operacyjny. Układ **master-detail** (split view).

### 4.1 Lewa kolumna - lista szkiców (320 px, scroll niezależny)

- Nagłówek: zakładki-filtry z licznikami: **Do weryfikacji (3)** (domyślna), **Niesparsowane (1)**, **Zatwierdzone**, **Odrzucone**; pole wyszukiwania po nadawcy/temacie.
- Element listy (wysokość ~88 px): nadawca (pogrubiony), temat, data otrzymania, **badge pewności parsowania**: `Wysoka` (zielony, mail z formularza - format rozpoznany), `Średnia` (żółty, wolny tekst - AI wyekstrahowało pola), `Niska` (czerwony, brakuje pól obowiązkowych); jeżeli rozpoznano firmę po NIP - mała ikona budynku + nazwa firmy.
- Zakładka „Niesparsowane": maile, z których nie udało się wyciągnąć zamówienia (np. zapytanie ofertowe) - akcje „Utwórz zamówienie ręcznie z tego maila" (prefill treścią) lub „Oznacz jako nie-zamówienie".

### 4.2 Prawa część - porównanie mail ↔ dane (dwa panele obok siebie)

**Panel „Oryginalny mail" (lewy, ~45%):** nagłówki (Od, Do, Data, Temat), treść w kontenerze monospaced/plain z zachowaniem łamania linii, załączniki jako chipy do pobrania. **Fragmenty, z których wyekstrahowano pola, podświetlone żółtym markerem** `#FEF08A`; najechanie na pole formularza w prawym panelu → odpowiedni fragment maila dostaje mocniejsze podświetlenie i scroll do niego (dwustronne wiązanie źródło↔pole - kluczowy mechanizm zaufania do parsera).

**Panel „Wyekstrahowane zamówienie" (prawy, ~55%):** edytowalny formularz - identyczny komponentowo z formularzem ręcznym (sekcja 6), z dodatkami:
- przy każdym polu mała ikona statusu ekstrakcji: ✓ zielona (pewne), ? żółta (do sprawdzenia - pole ma żółtą ramkę i wymaga kliknięcia/edycji przed zatwierdzeniem), ∅ szara (nie znaleziono w mailu - puste),
- sekcja „Dopasowanie klienta": jeśli NIP z maila pasuje do istniejącej firmy - zielony box „Rozpoznano: Alfa Sp. z o.o. (NIP 521-…) · 14 wcześniejszych zamówień · [Zobacz profil]"; jeśli NIP nowy - niebieski box „Nowa firma - profil zostanie utworzony automatycznie"; jeśli brak NIP - pole NIP puste z podpowiedzią „B2C lub uzupełnij NIP",
- pozycje zamówienia jako edytowalne wiersze (produkt - combobox z listy produktów + wpis wolny, ilość, cena jedn. netto, wartość), sumy: netto / VAT (stawka z ustawień, edytowalna per pozycja) / brutto.

**Pasek akcji (przyklejony do dołu prawej części):**
- `Zatwierdź zamówienie` - primary, duży; aktywny dopiero, gdy pola obowiązkowe wypełnione i żadne pole nie ma statusu „?" niepotwierdzonego; skrót `Ctrl+Enter`. Po zatwierdzeniu: toast „Zamówienie #124 utworzone", automatyczne przejście do następnego szkicu z listy (szybki przepływ seryjny).
- `Odrzuć` (secondary) → wybór powodu: „To nie zamówienie" / „Duplikat" / „Spam".
- `Zapisz szkic` (ghost) - zapis częściowej edycji bez zatwierdzania.

---

## 5. Zamówienia

### 5.1 Lista

- Pasek filtrów nad tabelą: zakres dat, Typ (B2B/B2C), Źródło (E-mail/Telefon/Stacjonarnie), Kanał marketingowy, Status, wyszukiwarka (nr, klient, NIP, produkt).
- Tabela: kolumny jak w 3.7 + kolumna akcji (menu `⋯`: Edytuj, Anuluj, Duplikuj). Suma netto przefiltrowanych zamówień w stopce tabeli. Paginacja po 25.
- Przycisk eksportu CSV nad tabelą (prawy róg).

### 5.2 Szczegóły zamówienia (`/zamowienia/:id`)

Dwie kolumny: lewa (8/12) - pozycje zamówienia (tabela: produkt, ilość, cena jedn. netto, stawka VAT, wartość netto/brutto), podsumowanie kwot, notatki; prawa (4/12) - karta klienta (link do profilu firmy przy B2B), metadane: źródło (przy mailowym - link „Pokaż oryginalny mail" otwierający podgląd w modalu), kanał marketingowy (edytowalny select - ręczna atrybucja np. „klient powiedział przez telefon, że z Facebooka"), status z historią zmian, daty.

---

## 6. Formularz ręcznego dodawania zamówienia

Otwierany jako **modal pełnowysokościowy z prawej strony (drawer 560 px)** z przycisku „+ Nowe zamówienie" - dostępny z każdego widoku bez utraty kontekstu. Sekcje od góry:

**1. Klient**
- Przełącznik segmentowy: `B2B` / `B2C` (domyślnie B2B).
- Przy B2B: pole **NIP z autouzupełnianiem** - po wpisaniu ≥ 3 znaków dropdown z pasującymi firmami z bazy („Alfa Sp. z o.o. · NIP 5213…, ostatnie zam. 02.07"); wybór wypełnia nazwę i dane firmy. NIP walidowany checksumą (błąd inline: „Nieprawidłowy NIP - sprawdź cyfry"). NIP spoza bazy → pola: Nazwa firmy (obowiązkowe), E-mail, Telefon + informacja „Zostanie utworzony nowy profil firmy". Dodatkowo pole „Osoba zamawiająca" (imię i nazwisko pracownika - buduje historię kontaktów w profilu firmy).
- Przy B2C: Imię i nazwisko (obowiązkowe), Telefon lub E-mail (min. jedno).

**2. Pozycje** - dynamiczna lista wierszy: Produkt (combobox: lista produktów z ustawień z cenami domyślnymi + opcja „dodaj nowy produkt" inline), Ilość (stepper), Cena jedn. netto (prefill z cennika, edytowalna), VAT (select 23%/8%/5%/0%, domyślna z ustawień), Wartość netto (liczona). Przycisk „+ Dodaj pozycję". Podsumowanie: Netto / VAT / Brutto - duże, na żywo. Alternatywny tryb „kwota łączna" (checkbox „bez rozbijania na pozycje"): jedno pole kwoty brutto lub netto + stawka VAT - dla szybkich wpisów telefonicznych.

**3. Szczegóły** - Źródło (segment: `Telefon` / `Stacjonarnie`; przy tworzeniu ze Skrzynki automatycznie `E-mail`, zablokowane), Data zamówienia (domyślnie teraz, edytowalna wstecz), Kanał marketingowy (select opcjonalny: Meta Ads / FB-IG organicznie / Google Ads / Polecenie / Inny / Nieznany - domyślnie Nieznany), Status (domyślnie Potwierdzone), Notatka (textarea).

**Stopka drawera (przyklejona):** `Zapisz zamówienie` (primary, `Ctrl+Enter`), `Zapisz i dodaj kolejne` (secondary - czyści formularz, zostawia drawer otwarty; scenariusz wpisywania kilku zamówień po dniu targowym), `Anuluj`. Próba zamknięcia z niezapisanymi danymi → dialog potwierdzenia.

---

## 7. Firmy B2B

### 7.1 Lista firm

Tabela: Nazwa, NIP, Liczba zamówień, **LTV** (suma netto od początku), **Częstotliwość** („co ~18 dni" - średni odstęp między zamówieniami; „-" przy < 2 zamówieniach), Ostatnie zamówienie (data + badge „ponad 60 dni temu" na czerwono - sygnał ryzyka utraty klienta), Śr. wartość zamówienia. Sortowanie domyślne po LTV malejąco. Wyszukiwarka po nazwie/NIP. Filtr „Nieaktywne > 60 dni".

### 7.2 Profil firmy (`/firmy/:id`)

- **Nagłówek:** nazwa firmy (H1), NIP z przyciskiem kopiowania, dane kontaktowe (e-maile i telefony zebrane ze wszystkich zamówień), przycisk „+ Nowe zamówienie" (prefill firmą), edycja danych.
- **Wiersz 4 kart KPI firmy:** LTV (netto), Liczba zamówień, Częstotliwość zakupów (śr. odstęp w dniach + trend „przyspiesza/zwalnia" wg porównania ostatnich 3 odstępów ze średnią), Śr. wartość zamówienia. Pod kartami dyskretna linia: „Klient od: 03.2025 · Pozyskany z: Google Ads · Przewidywane następne zamówienie: ~28.07" (data = ostatnie zamówienie + śr. odstęp).
- **Wykres:** słupkowy - wartość zamówień netto per miesiąc od początku współpracy.
- **Osoby kontaktowe:** lista osób zamawiających (imię i nazwisko / e-mail wyciągnięte z maili i wpisów ręcznych) z liczbą zamówień każdej - pokazuje, że NIP grupuje wielu pracowników.
- **Historia zamówień:** tabela wszystkich zamówień firmy (jak 5.1, bez kolumny klienta).
- **Notatki:** wolne pole tekstowe (np. „preferują odbiór osobisty, dzwonić po 12").

---

## 8. Czat AI - szczegóły

### 8.1 Wygląd wiadomości

- Wiadomości użytkownika: wyrównane do prawej, tło `#4F46E5`, tekst biały, zaokrąglenie 16 px (prawy dolny róg 4 px), maks. 85% szerokości panelu.
- Wiadomości asystenta: do lewej, tło `#F4F4F5`, tekst `#18181B`, zaokrąglenie 16 px (lewy dolny 4 px). Bez awatarów (zbędne przy dwóch stronach rozmowy), znacznik czasu 11 px `#A1A1AA` pod bąbelkiem.
- **Wskaźnik pracy narzędzi (tool use):** podczas generowania - pasek statusu nad polem odpowiedzi: „⚙ Pobieram zamówienia (17.07 15:00 - 19.07)…", kolejne kroki dopisują się jako lista zwijana do jednej linii „Wykonano 3 zapytania ▸" po zakończeniu (rozwijalna - transparentność tego, co AI policzyło).
- Odpowiedzi streamowane token po tokenie; przycisk „Zatrzymaj" podczas generowania.

### 8.2 Renderowanie treści odpowiedzi

Markdown: nagłówki, listy, pogrubienia. Ponadto:
- **Tabele:** pełna szerokość panelu, kompaktowe (wiersz 32 px), nagłówek przyklejony przy przewijaniu, wyrównanie liczb do prawej, przy > 5 kolumnach scroll poziomy wewnątrz bąbelka; nad tabelą pasek narzędzi: „Kopiuj", „Pobierz CSV", „Rozwiń" (modal pełnoekranowy z tabelą).
- **Mini-wykresy:** asystent może zwrócić prostą specyfikację wykresu (typ linia/słupki + dane), renderowaną tym samym komponentem co dashboard, wysokość 180 px; przycisk „Rozwiń".
- **Karty-odnośniki:** gdy AI wspomina konkretne zamówienie/firmę - inline chip „Zamówienie #124" / „Alfa Sp. z o.o." linkujący do widoku.
- Kwoty i procenty w odpowiedziach w formacie polskim (spójnie z resztą UI).

### 8.3 Historia rozmów

Menu `⋯` → „Historia": lista poprzednich rozmów (tytuł auto-generowany z pierwszego pytania, data), klik wczytuje rozmowę. „Nowa rozmowa" archiwizuje bieżącą.

### 8.4 Przyciski szybkich pytań

Rząd chipów nad polem wpisywania (scroll poziomy), **kontekstowe względem aktywnego widoku**:
- Dashboard: „Podsumuj ten tydzień", „Co się zmieniło vs poprzedni miesiąc?", „Który kanał ma najlepszy ROAS?"
- Skrzynka: „Streść maile czekające na weryfikację"
- Firmy: „Którzy klienci są zagrożeni odejściem?", „Top 5 firm wg LTV"
- Marketing: „Które posty najlepiej konwertowały?", „Porównaj Meta i Google Ads"
- Profil firmy: „Podsumuj historię tej firmy" (przekazuje kontekst `firma_id`).
Klik chipa = wysłanie pytania. Ostatni chip zawsze: „Pokaż przykłady pytań" → asystent wypisuje możliwości.

---

## 9. Marketing

Widok z zakładkami poziomymi pod topbarem: **Podsumowanie · Meta Ads · Google Ads · FB/IG organicznie · GA4 (ruch)**.

- **Podsumowanie:** tabela porównawcza kanałów (rozszerzona wersja 3.5) + wykres wydatki vs przychód per kanał w czasie + karta „Status synchronizacji" (per integracja: ostatnie udane pobranie, częstotliwość, przycisk „Synchronizuj teraz", stan błędu z treścią komunikatu).
- **Meta Ads / Google Ads:** karty KPI kanału (Wydatki, Wyświetlenia, Kliknięcia, CTR, CPC, Zamówienia przypisane, ROAS, CAC), tabela kampanii (nazwa, status, wydatki, wyświetlenia, kliknięcia, CTR, konwersje, ROAS) sortowalna, mini-lejek kanału (ten sam komponent co 3.4).
- **FB/IG organicznie:** lista postów jako karty w siatce 3-kolumnowej - miniatura, data, typ treści (badge: zdjęcie/wideo/karuzela/reels), zasięg, reakcje, kliknięcia linku, zaangażowanie %; sortowanie po zasięgu/zaangażowaniu; przy poście z rekomendacją AI - ikona żarówki.
- **GA4:** sesje wg źródło/medium (tabela), wykres sesji w czasie, konwersje zdarzeń formularza kontaktowego.

## 10. Rekomendacje

- Lista kart rekomendacji, najnowsze na górze. Karta: data, kategoria (badge: `Treści organiczne` / `Meta Ads` / `Google Ads` / `Ogólne`), tytuł-teza (np. „Karuzele produktowe konwertują 3× lepiej niż zdjęcia pojedyncze"), rozwijane uzasadnienie z danymi (tabelka/wartości, na których AI oparło wniosek - te same komponenty co w czacie), sugerowane działanie („Publikuj 2 karuzele tygodniowo zamiast pojedynczych zdjęć").
- Akcje na karcie: 👍 „Trafna" / 👎 „Nietrafna" (feedback zapisywany, wpływa na przyszłe rekomendacje), „Omów w czacie" (otwiera panel AI z prefill „Rozwiń rekomendację z 18.07 o karuzelach"), „Archiwizuj".
- Nagłówek widoku: informacja o cyklu („Rekomendacje generowane co poniedziałek, 8:00") + przycisk „Generuj teraz".

## 11. Ustawienia

Zakładki pionowe (lewa kolumna wewnątrz widoku): **Skrzynka e-mail** (IMAP: host, port, użytkownik, hasło - maskowane, folder, przycisk „Testuj połączenie" z wynikiem inline; reguły: które adresy nadawców traktować jako formularz), **Integracje** (Meta Ads, Google Ads, GA4 - status połączenia, klucze/OAuth, częstotliwość synchronizacji), **Asystent AI** (klucz API Anthropic - maskowany, wybór modelu, limit miesięczny kosztów z paskiem zużycia), **Produkty i ceny** (tabela produktów: nazwa, aliasy do parsera maili, cena domyślna netto, stawka VAT), **Firma** (dane własne, domyślna stawka VAT, waluta), **Kopie zapasowe** (ostatni backup, przycisk pobrania zrzutu).

---

## 12. Styl wizualny

### 12.1 Paleta

| Token | Hex | Zastosowanie |
|---|---|---|
| `primary` | `#4F46E5` (indygo) | akcje główne, aktywna nawigacja, wiadomości użytkownika, seria główna wykresów |
| `primary-hover` | `#4338CA` | hover przycisków |
| `primary-soft` | `#EEF2FF` | tła aktywnych elementów, podświetlenia |
| `background` | `#FAFAFA` | tło aplikacji |
| `surface` | `#FFFFFF` | karty, tabele, sidebar |
| `border` | `#E4E4E7` | ramki, separatory |
| `text` | `#18181B` | tekst główny |
| `text-muted` | `#71717A` | etykiety, opisy |
| `success` | `#16A34A` / tło `#F0FDF4` | wzrosty, statusy OK, badge Wysoka |
| `warning` | `#D97706` / tło `#FFFBEB` | ostrzeżenia, badge Średnia |
| `danger` | `#DC2626` / tło `#FEF2F2` | błędy, spadki, badge Niska |
| kanały (wykresy) | Meta `#2563EB`, Google `#EA580C`, Organiczny `#9333EA`, Bezpośredni `#0D9488`, Telefon/stacjonarnie `#64748B` | spójne kolory kanałów we WSZYSTKICH wykresach i kropkach tabel |

Zasada: kolor nigdy nie jest jedynym nośnikiem informacji (badge zawsze z tekstem, delty ze strzałką) - dostępność.

### 12.2 Typografia

- **Inter** (self-host przez `@fontsource/inter` - pełne polskie znaki diakrytyczne, doskonała czytelność liczb; bez zależności od Google Fonts CDN).
- Liczby w tabelach i KPI z `font-variant-numeric: tabular-nums` (równe kolumny cyfr).
- Skala: 26/700 (wartości KPI), 18/600 (H1 widoku), 15/600 (nagłówki kart), 14/400 (tekst podstawowy), 12/500 (etykiety, nagłówki tabel - uppercase, letter-spacing 0.04em), 11/400 (metadane).

### 12.3 Biblioteka komponentów: **shadcn/ui** (Tailwind + Radix)

Uzasadnienie: (1) komponenty kopiowane do repo - zero ryzyka porzucenia biblioteki i pełna kontrola nad stylami przy małym projekcie utrzymywanym latami; (2) Radix daje dostępność (fokus, klawiatura) bez pracy; (3) zawiera wszystko, czego potrzebuje ten UI: Dialog/Drawer (formularz zamówienia), Command (autouzupełnianie NIP - komponent `Combobox`), DataTable na TanStack Table, Toast, Tabs, DatePicker (react-day-picker); (4) naturalna para z React + Vite z proponowanego stacku; (5) estetyka domyślna bliska projektowanej (neutralne szarości Zinc + jeden akcent). Mantine jest pełnoprawną alternatywą (bogatszy DatePicker „out of the box"), ale narzuca własny system stylowania i cięższy runtime - przy panelu dla jednej osoby przewaga kontroli shadcn wygrywa.

### 12.4 Biblioteka wykresów: **Recharts**

Uzasadnienie: (1) deklaratywne komponenty React - wykres przychodu, sparkline'y, słupki i lejek (poziome pasy = `BarChart` layout="vertical") pokrywają 100% potrzeb; (2) najmniejszy próg wejścia i najłatwiejsze utrzymanie; (3) łatwe współdzielenie komponentu wykresu między dashboardem a odpowiedziami czatu AI (sekcja 8.2); (4) shadcn/ui ma gotową warstwę `Chart` opartą właśnie o Recharts (spójne tooltipzy i legendy z resztą UI). Odrzucone: ECharts (potężny, ale imperatywny i ciężki - nadmiarowy przy tej skali), Chart.js (canvas - gorsza integracja z Reactem i tooltipami DOM), d3 bezpośrednio (koszt utrzymania).

### 12.5 Pozostałe tokeny

Zaokrąglenia: 8 px (kontrolki), 12 px (karty), 16 px (bąbelki czatu). Cienie: karty bez cienia (ramka wystarcza), elementy pływające (dropdown, drawer, toast) `0 4px 16px rgba(0,0,0,0.08)`. Odstępy: skala 4 px (4/8/12/16/24/32). Ikony: lucide-react, 20 px w nawigacji, 16 px w tabelach i przyciskach.

---

## 13. Stany brzegowe (wymagane w makietach)

- **Puste stany** (pierwsze uruchomienie): Dashboard - ilustracja + „Brak danych. Skonfiguruj skrzynkę e-mail i integracje, aby zobaczyć statystyki. [Przejdź do ustawień]"; Skrzynka - „Wszystko zweryfikowane ✓" (stan pożądany, pozytywny komunikat); Firmy - „Profile firm utworzą się automatycznie z zamówień z NIP-em".
- **Ładowanie:** skeletony w kształcie docelowych komponentów (karty KPI, wiersze tabel, obszar wykresu) - bez spinnerów pełnoekranowych.
- **Błędy danych:** karta z komunikatem inline „Nie udało się pobrać danych Meta Ads - pokazuję ostatnie dostępne (z 18.07, 14:00). [Ponów]" - nigdy pusta biała karta.
- **Częściowa świeżość:** przy danych z synchronizacji cyklicznej każda karta kanału ma znacznik „stan na 15:32" w rogu.
- **Czat offline / brak klucza API:** panel czatu pokazuje stan „Asystent niedostępny - sprawdź klucz API w ustawieniach", reszta panelu działa normalnie (dashboard nie zależy od AI).