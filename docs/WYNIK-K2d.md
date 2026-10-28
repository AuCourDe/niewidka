# K2d — poziom 2 (OSOBA) bez nowego modelu: dwa warianty

Uzupełnienie poziomu 1 (bardsai ONNX) technikami łapiącymi więcej OSOBA bez
nowego modelu. Kryteria §4 `KRYTERIA.md`: recall OSOBA ≥ 0.95, precision
żadnego typu nie niższa niż poziomu 1, próg dawny bez zmian. Pomiary: korpus
182 próbki (`tests/korpus`), CPU, katalog wag `~/models/niewidka`.

## Warianty

- **A (`poziom2-a`)** — reguły + bardsai z **obniżonym progiem pewności OSOBA**
  (token bez argmax w klasach mapy: kandydat OSOBA, gdy p(B-/I-OSOBA) ≥ próg)
  + **drugi przebieg okien przesuniętych o pół kroku** (krok 224, zakładka 62).
- **B (`poziom2-b`)** — A + słownik polskich imion: rdzeń pierwszego słowa
  przeszedł w słownik GUS/PESEL (`niewidka/dane/imiona_gus.txt`, 3000 imion,
  CC0 1.0, dane.gov.pl zbiór id `1667`) i **następne słowo z wielkiej litery**;
  forma fleksyjna poprzez `rdzen_nazwiska` (reuse z `osoby.py`).

## Wyniki

| poziom | próg | OSOBA TP/FP/FN | recall | precision | czas/próbkę | RAM |
|---|---|---|---|---|---|---|
| poziom 1 (referencja K1) | — | 100 / 6 / 3 | 0.971 | 0.943 | 7.8 ms | 798 MiB |
| poziom 2 **A** | 0.2 | 101 / 5 / 2 | **0.981** | **0.953** | 8.8 ms | 798 MiB |
| poziom 2 **A** | 0.3 | 101 / 5 / 2 | 0.981 | 0.953 | 9.3 ms | 797 MiB |
| poziom 2 **A** | 0.5 | 100 / 6 / 3 | 0.971 | 0.943 | 7.8 ms | 797 MiB |
| poziom 2 **B** (+słownik) | 0.2 | 101 / 5 / 2 | 0.981 | 0.953 | 13.2 ms | 798 MiB |
| poziom 2 **B** (+słownik) | 0.9 | 100 / 6 / 3 | 0.971 | 0.943 | — | — |

Inne typy (ADRES/DATA/DOKUMENT/EMAIL/IBAN/NIP/PESEL/REGON/TELEFON) bez zmian
we wszystkich wariantach: TP jak poziom 1, FN 0, FP 0 — próg i półkrok
dotykają tylko OSOBA.

## Szczegóły

- Pozostałe FP poziomu 2-a (próg 0.2, 5 sztuk — identycznie w B): nazwisko
  w funkcji rzeczownika pospolitego u początku zdania
  (`rzeczownik-kowal` „Kowal (0,5)“, `rzeczownik-nowak` „Nowak (0,5)“,
  `homonim-056` „Kowal (24,29)“, `homonim-057` „Wiśniewski (31,41)“) oraz
  **„Adama Mickiewicza“** (inst-061 — patron muzeum trafił jako OSOBA
  z modelu, a powinno być instytucja).
- Poniesione FP poziomu 1: „Piotrowi (18,26)“ w próbce `osoba-011` — poziom 2
  łapie pełne „Piotrowi Wiśniewskiemu (18,40)“ → FP zamienia się w TP.
- Pozostałe FN (warianty A i B, identycznie):
  - `homonim-kowal`: „Kowal wykuł podkowę…“ — homonim nazwisko/zawód;
  - `homonim-058`: „Róża kupiła róże na bazarze.“ — homonim imię/rzecz pospolita.

## Diagnoza

- **próg**: kandydat z p ≥ 0.2 łapie 1 dodatkowe TP; 0.2 i 0.3 dają identyczne
  wyniki (nie trzeba agresywnego progu); 0.5 na korpusie bez efektu.
- **półkrok**: składnik potrzebny; encja dłuższa niż zakładka (71 tokenów
  w teście jednostkowym) zamienia się z fragmentu w pełen łańcuch B..I
  dopiero po drugim przebiegu okien.
- **słownik (B)**: na tym korpusie **nic nie wnosi**: 1 jego trafienie
  („Piotrowi Wiśniewskiemu“) zawsze już łapane przez próg albo nachodzi
  na FP podstawy i jest odrzucane przez filtr nakładania — ten filtr blokuje
  wartość słownika: przy progu 0.9 słownik nie odzyskuje TP przegranego
  przez model (zastępowane fragmentem FP podstawy), a przy progu 0.2 model
  sam łapie pełną encję. Koszt B: +4.4 ms/próbkę.
- słownik działa poprawnie w izolacji (`TestSlownikImion`): sam łapie
  „Jan Kowalski“, „Anna Nowak“, „Piotrowi Wiśniewskiemu“ (rdzeń + wielkość
  liter).

## Werdykt pracowniczy

- **Poziom 2 = wariant A (`poziom2-a`, próg OSOBA=0.2)**: OSOBA recall
  0.971 → **0.981**, precision 0.943 → **0.953**, koszt +1 ms/próbkę,
  RAM bez zmian. Kryteria §4 spełnione: recall ≥ 0.95 ✓, precision ≥ 0.943 ✓,
  próg dawny nieprzesunięty ✓. **Wymaga dokończenia**: przyjęcie wersji
  (nie tylko pomiaru) jako poziom domyślny — umieszczenie `poziom2-a`
  do `niewidka/api.py` — do oddzielnego zleceń.
- **Wariant B** — bez zysku na korpusie; zostaje jako eksperyment dostępny
  przez `--detektor poziom2-b`, ale nie zostaje poziomem domyślnym: trudno
  o jego praktyczny zysk, gdyż filtr nakładania odrzuca trafienia słownika
  nachodzące na wyniki podstawy (FP podstawy „Piotrowi (18,26)“ blokuje
  słownikowe „Piotrowi Wiśniewskiemu (18,40)“).

## Metodologia pomiaru

```bash
NIEWIDKA_MODELE_KATALOG=~/models/niewidka \
  .venv/bin/python -m narzedzia.pomiar --detektor poziom1
NIEWIDKA_MODELE_KATALOG=~/models/niewidka \
  .venv/bin/python -m narzedzia.pomiar --detektor poziom2-a --prog-osoba 0.2
NIEWIDKA_MODELE_KATALOG=~/models/niewidka \
  .venv/bin/python -m narzedzia.pomiar --detektor poziom2-b --prog-osoba 0.2
```

Wagi modelu bez zmian; bardsai jedzie na istniejącej wadze z dodanym
`próg` oraz półkrokowymi oknami; słownik dostępny w `poziom2-b`, odtworzenie
słownika: `python -m narzedzia.pobierz_imiona` (httpx, licencja CC0).
Testy jednostkowe: `pytest tests/test_detektory.py tests/test_pomiar.py -m "not model"`
— 83 passed, 0 failed.

