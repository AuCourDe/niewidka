"""Ocena jakości: R95 z kalibracji (`dane/r95.json`), stała per poziom, nie ocena pliku.
Poziom bez kalibracji = None; przy małej próbie (`proba`) bez etykiety ryzyka.
"""

from __future__ import annotations

import json
from pathlib import Path

DANE = Path(__file__).parent / "dane" / "r95.json"

# poniżej tyle przykładów górna granica Cloppera-Pearsona wychodzi wysoka
# nawet przy zero pominięć — mówimy, ile było przykładów, zamiast etykietować.
PROG_PROBY = 50


def _raport_r95(katalog_danych: Path | None) -> dict:
    plik = (katalog_danych or DANE.parent) / "r95.json"
    if not plik.is_file():
        return {}
    return json.loads(plik.read_text(encoding="utf-8"))


def r95_z_kalibracji(poziom: int, typ: str, katalog_danych: Path | None = None) -> float | None:
    """R95 typu dla poziomu z dane/r95.json; brak wpisu = None (bez zmyślania)."""
    wpis = _raport_r95(katalog_danych).get("poziomy", {}).get(str(poziom), {})
    return wpis.get("r95", {}).get(typ)


def r95_poziomy(katalog_danych: Path | None = None) -> dict[int, dict[str, float]]:
    """R95 wszystkich skalibrowanych poziomów (dla /api/stan i interfejsu)."""
    poziomy = _raport_r95(katalog_danych).get("poziomy", {})
    return {
        int(poziom): dane.get("r95", {})
        for poziom, dane in poziomy.items()
        if poziom.isdigit()
    }


def _liczebnik(liczba: int, formy: tuple[str, str, str]) -> str:
    """Odmiana polska: 1 pominięcie, 2-4 (nie 12-14) pominięcia, pozostałe pominięć.

    Forma "1" tylko dla dokładnie 1 (21 przykładów, nie 21 przykład)."""
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
    """Gotowy tekst po polsku; przy małej próbie (n < prog) bez etykiety ryzyka.

    Tekst musi być identyczny jak dotychczasowy z interfejsu (etykiety) albo uczciwie
    opisywać próbę ("w testach: 0 pominięć na 7 przykładów").
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
        # int(x + 0.5) = Math.round z dotychczasowego interfejsu (Python round
        # zaokrągla połowę w dół, JS w górę)
        return f"małe do umiarkowanego: co najwyżej ok. 1 na {int(1 / r95 + 0.5)}"
    return "podwyższone: przejrzyj wynik własnym okiem"


def opisy_ryzyka(
    poziom: int, typy: list[str], katalog_danych: Path | None = None
) -> dict[str, dict]:
    """{typ: {r95, n, k, opis}} dla typów występujących w dokumencie.

    Interfejs dostaje tekst gotowy do wyświetlenia i nie liczy sam; typy bez
    kalibracji nie wychodzą (jak dotychczasowe odfiltrowanie None).
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
        wynik[typ] = {"r95": wartosc, "n": n, "k": k, "opis": opis_ryzyka(wartosc, n, k)}
    return wynik
