# WYNIK pomiaru K7a — kwantyzacja int4 (Q4) bardsai i LFM2.5

Data: 2026-10-28 (sesja claude-glm b244, zlecenie K7a — tylko pomiar, produkt bez zmian).
Tło: pakiety modeli pobierane po instalacji, klasa Q4 (mniejsze), trzy pakiety do wyboru
(Szybki / Dokładny / Najdokładniejszy; właściciel 14:05 i 14:08). Progi `KRYTERIA.md`
**bez zmian**. Narzędzie: `narzedzia/kwantyzuj_q4.py` (onnxruntime 1.31
`MatMulNBitsQuantizer`, int4 weight-only, bloki 32 i 128, symetryczna, z embeddingami).

## Metodologia

- **Źródła fp32**: bardsai `onnx/model.onnx` z HF (pobrane httpx do
  `~/models/niewidka/bardsai-fp32`, manifest SHA-256, 1110 MB); LFM2.5
  `lfm25/fp32/` z eksportu K2b (1419 MB).
- **Co kwantyzuje**: MatMul → `MatMulNBits` (wagi int4 w blokach) ORAZ Gather
  → `GatherBlockQuantized` (tabele embeddingów). Bez embeddingów Q4 bardsai miałoby
  **785 MB** (embedding RoBERTy to 732 MB fp32 — dominuje model); z nimi **174 MB**.
  Wymuszone podniesienie grafu LFM2.5 z opset 17 do 18 (`ReduceMean`: atrybut `axes`
  → wejście) — sanity je wyłapało jako nieważny model.
- **Sanity** (3 stałe przykłady, logits vs fp32): bardsai bl32 różnice argmax 4/68
  tokenów, bl128 2/68; LFM2.5 bl32 3/74, bl128 1/74. Na tokenach OSOBA z przykładów
  argmax identyczny z fp32. Granicę jakości stanowi pomiar na korpusie, nie sanity.
- **Pomiar**: `narzedzia/pomiar.py`, korpus **190 próbek** (`--plik probki.jsonl` —
  bez `probki_nowe_typy.jsonl` sesji K2e, to osobny eksperyment K2e), poziomy przez
  `detektory.zbuduj_poziom` (ta sama funkcja co produkt), CPU (WSL, 8 wątków).
  Typy regułowe identyczne we WSZYSTKICH wariantach (reguły nie zależą od wag):
  recall/precision 1.000/1.000, PN 21 — tabelach poniżej tylko OSOBA i zbiorcze.

## Rozmiary i czas kwantyzacji

| wagi | rozmiar model.onnx | czas kwantyzacji | RAM pomiaru (szczyt) |
|---|---|---|---|
| bardsai fp32 | 1110.2 MB | — (źródło z HF) | 2140 MiB |
| bardsai INT8 (z HF) | 278.7 MB | — | 798 MiB |
| **bardsai Q4 bl32** | **174.1 MB** | 6.2 s | 606 MiB |
| bardsai Q4 bl128 | 148.1 MB | 4.8 s | 581 MiB |
| LFM2.5 fp32 | 1419.0 MB | — (eksport K2b) | 2250 MiB |
| LFM2.5 INT8 | 355.4 MB | — (eksport K2b) | 650 MiB |
| LFM2.5 Q4 bl32 | 222.4 MB | 3.3 s | 421 MiB |
| LFM2.5 Q4 bl128 | 189.2 MB | 2.7 s | 400 MiB |

## Poziom 1 (reguły + bardsai) — korpus 190

| wagi | OSOBA TP/FP/FN | OSOBA R/P | próg R/P | łącz. R/P | czas/próbkę | RAM |
|---|---|---|---|---|---|---|
| INT8 (referencja) | 100/6/3 | 0.971 / 0.943 | ≥0.90 / ≥0.95 | 0.983 / 0.966 | **8.0 ms** | 798 MiB |
| fp32 | 102/5/1 | 0.990 / 0.953 | | 0.994 / 0.972 | 18.5 ms | 2140 MiB |
| **Q4 bl32** | 102/4/1 | **0.990 / 0.962** | | 0.994 / 0.977 | 13.2 ms | **606 MiB** |
| Q4 bl128 | 101/5/2 | 0.981 / 0.953 | | 0.989 / 0.972 | 13.3 ms | 582 MiB |

