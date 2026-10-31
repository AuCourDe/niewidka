"""Deterministic generator of fictitious numbers for the test corpus.

"Valid" numbers have correct checksums, "invalid" ones differ by exactly
one digit from a valid counterpart. The corpus author copies the numbers
from `tests/korpus/numery.json`; corpus validation (tests/test_korpus.py)
checks them with python-stdnum and an independent ID-card algorithm, independently of the niewidka package.

Run: `python narzedzia/numery.py --ile 6 > tests/korpus/numery.json`.
"""

from __future__ import annotations

import argparse
import json
import sys

_WAGI_PESEL = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
_WAGI_NIP = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_WAGI_REGON = (8, 9, 2, 3, 4, 5, 6, 7)
# Weights per python-stdnum (stdnum.pl.regon.calc_check_digit), not per older descriptions.
_WAGI_REGON14 = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
_WAGI_DOWOD = (7, 3, 1, 9, 7, 3, 1, 7, 3)


def _suma_kontrolna(cyfry: str, wagi: tuple[int, ...]) -> int:
    return sum(int(c) * w for c, w in zip(cyfry, wagi))


def pesel(indeks: int) -> str:
    """11 digits: birth date depending on the index (birth years 1944-1953) + checksum."""
    data = f"{44 + indeks % 10:02d}{1 + indeks % 12:02d}{1 + indeks % 28:02d}"
    reszta = f"{indeks * 7919 % 10000:04d}"
    baza = data + reszta
    suma = _suma_kontrolna(baza, _WAGI_PESEL) % 10
    return baza + str((10 - suma) % 10)


def nip(indeks: int) -> str:
    for proba in range(100):
        baza = (
            f"{(indeks + proba) % 899 + 101:03d}"
            f"{(indeks * 13 + proba) % 899 + 100:03d}"
            f"{(indeks * 37 + proba) % 899 + 100:03d}"
        )
        suma = _suma_kontrolna(baza, _WAGI_NIP) % 11
        if suma < 10:  # remainder 10 gives an invalid NIP - try the next base
            return baza + str(suma)
    raise ValueError("nie znaleziono poprawnej bazy NIP")


def regon(indeks: int) -> str:
    # REGON-9 = 8 base digits + check digit; remainder 10 gives digit 0 (mod 11 mod 10)
    baza = f"49{(indeks * 100000 + 1) % 10**6:06d}"
    return baza + str(_suma_kontrolna(baza, _WAGI_REGON) % 11 % 10)


def regon14(indeks: int) -> str:
    # REGON-14 = a valid REGON-9 (9 digits) + 4 digits + a sum with the 14-digit weights
    baza13 = regon(indeks) + f"{indeks * 7 % 10000:04d}"
    return baza13 + str(_suma_kontrolna(baza13, _WAGI_REGON14) % 11 % 10)


def iban(indeks: int) -> str:
    """PL-IBAN (26 NRB digits) with spaces every 4 characters, e.g. "PL61 1090 ... 2874"."""
    nrb = f"10901014{indeks * 48075369 % 10**16:016d}"
    # IBAN: move country+00 to the end, replace letters with numbers, mod 97.
    do_modulo = nrb + "252100"  # P=25, L=21, "00"
    reszta = 0
    for znak in do_modulo:
        reszta = (reszta * 10 + int(znak)) % 97
    return "PL" + f"{98 - reszta:02d}" + nrb


def iban_sformatowany(indeks: int) -> str:
    """PL-IBAN written with spaces every 4 characters, e.g. "PL61 1090 ... 2874"."""
    nr = iban(indeks)
    return " ".join(nr[i : i + 4] for i in range(0, len(nr), 4))


def waliduj_dowod(zapis: str) -> bool:
    """ID-card checksum: weights 7,3,1,9,7,3,1,7,3 (weight 9 on the check digit);
    letters A=10..Z=35; the sum over all 9 characters mod 10 must be 0. Spaces/hyphens
    in the notation are ignored."""
    nr = zapis.replace(" ", "").replace("-", "").upper()
    if len(nr) != 9 or not nr[:3].isalpha() or not nr[3:].isdigit():
        return False
    wartosci = [ord(z) - 55 for z in nr[:3]] + [int(c) for c in nr[3:]]
    return sum(w * waga for w, waga in zip(wartosci, _WAGI_DOWOD)) % 10 == 0


def dowod(indeks: int) -> str:
    """3 letters + 6 digits; the first digit is the check digit."""
    litery = "".join(chr(65 + (indeks * (97 + i * 31) + i * 11) % 26) for i in range(3))
    for proba in range(100):
        ogon = f"{(indeks + proba) % 100000:05d}"
        reszta = sum(int(c) * w for c, w in zip(ogon, (7, 3, 1, 7, 3)))
        litery_suma = sum((ord(z) - 55) * w for z, w in zip(litery, (7, 3, 1)))
        for cyfra in range(10):
            if (litery_suma + 9 * cyfra + reszta) % 10 == 0:
                return litery + str(cyfra) + ogon
    raise ValueError("nie znaleziono poprawnego dowodu")


def _zepsuj(nr: str, pozycja: int, walidator) -> str:
    """Changes the digit at the given position so that the validator rejects the number."""
    for delta in range(1, 10):
        nowa = (int(nr[pozycja]) + delta) % 10
        kandydat = nr[:pozycja] + str(nowa) + nr[pozycja + 1 :]
        if not walidator(kandydat):
            return kandydat
    raise ValueError(f"nie znaleziono błędnego wariantu: {nr}")


def bledny(poprawny: str, walidator) -> str:
    """A corrupted number variant differing by one digit.

    `walidator` is a str -> bool function (e.g. stdnum or waliduj_dowod);
    it picks the digit to change by the shape: in an ID card the check
    digit is the 4th character, otherwise the last digit is changed.
    """
    pozycja = 3 if (poprawny[3].isdigit() and poprawny[:3].isalpha()) else len(poprawny) - 1
    return _zepsuj(poprawny, pozycja, walidator)


def main(argv: list[str] | None = None) -> int:
    import stdnum.iban
    import stdnum.pl.nip
    import stdnum.pl.pesel
    import stdnum.pl.regon

    parser = argparse.ArgumentParser(description="Generator numerów do korpusu Niewidki")
    parser.add_argument("--ile", type=int, default=6, help="ile numerów per typ")
    argumenty = parser.parse_args(argv)
    wynik = {}
    for nazwa, generator, walidator in (
        ("pesel", pesel, stdnum.pl.pesel.is_valid),
        ("nip", nip, stdnum.pl.nip.is_valid),
        ("regon", regon, stdnum.pl.regon.is_valid),
        ("regon14", regon14, stdnum.pl.regon.is_valid),
        ("iban", iban_sformatowany, stdnum.iban.is_valid),
        ("dowod", dowod, waliduj_dowod),
    ):
        wynik[nazwa] = {
            "poprawne": [generator(i) for i in range(argumenty.ile)],
            "bledne": [bledny(generator(i), walidator) for i in range(argumenty.ile)],
        }
    json.dump(wynik, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
