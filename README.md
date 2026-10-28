# Niewidka

Lokalna anonimizacja danych osobowych w polskim tekście.

## Kandydaci (stan 2026-10-28, liczby = pomiary na korpusie 182 próbek)

| Model | Rozmiar | Polski | Licencja | Wynik pomiaru |
|---|---|---|---|---|
| [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/bardsai/eu-pii-anonimization-multilang) | 0,3B (XLM-R) | tak (24 języki UE) | Apache 2.0 | **poziom 1 zmierzony** (`docs/WYNIK-K2b.md`): OSOBA recall **0.971** / precision **0.943**, 7,6 ms/próbkę CPU, 798 MiB |
| [LiquidAI/LFM2.5-Encoder-350M-PII-Detector](https://huggingface.co/LiquidAI/LFM2.5-Encoder-350M-PII-Detector) | 350M | wg właściciela tak; karta: 16 języków | LFM Open License v1.0 | **poziom 2 zmierzony** (`docs/WYNIK-K2b.md`): solo OSOBA 0.553/0.814 (fp32); w kompozycie **obniża** recall i precision poziomu 1 — nie wchodzi; eksport ONNX w repo (`narzedzia/eksport_lfm25.py`) |
| [nvidia/gliner-PII](https://huggingface.co/nvidia/gliner-PII) | ~0,5B (GLiNER) | nieudokumentowany | NVIDIA Open Model License | kandydat na drugi głos OSOBA (opcja 4 z `docs/WYNIK-K2.md`) |
| [OpenMed/privacy-filter-multilingual-v2](https://huggingface.co/OpenMed/privacy-filter-multilingual-v2) | 1,4B MoE | nie | Apache 2.0 | punkt odniesienia |

## Poziomy wykrywania (suwak jakości, `docs/WYNIK-K2d.md`)

| poziom | skład | OSOBA recall/precision | R95 OSOBA |
|---|---|---|---|
| 1 | reguły + bardsai | 0.971 / 0.943 | 0.0736 |
| 2 | 1 + próg pewności OSOBA 0.2 (`NIEWIDKA_PROG_OSOBA`) + okna półkrokowe | 0.981 / 0.953 | 0.0599 |
| 3 | 2 + słownik imion GUS (CC0) | 0.981 / 0.953 (bez zysku na korpusie) | 0.0599 |

Pełne R95 per typ i poziom: `niewidka/dane/r95.json`; `/api/stan` podaje poziomy
i R95 dla interfejsu. Próg i parametry z konfiguracji (`niewidka/konfig.py`,
TOML `detekcja.prog_osoba`), nie z kodu.

## Stan

- **K4 gotowe**: mapa (AES-256-GCM), klucze (plik 0600/keyring), przywracanie,
  API (`/api/ukryj`, `/api/przywroc`, `/api/stan`) — `docs/WYNIK-K4.md`.
- **K3 gotowe**: adaptery TXT i DOCX (runy, czyszczenie, allowlista, blokady),
  round-trip z weryfikacją zapisu — `tests/test_formaty.py`, `docs/WYNIK-K2b.md`.
- Brama K2: precision OSOBA 0.943 < 0.95 — **nie blokuje** (decyzja właściciela:
  FN groźniejszy niż FP); poziomy 2/3 podnoszą OSOBA do 0.981/0.953 (`docs/WYNIK-K2d.md`).
- Następny krok: K5 (web lokalny), potem K6 (desktop Windows) — `docs/KAMIENIE.md`.
