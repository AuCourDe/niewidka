# Przegląd kodu modelu LFM2.5-Encoder-350M-PII-Detector (K2b)

Repo: [LiquidAI/LFM2.5-Encoder-350M-PII-Detector](https://huggingface.co/LiquidAI/LFM2.5-Encoder-350M-PII-Detector).
Model wymaga `trust_remote_code`, więc PRZED pierwszym uruchomieniem przejrzano pliki
kodu (2026-10-28, sesja claude-glm e79f; kopia do przeglądu: pliki źródłowe w
`~/models/niewidka/lfm25/`, manifest SHA-256). Gotowego ONNX w repo NIE MA —
eksport robimy sami (`narzedzia/eksport_lfm25.py`), inferencja produkcyjna wyłącznie
`onnxruntime` (kondycja: runtime nie ładuje żadnego kodu z tego repo).

## Licencja

**LFM Open License v1.0** („other" na HF) — nie standard Apache/MIT. Do użytku
wewnętrznego (narzędzie w organizacji) dopuszcza użycie i dystrybucję wyników;
przy JAKIEJKOLWIEK dystrybucji poza organizacją przeczytać całość przed wydaniem.
Odnotowane jako ryzyko zależności (środowisko B: biblioteki kontrolowane przez JFrog;
tu zależność to artefakt wag, nie pakiet).

## Co jest w repo (10 plików, `narzedzia/pobierz_model.py --model lfm25`)

| plik | zawartość |
|---|---|
| `model.safetensors` | wagi: LFM2.5-Encoder-350M (full fine-tune) + głowa token-klasyfikacji |
| `config.json` | architektura: 16 warstw (8× shortconv + full attention na zmianę — `layer_types`), hidden 1024, vocab 65536, max_position 128k, `id2label` 161 etykiet **BIOES** (40 typów PII + O), `classifier_dropout` 0.1; `auto_map` wskazuje `modeling_phase2_tc.py` |
| `modeling_phase2_tc.py` | **jedyne plik z torch/transformers**. Definiuje `Lfm2BidirP2ForTokenClassification`: (a) łata `transformers.models.lfm2` na dwukierunkowość (maska nieprzyczynowa, konwolucja bez przyczynowości) — to encoder MLM, nie generator; (b) dokłada standardową głowę `nn.Linear(hidden, num_labels)` i `TokenClassifierOutput`. Forward: `input_ids, attention_mask -> logits`. **Brak I/O, sieci, subprocess, eval/exec** |
| `context_cued.py` | czysty `re`: słowniki fraz-wskazówek („Passport No:", „numer paszportu", …) łapiące alfanumeryczne ID bez kształtu (paszport, case number, login/hasło). **Uwaga:** `_load_base_decode()` (lazy, wywoływana tylko przez `hybrid_with_context`) próbuje załadować plik ze SZTYWNEJ ścieżki `/lambdafs/simon/models/pii-detect-v8/...` — to pozostałość środowiska treningowego LiquidAI; u nas ścieżka nie istnieje i funkcja **nie jest używana** (nasz adapter używa wyłącznie ONNX, bez warstw cue) |
| `pii_hybrid_decode.py` | dekoder hybrydowy: regexy AUTH (e-mail, IBAN+walidator, JWT, karta+Luhn…) + dopasowanie granic modelu („snap"). Używany przez producenta przy inferencji transformers. U nas pomijany — typy z kształtem wykrywają reguły Niewidki (pewność 1.0, KRYTERIA §1.3) |
| `label_schema.json` | spis typów (dokumentacyjny; `num_labels: 109` — starszy niż config 161, liczy się config) |
| `tokenizer.json` + `tokenizer_config.json` | tokenizer BPE (backend `tokenizers`), tokeny specjalne `<|startoftext|>/<|pad|>/<|mask|>`, `model_input_names: input_ids, attention_mask` |
| `README.md`, `LICENSE` | karta modelu; LFM Open License v1.0 (wyżej) |

## Werdykt przeglądu

Kod **bezpieczny do uruchomienia jednorazowo** (eksport): tylko torch/transformers/re,
brak dostępu do sieci, plików, subprocessów; brak obserwowalności/telemetrii. Jedyne
zastrzeżenie (martwa ścieżka `/lambdafs/...` w nieużywanej funkcji) nie jest kodem
wykonawczym przy imporcie. Eksport wykonuje `narzedzia/eksport_lfm25.py` na kopii z
manifestem SHA-256; runtime NIEWIDKI ładuje wyłącznie wyeksportowany `.onnx` przez
`onnxruntime` — kod z repo HF nie jest już nigdy wykonywany.

## Decyzje integracji (przed pomiarem jakościowym)

1. Adapter dostarcza **wyłącznie OSOBA** (`identity.person_name`) — jak bardsai
   (WYNIK-K2): typy z sumą kontrolną/regułami mają dokładne granice z reguł; 39
   pozostałych klas pomijanych.
2. Dekoder rozszerzony o **BIOES** (`zdekoduj_bio`): E=koniec encji, S=jedno-tokenowa.
3. Okna przesuwne 510/448 tokenów — jak poziom 1 (porównywalność); model wspiera do
   128k, ale segmenty tekstów biurowych są krótkie, a krotność okien mierzalna.
4. Eksport: fp32 (`lfm25/fp32/`) + INT8 dynamiczne (`lfm25/int8/`), oba z manifestem
   SHA-256; do poziomu 2 wchodzi INT8, o ile nie psuje recall (pomiar obu).