- Czas stabilny w powtórce: INT8 7.9/8.0 ms, Q4 bl32 13.2/13.5 ms (koszt
  dekwantyzacji int4: **+65%**).
- **Bramka poziomu 1**: progi typów regułowych = 1.00 wszędzie ✓; OSOBA: Q4 bl32
  i fp32 spełniają formalnie (P ≥ 0.95), INT8 nie (0.943 — znane, decyzja
  właściciela: nie blokuje, `WYNIK-K2b.md`). Uczciwie: różnice 1-2 encji na 103
  OSOBA to szum korpusu — **nie ogłaszać „Q4 naprawił precision"**, tylko „Q4 nie
  degraduje jakości względem INT8, a wagi są 1.6× mniejsze i RAM niższe".

## Poziom 2 produktowy (wariant A: próg OSOBA 0.2 + półkrok) — korpus 190

| wagi | OSOBA TP/FP/FN | OSOBA R/P | łącz. R/P | czas/próbkę | RAM | reguły |
|---|---|---|---|---|---|---|
| INT8 (referencja) | 101/5/2 | 0.981 / 0.953 | 0.989 / 0.972 | **9.4 ms** | 798 MiB | 16/16 ADRES ✓ |
| fp32 | 102/5/1 | 0.990 / 0.953 | 0.994 / 0.972 | 26.2 ms | 2140 MiB | ✓ |
| **Q4 bl32** | 102/4/1 | **0.990 / 0.962** | 0.994 / 0.977 | 15.3 ms | **606 MiB** | 16/16 ADRES ✓ |
| Q4 bl128 | 102/5/1 | 0.990 / 0.953 | 0.989 / 0.972 | 13.5 ms | 582 MiB | **ADRES 15/16** ✗ |

- **Q4 bl128 gubi 1 ADRES**: `adr-kod-bez-przecinka` — „Biuro: al. Pracy 12 25-422
  Kielce.": kandydat OSOBA z progu 0.2 nachodzi na adres, unia scalania zmienia
  dokładne granice → ADRES recall 0.938 (częściowe pokrycie = FN+FP, KRYTERIA §1.3).
  Formalnie progi poziomu 2 wciąż spełnione (ADRES P = 1.000, recall ≥ 0.80), ale
  to **wyciek danych** (część adresu jawna) — mechanizm znany z K2b, tu wyzwolony
  przez inny rozkład pewności po kwantyzacji. Dlatego **bl128 odpada** mimo
  najmniejszego rozmiaru.
- Q4 bl32: FN reguł 0, progi poziomu 1 i 2 spełnione w całości.

## LFM2.5 solo — korpus 190 (OSOBA; reguł LFM2.5 nie dostarcza)

| wagi | OSOBA TP/FP/FN | OSOBA R/P | czas/próbkę | RAM |
|---|---|---|---|---|
| fp32 (K2b) | 57/13/46 | 0.553 / 0.814 | 64.2 ms | 2250 MiB |
| INT8 (K2b) | 41/17/62 | 0.398 / 0.707 | 24.8 ms | 650 MiB |
| **Q4 bl32** | 48/8/55 | 0.466 / **0.857** | 45.6 ms | 421 MiB |
| Q4 bl128 | 48/9/55 | 0.466 / 0.842 | 44.0 ms | 400 MiB |

- Q4 odwraca degradację INT8 (recall 0.466 vs 0.398, precision 0.857 vs 0.707),
  ale nadal jest daleko za fp32 (0.553) i **nieporównywalny z bardsai** (0.971
  na poziomie 1). LFM2.5 pozostaje modelem wsadowym/eksperymentalnym, nie
  detektorem produktowym.
- Zysku poziomu 2 z LFM2.5 brak (potwierdzenie K2b/K2c na Q4): solo słabszy od
  bardsai, a dołączany (unia albo uzupełnianie) psuje dokładne granice bardsai.

