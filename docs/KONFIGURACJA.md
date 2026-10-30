# Niewidka: konfiguracja

Instrukcja dla osoby, która instaluje program albo opiekuje się nim w urzędzie.

## Skąd program bierze ustawienia

1. Wartości domyślne. Program działa od razu, bez konfiguracji.
2. Plik `niewidka.toml`. Wzór ze wszystkimi opcjami: `konfiguracja/niewidka.przyklad.toml`.
   - Wersja okienkowa czyta plik z folderu, w którym leży `Niewidka.exe`.
   - Wersja w przeglądarce czyta plik z folderu, z którego ją uruchamiasz.
3. Zmienne środowiskowe `NIEWIDKA_*`. Wygrywają z plikiem.

Po zmianie ustawień uruchom program ponownie. Błędna wartość zatrzyma start i program
poda nazwę złej opcji.

## Gdzie program trzyma dane

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\Niewidka` |
| Linux i macOS | `~/.local/share/Niewidka` (albo `$XDG_DATA_HOME/Niewidka`) |

W środku są foldery `modele` i `mapy`, pliki `listy.json`, `ustawienia.json` i rejestr
wydanych map. Aktualizacja programu nie rusza tego folderu. Modele i mapy zostają na dysku.

## Klucz mapy

Klucz szyfruje mapy. Program go u siebie nie zapisuje. Odczytuje go przy każdym użyciu
z magazynu systemu albo ze wskazanego pliku.

- **Magazyn systemu** (domyślnie). W wersji okienkowej kliknij „Utwórz klucz”. W wersji
  w przeglądarce uruchom `python -m niewidka.klucze do-keyringa`.
- **Plik.** Dla Linuksa bez pulpitu, gdzie nie ma magazynu haseł. Utwórz klucz poleceniem
  `python -m niewidka.klucze nowy-plik /etc/niewidka/klucz-mapy`. Wskaż go w pliku
  ustawień (`[klucze] plik = "/etc/niewidka/klucz-mapy"`) albo zmienną `NIEWIDKA_KLUCZ_PLIK`.
  Na Linuksie plik musi mieć uprawnienia `0600`, inaczej program go odrzuci.

Nowy klucz unieważnia wszystkie stare mapy. Program nie nadpisze istniejącego klucza.
W magazynie systemu wymianę wymusza `do-keyringa --nadpisz`. Polecenie `nowy-plik`
nie nadpisuje istniejącego pliku: podaj nową ścieżkę albo najpierw usuń stary plik.

## Wersja okienkowa

Rozpakuj ZIP w dowolnym folderze. Nie musisz niczego instalować. Aktualizacja to
rozpakowanie nowego ZIP w to samo miejsce.

Najczęściej przydatne zmienne:

| Co | Jak |
|---|---|
| modele w innym folderze | `NIEWIDKA_MODELE_KATALOG` |
| stały port zamiast losowego | `NIEWIDKA_PORT` |
| dziennik błędów do pliku | `NIEWIDKA_LOG_PLIK=C:\Niewidka\niewidka.log` |
| pobieranie modeli z serwera w urzędzie | `NIEWIDKA_MODELE_ZRODLO=https://lustro.urzad.local/niewidka/` |

**Komputery bez internetu.** Wystaw pliki pakietów na serwerze HTTP w sieci urzędu.
Nazwy plików są w polu `zrodlo` w `niewidka/dane/pakiety.json`. Ustaw na komputerach
`NIEWIDKA_MODELE_ZRODLO` na adres tego folderu. Przycisk „Pobierz podstawowy (zalecane)”
pobierze wtedy modele z serwera urzędu. Program sprawdza sumy SHA-256 każdego pliku.

Aktualizacje modeli w sieci bez internetu opisuje `docs/WYDANIE.md`.

## Wersja w przeglądarce

