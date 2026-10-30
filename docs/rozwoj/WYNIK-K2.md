# WYNIK pomiaru K2 — detekcja modelowa poziomu 1 (reguły + bardsai)

Data: 2026-10-28 (nocy sesja). Detektor: `--detektor poziom1` = reguły K1
+ [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/bardsai/eu-pii-anonimization-multilang)
ONNX INT8 (`onnx/model_quantized.onnx`, 278 MB, XLM-R, 69 etykiet BIO, Apache 2.0).
Korpus: 62 próbki (ten sam co K1, autor zewnętrzny). Progi: `KRYTERIA.md` —
**nieprzesunięte**; porównanie z wynikiem poniżej, rewizje żadne.
Wagi: `~/models/niewidka` (env `NIEWIDKA_MODELE_KATALOG`), manifest SHA-256
sprawdzany przy ładowaniu; pobranie httpx (`narzedzia/pobierz_model.py`), bez huggingface_hub.

## Adapter modelu (decyzje zapisane PRZED pomiarem jakościowym)

1. **Adapter dostarcza wyłącznie OSOBA** (`PERSON_NAME`, `PERSON_ALIAS` → OSOBA).
   Typy z sumą kontrolną i dokładnymi granicami mają reguły (pewność 1.0, WYNIK-K1);
   dołączenie modelowych PESEL/EMAIL/ADRES rozmyłoby granice (unia scalania = szerszy
   zakres = FN+FP przy zerowej tolerancji, KRYTERIA §1.3). Pozostałe 32 klasy modelu
   (m.in. LOCATION, PERSON_IDENTIFIER) — pomijane.
2. **Rozciągnięcie zakresów do granic słowa** (`rozciagnij_do_slow`): tokenizery subword
   tną „Kowal" na „Ko"+"wal"; bez tej korekty model gubił końcówki („Róża"→„Róż")
   i dzielił jedno słowo na dwie encje. Pomiar artefaktów: OSOBA recall 0.870 →
   **0.957**, precision 0.800 → **0.917** (poprawka mechanistyczna dekodera, nie strojenie).
3. Okna przesuwne 510 tokenów, krok 448 (zakładka 62); duplikaty między oknami zdejmuje
   globalne scalanie (LLD §4). Błędy modelu = `BladDetektora` (fail-closed).

## Liczby per typ vs progi poziomu 1 (`KRYTERIA.md` §3+§4)

| typ | TP | FP | PN | FN | recall | próg | precision | próg | werdykt |
|---|---|---|---|---|---|---|---|---|---|
| PESEL | 5 | 0 | 3 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| NIP | 5 | 0 | 2 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| REGON | 5 | 0 | 2 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| IBAN | 4 | 0 | 2 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| DOKUMENT | 3 | 0 | 2 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| EMAIL | 4 | 0 | 0 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| TELEFON | 4 | 0 | 0 | 0 | 1.000 | ≥ 0.90 | 1.000 | ≥ 0.95 | **spełnia** |
| ADRES | 6 | 0 | 0 | 0 | 1.000 | ≥ 0.80 | 1.000 | ≥ 0.90 | **spełnia** |
| DATA | 4 | 0 | 0 | 0 | 1.000 | ≥ 0.90 | 1.000 | ≥ 0.95 | **spełnia** |
| **OSOBA** | **22** | **2** | 0 | **1** | **0.957** | **≥ 0.90** | **0.917** | **≥ 0.95** | **precision NIE spełnia** |
| łącznie (K1, bez OSOBA) | 40 | 0 | 11 | 0 | 1.000 | ≥ 0.90 | 1.000 | ≥ 0.95 | **spełnia** |
| łącznie (z OSOBA, poziom 1) | 62 | 2 | 11 | 1 | 0.984 | ≥ 0.90 | 0.969 | ≥ 0.95 | **spełnia** |

## Brama K2 (KAMIENIE.md): **NIE zaliczona** — precision OSOBA 0.917 < 0.95

