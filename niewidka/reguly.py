"""Reguły detekcji: wyrażenia regularne + sumy kontrolne (LLD §3).

Walidatory dostają tekst znormalizowany (bez spacji i myślników, wielkimi
literami). Znacznik `suma_kontrolna=True` oznacza najwyższy priorytet przy
scalaniu i pewność 1.0; reguły bez walidatora mają pewność 0.9.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import stdnum.iban
import stdnum.pl.nip
import stdnum.pl.pesel
import stdnum.pl.regon

from niewidka.model import TypEncji, Zakres

PEWNOŚC_BEZ_SUMY = 0.9

# Dowód osobisty: python-stdnum go nie obejmuje — własny walidator (LLD §3).
# Wagi 7,3,1,9,7,3,1,7,3; litery A=10..Z=35; suma iloczynów mod 10 równa się
# 4. znakowi (algorytm.org). W narzedzia/numery.py istnieje celowa kopia:
# korpus testowy nie może zależeć od walidowanego kodu rdzenia.
_WAGI_DOWODU = (7, 3, 1, 9, 7, 3, 1, 7, 3)


@dataclass(frozen=True)
class Regula:
    typ: TypEncji
    wzorzec: re.Pattern[str]
    walidator: Callable[[str], bool] | None  # suma kontrolna na znormalizowanym tekście
    suma_kontrolna: bool


def _znormalizuj(zapis: str) -> str:
    return zapis.replace(" ", "").replace("-", "").upper()


def _pesel_ok(zapis: str) -> bool:
    return stdnum.pl.pesel.is_valid(_znormalizuj(zapis))


def _nip_ok(zapis: str) -> bool:
    return stdnum.pl.nip.is_valid(_znormalizuj(zapis))


def _regon_ok(zapis: str) -> bool:
    nr = _znormalizuj(zapis)
    return len(nr) in (9, 14) and stdnum.pl.regon.is_valid(nr)


def _iban_ok(zapis: str) -> bool:
    return stdnum.iban.is_valid(_znormalizuj(zapis))


def _dowod_ok(zapis: str) -> bool:
    nr = _znormalizuj(zapis)
    if len(nr) != 9 or not nr[:3].isalpha() or not nr[3:].isdigit():
        return False
    wartosci = [ord(z) - 55 for z in nr[:3]] + [int(c) for c in nr[3:]]
    return sum(w * waga for w, waga in zip(wartosci, _WAGI_DOWODU)) % 10 == int(nr[3])


REGULY: tuple[Regula, ...] = (
    Regula(
        typ=TypEncji.PESEL,
        wzorzec=re.compile(r"(?<!\d)\d{11}(?!\d)"),
        walidator=_pesel_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.NIP,
        wzorzec=re.compile(r"(?<!\d)\d{3}[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}(?!\d)"),
        walidator=_nip_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.REGON,
        wzorzec=re.compile(r"(?<!\d)\d{9}(?!\d)"),
        walidator=_regon_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.REGON,
        wzorzec=re.compile(r"(?<!\d)\d{14}(?!\d)"),
        walidator=_regon_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.IBAN,
        wzorzec=re.compile(r"(?<![A-Za-z0-9])PL\d{2}(?: ?[A-Z0-9]{4}){6}(?![A-Za-z0-9])"),
        walidator=_iban_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.DOKUMENT,
        wzorzec=re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}[ -]?\d{6}(?![A-Za-z0-9])"),
        walidator=_dowod_ok,
        suma_kontrolna=True,
    ),
)


def _pewnosc(regula: Regula) -> float:
    return 1.0 if regula.suma_kontrolna else PEWNOŚC_BEZ_SUMY


def znajdz(tekst: str) -> list[Zakres]:
    """Kandydaci ze wszystkich reguł (bez scalania), sortowane wg pozycji."""
    kandydaci = []
    for regula in REGULY:
        for dopasowanie in regula.wzorzec.finditer(tekst):
            if regula.walidator and not regula.walidator(dopasowanie.group(0)):
                continue
            kandydaci.append(
                Zakres(
                    start=dopasowanie.start(),
                    koniec=dopasowanie.end(),
                    typ=regula.typ,
                    pewnosc=_pewnosc(regula),
                    zrodlo="regula",
                    suma_kontrolna=regula.suma_kontrolna,
                )
            )
    return sorted(kandydaci, key=lambda z: (z.start, z.koniec))
