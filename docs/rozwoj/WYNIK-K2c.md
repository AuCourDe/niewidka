# WYNIK pomiaru K2c — warianty uzupełniające (LFM2.5 fp32)

Data: 2026-10-28 (sesja). Korpus: **182 próbki** (jak w K2b). Progi: `KRYTERIA.md` — **nieprzesunięte**.  
LFM2.5 w wariancie fp32 ładowany wyłącznie jako uzupełnienie OSOBA tam, gdzie nie nachodzi na zakresy z reguł/bardsai (pierwszeństwo granic).

## Porównanie OSOBA — TP/FP/FN, recall, precision

| detektor | OSOBA TP/FP/FN | OSOBA recall | OSOBA precision |
|---|---|---|---|
| poziom 1 (reguły + bardsai, referencja K2b) | 100/6/3 | 0.971 | 0.943 |
| poziom2-uzup (LFM2.5 fp32, tylko nie nachodzące, bez dodatkowych filtrów) | 100/7/3 | 0.971 | 0.935 |
| poziom2-uzup-b (jak wyżej + zaczyna się wielką literą i ≥ 2 znaki) | 100/7/3 | 0.971 | 0.935 |

## Pełny raport (wszystkie typy)

### poziom 1 (referencja)
| typ | TP | FP | PN | FN | recall | precision |
|---|---|---|---|---|---|---|
| ADRES | 10 | 0 | 0 | 0 | 1.000 | 1.000 |
| DATA | 8 | 0 | 0 | 0 | 1.000 | 1.000 |
| DOKUMENT | 5 | 0 | 4 | 0 | 1.000 | 1.000 |
| EMAIL | 7 | 0 | 0 | 0 | 1.000 | 1.000 |
| IBAN | 6 | 0 | 4 | 0 | 1.000 | 1.000 |
| NIP | 7 | 0 | 4 | 0 | 1.000 | 1.000 |
| OSOBA | 100 | 6 | 0 | 3 | 0.971 | 0.943 |
| PESEL | 7 | 0 | 5 | 0 | 1.000 | 1.000 |
| REGON | 7 | 0 | 4 | 0 | 1.000 | 1.000 |
| TELEFON | 8 | 0 | 0 | 0 | 1.000 | 1.000 |
| **łącznie (K1, bez OSOBA)** | 65 | 0 | 21 | 0 | 1.000 | 1.000 |
| **łącznie (wszystkie)** | 165 | 6 | 21 | 3 | 0.982 | 0.965 |

Czas na próbkę (CPU): średnia 13.4 ms, mediana 12.1 ms, max 38.0 ms (próbek: 182)  
RAM procesu (szczyt RSS): 797 MiB

### poziom2-uzup (LFM2.5 fp32, uzupełniający)
| typ | TP | FP | PN | FN | recall | precision |
|---|---|---|---|---|---|---|
| ADRES | 10 | 0 | 0 | 0 | 1.000 | 1.000 |
| DATA | 8 | 0 | 0 | 0 | 1.000 | 1.000 |
| DOKUMENT | 5 | 0 | 4 | 0 | 1.000 | 1.000 |
| EMAIL | 7 | 0 | 0 | 0 | 1.000 | 1.000 |
| IBAN | 6 | 0 | 4 | 0 | 1.000 | 1.000 |
| NIP | 7 | 0 | 4 | 0 | 1.000 | 1.000 |
| OSOBA | 100 | 7 | 0 | 3 | 0.971 | 0.935 |
| PESEL | 7 | 0 | 5 | 0 | 1.000 | 1.000 |
| REGON | 7 | 0 | 4 | 0 | 1.000 | 1.000 |
| TELEFON | 8 | 0 | 0 | 0 | 1.000 | 1.000 |
| **łącznie (K1, bez OSOBA)** | 65 | 0 | 21 | 0 | 1.000 | 1.000 |
| **łącznie (wszystkie)** | 165 | 7 | 21 | 3 | 0.982 | 0.959 |

Czas na próbkę (CPU): średnia 256.3 ms, mediana 226.7 ms, max 759.7 ms (próbek: 182)  
RAM procesu (szczyt RSS): 2685 MiB

### poziom2-uzup-b (jak wyżej + wielka litera i ≥ 2 znaki)
| typ | TP | FP | PN | FN | recall | precision |
|---|---|---|---|---|---|---|
| ADRES | 10 | 0 | 0 | 0 | 1.000 | 1.000 |
| DATA | 8 | 0 | 0 | 0 | 1.000 | 1.000 |
| DOKUMENT | 5 | 0 | 4 | 0 | 1.000 | 1.000 |
| EMAIL | 7 | 0 | 0 | 0 | 1.000 | 1.000 |
| IBAN | 6 | 0 | 4 | 0 | 1.000 | 1.000 |
| NIP | 7 | 0 | 4 | 0 | 1.000 | 1.000 |
| OSOBA | 100 | 7 | 0 | 3 | 0.971 | 0.935 |
| PESEL | 7 | 0 | 5 | 0 | 1.000 | 1.000 |
| REGON | 7 | 0 | 4 | 0 | 1.000 | 1.000 |
| TELEFON | 8 | 0 | 0 | 0 | 1.000 | 1.000 |
| **łącznie (K1, bez OSOBA)** | 65 | 0 | 21 | 0 | 1.000 | 1.000 |
| **łącznie (wszystkie)** | 165 | 7 | 21 | 3 | 0.982 | 0.959 |

Czas na próbkę (CPU): średnia 308.7 ms, mediana 258.1 ms, max 1045.3 ms (próbek: 182)  
RAM procesu (szczyt RSS): 2696 MiB

## Werdykt wg KRYTERIA §4 (progi nie przesunięte)

- **Poziom 1**: spełnia progi K1; OSOBA recall 0.971 ≥ 0.90, precision 0.943 < 0.95 (brak formalnego zaliczenia bramy poziomu 1 dla OSOBA wg tabeli §4 — jak odnotowano w K2b).
- **Poziom 2 (wariant uzupełniający)**: kryterium poziomu 2 wymaga m.in. OSOBA recall ≥ 0.95 ORAZ precision żadnego typu nie spada poniżej poziomu 1.  
  W obu wariantach **precision OSOBA spada** (0.943 → 0.935, +1 FP) przy niezmienionym recall (0.971). Dodatkowo wariant B nie eliminuje fałszywych trafień nie nachodzących na zakresy podstawy (np. „Koleżanka” w kontekście z osobą). **Warianty nie spełniają kryterium poziomu 2.** LFM2.5 fp32 dodany wyłącznie jako uzupełnienie nie przynosi zysku na tym korpusie — potwierdza obserwacje K2b.
