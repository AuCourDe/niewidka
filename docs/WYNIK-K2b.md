# WYNIK pomiaru K2b — poziom 2 (LFM2.5-Encoder-350M-PII-Detector) + naprawa reguł

Data: 2026-10-28 (sesja claude-glm e79f). Korpus: **182 próbki** (62 z K2 + 120 od
niezależnego autora, commit `10c77f6`). Progi: `KRYTERIA.md` — **nieprzesunięte**.
Wagi i eksport: `~/models/niewidka/lfm25/{zrodlo,fp32,int8}` (manifest SHA-256),
pobranie httpx (`narzedzia/pobierz_model.py --model lfm25`), eksport jednorazowy
`narzedzia/eksport_lfm25.py` po przeglądzie kodu (`docs/KOD-LFM25.md`, werdykt: kod
bezpieczny; runtime ładuje wyłącznie ONNX przez onnxruntime).

## Eksport ONNX (jednorazowy)

| wariant | rozmiar | czas eksportu | sanity vs torch (3 przykłady, 74 tokeny) |
|---|---|---|---|
| fp32 (`lfm25/fp32/`) | 1353,3 MB | 12,4 s | max diff **1,5e-05**, 0 różnic argmax |
| int8 dynamiczny (`lfm25/int8/`) | 339,0 MB | 14,8 s | max diff 7,59, **4/74 różnic argmax** |

## Pomiar na korpusie 182 — per typ vs progi

### Poziom 1 (reguły + bardsai) — przed i po naprawie reguł

Nowy korpus ujawnił 3 FN reguł (tel-085 `+48 123 456 789`, tel-086 `123-456-789`,
data-094 `1982-05-13`): telefony stacjonarne 3-3-3 od cyfry 1–4 i data ISO RRRR-MM-DD
były poza wzorcami. Naprawa (TDD, commit `3af2316`): stacjonarny 3-3-3 od 1–4
(separatory OBOWIĄZKOWE — ciąg 9 cyfr bez spacji to pułapka na REGON) + ISO w DATA.

| typ | przed naprawą R/P | po naprawie R/P | próg R/P | werdykt po naprawie |
|---|---|---|---|---|
| PESEL–EMAIL, DOKUMENT | 1.000 / 1.000 | 1.000 / 1.000 | = 1.00 | **spełnia** |
| ADRES | 1.000 / 1.000 | 1.000 / 1.000 | ≥ 0.80 / ≥ 0.90 | **spełnia** |
| DATA | 0.875 / 1.000 | **1.000** / 1.000 | ≥ 0.90 / ≥ 0.95 | **spełnia** |
| TELEFON | 0.750 / 1.000 | **1.000** / 1.000 | ≥ 0.90 / ≥ 0.95 | **spełnia** |
| **OSOBA** | **0.971 / 0.943** | 0.971 / 0.943 | ≥ 0.90 / ≥ 0.95 | recall **spełnia**, precision **NIE** (0.943 < 0.95) |
| łącznie (K1) | 0.954 / 1.000 | **1.000 / 1.000** | ≥ 0.90 / ≥ 0.95 | **spełnia** |
| łącznie (z OSOBA) | 0.964 / 0.964 | 0.982 / 0.965 | ≥ 0.90 / ≥ 0.95 | **spełnia** |

Poziom 1: 6 FP OSOBA na 182 próbki (użycia metajęzykowe), 3 FN (długie/wariantowe
formy). Wydajność: **7,6 ms/próbkę** (CPU, 8 wątków WSL), RAM 798 MiB.
R95 po naprawie → `niewidka/dane/r95.json` (OSOBA **0.0736**; typy reguł 0.19–0.45).

### LFM2.5 solo i poziom 2 (kompozyt reguły + bardsai + LFM2.5) — po naprawie reguł

Typy regułowe w poziomie 2 identyczne jak poziom 1 (1.000 / 1.000, 0 FN); różnica
wyłącznie w OSOBA — LFM2.5 dostarcza drugi głos przez unię scalania:

| detektor | OSOBA TP/FP/FN | OSOBA recall | OSOBA precision | czas/próbkę | RAM |
|---|---|---|---|---|---|
| poziom 1 (referencja) | 100/6/3 | **0.971** | **0.943** | 7,6 ms | 798 MiB |
| LFM2.5 fp32 solo | 57/13/46 | 0.553 | 0.814 | 66,0 ms | 2268 MiB |
| LFM2.5 int8 solo | 41/17/62 | **0.398** | 0.707 | 28,4 ms | 654 MiB |
| poziom 2 (fp32) | 95/12/8 | 0.922 | 0.888 | 90,6 ms | 2787 MiB |
| poziom 2 (int8) | 97/9/6 | 0.942 | 0.915 | 43,3 ms | 1190 MiB |

## Werdykt poziomu 2 (KRYTERIA §4): **NIE zaliczony — zysku brak, jest strata**

Kryterium poziomu 2: progi poziomu 1 ORAZ OSOBA recall ≥ 0.95 ORAZ precision żadnego
typu nie spada poniżej poziomu 1. Oba warianty zawodzą dwukrotnie:

