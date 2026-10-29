# Mapy z retencją, przywracanie przez wklejenie, poprawki w podglądzie, aktualizacje modeli

Zlecenie właściciela 2026-10-29 07:40 (todo.md). Projekt spisany przed kodem.

## 1. Jak to wygląda dla użytkownika

1. Użytkownik wkleja pismo i klika „Ukryj dane”. Program **sam zapisuje zaszyfrowaną mapę** w katalogu
   danych programu. Nie trzeba niczego pobierać ani pilnować pliku.
2. Kopiuje wynik do czatu AI i dostaje odpowiedź ze znacznikami `[OSOBA_1]`.
3. Na zakładce „Przywróć” **wkleja odpowiedź**. Program bierze mapę po identyfikatorze z dopisku.
   Gdy czat dopisek zgubił, program proponuje ostatnie zadanie z listy („dziś 7:41, 3 osoby, 1 PESEL”),
   a użytkownik może wybrać inne. Wynik od razu widać z przyciskiem „Kopiuj”.
4. Plik mapy (.nwidka) nadal da się pobrać, np. do akt sprawy. To opcja, nie obowiązek.
5. Po terminie retencji mapa **znika sama**. Od tej chwili nie przywróci danych także jej pobrana kopia,
   bo program skreśla ją z rejestru wydanych map.

## 2. Magazyn map i retencja (RODO)

- Miejsce: `<katalog danych>/mapy/` (Windows `%LOCALAPPDATA%\Niewidka\mapy`). Na każde zadanie dwa pliki:
  `<id>.nwidka` (szyfrogram AES-256-GCM, jak dziś) i `<id>.json` (metadane bez danych osobowych:
  utworzono, wygasa, poziom, liczby per typ). Zapis atomowy, na POSIX uprawnienia 0600.
- Klucz zostaje w magazynie systemowym (keyring) albo pliku sekretów. Kradzież katalogu `mapy` bez
  klucza nie ujawnia danych.
- Konfiguracja (TOML `[mapy]` albo env):
  - `retencja_dni` / `NIEWIDKA_MAPY_RETENCJA_DNI`, domyślnie **30**. `0` = nie zapisuj automatycznie
    (zostaje tylko pobranie pliku, jak dziś). Wartość ustawia organizacja zgodnie ze swoim okresem
    przechowywania.
  - `katalog` / `NIEWIDKA_MAPY_KATALOG`, domyślnie `<katalog danych>/mapy`.
- Usuwanie po terminie: przy starcie i przy każdym wywołaniu ukryj/przywróć/lista.
  SIMPLIFICATION: bez stałego zegara w tle; program wyłączony nie sprząta, ale sprząta przy następnym
  starcie, zanim cokolwiek przywróci. Kiedy rozbudować: wersja serwerowa działająca miesiącami bez ruchu.
- Usunięcie (po terminie albo ręczne) skreśla mapę z rejestru wydanych map (`wydane-mapy.jsonl`
  przepisany bez niej), więc pobrane kopie też przestają działać.
- Dziennik zdarzeń `mapy/dziennik.jsonl` do audytu: czas, zdarzenie (`utworzono`, `przywrocono`,
  `usunieto`, `wygasla`), skrót identyfikatora (12 znaków), poziom, liczby per typ. **Żadnych danych
  osobowych, nazw plików ani treści.**
- Ustawienia: sekcja „Zapisane mapy”: lista (data, liczby per typ, data usunięcia), przycisk „Usuń”
  przy każdej i „Usuń wszystkie”, zdanie o okresie przechowywania.

## 3. API

- `POST /api/ukryj`: bez zmian w odpowiedzi; dodatkowo zapis do magazynu (gdy retencja > 0).
  Nagłówek `x-niewidka-mapa-zapisana: <data wygaśnięcia ISO>` albo brak.
- `POST /api/przywroc`: `wynik` (plik) **albo** `tekst` (pole formularza); `mapa` (plik) opcjonalna;
  `identyfikator` opcjonalny (wybór z listy). Kolejność: plik mapy → identyfikator z dopisku w tekście →
  pole `identyfikator`. Dopisek i pole wskazują różne mapy = 422. Nic nie wskazuje mapy = 422
  `{"kod": "wybierz_mape"}`. Dla `tekst` odpowiedź `text/plain; charset=utf-8`.
- `GET /api/mapy` → `{"retencja_dni": N, "mapy": [{id, utworzono, wygasa, poziom, statystyki}]}`
  od najnowszej. `id` to pełny identyfikator (potrzebny do wyboru); to nie jest dana osobowa.
