# Models and quality levels

[Polski](MODELE.md) · **English**

## Model packages

| Package | Model | What it provides | Download size |
|---|---|---|---|
| **Podstawowy** (Basic, required) | [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/bardsai/eu-pii-anonimization-multilang), ONNX Q4 | full operation at all levels | approx. 191 MB |
| **Rozszerzony** (Extended, optional) | [LiquidAI/LFM2.5-Encoder-350M-PII-Detector](https://huggingface.co/LiquidAI/LFM2.5-Encoder-350M-PII-Detector), ONNX Q4 | at the Najdokładniej (Most thorough) level additionally IP addresses, SWIFT codes and logins | approx. 227 MB |

Numbers with a checksum (PESEL, NIP, REGON, IBAN, cards, ID cards) are detected by rules,
independently of the models. IP addresses and card numbers are already detected by the Basic package.

## Detection levels

Measured on a corpus of 233 made-up samples with Polish personal data (2026-11-03).

| Level | Composition | OSOBA recall / precision | R95 OSOBA |
|---|---|---|---|
| 1 Szybko (Fast) | rules + basic model | 0.990 / 0.962 | 0.0452 |
| 2 Dokładniej (More thorough) | 1 + person confidence threshold 0.2 + a second pass over windows shifted by half | 0.990 / 0.944 | 0.0452 |
| 3 Najdokładniej (Most thorough) | 2 + GUS first-name dictionary (CC0), with the Extended package also IP, SWIFT, logins | 0.990 / 0.936 | 0.0452 |

R95 is the upper bound (95%) of the share of personal data that may remain in the text. Full
values for every type and level are in `niewidka/dane/r95.json`, and `/api/stan` provides them to
the interface. You can set the confidence threshold in `niewidka.toml` (`[detekcja] prog_osoba`).

The program deliberately prefers to hide too much rather than too little: a missed piece of personal data costs more
than an ordinary word replaced with a placeholder.

## Measuring on your own

`narzedzia/pomiar.py` calculates recall, precision and R95 on the `tests/korpus/` corpus.
`narzedzia/kalibracja.py` selects the confidence threshold. Both require the models to be downloaded.
