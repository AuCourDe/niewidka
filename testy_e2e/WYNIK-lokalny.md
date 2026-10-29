# WYNIK testów E2E API Niewidki — bieg lokalny

Data: 2026-10-29, 00:35-00:42. Serwer na żywo: `http://127.0.0.1:8871`
(stacjonarka DESKTOP-VNC1F3P, wagi `~/models/niewidka`, klucz `/tmp/niew/klucz`).
Raport surowy: `testy_e2e/raport-lokalny.json`.

## Środowisko

- Serwer: `PYTHONPATH=. NIEWIDKA_MODELE_KATALOG=~/models/niewidka NIEWIDKA_KLUCZ_PLIK=/tmp/niew/klucz NIEWIDKA_PORT=8871 .venv/bin/python -m uvicorn niewidka.api:create_app --factory --port 8871`
- **Uwaga konfiguracyjna:** `NIEWIDKA_PORT=8871` jest konieczne. Walidacja Origin
  porównuje nagłówek z `konfig.port` (`niewidka/api.py`, `originy`), a samo
  `--port 8871` uvicorna zmienia tylko port nasłuchu. Bez tej zmiennej środowiskowej
  każde żądanie „jak z przeglądarki" (Origin = `http://127.0.0.1:8871`) dostaje 403.
- Model: `reguly, onnx:bardsai` (pakiety podstawowy + rozszerzony zainstalowane,
  weryfikacja SHA-256 zakończona przed testami T2).
- Korpus: 8 TXT (2480-3450 znaków) + DOCX z dokumentu 01; wyłącznie dane fikcyjne;
  sumy kontrolne PESEL/NIP/REGON/IBAN/dowód policzone i sprawdzone skryptem
  `waliduj_korpus.py` (wynik: KORPUS OK); oczekiwania w plikach JSON
  (`musza_zniknac` łącznie 94 fragmenty, `moga_zostac` 30 fragmentów).

## Kryteria (spisane przed biegiem, wg zlecenia)

- T1: GET /api/pakiety bez tokenu → 403; POST /api/ukryj z obcym Origin → 403; z obcym Host → 403.
- T2: /api/ukryj → 200, `x-niewidka-status: ukonczony`, wynik zaczyna się od
  „ZANONIMIZOWANY", zero fragmentów z `musza_zniknac` w wyniku; zapis statystyk,
  czasów, wycieków i nadmiaru.
- T3: wynik + mapa → przywrócony tekst identyczny z oryginałem (TXT bajt w bajt,
  DOCX porównanie tekstu akapitów) i zero rozbieżności.
- T4: mapa z innego dokumentu → odmowa 4xx z komunikatem.
- T5: nieobsługiwany format i pusty tekst → czytelny błąd 4xx.
- Kod wyjścia 1, gdy jakikolwiek wyciek albo błąd. Błędy aplikacji to wynik testu.

## Wyniki

- **T1 bezpieczeństwo: 3/3 zaliczone** (403 `brak albo zły token sesji` /
  `niedozwolony Origin` / `niedozwolony Host`).
- **T4: zaliczone** — wynik 01-wezwanie + mapa z 02-umowa-najmu → HTTP 422,
  komunikat „wynik nie zawiera identyfikatora tej mapy — dokument i mapa pochodzą
  z różnych zadań".
- **T5: zaliczone** — `.exe` → 415 „nieznany format pliku; obsługiwane: docx, txt";
  pusty tekst → 422 „podaj dokładnie jedno: plik albo tekst".
- **T2+T3: 27 komórek (9 dokumentów × 3 poziomy): 14 ok, 2 wycieki, 11 zablokowanych, 0 błędów.**

