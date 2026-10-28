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

Stan wdrożenia i test na Windows: sekcje niżej (uzupełniane w toku K7b).
