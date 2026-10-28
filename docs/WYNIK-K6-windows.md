# WYNIK K6-Windows — aplikacja okienkowa na Windows

Data: 2026-10-28 (sesja claude-glm). Zakres wg zlecenia: `niewidka/okno.py` (API w
wątku + pywebview), klucz mapy w Windows Credential Manager przez keyring, wagi obok
aplikacji, `narzedzia/zbuduj_windows.ps1` (PyInstaller onedir), budowa na Windows z
klonu GitHuba (`py -3.13`), test exe na Windows (TXT i DOCX przez API), zrzuty,
rozmiar/start/RAM. Linux/Mac/Android później (zlecenie 12:45). Bez Dockera, bez codex.

## Co powstało

| plik | treść |
|---|---|
| `niewidka/okno.py` | desktop: uvicorn w wątku demona na 127.0.0.1, port **wolny ephemeral** albo `NIEWIDKA_PORT`; `NIEWIDKA_MODELE_KATALOG` ustawiany launcherem przez `setdefault` na `<katalog aplikacji>\modele` (jawne env/TOML wygrywa); okno pywebview z UI K5 (to samo `create_app` i ten sam rdzeń — zero duplikacji logiki); zamknięcie okna = `server.should_exit` + join; pierwsze uruchomienie bez klucza = **jawny ekran konfiguracji** (most `js_api`: tylko `utworz_klucz` i `otworz_aplikacje`); awarie startu (wagi/port/webview) = ekran błędu, a gdy webview sam nie działa = natywny `MessageBoxW`; `ustaw_katalog_roboczy()` = `chdir` na katalog aplikacji (cwd z UNC zawiesza WebView2); `NIEWIDKA_LOG_PLIK` = log startu bez konsoli; okno bez konsoli (`--windowed`) |
| `niewidka/klucze.py` | `utworz_klucz_w_keyringu(usluga, nadpisz=False)`: nowy klucz **wprost do magazynu systemowego** (Windows: Menedżer poświadczeń, backend WinVault przez keyring); istniejący wpis **blokuje** (nadpisanie odebrałoby dostęp do starych map), zamiana tylko świadomie (`--nadpisz` w CLI `do-keyringa`); klucz nigdy plik obok exe, nigdy w kodzie ani logach |
| `narzedzia/zbuduj_windows.ps1` | pełna budowa na Windows: klon z GitHuba (`pull --ff-only` przy ponownym biegu) → venv `py -3.13` → zależności runtime + `pywebview pythonnet pyinstaller pytest scipy` → **pytest jako bramka** (`$LASTEXITCODE`) → ikona (`narzedzia/ikona.py`) → plik wersji z `pyproject.toml` (walidacja loaderem PyInstallera PRZED budowaniem) → PyInstaller onedir `--windowed` (bramka `$LASTEXITCODE`; throw, gdy Niewidka działa i trzyma DLL w dist) → wagi bardsai + `manifest.json` z weryfikacją SHA-256 w skrypcie (ponownie przy ładowaniu w `detektory.py`) → ZIP onedir → Inno Setup tylko gdy `iscc` jest |
| `narzedzia/ikona.py` | ikona .ico (256/64/32/16, PNG wewnątrz ICO) pisana czystym stdlib, bez Pillow; karta z zaślepką w palecie styl.css; **placeholder** do czasu decyzji właściciela o logo (zlecenie 12:55) |
| testy | `tests/test_okno.py` (21: port, wagi obok exe, most klucza bez nadpisywania, fallback systemowy, strumienie/atrapy, katalog roboczy, awaria wątku serwera, teksty bez półpauz), `tests/test_klucze.py` (+5: generacja do keyringa, odmowa nadpisania, CLI `--nadpisz`, Windows ignoruje uprawnienia), `tests/test_ikona.py` (2), backend pamięciowy keyringa w `tests/conftest.py` |

## Kroki budowy dla IT (Windows 10/11 x64)

1. Wymagania: Python 3.13 (`py -3.13`), git, katalog z wagami bardsai
   (`model.onnx`, `tokenizer.json`, `config.json`, `tokenizer_config.json`,
   `manifest.json`); WebView2 Runtime (preinstalowany na Win10/11).
2. `powershell -ExecutionPolicy Bypass -File narzedzia\zbuduj_windows.ps1 -Wagi <katalog wag>`
   — skrypt sam klonuje `https://github.com/AuCourDe/niewidka.git` do
   `C:\Users\uzytkownik\niewidka-build\repo`, stawia venv, puszcza testy, buduje.
3. Wynik: `dist\Niewidka\Niewidka.exe` (uruchomienie dwuklikiem) + wagi w
   `dist\Niewidka\modele` + `Niewidka-0.1.0-windows-x64.zip`.
4. Diagnostyka bez konsoli: `set NIEWIDKA_LOG_PLIK=C:\temp\log.txt` przed startem.

## Test na Windows (pomiar, budowa z commita `81e536b`)