```
dokument                        poz. status       wycieki nadmiar przywroc.  ukryj[s] przyw[s]
-------------------------------------------------------------------------------------------
01-wezwanie.txt                 1    ok                 0       1       tak      2.44     0.00
01-wezwanie.txt                 2    ok                 0       1       tak      2.57     0.00
01-wezwanie.txt                 3    ok                 0       1       tak      5.16     0.00
01-wezwanie.docx                1    ok                 0       1       tak      1.68     0.01
01-wezwanie.docx                2    zablokowany        0       0         -      1.49     0.00
01-wezwanie.docx                3    zablokowany        0       0         -     13.53     0.00
02-umowa-najmu.txt              1    zablokowany        0       0         -      1.38     0.00
02-umowa-najmu.txt              2    zablokowany        0       0         -      1.41     0.00
02-umowa-najmu.txt              3    ok                 0       1       tak      6.45     0.00
03-skarga-bank.txt              1    zablokowany        0       0         -      1.34     0.00
03-skarga-bank.txt              2    zablokowany        0       0         -      1.38     0.00
03-skarga-bank.txt              3    ok                 0       0       tak      6.46     0.00
04-protokol-wspolnota.txt       1    zablokowany        0       0         -      1.31     0.00
04-protokol-wspolnota.txt       2    zablokowany        0       0         -      2.51     0.00
04-protokol-wspolnota.txt       3    zablokowany        0       0         -     13.06     0.00
05-mail-hr.txt                  1    ok                 0       2       tak      2.56     0.00
05-mail-hr.txt                  2    ok                 0       2       tak      2.50     0.00
05-mail-hr.txt                  3    ok                 0       2       tak      5.02     0.00
06-notatka-policja.txt          1    wyciek             1       0       tak      1.37     0.00
06-notatka-policja.txt          2    wyciek             1       0       tak      1.33     0.00
06-notatka-policja.txt          3    ok                 0       0       tak      4.58     0.00
07-zaswiadczenie-lekarskie.txt  1    ok                 0       0       tak      2.48     0.00
07-zaswiadczenie-lekarskie.txt  2    ok                 0       0       tak      2.47     0.00
07-zaswiadczenie-lekarskie.txt  3    ok                 0       0       tak      5.08     0.00
08-pelnomocnictwo.txt           1    zablokowany        0       0         -      1.30     0.00
08-pelnomocnictwo.txt           2    zablokowany        0       0         -      1.23     0.00
08-pelnomocnictwo.txt           3    ok                 0       1       tak      4.99     0.00
```

Przywrócenie (T3): **każda z 14 komórek z wynikiem wróciła identycznie** (TXT bajt
w bajt, DOCX tekst akapitów akapit w akapit), zero rozbieżności. Przykładowe
statystyki (01-wezwanie.txt poziom 3): OSOBA 9, ADRES 2, DATA 6, EMAIL 1, PESEL 1,
TELEFON 1.

## Znaleziska (błędy aplikacji — wynik testu, nie naprawiane)

1. **Kontrola blokuje pisma urzędowe (11 z 27 komórek, kod 422 „zablokowany",
   znaleziska typu ORYGINAL: 1-2).** Odtworzenie zgłoszenia właściciela z todo
   (23:55 „aplikacja nie anonimizuje, nic się nie zmienia"): umowa najmu, skarga
   do banku, protokół wspólnoty i pełnomocnictwo padają na poziomach 1-2, protokół
   wspólnoty także na poziomie 3; DOCX wezwania pada na poziomach 2-3, choć ten
   sam tekst jako TXT przechodzi na wszystkich poziomach. Użytkownik dostaje STOP
   zamiast dokumentu — żaden fragment nie jest anonimizowany. Komunikat blokady
   niesie tylko typy i liczniki (bez fragmentów), zgodnie z K4b.
2. **Wyciek imienia i nazwiska „Piotr Wrona" na poziomach 1 i 2** (notatka
   policji, podpis „st. asp. Piotr Wrona, komendant posterunku"). Poziom 3
   (słownik imion) już go maskuje. To OSOBA w krótkiej linii podpisu bez imienia
   w treści — model jej nie łapie, a kontrola nie liczy jej za wyciek (model
   zgodnie się powtarza), więc dokument wychodzi z jawnym nazwiskiem.
3. **Nadmiar (12 zamaskowanych fragmentów z `moga_zostac`):** adresy e-mail
   instytucji (`referat.obywatelski@…`, `rekrutacja@…`, `biuro@…`) oraz NIP firmy
   w stopce maila HR. Maskowanie danych firmowych to zachowanie zachowawcze —
   do odnotowania, nie błąd blokujący.

## Werdykt

**PORAŻKA (kod wyjścia 1)** — spełnione T1, T4, T5 i cała odwracalność (T3),
ale T2 nie: 2 wycieki + 11 blokad. Zestaw testowy jest powtarzalny: dwa biegi
pod rząd dały identyczny rozkład 14/2/11/0 (różne tylko czasy).

## Jak powtórzyć

```bash
# 1. klucz (raz): .venv/bin/python -m niewidka.klucze nowy-plik /tmp/niew/klucz
# 2. serwer:
PYTHONPATH=. NIEWIDKA_MODELE_KATALOG=~/models/niewidka \
NIEWIDKA_KLUCZ_PLIK=/tmp/niew/klucz NIEWIDKA_PORT=8871 \
.venv/bin/python -m uvicorn niewidka.api:create_app --factory --port 8871
# 3. testy:
cd testy_e2e && ../.venv/bin/python test_api.py --baza http://127.0.0.1:8871 --wyjscie raport-lokalny.json
# (na Windows: py -3.13 test_api.py ...; skrypt używa wyłącznie biblioteki standardowej)
```
