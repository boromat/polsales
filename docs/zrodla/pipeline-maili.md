# Pipeline przetwarzania maili z zamówieniami - specyfikacja techniczna (materiał surowy)

## 0. Architektura ogólna toru

```
IMAP (skrzynka na własnej domenie)
   │  polling co 2 min (APScheduler)
   ▼
[1] Ingest: pobranie nowych maili (UID > last_seen_uid) → zapis surowego maila do DB (tabela emails, status=odebrany)
   ▼
[2] Pre-klasyfikacja regułowa (zero kosztu): spam/newsletter/auto-reply → status=odrzucony_automatycznie
   ▼
[3] Router parsowania:
      ├─ mail z formularza (wykryty po nadawcy+temacie+markerach) → parser regułowy
      └─ wolny tekst → ekstrakcja Claude (structured output JSON)
   ▼
[4] Walidacja + dopasowanie produktów do katalogu (fuzzy matching) + dopasowanie firmy po NIP
   ▼
[5] Szkic zamówienia w kolejce rewizji (status=do_weryfikacji) → panel → zatwierdzone / odrzucone
```

Każdy etap zmienia wyłącznie status rekordu w DB - pipeline jest wznawialny po restarcie z dowolnego miejsca, bo stan nie żyje w pamięci procesu.

---

## (a) Polling IMAP

**Biblioteka:** `imap-tools` (Python; wysokopoziomowy wrapper na `imaplib` ze stdlib, dojrzała, bez zależności natywnych). Alternatywa `imapclient` - również akceptowalna; nie używać surowego `imaplib` (obsługa literałów i kodowań jest błędogenna). IMAP IDLE (push) jest zbędny przy 100-150 mailach/mies. - polling wystarcza i jest odporniejszy na zrywanie połączeń przez tani hosting poczty.

**Częstotliwość:** zadanie APScheduler co **2 minuty** (typ `interval`, `max_instances=1`, `coalesce=True` - żeby zaległe uruchomienia po przestoju nie odpalały się równolegle). Zamówienie mailowe nie wymaga reakcji w sekundach; 2 min to dobry kompromis między świeżością a obciążeniem serwera poczty.

**Folder:** czytamy wyłącznie `INBOX`. Po pomyślnym zapisaniu do DB mail jest **kopiowany do folderu `Przetworzone`** (IMAP COPY + flaga `\Seen`), a przy błędzie krytycznym do `Bledy_importu`. Skrzynka pozostaje źródłem prawdy - nigdy nie kasujemy maili (EXPUNGE zabroniony).

**Idempotencja i odporność na restart (kluczowy mechanizm):**

1. **Stan kursora:** tabela `imap_state` przechowuje parę `(uidvalidity, last_seen_uid)`. Przy każdym połączeniu:
   - odczyt `UIDVALIDITY` folderu; jeśli różni się od zapisanego → serwer przenumerował skrzynkę → reset kursora i pełna resynchronizacja z deduplikacją po `Message-ID` (patrz pkt 3),
   - pobranie `UID SEARCH UID last_seen_uid+1:*`.
2. **Kolejność zapisu (at-least-once + dedup = exactly-once w skutkach):** najpierw `INSERT` surowego maila do tabeli `emails` **w transakcji**, dopiero po commit podbicie `last_seen_uid`. Jeśli proces padnie między insertem a podbiciem kursora, mail zostanie pobrany ponownie - i odbije się od unikalności (pkt 3). Żaden mail nie ginie; żaden nie jest przetworzony dwa razy.
3. **Deduplikacja twarda w DB:**
   - `UNIQUE (uidvalidity, uid)` - dedup na poziomie transportu,
   - `UNIQUE (message_id_hash)` - SHA-256 znormalizowanego nagłówka `Message-ID`; łapie przypadki resynchronizacji po zmianie `UIDVALIDITY` oraz mail wysłany do dwóch aliasów tej samej skrzynki. Maile bez `Message-ID` (rzadkie, ale legalne): hash z `(from, date, sha256(body))`.
   - Konflikt unikalności = `ON CONFLICT DO NOTHING` + log DEBUG, nie błąd.
