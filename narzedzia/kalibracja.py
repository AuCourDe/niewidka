"""R95 calibration: the Clopper-Pearson upper bound of the escape rate.

R95(type) = beta.ppf(0.95, FN+1, TP+FN-FN) on the validation corpus - the runtime does not
need scipy, it is computed only here. Output: dane/r95.json with a per-level
structure; each run adds/refreshes its own level, the others stay.

    .venv/bin/python -m narzedzia.kalibracja --detektor poziom1 \
        --modele ~/models/niewidka
    .venv/bin/python -m narzedzia.kalibracja --detektor poziom2 --prog-osoba 0.2 \
        --modele ~/models/niewidka
    .venv/bin/python -m narzedzia.kalibracja --detektor poziom3 --prog-osoba 0.2 \
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

from narzedzia.pomiar import wczytaj_probki, zmierz
from niewidka.detektory import RegulyDetektor, zbuduj_poziom
from niewidka.konfig import PROG_OSOBA_DOMYSLNY

WZOR = "beta.ppf(0.95, FN+1, TP+FN-FN) — górna granica Cloppera-Pearsona stopy ucieczek"


def r95_gorna(k: int, n: int) -> float:
    """One-sided (95%) upper bound of the failure rate given k failures out of n."""
    if n <= 0 or k >= n:
        return 1.0
    return float(beta.ppf(0.95, k + 1, n - k))


def zbuduj_wpis(detektor: str, wyniki: dict, prog_osoba: float | None = None) -> dict:
    """Level entry: R95 + sample (k misses out of n examples) per type.

    k and n go into r95.json straight from the measurement - no inventing; the sample decides
    in jakosc.opis_ryzyka whether R95 gets a label at all.
    """
    r95: dict[str, float] = {}
    proba: dict[str, dict[str, int]] = {}
    for typ, w in sorted(wyniki.items()):
        n = w.tp + w.fn
        r95[typ] = round(r95_gorna(w.fn, n), 4)
        proba[typ] = {"k": w.fn, "n": n}
    wpis: dict = {"detektor": detektor, "r95": r95, "proba": proba}
    if prog_osoba is not None:
        wpis["prog_osoba"] = prog_osoba
    return wpis


def zapisz_poziom(plik: Path, poziom: int, wpis: dict, korpus_probek: int) -> None:
    """Add/refresh the entry of one level in dane/r95.json; the others stay."""
    raport: dict = {}
    if plik.is_file():
        raport = json.loads(plik.read_text(encoding="utf-8"))
    raport.setdefault("poziomy", {})[str(poziom)] = wpis
    raport["korpus_probek"] = korpus_probek
    raport["wzor"] = WZOR
    raport["wygenerowano"] = datetime.now(UTC).isoformat(timespec="seconds")
    raport["maszyna"] = platform.machine()
    plik.write_text(json.dumps(raport, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kalibracja R95 do dane/r95.json")
    parser.add_argument("--korpus", type=Path, default=Path("tests/korpus"))
    parser.add_argument(
        "--detektor",
        choices=("poziom1", "poziom2", "poziom3", "reguly"),
        default="poziom1",
        help="poziomy produktu (2 = wariant A, 3 = wariant B); reguly = sanity",
    )
    parser.add_argument(
        "--prog-osoba",
        type=float,
        default=PROG_OSOBA_DOMYSLNY,
        help=f"próg pewności OSOBA poziomów 2/3 (domyślnie {PROG_OSOBA_DOMYSLNY})",
    )
    parser.add_argument(
        "--modele",
        type=Path,
        default=Path(os.environ["NIEWIDKA_MODELE_KATALOG"])
        if os.environ.get("NIEWIDKA_MODELE_KATALOG")
        else None,
        help="katalog wag (domyślnie z NIEWIDKA_MODELE_KATALOG)",
    )
    parser.add_argument("--dane", type=Path, default=Path("niewidka/dane"))
    argumenty = parser.parse_args(argv)
    if argumenty.detektor != "reguly" and argumenty.modele is None:
        parser.error("--detektor poziom1/2/3 wymaga --modele albo NIEWIDKA_MODELE_KATALOG")

    poziom = {"poziom1": 1, "poziom2": 2, "poziom3": 3, "reguly": 1}[argumenty.detektor]
    detektor = (
        RegulyDetektor()
        if argumenty.detektor == "reguly"
        else zbuduj_poziom(poziom, argumenty.modele, próg_osoba=argumenty.prog_osoba)
    )
    probki = wczytaj_probki(argumenty.korpus)
    wyniki = zmierz(probki, detektor)
    wpis = zbuduj_wpis(
        argumenty.detektor, wyniki, prog_osoba=argumenty.prog_osoba if poziom > 1 else None
    )
    for typ, wartosc in wpis["r95"].items():
        proba = wpis["proba"][typ]
        print(f"R95 {typ:10s} k={proba['k']} n={proba['n']:3d} -> {wartosc}")
    plik = argumenty.dane / "r95.json"
    zapisz_poziom(plik, poziom, wpis, len(probki))
    print(f"zapisano poziom {poziom} w {plik}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
