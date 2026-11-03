# Niewidka: configuration

[Polski](KONFIGURACJA.md) · **English**

For the person who installs the program or looks after it in an organization.

## Where the program gets its settings

1. Default values. The program works right away, with no configuration.
2. The `niewidka.toml` file. A template with all options: `konfiguracja/niewidka.przyklad.toml`.
   - The desktop version reads the file from the folder where `Niewidka.exe` lives.
   - The browser version reads the file from the folder you start it from.
3. `NIEWIDKA_*` environment variables. They override the file.

Restart the program after changing settings. An invalid value stops startup and the program
names the offending option.

## Where the program keeps its data

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\Niewidka` |
| Linux and macOS | `~/.local/share/Niewidka` (or `$XDG_DATA_HOME/Niewidka`) |

Inside are the `modele` and `mapy` folders, the `listy.json` and `ustawienia.json` files, and the
registry of issued maps. Updating the program does not touch this folder. Models and maps stay on disk.

## Map key

The key encrypts the maps. The program does not store it itself. It reads it on every use
from the system store or from a specified file.

- **System store** (default). In the desktop version click „Utwórz klucz” (Create key). In the
  browser version run `python -m niewidka.klucze do-keyringa`.
- **File.** For Linux without a desktop, where there is no password store. Create the key with
  `python -m niewidka.klucze nowy-plik /etc/niewidka/klucz-mapy`. Point to it in the settings
  file (`[klucze] plik = "/etc/niewidka/klucz-mapy"`) or with the `NIEWIDKA_KLUCZ_PLIK` variable.
  On Linux the file must have `0600` permissions, otherwise the program rejects it.
  When the configured file is missing, the program reports an error and does not use the system store.

A new key invalidates all old maps. The program will not overwrite an existing key.
In the system store, replacing the key is forced with `do-keyringa --nadpisz`. The `nowy-plik`
command does not overwrite an existing file: give it a new path or delete the old file first.

## Desktop version

Unpack the ZIP into any folder. You do not need to install anything. Updating means
unpacking the new ZIP into the same place.

The most useful variables:

| What | How |
|---|---|
| models in a different folder | `NIEWIDKA_MODELE_KATALOG` |
| fixed port instead of a random one | `NIEWIDKA_PORT` |
| error log to a file | `NIEWIDKA_LOG_PLIK=C:\Niewidka\niewidka.log` |
| downloading models from a server on the local network | `NIEWIDKA_MODELE_ZRODLO=https://lustro.firma.local/niewidka/` |

**Computers without internet.** Download the package files once, on a computer with internet access.
The file names are in the `zrodlo` field in `niewidka/dane/pakiety.json`, and the files are on the
releases page. Then choose one of two ways:

- Folder. Put the files in a network folder. The user pastes the path in Ustawienia (Settings)
  and clicks „Zainstaluj z folderu” (Install from folder) next to the package.
- HTTP server. Publish the folder on a server on the local network and set `NIEWIDKA_MODELE_ZRODLO`
  on the computers to its address. The „Pobierz” (Download) button then downloads the models from there.

In both cases the program checks the size and SHA-256 checksum of every file.

Model updates on networks without internet are described in `docs/WYDANIE.en.md`.

## Browser version

