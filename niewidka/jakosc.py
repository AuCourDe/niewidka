"""Ocena jakości (LLD §11): R95 z kalibracji — stała per poziom, nie ocena pliku.

Struktura `dane/r95.json` per poziom (K2d): `{"poziomy": {"1": {"detektor": ...,
"r95": {...}}, "2": {...}}, ...}`; poziom bez kalibracji = brak wartości (None,
bez zmyślania).
"""

from __future__ import annotations

import json
from pathlib import Path

DANE = Path(__file__).parent / "dane" / "r95.json"


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
