"""Słownik polskich imion: CSV GUS/dane.gov.pl -> niewidka/dane/imiona_gus.txt.

Źródło (otwarte dane, MSWiA): dane.gov.pl, zbiór id 1667 „Lista imion występujących
w rejestrze PESEL", przegląd plików `IMIONA_MĘSKIE.csv` i `IMIONA_KOBIET.csv` (stan 18.07.2019, imię pierwsze), kolumny `IMIĘ 1` + `Liczba`.
Licencja zbioru: CC0 1.0 (atrybut `license_name` API dane.gov.pl).

Uruchomienie z katalogu repo (dane pobieramy httpx — zasada projektowa):

    .venv/bin/python -m narzedzia.pobierz_imiona

Generuje `niewidka/dane/imiona_gus.txt`: `# komentarze nagłówkowe` + `IMIĘ\tliczba`,
scala oba pliki, sortuje wg liczby malejąco, obcina do limitu najczęstszych.
"""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

import httpx

DATASET_URL = "https://dane.gov.pl/pl/dataset/1667,lista-imion-wystepujacych-w-rejestrze-pesel"
LICENCJA = "CC0 1.0 (dane.gov.pl, zbiór id 1667, MSWiA — rejestr PESEL)"
PLIKI: dict[str, str] = {
    "męskie": "https://api.dane.gov.pl/media/resources/20190719/IMIONA_M%C4%98SKIE.csv",
    "żeńskie": "https://api.dane.gov.pl/media/resources/20190719/IMIONA_KOBIET.csv",
}
LIMIT = 3000  # kilka tysięcy najczęstszych
WYJSCIE = Path("niewidka") / "dane" / "imiona_gus.txt"


def pobierz_klientem() -> dict[str, str]:
    with httpx.Client(
        timeout=120.0, follow_redirects=True, headers={"User-Agent": "Niewidka-K2d/1.0"}
    ) as k:
        return {plec: k.get(url).content.decode("utf-8-sig") for plec, url in PLIKI.items()}


def sczytaj_czestosci(csv_tekst: str) -> dict[str, int]:
    """`IMIĘ 1,Liczba` -> {imię nº: liczba}; czyta też niepełne wiersze."""
    czestosci: dict[str, int] = {}
    for wiersz in csv.reader(io.StringIO(csv_tekst)):
        if not wiersz or wiersz[0].strip().upper() == "IMIĘ 1":
            continue
        imie, *reszta = [p.strip() for p in wiersz]
        if len(reszta) < 1 or not imie:
            continue
        try:
            liczba = int(reszta[0])
        except ValueError:
            continue
        czestosci[imie.title()] = max(czestosci.get(imie.title(), 0), liczba)
    return czestosci


def zapisz(czestosci: dict[str, int], cel: Path, limit: int) -> int:
    rankowane = sorted(czestosci.items(), key=lambda p: (-p[1], p[0]))[:limit]
    naglowek = [
        "# Słownik polskich imion do wykrywacza słownikowego (Niewidka K2d).",
        f"# Źródło: {DATASET_URL} (otwarte dane MSWiA, rejestr PESEL, stan 18.07.2019, imię pierwsze).",
        f"# Licencja: {LICENCJA}",
        "# Format: <Imię><TAB><liczba osób z tym imieniem>; sortowane wg liczby malejąco,",
        f"# pierwszych {limit} najczęstszych (ograniczonych wg liczby) z plików męskich i żeńskich.",
    ]
    cel.parent.mkdir(parents=True, exist_ok=True)
    with cel.open("w", encoding="utf-8") as plik:
        plik.write("\n".join(naglowek) + "\n")
        for imie, liczba in rankowane:
            plik.write(f"{imie}\t{liczba}\n")
    return len(rankowane)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=LIMIT)
    parser.add_argument("cel", type=Path, nargs="?", default=WYJSCIE)
    argumenty = parser.parse_args(argv)
    zgromadzone: dict[str, int] = {}
    for tekst in pobierz_klientem().values():
        for imię, liczba in sczytaj_czestosci(tekst).items():
            # max: rzadkie imię męskie bywa także na liście żeńskiej (błędne dowry)
            zgromadzone[imię] = max(zgromadzone.get(imię, 0), liczba)
    if not zgromadzone:
        raise SystemExit("CSV GUS: nie odczytano żadnego imienia")
    ile = zapisz(zgromadzone, argumenty.cel, argumenty.limit)
    print(f"zapisano {ile} imion -> {argumenty.cel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
