# WYNIK K7b — pakiety modeli, pierwsze uruchomienie, wydanie EXE

Data: 2026-10-28 (sesja claude-glm, zlecenie K7b + decyzja orkiestratora 14:40).
Pakiety są DWA (decyzja nadpisuje „3 pakiety" z 14:05; podstawą pomiar
`docs/WYNIK-K7-q4.md`: bardsai Q4 bl32 nie gorszy od INT8, więc pakiet INT8 nie ma sensu):

| pakiet | wagi | rozmiar | poziomy suwaka | co dodaje |
|---|---|---|---|---|
| **Podstawowy** (wymagany) | bardsai Q4 bl32 | 190,9 MB | 1/2/3 | pełne działanie programu |
| **Rozszerzony** (opcjonalny) | LFM2.5 Q4 bl32 | 227,2 MB | 3 | adresy IP, kody SWIFT, loginy (tylko tam, gdzie zakres nie nachodzi na inne wykrycia; nie dotyka OSOBA ani typów regułowych) |

## Nowe typy w regułach poziomu 1 (niezależnie od pakietów)

IP v4/v6 i karta płatnicza z sumą Luhna (TDD, 12 nowych testów; nowe typy znaczników
IP, KARTA, SWIFT, LOGIN). Pomiary (korpus 190 `probki.jsonl` + 43 `probki_nowe_typy.jsonl`):

- **typy K1 identyczne jak przed zmianą**: 71 TP, 0 FP, PN 21, 1.000/1.000 na wszystkich
  typach regułowych — nowe reguły niczego nie psują.
- **IP 3/3 = 1.000/1.000** (v4; v6 ma testy jednostkowe, w korpusie nie ma próbek v6).
- **KARTA 6/6 = 1.000/1.000** na korpusie nowych (3 numery fikcyjne z błędnym Luhnem
  od zewnętrznego autora + 3 dopisane z poprawnym, wyliczonym algorytmem Luhna).
  Na korpusie głównym KARTA dodaje 4 PN (16-cyfrowe okna IBAN/REGON-14 bez poprawnego
  Luhna) — nadmaskowanie bezpieczne, spójne z filozofią „podejrzane maskowane z flagą".
- Karta w oknie IBAN nie wygrywa etykiety: `scalanie._bez_fragmentow_pewnych` odrzuca
  kandydata w pełni zawartego w kandydacie z sumą kontrolną (unia maskowania bez zmian,
  własność testowana).
- Kontrola zapisu: karta z BŁĘDNYM Luhnem pomijana w skanie surowym (`_techniczny`,
  precedens DATA) — panose fontów w fontTable.xml (16 cyfr) blokował wzorcowy DOCX
  na żywym biegu; karta z poprawną sumą nadal ostrzega.

## Poziom 3 z pakietem Rozszerzonym — warunek identyczności (polecenie 14:40)

„Przed podpięciem LFM2.5 zmierz poziom 3 z pakietem Rozszerzonym na obu korpusach;
typy regułowe i OSOBA muszą mieć wyniki identyczne jak bez niego". Wag: bardsai Q4 bl32
w katalogu głównym + `lfm25/q4-bl32` (jak po instalacji pakietów); detektor
`poziom3-rozszerzony` przez tę samą `zbuduj_poziom` co produkt.

| korpus | detektor | typy regułowe (łącznie K1) | OSOBA | SWIFT | LOGIN | IP | KARTA |
|---|---|---|---|---|---|---|---|
| 190 | poziom 3 bez pakietu | 71 TP / 0 FP / PN 21 = 1.000/1.000 | 102/5/1 = 0.990/0.953 | — | — | — | — |
| 190 | poziom 3 **z pakietem** | 71 TP / 0 FP / PN 21 = 1.000/1.000 (**identyczne**) | 102/5/1 = 0.990/0.953 (**identyczne**) | — | — | — | — |
| 43 nowe | poziom 3 bez pakietu | 9 TP / 0 FP = 1.000/1.000 | 0/2/0 | 0/3 | 0/3 | 3/3 | 6/6 |
| 43 nowe | poziom 3 **z pakietem** | 9 TP / 0 FP = 1.000/1.000 (**identyczne**) | 0/2/0 (**identyczne**) | **1/3** (0.333/1.000) | **1/3** (0.333/1.000) | 3/3 | 6/6 |

- Warunek **spełniony**: z pakietem ani typy regułowe, ani OSOBA nie zmieniają
  żadnej liczby (identyczne TP/FP/FN/PN na obu korpusach).
- Zysk pakietu na nowych typach: SWIFT +1 TP, LOGIN +1 TP (po 2 FN zostają:
  „PKOPPLPW12X" z cyframi w oddziale, „INGBPLPW" w innym zapisie; IP i karty już
  łapie poziom 1 z reguł). Koszt: ok. +26 ms/próbkę (94,3 vs 68,7 ms mediany)
  i RAM 852 MiB (vs ~610 MiB bez LFM2.5).
- FP OSOBA „Marzenka1988" (login jako imię) istnieje też BEZ pakietu (słownik
  imion poziomu 3) — nie pochodzi z LFM2.5.

