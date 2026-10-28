# Niewidka

Lokalna anonimizacja danych osobowych w polskim tekście.

## Kandydaci (stan 2026-10-27, liczby = deklaracje autorów, niezweryfikowane)

| Model | Rozmiar | Polski | Licencja | Uwagi |
|---|---|---|---|---|
| [LiquidAI/LFM2.5-Encoder-350M-PII-Detector](https://huggingface.co/LiquidAI/LFM2.5-Encoder-350M-PII-Detector) | 350M | wg właściciela tak; karta podaje 16 języków bez listy | LFM Open License v1.0 | 40 typów PII, kontekst 8k, `trust_remote_code` |
| [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/bardsai/eu-pii-anonimization-multilang) | 0,3B (XLM-R) | tak (24 języki UE) | Apache 2.0 | 36 klas z art. 9 RODO, ONNX INT8 pod CPU; **poziom 1 zmierzony** (`docs/WYNIK-K2.md`): OSOBA recall 0.957 / precision 0.917 |
| [nvidia/gliner-PII](https://huggingface.co/nvidia/gliner-PII) | ~0,5B (GLiNER) | nieudokumentowany | NVIDIA Open Model License | etykiety zero-shot w zapytaniu |
| [OpenMed/privacy-filter-multilingual-v2](https://huggingface.co/OpenMed/privacy-filter-multilingual-v2) | 1,4B MoE | nie | Apache 2.0 | punkt odniesienia |

## Następny krok

Brama K2 poziomu 1: precision OSOBA 0.917 < 0.95 (opcje dalsze w `docs/WYNIK-K2.md`).
Poziom 2 (LFM2.5) — **czeka na miejsce na dysku** (`~/models`: 887 MB wolne,
model ~1.4 GB).
