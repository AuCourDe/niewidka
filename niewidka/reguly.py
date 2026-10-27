"""Reguły detekcji: wyrażenia regularne + sumy kontrolne (LLD §3).

Walidatory dostają tekst znormalizowany (bez spacji i myślników, wielkimi
literami). Znacznik `suma_kontrolna=True` oznacza najwyższy priorytet przy
scalaniu i pewność 1.0; reguły bez walidatora mają pewność 0.9.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import stdnum.pl.pesel

from niewidka.model import TypEncji, Zakres

PEWNOŚC_BEZ_SUMY = 0.9


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


REGULY: tuple[Regula, ...] = (
    Regula(
        typ=TypEncji.PESEL,
        wzorzec=re.compile(r"(?<!\d)\d{11}(?!\d)"),
        walidator=_pesel_ok,
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