4. **Flagi IMAP nie są źródłem prawdy** - `\Seen` ustawiamy tylko informacyjnie; wznowienie po restarcie opiera się wyłącznie o DB.

**Tabela `emails` (szkic):** `id, uidvalidity, uid, message_id_hash, from_addr, subject, date_received, raw_headers, body_text, body_html, has_attachments, attachment_meta jsonb, in_reply_to, references_ids text[], status, error_detail, created_at`.

**Statusy maila:** `odebrany → sklasyfikowany → sparsowany → zamowienie_utworzone` | `odrzucony_automatycznie` | `blad_parsowania` | `duplikat`.

---

## (b) Klasyfikacja „zamówienie / nie-zamówienie" - tani lejek odsiewu

Zasada: **AI dotyka maila dopiero wtedy, gdy tanie reguły nie dały werdyktu.** Kolejność filtrów (pierwszy pasujący kończy):

1. **Twarde odrzucenie po nagłówkach (koszt ~0):**
   - `List-Unsubscribe` obecny → newsletter,
   - `Precedence: bulk|list|junk`, `Auto-Submitted: auto-generated|auto-replied` → automat/autoresponder,
   - `X-Spam-Flag: YES` / wynik SpamAssassina z serwera poczty powyżej progu → spam,
   - nadawca na czarnej liście domen (utrzymywanej w panelu: no-reply@, newsletter@, znane domeny marketingowe).
2. **Twarda akceptacja - mail z formularza strony:** rozpoznanie po stałym nadawcy (np. `formularz@domena.example`), stałym prefiksie tematu (np. `[Zamówienie ze strony]`) i markerze w treści. Trafia od razu do parsera regułowego, z pominięciem dalszej klasyfikacji.
3. **Biała lista klientów:** nadawca (lub domena nadawcy) występuje już w tabeli firm/klientów → kieruj do ekstrakcji AI bez klasyfikacji (klient piszący ponownie prawie na pewno pisze w sprawie zamówienia lub zamówienia dotyczącej - a fałszywy pozytyw i tak zatrzyma się na ręcznej weryfikacji).
4. **Heurystyka słów kluczowych (koszt ~0):** prosty scoring na lematach/frazach PL: „zamawiam", „zamówienie", „proszę o wycenę", „sztuk", „szt.", „faktura", „NIP", „dostawa", nazwy produktów z katalogu (dopasowanie trigramowe). Score ≥ próg → do ekstrakcji AI; score ≈ 0 i brak sygnałów → `odrzucony_automatycznie` (z podglądem w panelu - nic nie znika bezpowrotnie).
5. **Strefa szara → klasyfikacja nie jest osobnym wywołaniem AI.** Zamiast oddzielnego calla klasyfikującego, mail ze strefy szarej idzie do tego samego wywołania ekstrakcji Claude, którego schemat wyjścia zawiera pole `is_order`. Jedno wywołanie realizuje klasyfikację + ekstrakcję - przy tym wolumenie to tańsze i prostsze niż dwustopniowy tor.

Wszystkie decyzje filtrów logowane w `emails.status` + `emails.classification_reason` (audytowalność: właściciel widzi w panelu, dlaczego mail odpadł, i może go ręcznie przywrócić do przetworzenia).

---

## (c) Parsowanie hybrydowe

### c.1. Parser regułowy - maile z formularza strony

