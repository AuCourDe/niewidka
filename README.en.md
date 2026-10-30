# Niewidka

[Polski](README.md) · **English**

Niewidka hides personal data in Polish texts and documents before you send them to a chat AI.
It runs on your computer and sends nothing to the internet.

Paste a letter or pick a `.txt` or `.docx` file. Niewidka replaces names, PESEL and NIP
numbers, addresses, phone numbers, e-mails, bank accounts and ID card numbers with tags such
as `[OSOBA_1]` or `[PESEL_1]`. Send that text to a chat AI, paste the answer back, and
Niewidka puts the real data where the tags were.

The program is built for Polish: detection is tuned for Polish names in all their inflected
forms and for Polish identifiers with checksums. The interface is in Polish.

Niewidka helps, but it does not replace a person. Review the preview before you send anything.

## Two versions

| | Desktop | Browser |
|---|---|---|
| For | anyone on Windows | IT staff and people who run Python programs |
| Start | `Niewidka.exe` | `python -m niewidka.api`, then a web browser |
| Install | unzip | Python 3.11 or newer and `uv` |
| Runs on | Windows 10 and 11 | Windows, Linux, macOS |

Both versions look and work the same. The program listens only on your computer
(`127.0.0.1`), so nobody on the network can connect to it.

Models run on each computer or on one shared server in the local network. With a shared
server users do not download models. Admin guide (Polish): `docs/SERWER-INFERENCJI.md`.

## Quick start: desktop

1. Download `Niewidka-<version>-windows-x64.zip` from
   <https://github.com/AuCourDe/niewidka/releases>.
2. Unzip it anywhere and run `Niewidka.exe`.
3. Click „Utwórz klucz” (Create key). The key is stored in Windows Credential Manager.
4. Click „Pobierz podstawowy (zalecane)” (Download basic, recommended). The package is
   about 190 MB and you download it once.
5. Paste a text and click „Ukryj dane” (Hide data).

## Quick start: browser

```bash
git clone https://github.com/AuCourDe/niewidka.git
cd niewidka
uv sync
uv run python -m niewidka.klucze do-keyringa
uv run python -m niewidka.api
```

Open <http://127.0.0.1:8390> and download the basic package on first run. Change the port
with `NIEWIDKA_PORT` or in `niewidka.toml`.

Linux without a desktop has no password store. Create a key file instead of `do-keyringa`:

```bash
mkdir -p ~/.config/niewidka
uv run python -m niewidka.klucze nowy-plik ~/.config/niewidka/klucz
NIEWIDKA_KLUCZ_PLIK=~/.config/niewidka/klucz uv run python -m niewidka.api
```

## What it detects

Personal names (with inflection), PESEL, NIP, REGON, IBAN, payment card and Polish ID card
numbers (checksum validated), addresses, phone numbers, e-mails, dates, IP addresses,
SWIFT codes and logins. You can add your own words with „Ukryj wszędzie” (Hide everywhere)
or with permanent lists in the settings.

Three quality levels trade speed for recall. After hiding, an independent check re-reads
the output and lists anything that still looks like personal data. By default the export
waits until you decide about each such place.

The map that links tags to real data is encrypted with AES-256 and stored locally. The key
lives in the system password store or in a file chosen by IT, never inside the program.
Maps expire after 30 days by default.

## Documentation (Polish)

- `docs/PRZEWODNIK.md`: features, how it works, deployment options.
- `docs/INSTRUKCJA.md`: step by step user guide.
- `docs/KONFIGURACJA.md`: all settings, `niewidka.toml` and environment variables.
- `docs/SERWER-INFERENCJI.md`: shared model server.
- `docs/MODELE.md`: models, quality levels and measurements.
- `docs/LICENCJE.md`: model and library licenses.
- `docs/rozwoj/`: design documents, measurements and build notes.

## Build from source (Windows)

You need Windows 10 or 11, Python 3.13 (`py -3.13`) and Git.

```powershell
git clone https://github.com/AuCourDe/niewidka.git C:\niewidka-src
cd C:\niewidka-src
powershell -ExecutionPolicy Bypass -File narzedzia\zbuduj_windows.ps1 -KatalogBudowy C:\niewidka-build
```

The script installs dependencies, runs the tests and builds `Niewidka.exe` and a ZIP.
Models are not bundled; the program downloads them on first run.

Tests: `uv run pytest`. Lint: `uv run ruff check`.

## License

The code is MIT licensed (`LICENSE`). You may use, change and share it, also in public
administration and companies. The MIT license does not cover the models. They are
downloaded separately under their authors' licenses: the basic package under Apache 2.0,
the extended package under LFM Open License v1.0, which limits commercial use.
Details: `docs/LICENCJE.md`.

Niewidka uses statistical models and does not find every piece of personal data in every
text. Check the result before you pass a document on. The authors are not liable for
incomplete anonymization. Report security issues as described in `SECURITY.md`.
