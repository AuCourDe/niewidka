# Modele i poziomy jakości

**Polski** · [English](MODELE.en.md)

## Pakiety modeli

| Pakiet | Model | Co daje | Do pobrania |
|---|---|---|---|
| **Podstawowy** (wymagany) | [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/bardsai/eu-pii-anonimization-multilang), ONNX Q4 | pełne działanie na wszystkich poziomach | ok. 191 MB |
| **Rozszerzony** (opcjonalny) | [LiquidAI/LFM2.5-Encoder-350M-PII-Detector](https://huggingface.co/LiquidAI/LFM2.5-Encoder-350M-PII-Detector), ONNX Q4 | na poziomie Najdokładniej dodatkowo adresy IP, kody SWIFT i loginy | ok. 227 MB |

Numery z sumą kontrolną (PESEL, NIP, REGON, IBAN, karty, dowody) wykrywają reguły,
niezależnie od modeli. Adresy IP i numery kart wykrywa już pakiet podstawowy.

## Poziomy wykrywania

Pomiar na korpusie 182 zmyślonych próbek z polskimi danymi osobowymi.

| Poziom | Skład | OSOBA recall / precision | R95 OSOBA |
|---|---|---|---|
| 1 Szybko | reguły + model podstawowy | 0.971 / 0.943 | 0.0736 |
| 2 Dokładniej | 1 + próg pewności osoby 0.2 + drugi przebieg okien przesuniętych o pół | 0.981 / 0.953 | 0.0599 |
| 3 Najdokładniej | 2 + słownik imion GUS (CC0), z pakietem rozszerzonym także IP, SWIFT, loginy | 0.981 / 0.953 | 0.0599 |

R95 to górna granica (95%) odsetka danych osobowych, które mogą zostać w tekście. Pełne
wartości dla każdego typu i poziomu są w `niewidka/dane/r95.json`, a `/api/stan` podaje je
interfejsowi. Próg pewności ustawisz w `niewidka.toml` (`[detekcja] prog_osoba`).

Program celowo woli ukryć za dużo niż za mało: pominięta dana osobowa kosztuje więcej
niż zwykłe słowo zamienione na znacznik.

## Pomiar u siebie

`narzedzia/pomiar.py` liczy recall, precision i R95 na korpusie `tests/korpus/`.
`narzedzia/kalibracja.py` dobiera próg pewności. Oba wymagają pobranych modeli.