- Formularz na stronie generuje mail o stałej strukturze - parser to zestaw regexów/parsowania liniowego na etykiety pól (`Imię i nazwisko:`, `Firma:`, `NIP:`, `Telefon:`, `Zamawiane produkty:` itd.).
- **Wersjonowanie szablonu:** w treści maila generowanego przez formularz umieścić ukryty marker wersji (np. `X-Form-Version: 2` w nagłówku lub stopka `[form-v2]`). Parser trzyma słownik `wersja → zestaw reguł`. Zmiana formularza na stronie = nowa wersja parsera, stare maile dalej parsowalne.
- **Degradacja do AI:** jeśli parser regułowy nie wyprodukuje kompletu pól obowiązkowych (np. ktoś zmodyfikował szablon, mail przeszedł przez forward i stracił formatowanie) → mail przechodzi na tor ekstrakcji Claude z flagą `parser_fallback=true`. Nigdy nie kończymy twardym błędem tylko dlatego, że regex nie zadziałał.
- Wynik parsera regułowego dostaje `confidence=1.0` i `extraction_method="reguly"`.

### c.2. Ekstrakcja Claude - wolny tekst

**Model - rekomendacja:** `claude-haiku-4-5` (1,00 USD / 1M tokenów wejścia, 5,00 USD / 1M wyjścia; kontekst 200K, wspiera structured outputs / strict tool use). Uzasadnienie: ekstrakcja pól z krótkiego polskiego maila to zadanie o niskiej złożoności rozumowania; o jakość wyniku i tak dba obowiązkowa ręczna weryfikacja (etap d), więc płacenie za wyższy tier nie kupuje niczego, czego lejek nie łapie. **Ścieżka eskalacji:** wywołania z `confidence < 0.5` lub z błędem walidacji schematu ponawiać na `claude-sonnet-4-6` (3/15 USD za 1M) - przy tym wolumenie dotyczy pojedynczych maili miesięcznie. (Domyślnym modelem najwyższej jakości w API jest `claude-opus-4-8`, 5/25 USD za 1M - można go wskazać jako model eskalacji zamiast Sonneta, różnica kosztowa przy tych wolumenach jest pomijalna; decyzję zostawić właścicielowi jako parametr konfiguracyjny.)

**Technika wywołania:** oficjalne SDK Pythona (`anthropic`), **structured outputs** - `client.messages.parse(...)` z modelem Pydantic (SDK samo waliduje odpowiedź względem schematu) lub `output_config={"format": {"type": "json_schema", "schema": ...}}` na `messages.create()`. Nie prosić o JSON „prozą" w promptcie - wymuszenie schematu eliminuje całą klasę błędów parsowania. `max_tokens` ok. 2000. System prompt stały (nazwa firmy, branża, instrukcja ekstrakcji, dzisiejsza data przekazywana w treści user-message, nie w system prompcie - ze względu na przyszły prompt caching).

