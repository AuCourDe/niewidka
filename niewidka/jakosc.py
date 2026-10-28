"""Ocena jakości (LLD §11): R95 z kalibracji — stała per poziom, nie ocena pliku."""

from __future__ import annotations

import json
from pathlib import Path

DANE = Path(__file__).parent / "dane" / "r95.json"


def r95_z_kalibracji(poziom: int, typ: str, katalog_danych: Path | None = None) -> float | None:
    """R95 typu dla poziomu z dane/r95.json; brak wpisu = None (bez zmyślania)."""
    plik = (katalog_danych or DANE.parent) / "r95.json"
    if not plik.is_file():
        return None
    raport = json.loads(plik.read_text(encoding="utf-8"))
    if raport.get("poziom") != poziom:
        return None
    return raport.get("r95", {}).get(typ)
