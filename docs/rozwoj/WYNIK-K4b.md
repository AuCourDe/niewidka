# WYNIK K4b — naprawa 15 znalezisk audytu bezpieczeństwa Codex/astra #1

Zlecenie 2026-10-28 (13:49). Audyt: `docs/konsultacje/06-przeglad-codex-astra-1.md`
(15 punktów, każde odtworzone przez audytora). Metoda: **TDD** — dla każdego punktu
najpierw test odtwarzający atak (RED: pada na właściwej asercji), potem poprawka
(GREEN), commit po każdym zielonym kroku. Testy ataków: `tests/test_k4b.py`
(32 testy, sekcja per punkt); poprawki w `niewidka/api.py`, `rdzen.py`, `kontrola.py`,
`mapa.py` (bez zmian), `reguly.py`, `konfig.py`, `znaczniki.py`, `archiwum.py` (nowy),
`formaty/docx_.py`, `formaty/tekst.py`, `formaty/__init__.py`, `web/apka.js`.

## Tabela 15 punktów

| # | Znalezisko (audyt) | Test ataku (RED) | Poprawka (GREEN) | Commit |
|---|---|---|---|---|
| 1 | „Zablokowany" wynik nadal do pobrania (200 z dokumentem) | DOCX z PESEL-em w zachowywanej części `word/theme/` zwracał 200 i pełny dokument; UI pokazywało pobranie | `BladKontroli` → 422 z `{"status": "zablokowany", "typy": {PESEL: n}}`, zerwane PRZED pakowaniem ZIP; UI: STOP bez pobrania/kopiowania (usunięta ścieżka `x-niewidka-status`) | `e4ca7d8` |
| 2 | Obrazy z danymi przechodzą bez ostrzeżenia; `word/media/*.bin` bez weryfikacji | PNG zostawał w wyniku, raport `ukonczony` i bez uwag; `.bin` przechodził cały | polityka obrazów `usun` (domyślnie) / `blokuj` / `zostaw` — `NIEWIDKA_OBRAZY` / `[kontrola] obrazy`; usunięty obraz = run „[OBRAZ USUNIĘTY]" + uwaga w raporcie (`x-niewidka-uwagi`) i w UI; część binarna poza rozszerzeniami obrazów = `ElementNieobslugiwany` (422) | `8e325fb` |
| 3 | Skan pomijał `e.tail` | `word/theme/proba.xml` z `<root><node/>PESEL</root>` dawał `ukonczony`, `[]` | skan wartości = `e.text` + `e.tail` + atrybuty | `b703b83` |
| 4 | Błąd parsowania zachowanej części XML = fail-open | niedomknięty `<root>PESEL` → ciche `continue`, część w wyniku | `XMLSyntaxError` → ostrzeżenie `XML_NIEPRAWIDLOWY` → wynik zablokowany (fail-closed) | `2dd54d9` |
| 5 | PII w NAZWACH części DOCX | `word/media/44051401359.bin` szedł do katalogu ZIP odbiorcy bez ostrzeżeń | kontrola skanuje nazwy części (typ `NAZWA_CZESCI`, DATA pomijana); adapter przemianowuje media na `obrazN.ext` z aktualizacją relacji (względne cele) i Override w `[Content_Types]` | `f8c141d` |
| 6 | Podmiana mapy między zadaniami tej samej sesji | mapa B do wyniku A (ta sama sesja) = 200 i przywrócenie cudzych danych | identyfikator mapy zapisany w dopisku wyniku (`znaczniki.dopisek`); przywracanie weryfikuje zgodność — niezgodne = `BladMapy` 422 | `42be490` |
| 7 | 24-bitowe identyfikatory (kolizje starych map ~77,5%) | `token_hex(3)`; cudzy szyfrogram z „wygraną" kolizją ID przechodził kontrolę sesji | `token_hex(16)` (128 bit); sesja rejestruje SHA-256 wydanych szyfrogramów i sprawdza PRZED odszyfrowaniem; w nazwach plików tylko 12-znakowy skrót (pełny ID w mapie i nagłówku) | `9fc0125` |
| 8 | Pełne PII w `X-Niewidka-Ostrzezenia` | PESEL z ukrytej części szedł jawnym nagłówkiem (fragment + nazwa części) | nagłówek = `{typ: liczba}` (`_licznik_typow`); `_ostrzezenia_lista` usunięte; UI renderuje z licznika bez fragmentów | `54e01dd` |
| 9 | Upload bez `Content-Length` omijał limit przed buforowaniem; spool na dysk; `/przywroc` bez limitu | chunked 1,125 MB przy limicie 1 MB szedł do parsera (rollover nastąpił); `/api/przywroc` bez żadnego limitu | middleware ASGI `LimitBajtow`: liczy bajty PRZED aplikacją (także chunked), po przekroczeniu 413 bez przekazania ani bajtu — rollover niemożliwy; obejmuje wszystkie POST-y | `ba8b2b0` |
| 10 | Limit ZIP ufał kłamliwym nagłówkom (8 MiB strumienia przy limicie 1 MiB) | wpis z deklaracją ≠ strumień przechodził sumę po nagłówkach i dekompresował całość | nowy `niewidka/archiwum.py`: odczyt porcjami 64 KiB pod budżetem RZECZYWISTYCH bajtów, weryfikacja długości w obie strony, tylko stored/deflate, `BadZipFile` → `BladArchiwum` (422); limit przepuszczony do adaptera DOCX i skanu surowego | `5ad592f` |
| 11 | Po timeoucie wątek pracował dalej, semafor zwolniony | timeout = 500, następne żądanie wchodziło równolegle mimo `Semaphore(1)` | semafor trzyma ZADANIE pracy (`create_task` + `asyncio.wait`); timeout = 503 z retry-after, slot puszczony dopiero po faktycznym końcu wątku; test czeka na realne zwolnienie semafora | `75bb908` |
| 12 | Kolejka nie ograniczała buforowanych uploadów | 8 uploadów mogło stać w pamięci poza kolejką (`kolejka=0` nie chroniła) | middleware `LicznikZlecen` (zewnętrzny): nadmiar POST-ów `/api/ukryj` i `/api/przywroc` → 503 ZANIM jakikolwiek bajt treści dotrze do aplikacji; limit `NIEWIDKA_ZLECENIA` (domyślnie 8), widoczny w `/api/stan` | `ff461e4` |
| 13 | Kwadratowy regex e-maila blokował GIL i timeouty | 100 tys. „a" bez @ = **7,15 s** w `finditer` (audyt: 0,24 s przy 16 tys.) | lookbehind granicy początku `(?<![A-Za-z0-9._%+-])` — próba startuje raz na ciąg; 100 tys. znaków **< 50 ms**, wykrywanie adresów bez zmian | `62bb625` |
| 14 | Nasłuch LAN = odszyfrowanie bez uwierzytelnienia | `NIEWIDKA_HOST=0.0.0.0` przechodził konfigurację | `wczytaj_konfig` odrzuca hosty poza `127.0.0.1`/`localhost`/`::1` (jawny `ValueError` na starcie, komunikat o wymaganej autoryzacji LAN) | `f26df6a`, `5812f7a` |
| 15 | Błędy odbijały dane wejściowe; walidacja z polem `input` | 415 odbijał osobową nazwę pliku; 422 wypisywał nazwy części; `poziom=44051401359-test` wracał w `input` | 415 = stały komunikat + lista formatów; 422 = liczba elementów bez nazw; handler `RequestValidationError` → „nieprawidłowe dane żądania" bez `input` | `65a1973` |

