# AGENTS.md

[Polski](README.md) · [English](README.en.md) · **For Agents**

Guidance for coding agents (Claude Code, Codex, Cursor, Gemini and others) that install,
configure, deploy, change or review Niewidka. Read it fully before the first change.
Human documentation lives in `docs/` in Polish (`*.md`) and English (`*.en.md`); this file
is the technical map that ties it together. When this file and the code disagree, the code
wins: fix this file in the same change.

## 1. Project overview

Niewidka hides personal data in Polish text before the text goes to a chat AI, and puts the
data back afterwards. Everything runs locally: rules and ONNX models on the user's CPU (GPU
optional), no cloud service.

```
Jan Kowalski, PESEL 44051401359, ul. Lipowa 5, Gdańsk
   ↓ hide (POST /api/ukryj)
[OSOBA_1], PESEL [PESEL_1], [ADRES_1]        + encrypted map <id>.nwidka
   ↓ the user edits the text in any chat AI, the tags survive
   ↓ restore (POST /api/przywroc)
Jan Kowalski, PESEL 44051401359, ul. Lipowa 5, Gdańsk
```

- **Input:** pasted text, `.txt` or `.docx` up to 25 MB. **Output:** the same format, first
  line `ZANONIMIZOWANY. ...` with the map id, data replaced by numbered tags.
- **Reversible:** tags are numbered per type in order of appearance; people keep one number
  across inflected forms (`[OSOBA_1_F2]` = person 1, form variant 2), so restoring works by
  (tag, variant) even after the chat rewrote the sentence.
- **Quality slider:** three levels, 1 Szybko (fast), 2 Dokładniej (more accurate),
  3 Najdokładniej (most accurate). For each level the UI shows R95: the 95% upper bound of
  the share of personal data that may remain, from calibration (`niewidka/dane/r95.json`).
- **Users:** non-technical people. The UI is Polish, plain language, no jargon.
- **Platforms:** Windows desktop app (EXE built by CI) and a browser version for any OS.
  Linux and macOS desktop packages and Android are planned, not built.
- **Non-goals:** no PDF, scans or images; no user accounts; no guarantee of 100% recall.
  The human always reviews the result.

## 2. How a request flows

Hide (`niewidka/rdzen.py: ukryj`):

1. **Format adapter** (`formaty/tekst.py`, `formaty/docx_.py`) splits the document into
   segments and runs. DOCX: structure allowlist, comments, footnotes, endnotes, headers,
   footers, thumbnails, document variables, extra properties and (by default) images are
   removed; tracked changes are accepted; fields become plain text (their result stays);
   a text box paragraph is a segment of its own;
   an unknown part is rejected. ZIP reading goes through `archiwum.py` (real byte budget, fail-closed).
2. **Detectors** (`detektory.py`) run on sliding windows: `reguly.py` (regex + checksums for
   PESEL, NIP, REGON, IBAN (also the domestic NRB form), ID card, card/Luhn, IP; valid sum =
   confidence 1.0, wrong sum = "suspicious" 0.5, never dropped) plus the ONNX
   token-classification model of the package.
   Level 2 lowers the person threshold and adds a second pass shifted by half a window;
   level 3 adds the GUS first-name list and, if installed, the extended model.
   With `[inferencja] adres` set, `zdalny.py` sends text to the shared server instead.
3. **Merging** (`scalanie.py`) turns candidates into entities; **people** (`osoby.py`) groups
   inflected forms of one person.
4. **Tags** (`znaczniki.py`) replace entities and add the header note.
5. **Write check** (`kontrola.py`) reads the result like a foreign document and scans it again
   at every level (DOCX also raw, part by part). Findings that are not tags become warnings;
   with `kontrola.blokada` they block copy and download until the user decides (STOP).
6. **Map** (`mapa.py`): JSON encrypted with AES-256-GCM, `b"NWID"` + version + nonce + id; the
   id is AAD. The key comes from `klucze.py` (keyring or key file), only inside the worker thread.