1. **Recall spada** mimo DOŁĄCZENIA drugiego detektora: 100 TP → 95 (fp32) / 97 (int8).
   Mechanizm: scalanie maskuje UNIĄ nakładających się zakresów (LLD §5); rozmyte
   granice LFM2.5 (m.in. wciąga „mgr ", „podpisał" albo gubi nazwisko w wielosłowach)
   nakładają się na dokładne trafienia bardsai i rozszerzają je poza oczekiwaną encję
   → dokładne TP zamieniają się w FN+FP. Ten sam mechanizm, przez który adaptery nie
   dostarczają typów regułowych (KRYTERIA §1.3).
2. **Precision spada**: 0.943 → 0.888 / 0.915.

Solo LFM2.5 też jest wyraźnie słabszy od bardsai w polskich zdaniach biurowych
(0.553 vs 0.971 recall). Dodatkowo zmierzona degradacja LFM2.5 z długością: na
powtarzalnych tekstach ~50+ tokenów liczba trafień spada (test odnotowany jako
xfail — cecha modelu, nie dekodera; ONNX zgodny z torch na 1e-05).

## Kwantyzacja INT8 (decyzja z polecenia: „jeśli nie psuje recall")

**Psuje** — solo recall 0.398 vs 0.553 (−28% względnie). INT8 odpada dla LFM2.5;
gdyby model wchodził, tylko fp32 (koszt: 1353 MB RAM zamiast 339 MB, ~2,3× wolniej).

## Decyzja orkiestratora — brama K2

Zgodnie z decyzją właściciela (2026-10-28): **w narzędziu do ukrywania danych FN
(wyciek) jest groźniejszy niż FP (nadmiarowe ukrycie), więc precision OSOBA < 0.95
przy recall ≥ 0.90 NIE blokuje dalszych kamieni.** Konkretnie:

- Brama K2 pozostaje **formalnie niezaliczona** (0.943 < 0.95) — próg w KRYTERIA.md
  **nie jest przesuwany**, wynik raportowany uczciwie (ta sekcja).
- Kamienie K3+ ruszają (K3 zrealizowany w tej samej sesji — niżej).
- Poprawa precision OSOBA to zadanie: (a) poziomu 2/3 — detekcja LFM2.5 jako
  ŹRÓDŁO UZUPEŁNIAJĄCE tam, gdzie bardsai milczy (głosowanie, nie unia), (b) podglądu
  „połącz/rozdziel/odznacz" w UI (K5) — człowiek zdejmuje FP metajęzykowe.
- LFM2.5 po pomiarze **nie wchodzi** do produktu (brak zysku, nakład RAM/czasu):
  adapter, eksport i pomiar zostają w repo jako mierzalny ślad; re-pomiar przy nowym
  modelu OSOBA albo większym korpusie (opcja 4 z WYNIK-K2.md — herbert/GLiNER PL).

## K3 — adaptery TXT i DOCX (MVP), zrealizowane w tej samej sesji

Zakres wg zlecenia; testy `tests/test_formaty.py` (27), generator wzorców
`narzedzia/generator_dokumentow.py` (python-docx): runy z przeplotem stylów, tabela,
nagłówek/stopka, komentarz, track changes (w:del/w:ins), hiperłącza http+mailto,
przypis, obraz z tekstem alternatywnym, właściwości, wariant z makrem i z częścią obcą.

- **TXT**: jeden segment; zapis = dopisek + treść (UTF-8, BOM tolerowany).
- **DOCX**: segment = akapit (także komórki tabel i pola tekstowe); wczytanie czyści
  w:del (usunięty tekst), odnośniki komentarzy/przypisów, rozpakowuje mailto/file;
  znaczniki wstawiane klonami runów w miejsce oryginalnych (styl lewego fragmentu);
  zapis: dopisek „ZANONIMIZOWANO w Niewidka…" pierwszym akapitem, usuwane części:
  comments, footnotes, header*, footer*, docProps/app, miniatura, customXml (wektor
  wstrzyknięcia danych — Astra pkt 5); core.xml czyszczone (autor/tytuł/…);
  Content_Types i rels przebudowane (usuwane wpisy osierocone); hiperłącza http
  zostają. **Allowlista**: cokolwiek poza spisem (np. makra `vbaProject.bin`,
  osadzone obiekty `word/embeddings/`) → `ElementNieobslugiwany` (blokada z listą).
- **Weryfikacja zapisu ZAWSZE** (Astra pkt 8): round-trip test ponownie wczytuje
  wynik i skanuje tymi samymi regułami — **0 nowych znalezisk**, znaczniki dokładnie
  na pozycjach encji, dane znalezione nieobecne w wyniku, pułapka (numer z błędną
  sumą) zamaskowana.
- Mapowanie przesunięć na runy: `podziel_segment`/`wstaw_znaczniki` — cięcia na
  granicach zamian ORAZ granicach runów; testy pokrywają zamianę w środku runu, na
  granicy runów i dziedziczenie stylu.

Dowód: `NIEWIDKA_MODELE_KATALOG=… .venv/bin/python -m pytest tests/ -q` →
**188 passed, 1 xfailed**, ruff czysty (commity sesji: `b077269`…`70a9506`).