You need Python 3.11 or newer and the `uv` tool (<https://docs.astral.sh/uv/>).

```bash
git clone https://github.com/AuCourDe/niewidka.git
cd niewidka
uv sync
uv run python -m niewidka.klucze do-keyringa   # once
cp konfiguracja/niewidka.przyklad.toml niewidka.toml
uv run python -m niewidka.api
```

The page is served at <http://127.0.0.1:8390>. The program listens only on this computer.
Each user runs it on their own machine. The program does not have user login yet,
so it cannot be shared over the network.

Several people can, however, use one model server. The page and the maps then stay
on the users' computers, and only the text to be checked goes to the server. Instructions:
`docs/SERWER-INFERENCJI.en.md`. Template for user settings: `konfiguracja/klient-web.przyklad.toml`.

## All options

In the tables: section and option name in `niewidka.toml`, environment variable, default value.

### `[serwer]`

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `host` | `NIEWIDKA_HOST` | `127.0.0.1` | only addresses of this computer |
| `port` | `NIEWIDKA_PORT` | `8390` | port of the browser version; the desktop version takes a free port unless you set the variable |

### `[detekcja]`

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `poziom` | `NIEWIDKA_POZIOM` | `1` | level for API requests that do not specify one: 1 Szybko (Fast), 2 Dokładniej (More thorough), 3 Najdokładniej (Most thorough); the slider in the program always sends a level |
| `prog_osoba` | `NIEWIDKA_PROG_OSOBA` | `0.2` | confidence threshold for persons at levels 2 and 3 |
| `wykrywaj_date` | `NIEWIDKA_WYKRYWAJ_DATE` | `true` | hiding dates |
| `modele_katalog` | `NIEWIDKA_MODELE_KATALOG` | data folder | folder with models |
| `provider` | `NIEWIDKA_PROVIDER` | `CPUExecutionProvider` | `CPUExecutionProvider` (processor), `CUDAExecutionProvider` (NVIDIA card, requires `onnxruntime-gpu`), `DmlExecutionProvider` (Windows, requires `onnxruntime-directml`) |
| `watki` | `NIEWIDKA_WATKI` | `0` | processor threads, 0 = automatic |

### `[klucze]`

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `plik` | `NIEWIDKA_KLUCZ_PLIK` | none | file with the map key |
| `usluga` | `NIEWIDKA_KEYRING_USLUGA` | `niewidka` | name of the entry in the system store |

### `[limity]`

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `rozmiar_mb` | `NIEWIDKA_MAX_ROZMIAR_MB` | `25` | largest input file in MB |
| `rozpakowane_mb` | `NIEWIDKA_MAX_ROZPAKOWANE_MB` | `200` | largest `.docx` after unpacking, in MB |
| `tekst_mb` | `NIEWIDKA_MAX_TEKST_MB` | `1` | largest text in MB |
| `kolejka` | `NIEWIDKA_KOLEJKA` | `4` | documents waiting in the queue |
| `zlecenia` | `NIEWIDKA_ZLECENIA` | `8` | requests handled at the same time |
| `timeout_s` | `NIEWIDKA_TIMEOUT_S` | `120` | time allowed for one document, in seconds |

### `[kontrola]`

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `blokada` | `NIEWIDKA_KONTROLA_BLOKADA` | `true` | when the check has doubts, the result waits for the user's decision |
| `obrazy` | `NIEWIDKA_OBRAZY` | `usun` | images in `.docx`: `usun` (remove), `blokuj` (block) or `zostaw` (keep) |

### `[mapy]`

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `retencja_dni` | `NIEWIDKA_MAPY_RETENCJA_DNI` | `30` | after how many days maps disappear; 0 = the program does not save them |
| `katalog` | `NIEWIDKA_MAPY_KATALOG` | data folder | folder of saved maps |
| `uniewaznij_pobrane` | `NIEWIDKA_MAPY_UNIEWAZNIJ_POBRANE` | `false` | a deleted map stops working also as a downloaded `.nwidka` file |

The 30-day period is a program setting. The correct period is set by the organization's data protection officer.

### `[poprawki]`

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `maks_zadan` | `NIEWIDKA_POPRAWKI_MAKS_ZADAN` | `4` | how many recent documents can be corrected |
| `ttl_s` | `NIEWIDKA_POPRAWKI_TTL_S` | `900` | for how long, in seconds |

### `[aktualizacje]`

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `tryb` | `NIEWIDKA_AKTUALIZACJE` | user's choice (`sprawdzaj`) | `reczne`, `sprawdzaj`, `automatyczne`, `wylaczone`; setting it blocks changes in Ustawienia (Settings) |

### `[listy]`

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `zawsze` | none | `[]` | administrator's list: always hide |
| `nigdy` | none | `[]` | administrator's list: never hide |
| `tylko_administrator` | `NIEWIDKA_LISTY_TYLKO_ADMINISTRATOR` | `false` | the user cannot change their own lists |
| `plik` | `NIEWIDKA_LISTY_PLIK` | data folder | the user's lists file |

The „nigdy” (never) list must not contain numbers with a checksum (PESEL, NIP, REGON, IBAN,
card number, ID card number). The same entry must not be on both lists.

### `[inferencja]`

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `adres` | `NIEWIDKA_INFERENCJA_ADRES` | none | address of the shared model server; none = local models |
| `token_plik` | `NIEWIDKA_INFERENCJA_TOKEN_PLIK` | none | file with the token from the administrator |
| `ca_plik` | `NIEWIDKA_INFERENCJA_CA_PLIK` | none | certificate of the internal certificate authority |
| `timeout_s` | `NIEWIDKA_INFERENCJA_TIMEOUT_S` | `60` | time to wait for the server, in seconds |
| `zezwol_bez_tls` | `NIEWIDKA_INFERENCJA_ZEZWOL_BEZ_TLS` | `false` | unencrypted connection, only on an isolated network |

### Environment variables only

| Variable | Default | Meaning |
|---|---|---|
| `NIEWIDKA_MODELE_ZRODLO` | releases page on GitHub | where to download models from |
| `NIEWIDKA_PAKIETY_LIMIT_CZASU_S` | `1800` | time limit for downloading a package, in seconds |
| `NIEWIDKA_REJESTR_MAP` | data folder | file with the registry of issued maps |
| `NIEWIDKA_LOG_PLIK` | none | desktop version: write the log to a file |

The shared model server has its own settings file: `konfiguracja/serwer-inferencji.przyklad.toml`,
described in `docs/SERWER-INFERENCJI.en.md`.