7. **Store** (`magazyn.py`) keeps `<id>.nwidka` + metadata without personal data in the data
   dir and deletes it after `retencja_dni`. Journal `dziennik.jsonl` never holds content.

Preview corrections (`POST /api/popraw`, `poprawki.py`) recompute from the cached detections
without calling the model again: "Ukryj wszędzie" (hide everywhere), "To nie dane" (not
personal data), "Odkryj". Numbers with a valid checksum can never be marked as "not data".
Constant lists "Zawsze ukrywaj" / "Nigdy nie ukrywaj" (`listy.py`) apply the same way.

Restore (`rdzen.py: przywroc`): the map comes from an uploaded `.nwidka`, from the id in the
header note, or from the store by the job the user picked; unknown or changed tags are
reported as discrepancies. Tags are numbered from 1 in every document, so without the note
the API never picks a map by itself: it returns `wybierz_mape` with the best-matching jobs.
Every preview correction issues a new map; the store keeps all versions of a job and lists
the newest one (`MagazynMap.lista`, `wersje`).

## 3. Repository layout

| Path | Responsibility |
|---|---|
| `niewidka/model.py` | data model: `TypEncji`, `Zakres`, `Encja`, `Segment`, `Dokument` (offsets in segment characters) |
| `niewidka/rdzen.py` | `ukryj()` and `przywroc()`; no HTTP, no GUI |
| `niewidka/reguly.py`, `detektory.py`, `scalanie.py`, `osoby.py`, `znaczniki.py`, `kontrola.py` | detection pipeline, see section 2 |
| `niewidka/formaty/` | format adapters, registry extension -> adapter |
| `niewidka/mapa.py`, `klucze.py`, `magazyn.py` | map encryption, key sources, map store with retention |
| `niewidka/poprawki.py`, `listy.py` | preview corrections, constant lists |
| `niewidka/jakosc.py` | R95 per level from calibration |
| `niewidka/pakiety.py`, `aktualizacje.py` | model download (resume, SHA-256), signed update catalog, rollback |
| `niewidka/konfig.py` | `Konfig` dataclass, TOML + `NIEWIDKA_*` env |
| `niewidka/api.py` | FastAPI app `create_app()`, entry `python -m niewidka.api` |
| `niewidka/okno.py` | desktop window (pywebview + embedded uvicorn), entry of the EXE |
| `niewidka/serwer_inferencji.py`, `zdalny.py` | optional shared model server and its client |
| `niewidka/web/` | UI: `index.html`, `apka.js`, `styl.css`, local fonts; no framework, no CDN |
| `niewidka/dane/` | `pakiety.json` (package files, sizes, SHA-256), `r95.json`, GUS names, control sample, catalog public key |
| `konfiguracja/*.przyklad.toml` | commented config templates (app, inference server, client) |
| `narzedzia/` | Windows build script, pinned build requirements, ONNX export, Q4 quantization, calibration, measurement, catalog signing |
| `tests/` | pytest suite; `tests/korpus/` fictional measurement corpus |
| `testy_e2e/` | browser UI script (`gui_poprawki.py`) and API runs against real models |
| `.github/workflows/wydanie.yml` | release pipeline on `v*` tags (the only workflow; there is no PR CI) |
| `docs/` | user, admin and release docs, PL and EN |

Dependency direction: `web` -> `api` / `okno` -> `rdzen` -> pipeline modules -> `model`.
The core never imports FastAPI, pywebview or anything from `web/`.

## 4. Setup and run

