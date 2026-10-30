# Niewidka

**Polski** · [English](README.en.md)

Niewidka ukrywa dane osobowe w polskich tekstach i dokumentach. Działa na Twoim komputerze.
Nic nie wysyła do internetu.

Wklej pismo albo wybierz plik `.txt` lub `.docx`. Program zamieni imiona, nazwiska, PESEL,
NIP, adresy, telefony, e-maile, numery kont i dokumentów na znaczniki, na przykład
`[OSOBA_1]` albo `[PESEL_1]`. Taki tekst możesz wysłać do czatu AI. Odpowiedź z czatu wklej
z powrotem do programu. Niewidka wstawi prawdziwe dane w miejsce znaczników.

Niewidka pomaga, ale nie zastępuje człowieka. Przejrzyj podgląd przed wysłaniem tekstu.

## Dwie wersje

| | Wersja okienkowa | Wersja w przeglądarce |
|---|---|---|
| Dla kogo | dla każdego, kto pracuje na Windowsie | dla IT i osób, które uruchamiają programy z Pythona |
| Jak się uruchamia | `Niewidka.exe` | `python -m niewidka.api` i przeglądarka |
| Instalacja | rozpakowanie ZIP | Python 3.11 lub nowszy i narzędzie `uv` |
| Gdzie działa | Windows 10 i 11 | Windows, Linux, macOS |

Obie wersje wyglądają i działają tak samo. Program nasłuchuje tylko na Twoim komputerze
(`127.0.0.1`). Nikt z sieci się do niego nie podłączy.

Modele działają na każdym komputerze osobno albo na jednym serwerze w sieci urzędu.
Przy wspólnym serwerze użytkownicy nie pobierają modeli. Opis dla administratora:
`docs/SERWER-INFERENCJI.md`.

## Szybki start: wersja okienkowa

1. Pobierz plik `Niewidka-<wersja>-windows-x64.zip` ze strony wydań:
   <https://github.com/AuCourDe/niewidka/releases>.
2. Rozpakuj plik w dowolnym folderze i uruchom `Niewidka.exe`.
3. Kliknij „Utwórz klucz”. Klucz zapisze się w Menedżerze poświadczeń Windows.
4. Kliknij „Pobierz podstawowy (zalecane)”. Pakiet ma około 190 MB. Pobierasz go tylko raz.
5. Wklej tekst i kliknij „Ukryj dane”.

## Szybki start: wersja w przeglądarce

```bash
git clone https://github.com/AuCourDe/niewidka.git
cd niewidka
uv sync
uv run python -m niewidka.klucze do-keyringa
uv run python -m niewidka.api
```

Otwórz w przeglądarce <http://127.0.0.1:8390>. Przy pierwszym uruchomieniu pobierz pakiet
podstawowy. Port zmienisz zmienną `NIEWIDKA_PORT` albo w pliku `niewidka.toml`.

Linux bez pulpitu nie ma magazynu haseł. Zamiast `do-keyringa` utwórz plik klucza:

```bash
mkdir -p ~/.config/niewidka
uv run python -m niewidka.klucze nowy-plik ~/.config/niewidka/klucz
NIEWIDKA_KLUCZ_PLIK=~/.config/niewidka/klucz uv run python -m niewidka.api
```

## Dokumentacja

- `docs/PRZEWODNIK.md`: co program umie, jak działa i jak go wdrożyć.
- `docs/INSTRUKCJA.md`: obsługa programu krok po kroku.
- `docs/KONFIGURACJA.md`: wszystkie ustawienia, plik `niewidka.toml` i zmienne środowiskowe.
- `docs/SERWER-INFERENCJI.md`: wspólny serwer modeli w sieci lokalnej.
- `docs/MODELE.md`: modele, poziomy jakości i wyniki pomiarów.
- `docs/LICENCJE.md`: licencje modeli i bibliotek.
- `docs/WYDANIE.md`: wydawanie i podpisywanie pakietów modeli.
- `docs/rozwoj/`: projekt techniczny, pomiary i notatki z budowy.

## Budowa programu ze źródeł (Windows)

Potrzebujesz Windows 10 lub 11, Pythona 3.13 (`py -3.13`) i programu Git.

```powershell
git clone https://github.com/AuCourDe/niewidka.git C:\niewidka-zrodla
cd C:\niewidka-zrodla
powershell -ExecutionPolicy Bypass -File narzedzia\zbuduj_windows.ps1 -KatalogBudowy C:\niewidka-build
```

Skrypt zainstaluje zależności, uruchomi testy i zbuduje `Niewidka.exe` oraz paczkę ZIP.
Paczka nie zawiera modeli. Program pobierze je przy pierwszym uruchomieniu.

Testy: `uv run pytest`. Sprawdzenie kodu: `uv run ruff check`.

## Licencja

Kod programu jest na licencji MIT (`LICENSE`). Możesz go używać, zmieniać i rozpowszechniać,
także w urzędzie i w firmie. Licencja MIT nie obejmuje modeli. Modele pobierasz osobno
i obowiązują je licencje ich twórców: pakiet podstawowy Apache 2.0, pakiet rozszerzony
LFM Open License v1.0, która ogranicza użycie komercyjne. Szczegóły: `docs/LICENCJE.md`.

Program używa modeli statystycznych i nie wykrywa wszystkich danych osobowych w każdym
tekście. Przed przekazaniem dokumentu dalej sprawdź wynik. Autor nie odpowiada za skutki
niepełnego ukrycia danych. Luki w zabezpieczeniach zgłaszaj według `SECURITY.md`.