## Zmierzony efekt pkt 13

| Wejście | Przed | Po |
|---|---|---|
| 16 tys. znaków bez @ | ~0,24 s (audyt) | < 5 ms |
| 100 tys. znaków bez @ | 7,15 s | < 50 ms (test: `assert czas < 0.05`) |

## Znalezisko własne w trakcie (nie z audytu)

**Losowe blokowanie dokumentów po połączeniu pkt 6+7:** identyfikator mapy w dopisku
jako surowy hex tworzył losowe 9–11-znakowe okna cyfr, które tripały reguły
PESEL/REGON w kontroli wyniku — dokumenty były blokowane w ~połowie uruchomień
(flakiness 355→349→355 passed między biegami). Naprawa: identyfikator w treści
kodowany na same litery (`znaczniki.zakoduj_identyfikator`, nibble → a..p) — zero
cyfr, w pełni odwracalne; test `test_pkt6_dopisek_zawiera_identyfikator` pilnuje
braku cyfr. Sześć kolejnych pełnych biegów z rzędu stabilnie zielonych.

## Weryfikacja

- `pytest` całości z wagami (`NIEWIDKA_MODELE_KATALOG=~/models/niewidka`):
  **408 passed, 1 xfailed** (xfail = świadomy, sprzed K4b).
- `ruff check niewidka/ tests/ narzedzia/`: **All checks passed**.
- Push: każdy punkt osobnym commitem na `main` (`e4ca7d8` … `65a1973`, + `34dda18`).

## Uwagi dla sesji równoległych

- Commit `b703b83` (pkt 3) przypadkowo włączył zakolejkowane pliki równoległej
  sesji (autostash odtworzył ich indeks): `docs/WYNIK-K2e.md`, `narzedzia/pomiar.py`,
  `niewidka/detektory.py`, `tests/korpus/probki_nowe_typy.jsonl`, `tests/test_korpus.py`,
  `tests/test_mapowanie_lfm25.py`, `todo.md`. Treść cudza, ale poprawna i additive;
  historii nie przepisano (push przed zauważeniem, force-push wykluczony).
- Testy `tests/test_klucze.py` i `tests/test_kwantyzuj_q4.py` w trakcie tej sesji
  należały do równoległych zleceń (K6-Windows, K7-pakiety) i bywały chwilowo czerwone
  w drzewie roboczym — nie dotknięte; w HEAD i w pełnym biegu końcowym nie występują.
- Zmiany UI (`apka.js`) zgodne z wytycznymi GUI: bez półpauz, komunikaty po ludzku
  (STOP z listą typów, uwagi o obrazach, ostrzeżenia z licznikami).
- Codex/astra wywołania: 0 w tej sesji (naprawy wykonywane bez kolejnych wywołań
  przeglądu; przegląd #1 już dostarczony).