Spełnione: wszystkie progi K1 (40/40, 0 pewnych FP — reguły nie zepsuły się pod
modelem), „łącznie" poziomu 1 (0.984/0.969), OSOBA recall 0.957. Nie spełnione:
OSOBA precision. Progi nieprzesunięte; wynik uczciwie odnotowany.

## Diagnoza pomyłek OSOBA (pełna lista, 62 próbki)

| próbka | tekst | pomyłka | pewność modelu | przyczyna |
|---|---|---|---|---|
| rzeczownik-kowal | „Kowal to dawny zawód, a Kowal jest naszym klientem." | FP „Kowal" (0,5) | 0.992 | użycie metajęzykowe (zawód jako pojęcie) |
| rzeczownik-nowak | „Nowak to popularne nazwisko; Nowak podpisał umowę najmu." | FP „Nowak" (0,5) | 0.965 | użycie metajęzykowe (nazwisko jako pojęcie) |
| homonim-kowal | „Kowal wykuł podkowę w starej kuźni." | FN — brak detekcji | — | „Kowal" jako podmiot-osoba model pominął |

To autentyczna granica modelu, nie dekodera: oba FP mają pewność > 0.96, więc próg
pewności ich nie odrzuci (a zabiłby poprawne TP przy 0.696). Dalsze mechanizmy
poprawy precision OSOBA tego adaptera są wyczerpane; opcje zapisane niżej.

## Wydajność CPU (stacjonarka, 8 wątków WSL, inferencja jednowątkowa onnxruntime)

- czas na próbkę (średnio 35 tokenów): **7.5 ms** (mediana 7.2, max 12.3)
- ładowanie modelu: ~0.9 s; RAM procesu (szczyt RSS): **798 MiB**
- dostawcy: tylko `CPUExecutionProvider` dostępny na tej maszynie (bez CUDA);
  `OnnxDetektor` użyje CUDA automatycznie, gdy będzie dostępny (nie wymaga)

## Kalibracja R95 → `niewidka/dane/r95.json`

Wg LLD §11: `beta.ppf(0.95, FN+1, TP+FN−FN)` (Clopper–Pearson, scipy tylko w
narzędziach). Poziom 1: OSOBA **0.1902** (k=1, n=23); typy reguł 0.39–0.63
(k=0, małe n → granice szerokie; to ryzyko resztkowe, nie pomiar trafności).

## Poziom 2 (LFM2.5): **czeka na miejsce na dysku**

`~/models` ma 887 MB wolnego (100% zapełnienia wolumenu); LFM2.5-Encoder
wymaga ~1.4 GB. Nie pobierany (polecenie właściciela); decyzja o poziomie 2 po
zwolnieniu miejsca. Decyzja KONSULTACJE pozostaje: LFM2.5 tylko przy wykazanym
pomiarem zysku.

## Opcje dalsze (decyzja właściciela — brama K2 formalnie niezaliczona)

1. **Akceptacja z ryzykiem**: precision 0.917 przy 2 FP na 62 próbki — FP to maskowane
   słowa-pojęcia (nadmaskowanie, bezpieczne dla danych, niebezpieczne dla czytelności);
   R95 OSOBA 0.19.
2. **Rozbudowa korpusu o nazwiska-rzeczowniki** (teraz 2 próbki metajęzykowe) i pomiar
   ponowny — jeśli odsetek FP spadnie, prógi mogą zostać osiągnięte bez zmiany detektora.
3. **Drugie źródło OSOBA**: poziom 2 (LFM2.5 — czeka na dysk) albo lista stop-words
   użycia metajęzykowego („to popularne nazwisko" — ryzyko strojenia pod korpus).
4. **Inny model OSOBA** (np. herbert/GLiNER PL) — osobny pomiar wg KRYTERIA.

## Powtarzalność

```
.venv/bin/python -m narzedzia.pobierz_model --katalog ~/models/niewidka
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m pytest tests/ -q   # 128 zielonych
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m narzedzia.pomiar --detektor poziom1
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m narzedzia.kalibracja --detektor poziom1
```

Bez wag: 131 zielonych, 3 pominięte (marker `model`).