| co | wynik |
|---|---|
| testy jednostkowe na Windows (`py -3.13`, bez wag) | **384 passed, 24 skipped** (18 s; pomijane tylko testy modelowe) |
| start exe → `/api/stan` 200 | **2,3 s** (Defender po pierwszym skanie; pierwsze uruchomienie po instalacji potrafi być dłuższe z powodu skanu plików) |
| ukryj TXT (przez API exe) | 74 ms, status `ukonczony`, OSOBA/PESEL/TELEFON/EMAIL |
| przywróć TXT | 200, rozbieżności `[]`, treść **identyczna** z oryginałem |
| ukryj DOCX | **0,4 s**, status `ukonczony` (po naprawie K5b: surowy skan na RegulyDetektor zamiast ONNX; przed nią 270,8 s i timeout 120 s — pomiar własny w WSL) |
| przywróć DOCX | 200, rozbieżności `[]`; treść zgodna z semantyką K3/K3b: `w:ins` jako treść (numery ze śledzonych zmian wracają), `w:del` usunięte, obrazy usunięte wg polityki (`[OBRAZ USUNIĘTY]` nie wraca — dokumentowane) |
| pierwsze uruchomienie bez klucza | okno „Niewidka: konfiguracja klucza" (zrzut `docs/zrzuty/k6-windows-konfiguracja.png`); „Utwórz klucz" pisze do Menedżera poświadczeń; exe z kluczem wchodzi od razu w aplikację |
| RAM | 716 MB working set / 1022 MB prywatnie (wagi INT8 266 MB + onnxruntime) |
| rozmiar paczki | onedir **406,6 MB** (exe 9,9 MB + `_internal` + wagi 282 MB), ZIP **274 MB** |
| środowisko | Windows 11 (10.0.26300), Python 3.13.5, pywebview 6.2.1 (EdgeChromium/WebView2), PyInstaller 6.22.3, onnxruntime (CPU) |
| procesy po teście | ubite (`Get-Process Niewidka` = 0) |

Zrzuty: `docs/zrzuty/k6-windows.png` (okno aplikacji), `docs/zrzuty/k6-windows-konfiguracja.png`
(pierwsze uruchomienie bez klucza); kopie w `Desktop/C`.

## Naprawione po drodze (każde z pomiaru, nie z domysłu)

| objaw | przyczyna | naprawa | commit |
|---|---|---|---|
| każdy klucz z pliku odrzucany na Windows (testy API 500) | kontrola 0600 pod `hasattr(os, "chmod")` — Windows też ma `chmod`, a plik zgłasza 0o666 | sprawdzanie tylko przy `os.name == "posix"` (LLD §8, Gemini pkt 10) | `8fd2d8a` |
| manifest nie w dist → `BladDetektora` przy starcie | skrypt kopiował pliki Z manifestu, nie sam manifest | kopiowanie `manifest.json` obok wag | `38ee7e0` |
| wiszenie w `create_window` (py-spy: `winforms.py:834`) | cwd dziedziczony z sesji WSL na `\\wsl.localhost` — WebView2 wisi | `ustaw_katalog_roboczy()` (chdir na katalog aplikacji) | `47196f1` |
| log startu zawsze pusty | PyInstaller `--windowed` daje stdout/stderr jako **nieme atrapy**, nie `None` | w zamrożonej aplikacji strumienie przekierowywane zawsze (`buffering=1`) | `4445e3e` |
| `RuntimeError: Directory '..._internal\niewidka\web' does not exist` | `StaticFiles` montuje `niewidka/web`, którego PyInstaller nie zbierał | `--add-data niewidka\web` + `--add-data niewidka\dane` (r95.json, imiona_gus.txt czytane po `__file__`) | `81e536b` |
| znikające zasoby pywebview | `--collect-all pywebview` to nazwa DYSTRYBUCJI; moduł nazywa się `webview` | `--collect-all webview` (+ minimalny probierz exe potwierdzający samo webview) | `2a8a4f6`/`81e536b` |
| skrypt chwalił się STARYM exe | wiszący exe trzymał DLL: PyInstaller `--clean` dostawał Odmowę dostępu, skrypt nie sprawdzał `$LASTEXITCODE` | bramka po PyInstallerze + throw, gdy Niewidka działa | `03935cc` |
| błędy wersja.txt (PyInstaller 6.22), scipy w testach, UNC w wagach | patrz commity | `8734f77` |

Metoda diagnostyczna, która rozwikłała wiszenie: `NIEWIDKA_LOG_PLIK` (log startu),
`py-spy dump` na żywym procesie (stosy wątków) i minimalny probierz PyInstaller+pywebview
(ażeby odciąć problem biblioteki od kodu aplikacji).

## Ograniczenia (świadome) i kroki do zrobienia

- **Instalator Inno Setup**: `iscc` nieobecny na tej maszynie — zostawiona paczka ZIP;
  instalator `.exe` jako krok do zrobienia (skrypt już ma gałąź dla `iscc`).
- **Ikona to placeholder** (karta z zaślepką, `narzedzia/ikona.py`); właściwe logo wchodzi
  z zlecenia 12:55 (K5b) — podmiana to jedna flaga `--icon` w skrypcie.
- **Pierwsze uruchomienie po instalacji** może potrwać dłużej (Defender skanuje ~400 MB
  pakietu); kolejne starty 2-3 s.
- Klucz w Credential Manager pod usługą `niewidka` (konto `mapa`), wartość base64 32 B;
  zamiana tylko `python -m niewidka.klucze do-keyringa --nadpisz`.
- K7b (zlecenie 14:05/14:08) przebuduje paczkę na wersję **bez wag** z pobieraniem
  pakietów modeli po instalacji — ten skrypt pozostaje podstawą budowy rdzenia.
- WebView2 Runtime wymagany (standard na Win10/11); na czystych maszynach korporacyjnych
  do sprawdzenia przez IT.

## Weryfikacja całości (WSL, drzewo robocze)

```
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m pytest tests/ -q
→ 437 passed, 1 xfailed in 56.99s
.venv/bin/python -m ruff check niewidka/ tests/ narzedzia/  → All checks passed!
```

(w pełnym zestawie pracują też pliki sesji równoległych K4b/K5b/K2e; udział K6: 21 testów
okna, 15 kluczy, 2 ikony; na Windows 384 passed / 24 skipped)