- `DELETE /api/mapy/{id}` i `DELETE /api/mapy` (wszystkie).
- Wszystko za tym samym tokenem i kontrolą Host/Origin co reszta API.

## 4. Poprawki w podglądzie (decyzja „Ukryj / To nie dane”)

- Zaznaczenie słowa w podglądzie → przycisk „Ukryj wszędzie”. Kliknięcie znacznika → „To nie dane
  osobowe”. Każda decyzja ponawia ukrywanie z listami `dodatkowe` i `pomin` (pola formularza JSON,
  limit 200 pozycji po 200 znaków). Lista „Twoje poprawki” z cofnięciem każdej.
- `pomin` zdejmuje wykrycie, którego tekst jest równy pozycji listy (po normalizacji spacji).
  Kontrola wyniku nie dokłada go z powrotem. Nadpisanie typu z sumą kontrolną (PESEL, NIP, IBAN…)
  dostaje ostrzeżenie w raporcie.
- `dodatkowe` ukrywa każde wystąpienie jako `[INNE_n]`, chyba że reguła rozpozna typ.
- Blokada kontroli: zamiast pustego ekranu podgląd wyniku z zaznaczonymi miejscami wątpliwymi
  i przyciskami „Ukryj” / „To nie dane” przy każdym. Kopiowanie i pobranie są aktywne dopiero po
  decyzji o wszystkich miejscach. Fragmenty pokazuje tylko interfejs na tym komputerze. Logi
  i dziennik nadal ich nie zawierają.

## 5. Aktualizacje modeli

- Wraz z wydaniem publikowany jest `katalog-pakietow.json` i podpis `katalog-pakietow.json.sig`
  (Ed25519). Klucz publiczny jest w programie (`niewidka/dane/klucz-katalogu.pub`). Klucz prywatny
  wydawcy leży wyłącznie w magazynie sekretów wydawcy (plik wskazany zmienną `NIEWIDKA_KLUCZ_PODPISU`).
  Program go nie zna.
- Katalog ma `wersja_katalogu` (liczba rosnąca) i `wersja` każdego pakietu. Program przyjmuje tylko
  katalog z poprawnym podpisem i wersją wyższą od znanej (ochrona przed cofnięciem do starej wersji).
  Przyjęty katalog zapisuje w katalogu danych i weryfikuje podpis przy każdym starcie (zły podpis =
  katalog wbudowany).
- Tryby (Ustawienia, zapamiętane w `<katalog danych>/ustawienia.json`): `reczne` (tylko przycisk
  „Sprawdź aktualizacje”), `sprawdzaj` (domyślny: sprawdza przy starcie, najwyżej raz na dobę, pokazuje
  „Dostępna aktualizacja”), `automatyczne` (sam pobiera i instaluje). Administrator może narzucić tryb
  w konfiguracji (`[aktualizacje] tryb`, `NIEWIDKA_AKTUALIZACJE`), także `wylaczone` dla sieci offline.
  Wtedy interfejs pokazuje „ustawione przez administratora”.
- Instalacja: pobranie do katalogu przejściowego, SHA-256 każdego pliku, **próbka kontrolna** (kilka
  fikcyjnych zdań z oczekiwanymi wykryciami, `niewidka/dane/probka-kontrolna.json`). Nowa wersja musi
  wykryć wszystko, co wykrywała stara. Dopiero wtedy zamiana. Poprzednia wersja zostaje w
  `modele/.poprzednie/` i można do niej wrócić przyciskiem.
- Sieć offline: „Zainstaluj z folderu” przyjmuje folder z katalogiem, podpisem i plikami (pendrive
  od IT). Obowiązuje ta sama weryfikacja podpisu i próbki.

## 6. „Jak to działa”

Dopisać uczciwie, co działa pod spodem. Na dziś to kilka metod naraz: reguły z sumami kontrolnymi,
model rozpoznawania osób (bardsai), słownik imion GUS, a z pakietem Rozszerzonym drugi model (LFM2.5).
Czyli **dwa modele językowe plus reguły i słownik**. Trzeciego modelu dziś nie ma.

## 7. Testy

- pytest dla każdego punktu (RED przed kodem): retencja z wstrzykniętym zegarem, skreślanie z rejestru,
  dziennik bez danych, przywracanie przez tekst w trzech wariantach wskazania mapy, `pomin`/`dodatkowe`,
  podpis katalogu (dobry, zły, stara wersja), próbka kontrolna odrzucająca gorszy model, cofnięcie wersji.
- Testy GUI (web i okno EXE) według `docs/testy/SCENARIUSZE.md`, uzupełnionego o nowe scenariusze.