Potrzebny jest Python 3.11 lub nowszy i narzędzie `uv` (<https://docs.astral.sh/uv/>).

```bash
git clone https://github.com/AuCourDe/niewidka.git
cd niewidka
uv sync
uv run python -m niewidka.klucze do-keyringa   # raz
cp konfiguracja/niewidka.przyklad.toml niewidka.toml
uv run python -m niewidka.api
```

Strona działa pod <http://127.0.0.1:8390>. Program nasłuchuje tylko na tym komputerze.
Każdy użytkownik uruchamia go u siebie. Program nie ma jeszcze logowania użytkowników,
więc nie da się go udostępnić w sieci.

Kilka osób może za to korzystać z jednego serwera modeli. Strona i mapy zostają wtedy
na komputerach użytkowników, a do serwera trafia sam tekst do sprawdzenia. Instrukcja:
`docs/SERWER-INFERENCJI.md`. Wzór ustawień użytkownika: `konfiguracja/klient-web.przyklad.toml`.

## Wszystkie opcje

W tabelach: sekcja i nazwa opcji w `niewidka.toml`, zmienna środowiskowa, wartość domyślna.

### `[serwer]`

| Opcja | Zmienna | Domyślnie | Znaczenie |
|---|---|---|---|
| `host` | `NIEWIDKA_HOST` | `127.0.0.1` | tylko adresy tego komputera |
| `port` | `NIEWIDKA_PORT` | `8390` | port wersji w przeglądarce; wersja okienkowa bierze wolny port, chyba że ustawisz zmienną |

### `[detekcja]`

| Opcja | Zmienna | Domyślnie | Znaczenie |
|---|---|---|---|
| `poziom` | `NIEWIDKA_POZIOM` | `1` | poziom dla zapytań API, które go nie podają: 1 Szybko, 2 Dokładniej, 3 Najdokładniej; suwak w programie zawsze podaje poziom |
| `prog_osoba` | `NIEWIDKA_PROG_OSOBA` | `0.2` | próg pewności dla osób na poziomach 2 i 3 |
| `wykrywaj_date` | `NIEWIDKA_WYKRYWAJ_DATE` | `true` | ukrywanie dat |
| `modele_katalog` | `NIEWIDKA_MODELE_KATALOG` | folder danych | folder z modelami |
| `provider` | `NIEWIDKA_PROVIDER` | `CPUExecutionProvider` | `CPUExecutionProvider` (procesor), `CUDAExecutionProvider` (karta NVIDIA, wymaga `onnxruntime-gpu`), `DmlExecutionProvider` (Windows, wymaga `onnxruntime-directml`) |
| `watki` | `NIEWIDKA_WATKI` | `0` | wątki procesora, 0 = automatycznie |

### `[klucze]`

| Opcja | Zmienna | Domyślnie | Znaczenie |
|---|---|---|---|
| `plik` | `NIEWIDKA_KLUCZ_PLIK` | brak | plik z kluczem mapy |
| `usluga` | `NIEWIDKA_KEYRING_USLUGA` | `niewidka` | nazwa wpisu w magazynie systemu |

### `[limity]`

| Opcja | Zmienna | Domyślnie | Znaczenie |
|---|---|---|---|
| `rozmiar_mb` | `NIEWIDKA_MAX_ROZMIAR_MB` | `25` | największy plik wejściowy w MB |
| `rozpakowane_mb` | `NIEWIDKA_MAX_ROZPAKOWANE_MB` | `200` | największy `.docx` po rozpakowaniu w MB |
| `tekst_mb` | `NIEWIDKA_MAX_TEKST_MB` | `1` | największy tekst w MB |
| `kolejka` | `NIEWIDKA_KOLEJKA` | `4` | dokumenty czekające w kolejce |
| `zlecenia` | `NIEWIDKA_ZLECENIA` | `8` | zapytania obsługiwane naraz |
| `timeout_s` | `NIEWIDKA_TIMEOUT_S` | `120` | czas na jeden dokument w sekundach |

### `[kontrola]`

| Opcja | Zmienna | Domyślnie | Znaczenie |
|---|---|---|---|
| `blokada` | `NIEWIDKA_KONTROLA_BLOKADA` | `true` | przy wątpliwościach kontroli wynik czeka na decyzję użytkownika |
| `obrazy` | `NIEWIDKA_OBRAZY` | `usun` | obrazy w `.docx`: `usun`, `blokuj` albo `zostaw` |

### `[mapy]`

| Opcja | Zmienna | Domyślnie | Znaczenie |
|---|---|---|---|
| `retencja_dni` | `NIEWIDKA_MAPY_RETENCJA_DNI` | `30` | po ilu dniach mapy znikają; 0 = program ich nie zapisuje |
| `katalog` | `NIEWIDKA_MAPY_KATALOG` | folder danych | folder zapisanych map |
| `uniewaznij_pobrane` | `NIEWIDKA_MAPY_UNIEWAZNIJ_POBRANE` | `false` | usunięta mapa przestaje działać także jako pobrany plik `.nwidka` |

Okres 30 dni to ustawienie programu. Właściwy okres dla urzędu ustala inspektor ochrony danych.

### `[poprawki]`

| Opcja | Zmienna | Domyślnie | Znaczenie |
|---|---|---|---|
| `maks_zadan` | `NIEWIDKA_POPRAWKI_MAKS_ZADAN` | `4` | ile ostatnich dokumentów można poprawiać |
| `ttl_s` | `NIEWIDKA_POPRAWKI_TTL_S` | `900` | jak długo, w sekundach |

### `[aktualizacje]`

| Opcja | Zmienna | Domyślnie | Znaczenie |
|---|---|---|---|
| `tryb` | `NIEWIDKA_AKTUALIZACJE` | wybór użytkownika (`sprawdzaj`) | `reczne`, `sprawdzaj`, `automatyczne`, `wylaczone`; wpis blokuje zmianę w Ustawieniach |

### `[listy]`

| Opcja | Zmienna | Domyślnie | Znaczenie |
|---|---|---|---|
| `zawsze` | brak | `[]` | lista administratora: zawsze ukrywaj |
| `nigdy` | brak | `[]` | lista administratora: nigdy nie ukrywaj |
| `tylko_administrator` | `NIEWIDKA_LISTY_TYLKO_ADMINISTRATOR` | `false` | użytkownik nie zmienia swoich list |
| `plik` | `NIEWIDKA_LISTY_PLIK` | folder danych | plik list użytkownika |

Na liście „nigdy” nie może być numerów z sumą kontrolną (PESEL, NIP, REGON, IBAN,
numer karty, numer dowodu). Ten sam wpis nie może być na obu listach.

### `[inferencja]`

| Opcja | Zmienna | Domyślnie | Znaczenie |
|---|---|---|---|
| `adres` | `NIEWIDKA_INFERENCJA_ADRES` | brak | adres wspólnego serwera modeli; brak = modele lokalne |
| `token_plik` | `NIEWIDKA_INFERENCJA_TOKEN_PLIK` | brak | plik z tokenem od administratora |
| `ca_plik` | `NIEWIDKA_INFERENCJA_CA_PLIK` | brak | certyfikat wewnętrznego urzędu certyfikacji |
| `timeout_s` | `NIEWIDKA_INFERENCJA_TIMEOUT_S` | `60` | czas oczekiwania na serwer w sekundach |
| `zezwol_bez_tls` | `NIEWIDKA_INFERENCJA_ZEZWOL_BEZ_TLS` | `false` | połączenie bez szyfrowania, tylko w sieci wydzielonej |

### Tylko zmienne środowiskowe

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `NIEWIDKA_MODELE_ZRODLO` | strona wydań na GitHubie | skąd pobierać modele |
| `NIEWIDKA_PAKIETY_LIMIT_CZASU_S` | `1800` | limit czasu pobierania pakietu w sekundach |
| `NIEWIDKA_REJESTR_MAP` | folder danych | plik rejestru wydanych map |
| `NIEWIDKA_LOG_PLIK` | brak | wersja okienkowa: zapis dziennika do pliku |

Wspólny serwer modeli ma osobny plik ustawień: `konfiguracja/serwer-inferencji.przyklad.toml`,
opis w `docs/SERWER-INFERENCJI.md`.