**Dokładny schemat JSON wyjścia:**

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["is_order", "confidence", "products", "customer", "notes", "ambiguities"],
  "properties": {
    "is_order": {
      "type": "boolean",
      "description": "true, jeśli mail jest zamówieniem lub konkretnym zapytaniem zakupowym; false dla reklamacji, pytań ogólnych, spamu"
    },
    "confidence": {
      "type": "number",
      "description": "Pewność całości ekstrakcji w skali 0-1 (0.0, 0.1, ... 1.0)"
    },
    "order_type": {
      "type": "string",
      "enum": ["zamowienie", "zapytanie_ofertowe", "modyfikacja_zamowienia", "inne"],
      "description": "Charakter wiadomości"
    },
    "products": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["raw_name", "quantity", "unit", "confidence"],
        "properties": {
          "raw_name": { "type": "string", "description": "Nazwa produktu dokładnie tak, jak napisał klient" },
          "quantity": { "type": ["number", "null"], "description": "Ilość; null jeśli nie podano" },
          "unit": { "type": ["string", "null"], "description": "Jednostka podana przez klienta: szt, kg, opak, m itp.; null jeśli brak" },
          "variant_notes": { "type": ["string", "null"], "description": "Kolor, rozmiar, wariant, jeśli wskazano" },
          "confidence": { "type": "number", "description": "Pewność 0-1 dla tej pozycji" }
        }
      }
    },
    "customer": {
      "type": "object",
      "additionalProperties": false,
      "required": ["company_name", "contact_person", "email", "phone", "nip", "delivery_address"],
      "properties": {
        "company_name": { "type": ["string", "null"] },
        "contact_person": { "type": ["string", "null"] },
        "email": { "type": ["string", "null"], "description": "Jeśli w treści podano inny niż adres nadawcy" },
        "phone": { "type": ["string", "null"], "description": "W formacie takim, jak podał klient" },
        "nip": { "type": ["string", "null"], "description": "Wyłącznie cyfry, bez prefiksu PL i separatorów; null jeśli nie podano - NIE zgadywać" },
        "delivery_address": { "type": ["string", "null"] }
      }
    },
    "requested_delivery_date": { "type": ["string", "null"], "description": "Termin dostawy/realizacji, jeśli podano; ISO 8601 lub opis słowny" },
    "notes": { "type": ["string", "null"], "description": "Istotne uwagi klienta niepasujące do pól powyżej" },
    "ambiguities": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Lista niejasności wymagających decyzji człowieka, po polsku, np. 'klient nie podał ilości dla pozycji X'"
    }
  }
}
```

Zasady w promptcie: nie wymyślać danych (brak = `null`), NIP tylko jeśli literalnie występuje w treści/stopce, pozycje produktowe rozbijać 1:1 bez agregowania, `ambiguities` wypełniać agresywnie - to jest wsad do UI weryfikacji. Do wywołania wchodzi: treść tekstowa maila (HTML konwertowany do tekstu), temat, adres i nazwa nadawcy, data. Obcięcie ogona cytowań (poprzednich wiadomości w wątku) przed wysłaniem - patrz (e).

**Walidacja po stronie kodu (nie ufać ślepo):** NIP - walidacja sumy kontrolnej (waga 10-cyfrowa); telefon - normalizacja do E.164 (`phonenumbers`, region PL); e-mail - walidacja składniowa. Nieprzechodzące walidacji pola nie są odrzucane, tylko flagowane w rekordzie do weryfikacji.

---

## (d) Kolejka rewizji i dopasowanie do katalogu

**Model danych:** `orders_draft` (szkice) - `id, email_id FK, extraction_method (reguly|ai), extraction_confidence, raw_extraction jsonb, status, company_id FK nullable, created_at, reviewed_at, reviewed_note` + `order_draft_items` - `id, draft_id FK, raw_name, quantity, unit, matched_product_id FK nullable, match_score, match_status (auto|zasugerowane|reczne|brak), variant_notes`.

**Statusy szkicu:** `nowy → do_weryfikacji → zatwierdzone | odrzucone`. Przejście `nowy → do_weryfikacji` wykonuje pipeline automatycznie po dopasowaniu produktów i firmy; `do_weryfikacji → zatwierdzone/odrzucone` wykonuje wyłącznie człowiek w panelu (jeden klik po sprawdzeniu). Zatwierdzenie tworzy właściwy rekord w `orders` (tabela transakcyjna, na której liczą się metryki LTV/CAC) - szkice nigdy nie wchodzą do metryk.

**Dopasowanie firmy po NIP:** jeśli ekstrakcja dała NIP z poprawną sumą kontrolną → lookup w tabeli `companies` po NIP; brak → propozycja utworzenia nowej firmy (do potwierdzenia w panelu). Jeśli NIP-u brak, dopasowanie pomocnicze po domenie e-mail nadawcy (z wykluczeniem domen publicznych: gmail.com, wp.pl, o2.pl, interia.pl, onet.pl) - zawsze tylko jako **sugestia**, nigdy automat.

**Fuzzy matching produktów (dwuwarstwowy):**

1. **Warstwa aliasów (uczenie się z korekt):** tabela `product_aliases` - `raw_name_normalized → product_id`, zasilana automatycznie przy każdej ręcznej korekcie w panelu. Dokładne trafienie w alias = dopasowanie pewne (`match_status=auto`, score 100). Po kilku tygodniach pracy większość powtarzalnych sformułowań klientów trafia w tę warstwę i fuzzy nie jest już potrzebny.
2. **Warstwa fuzzy:** `rapidfuzz` (`token_set_ratio` + `partial_ratio`, max z obu) na znormalizowanych nazwach (lowercase, usunięcie polskich znaków diakrytycznych do porównania, usunięcie interpunkcji) przeciwko nazwom + aliasom całego katalogu; dodatkowo indeks `pg_trgm` w PostgreSQL do preselekcji kandydatów, jeśli katalog > ~1000 pozycji. Progi:
   - **≥ 92** → dopasowanie automatyczne (`auto`), ale wciąż widoczne i edytowalne w widoku weryfikacji,
   - **70-91** → `zasugerowane`: dropdown z top-5 kandydatami posortowanymi po score,
   - **< 70** → `brak`: pole wyszukiwania po katalogu; wybór człowieka zapisuje nowy alias.

**UI weryfikacji (wymagania funkcjonalne):** widok szkicu = po lewej surowa treść maila (z podświetleniem, skąd co wyekstrahowano - na v1 wystarczy sama treść), po prawej formularz pozycji + dane firmy; pola z `confidence < 0.7` i wpisy z `ambiguities` wyróżnione kolorem; edycja każdego pola; przyciski Zatwierdź/Odrzuć (odrzucenie z opcjonalnym powodem). Licznik szkiców `do_weryfikacji` widoczny w nagłówku panelu.

---

## (e) Obsługa błędów i przypadków brzegowych

**Mail nieparsowalny:** wyjątek na dowolnym etapie → `emails.status=blad_parsowania` + pełny traceback w `error_detail` + mail widoczny w panelu w zakładce „Błędy" z surową treścią i przyciskiem „Utwórz zamówienie ręcznie" oraz „Ponów przetwarzanie". Błędy API Claude (429/5xx/timeout): retry z wykładniczym backoffem (SDK robi to domyślnie, `max_retries=4`); po wyczerpaniu - status błędu i automatyczny ponowny przebieg przy następnym ticku schedulera (maile w `blad_parsowania` z licznikiem prób < 5 wracają do kolejki). Zero cichych zgubień.

**Załączniki:** v1 - **nie parsujemy treści załączników.** Zapisujemy metadane (nazwa, typ MIME, rozmiar) w `attachment_meta`, plik składujemy na dysku (`/data/attachments/{email_id}/`), w panelu pokazujemy listę z możliwością pobrania, a szkic dostaje flagę `ma_zalaczniki` (podpowiedź dla weryfikującego: „zamówienie może być w załączniku"). Rozszerzenie w v2: PDF-y przez Claude API (natywne wejście PDF), po zmierzeniu, jak często zamówienia faktycznie przychodzą w załącznikach.

**Wątki i odpowiedzi:** przed utworzeniem szkicu sprawdzamy `In-Reply-To`/`References` przeciwko `message_id` wcześniej przetworzonych maili. Jeśli mail jest odpowiedzią w wątku, z którego już powstało zamówienie → **nie tworzymy nowego szkicu automatycznie**; mail dostaje status `odpowiedz_w_watku`, jest podpinany do istniejącego zamówienia jako notatka/korespondencja i podbija flagę „nowa wiadomość w wątku" na zamówieniu (właściciel decyduje: modyfikacja zamówienia czy zwykła korespondencja; pole `order_type=modyfikacja_zamowienia` z ekstrakcji jest tu podpowiedzią). Dodatkowo przed wysłaniem treści do Claude odcinamy cytowania (linie od `>`, bloki „Dnia ... napisał(a):", `-----Original Message-----`) - do modelu idzie tylko nowa treść.

**Duplikaty zamówień (poza dedupem Message-ID):** heurystyka miękka - przy tworzeniu szkicu porównanie z zamówieniami tego samego nadawcy/NIP z ostatnich 72 h; zgodność zbioru pozycji ≥ 80% → ostrzeżenie „możliwy duplikat zamówienia #X" na szkicu (klient wysłał to samo drugi raz „dla pewności", forward od wspólnika itd.). Decyzja zawsze po stronie człowieka - automat nigdy nie odrzuca.

---

## (f) Bezpieczeństwo poświadczeń IMAP

- Konto pocztowe dedykowane lub **hasło aplikacyjne** (jeśli hosting poczty wspiera) - nie główne hasło skrzynki właściciela; konto z minimalnymi uprawnieniami (sama skrzynka, bez panelu administracyjnego domeny).
- Połączenie wyłącznie **IMAPS (port 993, TLS)** z weryfikacją certyfikatu; jawny zakaz STARTTLS-fallback na plaintext.
- Poświadczenia w **Docker Compose secrets** (plik `secrets/imap_password` montowany jako `/run/secrets/...`, czytany przez aplikację z pliku) lub minimalnie w pliku `.env` poza repozytorium (`.gitignore`), z uprawnieniami `600`, właściciel = użytkownik usługi. Nigdy w obrazie, nigdy w repo, nigdy w logach (maskowanie w logerze).
- Ten sam mechanizm dla klucza `ANTHROPIC_API_KEY` i haseł DB.
- Backup skrzynki nie jest zadaniem aplikacji - aplikacja niczego nie kasuje, więc skrzynka + kopie DB z VPS wystarczają jako redundancja.
- Rotacja: procedura opisowa w README (zmiana hasła w panelu poczty → podmiana sekretu → `docker compose up -d`); brak automatyzacji na v1.

---

## (g) Szacunkowy koszt Claude API (100-150 maili/mies.)

Założenia: ~150 maili/mies. wchodzących w pipeline; po filtrach regułowych do AI trafia realnie 60-100 (reszta: formularz → parser regułowy za darmo, spam/newslettery → odsiew za darmo); liczymy pesymistycznie **150 wywołań/mies.** (wszystkie maile + retraje). Rozmiar wywołania: system prompt + schemat ~1500 tok., treść maila ~800 tok. → ~2300 tok. wejścia; wyjście ~500 tok.

| Pozycja | Haiku 4.5 (rekomendowany) | Sonnet 4.6 (eskalacja) | Opus 4.8 (referencyjnie) |
|---|---|---|---|
| Cena wejście / 1M tok. | 1,00 USD | 3,00 USD | 5,00 USD |
| Cena wyjście / 1M tok. | 5,00 USD | 15,00 USD | 25,00 USD |
| Wejście: 150 × 2300 = 345K tok. | 0,35 USD | 1,04 USD | 1,73 USD |
| Wyjście: 150 × 500 = 75K tok. | 0,38 USD | 1,13 USD | 1,88 USD |
| **Miesięcznie (ekstrakcja maili)** | **~0,73 USD** | **~2,17 USD** | **~3,61 USD** |

Wnioski: koszt ekstrakcji maili jest **pomijalny (< 1 USD/mies. na Haiku 4.5, < 4 USD/mies. nawet na Opusie)** i nie jest czynnikiem decyzyjnym architektury. Realnym kosztem Claude API w całym systemie będzie **asystent-analityk w panelu** (długie konteksty z danymi, tool use, wielokrotne tury) - to tam należy planować budżet i prompt caching, nie w pipelinie mailowym. Uwaga praktyczna do cache'owania w pipelinie: minimalny cache'owalny prefiks dla Haiku 4.5 to 4096 tokenów - przy krótkim promptcie systemowym cache się nie aktywuje, co przy tym koszcie nie ma znaczenia; nie komplikować.

**Parametry wywołania (do implementacji):** SDK `anthropic` (Python), `model="claude-haiku-4-5"`, structured output przez `client.messages.parse()` + model Pydantic (lub `output_config.format` z powyższym JSON Schema), `max_tokens=2000`, bez parametrów samplingu, retry SDK domyślne + własny licznik prób w DB; eskalacja przy `confidence < 0.5` na model skonfigurowany w ustawieniach (`claude-sonnet-4-6` domyślnie).