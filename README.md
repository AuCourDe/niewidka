# Niewidka

Lokalna anonimizacja danych osobowych w polskim tekście.

## Kandydaci (stan 2026-10-27, liczby = deklaracje autorów, niezweryfikowane)

| Model | Rozmiar | Polski | Licencja | Uwagi |
|---|---|---|---|---|
| [LiquidAI/LFM2.5-Encoder-350M-PII-Detector](https://huggingface.co/LiquidAI/LFM2.5-Encoder-350M-PII-Detector) | 350M | wg właściciela tak; karta podaje 16 języków bez listy | LFM Open License v1.0 | 40 typów PII, kontekst 8k, `trust_remote_code` |
| [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/brahim-23/eu-pii-anonimization-multilang) | 0,3B (XLM-R) | tak (24 języki UE) | Apache 2.0 | 36 klas z art. 9 RODO, ONNX INT8 pod CPU |
| [nvidia/gliner-PII](https://huggingface.co/nvidia/gliner-PII) | ~0,5B (GLiNER) | nieudokumentowany | NVIDIA Open Model License | etykiety zero-shot w zapytaniu |
| [OpenMed/privacy-filter-multilingual-v2](https://huggingface.co/OpenMed/privacy-filter-multilingual-v2) | 1,4B MoE | nie | Apache 2.0 | punkt odniesienia |

## Następny krok

Zestaw polskich próbek (PESEL, NIP, odmienione nazwiska, adresy) + `KRYTERIA.md`,
potem pomiar recall/precision każdego kandydata.