## Odtworzenie

```bash
# katalog wag jak po instalacji pakietów (tu dowiązania do wag K7a)
NIEWIDKA_MODELE_KATALOG=~/models/niewidka-pakiety-k7b \
  .venv/bin/python -m narzedzia.pomiar --detektor poziom3-rozszerzony \
  --plik probki.jsonl --typy-rdz
NIEWIDKA_MODELE_KATALOG=~/models/niewidka-pakiety-k7b \
  .venv/bin/python -m narzedzia.pomiar --detektor poziom2-b \
  --plik probki.jsonl --typy-rdz   # referencja bez pakietu
# (analogicznie --plik probki_nowe_typy.jsonl)
```

## Wdrożenie i test na Windows (exe zbudowany z klonu, bez wag)

Budowa: `narzedzia/zbuduj_windows.ps1` (bez wag; parametr `-Rpo` dla CI) na klonie
`C:\Users\uzytkownik\niewidka-build\repo` (origin = `//wsl.localhost/...`, `git pull` bez
sieci). Biegi budowy: 1 (pierwszy, 64 s PyInstaller), 4 i 5 po naprawach z żywego
biegu; testy w budowie 448 passed / 27 skipped (bez wag) na Windows.

| pomiar | wynik |
|---|---|
| paczka ZIP (bez wag) | **53,2 MB** (K6 z wagami: 274 MB) |
| start exe do /api/stan 200 (bez wag) | **2,4 s**, RAM 584 MB |
| ekran pierwszego uruchomienia | „Przygotowanie do pracy", 3 opcje (zrzut `docs/zrzuty/k7-pierwsze-uruchomienie.png`) |
| ukryj bez pakietu | **HTTP 409** z `brak_pakietu` (jasny błąd, nie 500) |
| pobranie pakietu Podstawowy z lokalnego lustra | **182 MB w 3 s** (lustro: `python -m http.server` na Windows, `NIEWIDKA_MODELE_ZRODLO=http://127.0.0.1:39950`) |
| po pobraniu | stan zainstalowany, poziomy_dostepne [1/2/3]; ekran pierwszego uruchomienia znika sam (odpyt 2,5 s) — zrzut `k7-aplikacja-po-pobraniu.png` |
| ukryj TXT (exe, poziom 2) | 1280 ms, 200 OK; statystyki: OSOBA 1, ADRES 1, PESEL 1, DOKUMENT 1, TELEFON 1, EMAIL 1, **IP 1** |
| ukryj DOCX (exe, poziom 2) | 689 ms, 200 OK; OSOBA 3, PESEL 2, TELEFON 2, EMAIL 1, NIP 1 |
| przywrócenie TXT | 38 ms, treść identyczna z oryginałem (PESEL wraca, bez znaczników) |
| Ustawienia | wiersze pakietów ze stanem, rozmiarem i Pobierz/Usuń (zrzut `k7-ustawienia.png`); wynik ukrywania z zaślepkami IP i KARTA: `k7-desktop-wynik.png` |
| procesy po teście | ubite (exe 0, lustra i serwer dev zabite) |

Naprawione z żywego biegu (każde RED→GREEN):

| objaw | przyczyna | naprawa |
|---|---|---|
| /api/stan 500 przy łagodnym starcie | `None.nazwa` na `app.state.detektor = None` | `modele = []` gdy brak detektora (commit `6c0946d`) |
| budowa padła na testach Windows | próg testu e-mail liniowego 0.05 s, Windows 0.055 s na brzegu | próg 0.1 s z komentarzem (cel: obrona regresji kwadratowej 7,15 s) (`ad39383`) |
| ekran pierwszego uruchomienia zalegał po instalacji spoza UI | strona odświeża stan tylko przy własnych akcjach | odpyt co 2,5 s tylko gdy ekran widoczny (`09c010f`) |

Środowiskowe notatki dla kolejnych testów: `~/models` to dowiązanie, którego
`\\wsl.localhost` nie prowadzi (jak w K6) — lustro pakietów trzeba kopiować z
`/mnt/projekty/models/...`, a pliki-lustra muszą być fizyczne (symlinki 9P nie
serwuje); transfer 174 MB przez forwarding Windows→WSL jest wolny, lustro lepiej
trzymać na Windows.

## Wydanie (GitHub Actions) — przygotowane, NIE uruchamiane

`.github/workflows/wydanie.yml`: tag `v*` → windows-latest → testy → PyInstaller
(skryptem budowy, `-Rpo` = checkout CI) → ZIP + SHA256SUMS → **draft release**.
Dry-run bez publikacji: `workflow_dispatch` (artefakty w Actions, wydanie nie
powstaje). Pliki Q4 obu pakietów wgrywa się do wydania z maszyny z wagami
(`gh release upload`, nazwy = pole `zrodlo` z `pakiety.json`) — runner ich nie ma,
a paczka EXE z definicji jest bez wag. Wydanie publiczne dopiero po przeglądzie
właściciela (decyzja 2c, repo prywatne).

