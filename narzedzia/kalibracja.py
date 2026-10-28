"""Kalibracja R95 (K2, LLD §11): górna granica Cloppera–Pearsona stopy ucieczek.

R95(typ) = beta.ppf(0.95, FN+1, TP+FN−FN) na korpusie walidacyjnym — runtime nie
wymaga scipy, liczone wyłącznie tutaj. Wynik: dane/r95.json.

    .venv/bin/python -m narzedzia.kalibracja --detektor poziom1 \
        --modele ~/models/niewidka
"""

from __future__ import annotations

import argparse
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path

from scipy.stats import beta

from narzedzia.pomiar import wczytaj_probki, zbuduj_detektor, zmierz


def r95_gorna(k: int, n: int) -> float:
    """Górna granica jednostronna (95%) stopy niepowodzeń przy k niepowodzeniach z n."""
    if n <= 0 or k >= n:
        return 1.0
    return float(beta.ppf(0.95, k + 1, n - k))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kalibracja R95 do dane/r95.json")
    parser.add_argument("--korpus", type=Path, default=Path("tests/korpus"))
    parser.add_argument("--detektor", choices=("reguly", "poziom1", "poziom2"), default="poziom1")
    parser.add_argument(
        "--modele",
        type=Path,
        default=Path(os.environ["NIEWIDKA_MODELE_KATALOG"])
        if os.environ.get("NIEWIDKA_MODELE_KATALOG")
        else None,
    )
    parser.add_argument("--dane", type=Path, default=Path("niewidka/dane"))
    argumenty = parser.parse_args(argv)

    probki = wczytaj_probki(argumenty.korpus)
    wyniki = zmierz(probki, zbuduj_detektor(argumenty.detektor, argumenty.modele))
    r95 = {}
    for typ, w in sorted(wyniki.items()):
        n = w.tp + w.fn
        r95[typ] = round(r95_gorna(w.fn, n), 4)
        print(f"R95 {typ:10s} k={w.fn} n={n:3d} -> {r95[typ]}")

    raport = {
        "poziom": 1,
        "detektor": argumenty.detektor,
        "korpus_probek": len(probki),
        "wzor": "beta.ppf(0.95, FN+1, TP+FN-FN) — górna granica Cloppera-Pearsona stopy ucieczek",
        "wygenerowano": datetime.now(UTC).isoformat(timespec="seconds"),
        "maszyna": platform.machine(),
        "r95": r95,
    }
    argumenty.dane.mkdir(parents=True, exist_ok=True)
    plik = argumenty.dane / "r95.json"
    plik.write_text(json.dumps(raport, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"zapisano {plik}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