## Rekomendacja pakietów (K7b)

| pakiet | wagi | do pobrania (model+tokenizer+config) | poziomy suwaka | status progów |
|---|---|---|---|---|
| **Szybki** (domyślny) | bardsai Q4 bl32 | **191 MB** | 1/2/3 | poziom 1 i 2 **spełnione** |
| **Dokładny** | bardsai INT8 | 296 MB | 1/2/3 | poziom 2 spełniony (poziom 1: P OSOBA 0.943, bramka K2 jak dotychczas) |
| **Najdokładniejszy** | Dokładny + LFM2.5 Q4 bl32 | 523 MB | 1/2/3 — **LFM2.5 nie podpięty do detekcji** | warunek „tylko jeśli pomiar pokaże zysk" **nie spełniony** |

- **Szybki = bardsai Q4 bl32**: jedyny wariant Q4, który nie gubi encji regułowych
  na poziomie 2 (bl128 gubi ADRES); koszty +4 ms/próbkę i −192 MiB RAM względem
  INT8. Jakość na korpusie co najmniej równa INT8.
- **Dokładny = bardsai INT8**: dotychczasowe wagi referencyjne; sens pakietu to
  dziś fallback od niezależnego od świeżej kwantyzacji (różnice vs Szybki to
  1-2 encje = szum). Gdy K7b chce układu tańszego — pakiet można odłożyć.
- **Najdokładniejszy**: pomiar **nie wykazał zysku** z LFM2.5 (sekcja wyżej) —
  wg warunku zlecenia NIE podpinać go do suwaka jako poziomu detekcji. Rozsądek
  pakietu: wagi LFM2.5 Q4 (222 MB) dystrybuowane tylko, gdy powstaje mechanizm
  z zyskiem (np. typy spoza Niewidki z K2e — patrz `docs/WYNIK-K2e.md`) z własnym
  pomiarem; inaczej pakiet nie ma sensu i lepiej go nie publikować.
- Rozmiary to sumy plików surowych; kompresja pakietu (zip) to decyzja K7b.

## Odtworzenie

```bash
# kwantyzacja (odtwarzalna, parametry z CLI; manifest SHA-256 w każdym katalogu)
.venv/bin/python -m narzedzia.kwantyzuj_q4 \
  --zrodlo ~/models/niewidka/bardsai-fp32 \
  --cel ~/models/niewidka/bardsai-q4-bl32 --block-size 32
.venv/bin/python -m narzedzia.kwantyzuj_q4 \
  --zrodlo ~/models/niewidka/lfm25/fp32 \
  --cel ~/models/niewidka/lfm25/q4-bl32 --block-size 32

# pomiar
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m narzedzia.pomiar \
  --detektor poziom1 --modele ~/models/niewidka/bardsai-q4-bl32 --plik probki.jsonl
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m narzedzia.pomiar \
  --detektor poziom2-a --modele ~/models/niewidka/bardsai-q4-bl32 --plik probki.jsonl
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m narzedzia.pomiar \
  --detektor lfm25 --wariant q4-bl32 --plik probki.jsonl
```

Warianty bardsai fp32/INT8/Q4 to osobne katalogi wag (`bardsai-fp32/`,
katalog główny = INT8, `bardsai-q4-bl32/`, `bardsai-q4-bl128/`), każdy z manifestem
SHA-256 weryfikowanym przy ładowaniu; LFM2.5 warianty to podkatalogi `lfm25/<wariant>/`.

## Ograniczenia

- Korpus 190 próbek (103 OSOBA) — różnice 1-2 encji między wariantami traktować
  jako szum; pewny jest kierunek „Q4 nie degraduje", nie pojedyncze liczby.
- Czasy z WSL/8 wątków, jedna maszyna; docelowo na maszynie klienta mogą być inne.
- Q4 zamienia błąd „bramek formalnych" na pytanie praktyczne: bl32 przechodzi
  poziom 1 (P OSOBA 0.962 ≥ 0.95), co przy szumie korpusu nie jest trwałą
  własnością — nie podnosić tego jako „zaliczenia K2".
