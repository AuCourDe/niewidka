"""Dictionary of Polish first names: GUS/dane.gov.pl CSV -> niewidka/dane/imiona_gus.txt.

Source (open data, Ministry of the Interior): dane.gov.pl, dataset id 1667 "List of first names occurring
in the PESEL register", files `IMIONA_MĘSKIE.csv` and `IMIONA_KOBIET.csv` (state of 18.07.2019, first name), columns `IMIĘ 1` + `Liczba`.
Dataset licence: CC0 1.0 (the `license_name` attribute of the dane.gov.pl API).

Run from the repo directory (data is fetched with httpx - a project rule):

    .venv/bin/python -m narzedzia.pobierz_imiona

Generates `niewidka/dane/imiona_gus.txt`: `# header comments` + `IMIĘ\tliczba`,
merges both files, sorts by count descending, truncates to the limit of the most frequent.
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
LIMIT = 3000  # a few thousand of the most frequent
WYJSCIE = Path("niewidka") / "dane" / "imiona_gus.txt"


def pobierz_klientem() -> dict[str, str]:
    with httpx.Client(
        timeout=120.0, follow_redirects=True, headers={"User-Agent": "Niewidka/1.0"}
    ) as k:
        return {plec: k.get(url).content.decode("utf-8-sig") for plec, url in PLIKI.items()}


def sczytaj_czestosci(csv_tekst: str) -> dict[str, int]:
    """`IMIĘ 1,Liczba` -> {name: count}; also reads incomplete rows."""
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
        "# Słownik polskich imion do wykrywacza słownikowego (Niewidka).",
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
            # max: a rare male name sometimes also appears on the female list (wrong counts)
            zgromadzone[imię] = max(zgromadzone.get(imię, 0), liczba)
    if not zgromadzone:
        raise SystemExit("CSV GUS: nie odczytano żadnego imienia")
    ile = zapisz(zgromadzone, argumenty.cel, argumenty.limit)
    print(f"zapisano {ile} imion -> {argumenty.cel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
