"""Quality rating: R95 from calibration (`dane/r95.json`), constant per level, not a rating of the file.
A level without calibration = None; with a small sample (`proba`) no risk label."""

from __future__ import annotations

import json
from pathlib import Path

DANE = Path(__file__).parent / "dane" / "r95.json"

# below this many examples the Clopper-Pearson upper bound comes out high
# even with zero misses - we state how many examples there were instead of labelling.
PROG_PROBY = 50


def _raport_r95(katalog_danych: Path | None) -> dict:
    plik = (katalog_danych or DANE.parent) / "r95.json"
    if not plik.is_file():
        return {}
    return json.loads(plik.read_text(encoding="utf-8"))


def r95_z_kalibracji(poziom: int, typ: str, katalog_danych: Path | None = None) -> float | None:
    """R95 of a type for a level from dane/r95.json; no entry = None (no guessing)."""
    wpis = _raport_r95(katalog_danych).get("poziomy", {}).get(str(poziom), {})
    return wpis.get("r95", {}).get(typ)


def r95_poziomy(katalog_danych: Path | None = None) -> dict[int, dict[str, float]]:
    """R95 of all calibrated levels (for /api/stan and the UI)."""
    poziomy = _raport_r95(katalog_danych).get("poziomy", {})
    return {
        int(poziom): dane.get("r95", {})
        for poziom, dane in poziomy.items()
        if poziom.isdigit()
    }


def _liczebnik(liczba: int, formy: tuple[str, str, str]) -> str:
    """Polish plural: 1 pominięcie, 2-4 (not 12-14) pominięcia, the rest pominięć.

        Form "1" only for exactly 1 (21 przykładów, not 21 przykład)."""
    if liczba == 1:
        return formy[0]
    if liczba % 100 in (12, 13, 14):
        return formy[2]
    if liczba % 10 in (2, 3, 4):
        return formy[1]
    return formy[2]


def opis_ryzyka(
    r95: float | None, n: int | None = None, k: int | None = None, prog: int = PROG_PROBY
) -> str:
    """Ready text in Polish; with a small sample (n < prog) no risk label.

        The text must match the earlier one from the UI (labels) or honestly
        describe the sample ("w testach: 0 pominięć na 7 przykładów").
        """
    if r95 is None:
        return "brak oszacowania dla tego poziomu jakości"
    if n is not None and n < prog:
        pominiecia = _liczebnik(k, ("pominięcie", "pominięcia", "pominięć"))
        przyklady = _liczebnik(n, ("przykład", "przykłady", "przykładów"))
        return f"w testach: {k} {pominiecia} na {n} {przyklady}"
    if r95 <= 0.02:
        return "bardzo małe: co najwyżej 1 na 50"
    if r95 <= 0.3:
        # int(x + 0.5) = Math.round from the earlier UI (Python round
        # rounds half down, JS up)
        return f"małe do umiarkowanego: co najwyżej ok. 1 na {int(1 / r95 + 0.5)}"
    return "podwyższone: przejrzyj wynik własnym okiem"


def opisy_ryzyka(
    poziom: int, typy: list[str], katalog_danych: Path | None = None
) -> dict[str, dict]:
    """{type: {r95, n, k, opis}} for types present in the document.

        The UI gets text ready to display and computes nothing itself; types without
        calibration are not returned (like the earlier None filtering).
        """
    wpis = _raport_r95(katalog_danych).get("poziomy", {}).get(str(poziom), {})
    r95_mapa = wpis.get("r95", {})
    proba = wpis.get("proba", {})
    wynik: dict[str, dict] = {}
    for typ in typy:
        wartosc = r95_mapa.get(typ)
        if wartosc is None:
            continue
        dane = proba.get(typ, {})
        n, k = dane.get("n"), dane.get("k")
        if n == 0:  # no example of the type in the corpus: no estimate, like no calibration
            continue
        wynik[typ] = {"r95": wartosc, "n": n, "k": k, "opis": opis_ryzyka(wartosc, n, k)}
    return wynik