Requirements: Python 3.11+ (the Windows build uses 3.13) and [uv](https://docs.astral.sh/uv/).
The project is not an installable package (`package = false`): use `uv sync`, never `pip install .`.

```bash
git clone https://github.com/AuCourDe/niewidka.git && cd niewidka
uv sync
uv run python -m niewidka.klucze do-keyringa          # once: map key in the system keyring
uv run python -m niewidka.api                         # http://127.0.0.1:8390
uv run python -m niewidka.okno                        # desktop window instead of the browser
```

Headless Linux has no keyring. Create a key file and point to it:

```bash
mkdir -p ~/.config/niewidka
uv run python -m niewidka.klucze nowy-plik ~/.config/niewidka/klucz   # refuses to overwrite
NIEWIDKA_KLUCZ_PLIK=~/.config/niewidka/klucz uv run python -m niewidka.api
```

Models are not in the repo or the EXE. On first run the user downloads the packages from the
latest GitHub release: `podstawowy` (basic, ~191 MB, required) and `rozszerzony` (extended,
~227 MB, optional). Same through the API: `POST /api/pakiety {"akcja":"pobierz","pakiet":"podstawowy"}`.
Model sources and licenses: `docs/MODELE.en.md`, `docs/LICENCJE.en.md`.

## 5. Deployment modes

| Mode | What to do | Docs |
|---|---|---|
| One computer | unzip the release ZIP or run `setup.exe`; models download on first run | `docs/INSTRUKCJA.en.md` |
| Many computers without internet | download the six package files once; users click „Zainstaluj z folderu” (Install from folder) in Settings, or serve the folder over HTTP and set `NIEWIDKA_MODELE_ZRODLO` | `docs/KONFIGURACJA.en.md` |
| Shared model server | one machine (CPU or GPU) runs `serwer_inferencji`; clients set `[inferencja]`; only text fragments travel, over TLS with a token; maps and keys stay on clients | `docs/SERWER-INFERENCJI.en.md` |

```bash
cp konfiguracja/serwer-inferencji.przyklad.toml serwer-inferencji.toml   # edit paths
uv run python -m niewidka.serwer_inferencji nowy-token /etc/niewidka/token
uv run python -m niewidka.serwer_inferencji --konfig serwer-inferencji.toml
```

Off loopback the server refuses to start without TLS and a token file (exit code 2).
The app itself never listens off loopback: each user runs their own copy. There is no
multi-user web deployment and no user accounts by design.

## 6. Configuration

Precedence: defaults < `niewidka.toml` (working directory; the EXE reads the file next to
itself) < `NIEWIDKA_*` environment variables. Every option is in
`konfiguracja/niewidka.przyklad.toml`; the full table is in `docs/KONFIGURACJA.en.md`.
Invalid values stop the start with the option name in the message.

| Env | Default | Meaning |
|---|---|---|
| `NIEWIDKA_PORT` | `8390` | browser version port (desktop picks a free port) |
| `NIEWIDKA_HOST` | `127.0.0.1` | loopback only, anything else is rejected |
| `NIEWIDKA_KLUCZ_PLIK` | unset | map key file (base64, 32 bytes, 0600 on Linux); unset = keyring |
| `NIEWIDKA_MODELE_KATALOG` | data dir | model folder |
| `NIEWIDKA_MODELE_ZRODLO` | latest GitHub release | mirror URL for offline networks |
| `NIEWIDKA_PROVIDER` | `CPUExecutionProvider` | `CUDAExecutionProvider` needs `onnxruntime-gpu`, `DmlExecutionProvider` needs `onnxruntime-directml` |
| `NIEWIDKA_POZIOM` | `1` | level for API calls without one (the UI always sends its own) |
| `NIEWIDKA_PROG_OSOBA` | from code | person confidence threshold |
| `NIEWIDKA_WYKRYWAJ_DATE` | `true` | hide dates |
| `NIEWIDKA_KONTROLA_BLOKADA` | `true` | write check findings block copy and download |
| `NIEWIDKA_OBRAZY` | `usun` | DOCX image policy |
| `NIEWIDKA_MAPY_RETENCJA_DNI` | `30` | stored map lifetime; `0` = do not store maps |
| `NIEWIDKA_LISTY_PLIK` | unset | constant lists file set by the admin |
| `NIEWIDKA_INFERENCJA_ADRES` | unset | shared server URL; unset = local models |
| `NIEWIDKA_AKTUALIZACJE` | see template | model update mode |

Data dir: `%LOCALAPPDATA%\Niewidka` on Windows, `$XDG_DATA_HOME/Niewidka` or
`~/.local/share/Niewidka` elsewhere. It holds models, maps, the journal and lists.

## 7. Local HTTP API

Served by `niewidka/api.py` on `127.0.0.1`. The main page `/` embeds a per-process session
token; every `POST`/`PUT`/`DELETE` on `/api/` and the sensitive `GET`s need header
`x-niewidka-token`, a matching `Host` and, if sent, a matching `Origin` (403 otherwise).
Errors return `{"blad": "..."}` with Polish text.

| Endpoint | Purpose |
|---|---|
| `POST /api/ukryj` | form: `poziom` 1-3, exactly one of `tekst` or `plik`; returns a ZIP (result + `.nwidka`) with `x-niewidka-*` headers: map id, task id, statistics, warnings, R95, markers with a valid checksum (`pewne`) |
| `POST /api/popraw` | JSON: `zadanie` + full lists `ukryj`, `nie_dane`, `zostaw`, `na_inne`, `odkryj`; recomputes without the model |
| `POST /api/przywroc` | form: `wynik` file or `tekst`, plus `mapa` file or `identyfikator` (or the id in the header note); with neither, 422 `wybierz_mape` lists the best-matching jobs |
| `GET /api/mapy`, `DELETE /api/mapy/{id}`, `DELETE /api/mapy` | stored maps |
| `GET`/`PUT /api/listy` | constant lists |
| `GET`/`POST /api/pakiety` | package status, `pobierz` (download) and `instaluj` (from folder) |
| `GET`/`POST /api/aktualizacje` | signed model updates |
| `GET /api/stan` | readiness, packages, R95 per level |

Shared server (`serwer_inferencji.py`): `POST /v1/wykryj` (text -> spans), `GET /v1/stan`,
bearer token. It never sees keys or maps and never stores or logs content.

Inference runs in a thread pool with one slot, a queue limit (`kolejka`, full = 503) and a
timeout. Size limits are checked before buffering and again after decompression.

## 8. Testing

```bash
uv run pytest -q                                   # unit + API; tests marked `model` skip without weights
uv run ruff check
NIEWIDKA_MODELE_KATALOG=<models> uv run pytest -q -m model   # with real weights
.venv/bin/python testy_e2e/gui_poprawki.py                   # UI in headless Chrome (Playwright)
uv run python testy_e2e/test_api.py --baza http://127.0.0.1:<port>   # corpus vs a live server
uv run python narzedzia/pomiar.py                  # recall, precision, R95 on tests/korpus/
```

- Expected values come from an independent source (the corpus annotations, a checksum
  computed by hand), never from the output of the code under test.
- Test data is fictional. Never add real personal data to tests, fixtures, docs or issues.
- `tests/test_web.py` enforces UI text rules (no en or em dashes) and checks the UI assets.
- Changing a level, threshold or model means re-running calibration (`narzedzia/kalibracja.py`)
  and updating `niewidka/dane/r95.json` and `docs/MODELE*.md` with the new numbers.

## 9. Build and release

Windows build, on Windows 10/11 with Python 3.13 and Git:

```powershell
powershell -ExecutionPolicy Bypass -File narzedzia\zbuduj_windows.ps1 -KatalogBudowy C:\niewidka-build
```

The script clones from GitHub (never from a working copy), installs the hash-pinned
`narzedzia/wymagania-budowy.txt`, runs the tests (`-PominTesty` skips them), builds
`dist\Niewidka\Niewidka.exe` with PyInstaller, zips it and builds `setup.exe` when Inno Setup
(`iscc`) is on PATH. Models are not bundled.

Release: push tag `vX.Y.Z`. `wydanie.yml` builds on `windows-latest` with `contents: read`,
then a separate publish job uploads the ZIP, the installer and `.sha256` files to the release.
Actions are pinned to full SHAs. The model package files, `podstawowy-LICENSE.txt`
(Apache 2.0), `rozszerzony-LICENSE.txt` (LFM Open License v1.0), `NOTICE.txt` and
`SHA256SUMS.txt` are uploaded separately from a machine with the weights; names must match
`zrodlo` in `niewidka/dane/pakiety.json`. Signed update catalogs: `docs/WYDANIE.en.md`.
To change a dependency: edit `narzedzia/wymagania-budowy.in`, regenerate the `.txt` with hashes.

## 10. Rules that are easy to miss

- **Fail-closed.** A detector, model or server error returns an error, never unchecked text.
  Do not add fallbacks that return the input or a partial result.
- **Loopback only.** Do not add an option to listen on another address.
- **Secrets.** The map key, inference token and signing key come only from the system keyring
  or a file named in config or env. Never in the repo, config values, logs, exceptions,
  `repr`, URLs or test output. No silent key generation.
- **No content in logs.** Errors log a UUID and the exception type. Map store metadata and
  the journal hold no personal data and no file names.
- **Checksums win.** A number with a valid checksum is always personal data; "To nie dane"
  cannot unhide it.
- **Restore is by (tag, variant), not by position.** Keep tag syntax `[TYP_N]` and
  `[OSOBA_N_Fk]` stable; the header note has no square brackets on purpose.
- **Offline first.** No CDN, no telemetry, no network call besides model downloads, the update
  catalog and the configured inference server. Downloads are verified by size and SHA-256
  before use.
- **Identifiers are Polish by design** (`ukryj`, `przywroc`, `poziom`, `TypEncji`). Keep that
  style for new code; do not rename existing identifiers to English.
- **Comments, docstrings and commit messages are English.** Keep comments minimal: only where
  the reason is not obvious from the code.
- **UI text is Polish**, plain language, no en or em dashes. Docs exist in Polish and English:
  change both files together.

## 11. Common tasks

| Task | Where |
|---|---|
| New rule-based data type | add the value to `TypEncji` (`model.py`), a rule with a validator in `reguly.py`, tag handling if special in `znaczniki.py`, tests in `tests/test_reguly.py`, the row in `docs/PRZEWODNIK*.md` |
| New config option | field in `Konfig` + parsing in `wczytaj_konfig` (`konfig.py`), the option in `konfiguracja/niewidka.przyklad.toml`, rows in `docs/KONFIGURACJA*.md`, tests in `tests/test_konfig.py` (the template must load to exactly `Konfig()`) |
| New file format | adapter in `niewidka/formaty/`, register it in `formaty/__init__.py`, raw scanning in `kontrola.py` if it is an archive, tests in `tests/test_formaty.py` |
| New or updated model | export (`narzedzia/eksport_lfm25.py`), quantize (`narzedzia/kwantyzuj_q4.py`), adapter in `detektory.py`, entry with sizes and SHA-256 in `niewidka/dane/pakiety.json`, calibration and `r95.json`, license files in the release, `docs/MODELE*.md`, `docs/LICENCJE*.md` |
| UI change | `niewidka/web/`; run `tests/test_web.py` and `testy_e2e/gui_poprawki.py`; keep it accessible (labels, focus, contrast in light and dark) |

## 12. Contributions and repository hygiene

- Write a failing test first for behavior changes; keep `pytest` and `ruff` green.
- Small, atomic commits with English messages; stage explicit paths, not `git add -A`.
- The repository holds the product only: code, tests and documentation for users and admins.
  No work notes, backlogs, chat transcripts, agent reports or consultation logs, and no
  mention of which tool or person suggested a change.
- Security issues go through private reporting (`SECURITY.md`), never a public issue.
- License: MIT for the code (`LICENSE`); models have their own licenses (`docs/LICENCJE.en.md`).
