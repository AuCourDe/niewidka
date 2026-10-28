# Niewidka

Lokalna anonimizacja danych osobowych w polskim tekście.

## Kandydaci (stan 2026-10-28, liczby = pomiary na korpusie 182 próbek)

| Model | Rozmiar | Polski | Licencja | Wynik pomiaru |
|---|---|---|---|---|
| [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/bardsai/eu-pii-anonimization-multilang) | 0,3B (XLM-R) | tak (24 języki UE) | Apache 2.0 | **poziom 1 zmierzony** (`docs/WYNIK-K2b.md`): OSOBA recall **0.971** / precision **0.943**, 7,6 ms/próbkę CPU, 798 MiB |
| [LiquidAI/LFM2.5-Encoder-350M-PII-Detector](https://huggingface.co/LiquidAI/LFM2.5-Encoder-350M-PII-Detector) | 350M | wg właściciela tak; karta: 16 języków | LFM Open License v1.0 | **poziom 2 zmierzony** (`docs/WYNIK-K2b.md`): solo OSOBA 0.553/0.814 (fp32); w kompozycie **obniża** recall i precision poziomu 1 — nie wchodzi; eksport ONNX w repo (`narzedzia/eksport_lfm25.py`) |
| [nvidia/gliner-PII](https://huggingface.co/nvidia/gliner-PII) | ~0,5B (GLiNER) | nieudokumentowany | NVIDIA Open Model License | kandydat na drugi głos OSOBA (opcja 4 z `docs/WYNIK-K2.md`) |
| [OpenMed/privacy-filter-multilingual-v2](https://huggingface.co/OpenMed/privacy-filter-multilingual-v2) | 1,4B MoE | nie | Apache 2.0 | punkt odniesienia |

## Stan

- **K3 gotowe**: adaptery TXT i DOCX (runy, czyszczenie, allowlista, blokady),
  round-trip z weryfikacją zapisu — `tests/test_formaty.py`, `docs/WYNIK-K2b.md`.
- Brama K2: precision OSOBA 0.943 < 0.95 — **nie blokuje** (decyzja właściciela:
  FN groźniejszy niż FP); poprawa = drugi głos + UI „połącz/rozdziel/odznacz" (K5).
- Następny krok: K4 (mapa, klucze, API) — `docs/KAMIENIE.md`.
