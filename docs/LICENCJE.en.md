# Licenses

[Polski](LICENCJE.md) · **English**

The Niewidka code is licensed under MIT (file `LICENSE`). The MIT license does not cover the models.
You download the models separately and they are governed by their authors' licenses, described below.

## Models

Source: the Hugging Face API (`/api/models/<repo>`, field `cardData.license`) and the `LICENSE` file in the model repository.
This is not legal advice; before deploying in an organization, the person responsible for compliance should read the license.

| Package | Model | License | Commercial use | Conditions for redistribution |
|---|---|---|---|---|
| Podstawowy (Basic) | [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/bardsai/eu-pii-anonimization-multilang) (XLM-RoBERTa) | Apache 2.0 | yes, no thresholds | copy of the license, marking of changed files (our file is an ONNX export with Q4 quantization, which counts as a change); the base model XLM-RoBERTa is licensed under MIT |
| Rozszerzony (Extended) | [LiquidAI/LFM2.5-Encoder-350M-PII-Detector](https://huggingface.co/LiquidAI/LFM2.5-Encoder-350M-PII-Detector) | LFM Open License v1.0 (based on Apache 2.0) | only if the organization has annual revenue below USD 10 million (§5); above the threshold, commercial use is not covered by the license; non-profit organizations have no threshold for non-commercial purposes | as with Apache 2.0: copy of the license, marking of changes (our file is ONNX with Q4 quantization, that is, a derivative work) |

## What follows from this
- "Commercial Use" in LFM means commercial advantage or compensation. Deciding whether a given use is such is up to the organization. The Extended package is optional; without it the program works at all levels.
- A company with revenue of USD 10 million or more should not use the Extended package commercially without a separate agreement with Liquid AI.
- Next to each package the interface shows the model address, the license name with a link and a short note, asking you to read the license before downloading. Downloading is not blocked.
- The model packages on the releases page come with the `LICENSE` files of both models and a `NOTICE` file stating the change (ONNX export, Q4 quantization). Description: `docs/WYDANIE.en.md`.
- The first-name dictionary `niewidka/dane/imiona_gus.txt` is GUS data from dane.gov.pl (a separate matter, not a model).

## Libraries

The desktop version includes the libraries below. The browser version installs them via `uv sync`.

| Library | License |
|---|---|
| FastAPI, Starlette, Pydantic | MIT, BSD-3-Clause, MIT |
| Uvicorn, HTTPX | BSD-3-Clause |
| ONNX Runtime | MIT |
| tokenizers (Hugging Face) | Apache 2.0 |
| NumPy | BSD-3-Clause |
| cryptography | Apache 2.0 or BSD-3-Clause |
| keyring | MIT |
| python-docx, lxml | MIT, BSD-3-Clause |
| python-multipart | Apache 2.0 |
| python-stdnum | LGPL 2.1 or later (shipped as unmodified Python files that can be replaced) |
| pywebview (desktop version) | BSD-3-Clause |
| PyInstaller (EXE build) | GPL 2 with an exception for the programs it builds |
| Lato font | SIL Open Font License 1.1 (`niewidka/web/fonty/README.md`) |
