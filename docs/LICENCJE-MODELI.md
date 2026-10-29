# Licencje modeli pobieranych przez Niewidkę (sprawdzone 2026-10-29)

Źródło: API Hugging Face (`/api/models/<repo>`, pole `cardData.license`) i plik `LICENSE` w repozytorium modelu.
To nie jest porada prawna; przed wdrożeniem w organizacji licencję czyta osoba odpowiedzialna za zgodność.

| Pakiet | Model | Licencja | Użycie komercyjne | Warunki przy rozpowszechnianiu |
|---|---|---|---|---|
| Podstawowy | [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/bardsai/eu-pii-anonimization-multilang) (XLM-RoBERTa) | Apache 2.0 | tak, bez progów | kopia licencji, oznaczenie zmienionych plików (nasz plik to eksport ONNX, czyli zmiana) |
| Rozszerzony | [LiquidAI/LFM2.5-Encoder-350M-PII-Detector](https://huggingface.co/LiquidAI/LFM2.5-Encoder-350M-PII-Detector) | LFM Open License v1.0 (na bazie Apache 2.0) | tylko gdy organizacja ma roczny przychód poniżej 10 mln USD (§5); ponad próg użycie komercyjne nie jest objęte licencją; organizacje non-profit bez progu dla celów niekomercyjnych | jak Apache 2.0: kopia licencji, oznaczenie zmian (nasz plik to ONNX z kwantyzacją Q4, czyli utwór zależny) |

## Co z tego wynika
- Urzędy: „Commercial Use” w LFM to korzyść handlowa albo wynagrodzenie. Praca urzędu zwykle nią nie jest, ale ocena należy do organizacji. Pakiet Rozszerzony jest opcjonalny; bez niego program działa na wszystkich poziomach.
- Firma z przychodem 10 mln USD i więcej nie powinna używać pakietu Rozszerzonego komercyjnie bez osobnej umowy z Liquid AI.
- Interfejs pokazuje przy każdym pakiecie adres modelu, nazwę licencji z linkiem i krótką uwagę, z prośbą o zapoznanie się z licencją przed pobraniem. Bez blokady (decyzja właściciela 2026-10-29).
- Do zrobienia przed publikacją wydania: dołączyć do paczek modeli pliki `LICENSE` obu modeli i informację o zmianie (eksport ONNX, kwantyzacja Q4). Dziś paczki zawierają tylko model, tokenizer i config.
- Słownik imion `niewidka/dane/imiona_gus.txt` to dane GUS z dane.gov.pl (osobny temat, nie model).
