# Licencje

Kod Niewidki jest na licencji MIT (plik `LICENSE`). Licencja MIT nie obejmuje modeli.
Modele pobierasz osobno i obowiązują je licencje ich twórców, opisane niżej.

## Modele (sprawdzone 2026-10-29)

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
- Paczki modeli na stronie wydań mają obok siebie pliki `LICENSE` obu modeli i plik `NOTICE` z informacją o zmianie (eksport ONNX, kwantyzacja Q4). Opis: `docs/WYDANIE.md`.
- Słownik imion `niewidka/dane/imiona_gus.txt` to dane GUS z dane.gov.pl (osobny temat, nie model).

## Biblioteki

Wersja okienkowa zawiera poniższe biblioteki. Wersja w przeglądarce instaluje je przez `uv sync`.

| Biblioteka | Licencja |
|---|---|
| FastAPI, Starlette, Pydantic | MIT, BSD-3-Clause, MIT |
| Uvicorn, HTTPX | BSD-3-Clause |
| ONNX Runtime | MIT |
| tokenizers (Hugging Face) | Apache 2.0 |
| NumPy | BSD-3-Clause |
| cryptography | Apache 2.0 albo BSD-3-Clause |
| keyring | MIT |
| python-docx, lxml | MIT, BSD-3-Clause |
| python-multipart | Apache 2.0 |
| python-stdnum | LGPL 2.1 lub nowsza (w paczce jako niezmienione pliki Pythona, które można podmienić) |
| pywebview (wersja okienkowa) | BSD-3-Clause |
| PyInstaller (budowa EXE) | GPL 2 z wyjątkiem dla budowanych programów |
| Font Lato | SIL Open Font License 1.1 (`niewidka/web/fonty/README.md`) |
