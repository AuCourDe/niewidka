"""Pomiar recall/precision detektora na korpusie (K0, zasady w KRYTERIA.md).

Dopasowanie dokładne: TP = identyczne (start, koniec, typ); pokrycie częściowe
liczy się jednocześnie jako FN i FP; detekcja podejrzana (`podejrzana=True`,
KRYTERIA §1.3) bez dopasowania liczy się osobno jako PN — nie zaniża precision.
Uruchomienie z katalogu repo:

    .venv/bin/python -m narzedzia.pomiar --detektor reguly
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from niewidka.detektory import (
    DetektorKompozyt,
    RegulyDetektor,
    wczytaj_bardsai,
    wczytaj_lfm25,
    wczytaj_poziom2_uzupelniajacy,
)
from niewidka.model import Zakres


@dataclass
class Oczekiwana:
    typ: str
    start: int
    koniec: int
    tekst: str
    suma: bool | None = None


@dataclass
class Probka:
    id: str
    opis: str
    tekst: str
    encje: list[Oczekiwana] = field(default_factory=list)


@dataclass
class WynikTypu:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    pn: int = 0  # podejrzane nadmaskowanie (KRYTERIA §1.3), poza precision


class DetektorPusty:
    """Sanity pomiaru: zero detekcji → recall 0 (KRYTERIA.md §1.5)."""

    def znajdz(self, tekst: str) -> list[Zakres]:
        return []


def zbuduj_detektor(nazwa: str, katalog_modeli: Path | None, wariant: str = "int8"):
    """Detektor pomiaru wg nazwy CLI; poziomy wg KRYTERIA §4 (poziom2 = +LFM2.5, K2b)."""
    if nazwa == "pusty":
        return DetektorPusty()
    if nazwa == "reguly":
        return RegulyDetektor()
    if nazwa in ("poziom1", "poziom2", "lfm25"):
        if katalog_modeli is None:
            raise ValueError(
                f"{nazwa} wymaga katalogu wag: NIEWIDKA_MODELE_KATALOG albo --modele"
            )
        if nazwa == "lfm25":
            return wczytaj_lfm25(katalog_modeli, wariant=wariant)
        czesci = [RegulyDetektor(), wczytaj_bardsai(katalog_modeli)]
        if nazwa == "poziom2":
            czesci.append(wczytaj_lfm25(katalog_modeli, wariant=wariant))
        return DetektorKompozyt(nazwa, czesci)
    if nazwa in ("poziom2-uzup", "poziom2-uzup-b"):
        if katalog_modeli is None:
            raise ValueError(
                f"{nazwa} wymaga katalogu wag: NIEWIDKA_MODELE_KATALOG albo --modele"
            )
        return wczytaj_poziom2_uzupelniajacy(
            katalog_modeli,
            wariant_b=(nazwa == "poziom2-uzup-b"),
            wariant_lfm25="fp32",
        )
    raise SystemExit(f"nieznany detektor: {nazwa}")


def zmierz_z_czasem(probki: list[Probka], detektor) -> tuple[dict[str, WynikTypu], list[float]]:
    """Pomiar jakości + czasu detekcji (ms) na próbkę, w kolejności próbek."""
    czasy: list[float] = []
    wyniki: dict[str, WynikTypu] = {}

    def wynik(typ: str) -> WynikTypu:
        return wyniki.setdefault(typ, WynikTypu())

    for probka in probki:
        start = time.perf_counter()
        detekcje = detektor.znajdz(probka.tekst)
        czasy.append((time.perf_counter() - start) * 1000)
        oczekiwane = {(e.start, e.koniec, e.typ) for e in probka.encje}
        trafione: set[tuple[int, int, str]] = set()
        for z in detekcje:
            klucz = (z.start, z.koniec, z.typ.value)
            trafione.add(klucz)
            w = wynik(klucz[2])
            if klucz in oczekiwane:
                w.tp += 1
            elif z.podejrzana:
                w.pn += 1
            else:
                w.fp += 1
        for brak in oczekiwane - trafione:
            wynik(brak[2]).fn += 1
    return wyniki, czasy


def wczytaj_probki(katalog: Path) -> list[Probka]:
    probki = []
    for plik in sorted(katalog.glob("*.jsonl")):
        for linia in plik.read_text(encoding="utf-8").splitlines():
            if not linia.strip():
                continue
            surowa = json.loads(linia)
            encje = [
                Oczekiwana(
                    typ=e["typ"],
                    start=e["start"],
                    koniec=e["koniec"],
                    tekst=e["tekst"],
                    suma=e.get("suma"),
                )
                for e in surowa["encje"]
            ]
            probki.append(
                Probka(id=surowa["id"], opis=surowa["opis"], tekst=surowa["tekst"], encje=encje)
            )
    return probki


def zmierz(probki: list[Probka], detektor) -> dict[str, WynikTypu]:
    wyniki, _ = zmierz_z_czasem(probki, detektor)
    return wyniki


def recall(w: WynikTypu) -> float | None:
    return w.tp / (w.tp + w.fn) if w.tp + w.fn else None


def precision(w: WynikTypu) -> float | None:
    return w.tp / (w.tp + w.fp) if w.tp + w.fp else None


def _mikro(wyniki: dict[str, WynikTypu], typy: set[str] | None = None) -> WynikTypu:
    suma = WynikTypu()
    for typ, w in wyniki.items():
        if typy is None or typ in typy:
            suma.tp += w.tp
            suma.fp += w.fp
            suma.fn += w.fn
            suma.pn += w.pn
    return suma


def wypisz_raport(wyniki: dict[str, WynikTypu]) -> None:
    print("| typ | TP | FP | PN | FN | recall | precision |")
    print("|---|---|---|---|---|---|---|")
    for typ in sorted(wyniki):
        w = wyniki[typ]
        r = recall(w)
        p = precision(w)
        print(
            f"| {typ} | {w.tp} | {w.fp} | {w.pn} | {w.fn} "
            f"| {'n/d' if r is None else f'{r:.3f}'} | {'n/d' if p is None else f'{p:.3f}'} |"
        )
    bez_osoby = {t for t in wyniki if t != "OSOBA"}
    calosc = _mikro(wyniki)
    k1 = _mikro(wyniki, bez_osoby)
    for nazwa, zbiorczy in (("łącznie (K1, bez OSOBA)", k1), ("łącznie (wszystkie)", calosc)):
        r, p = recall(zbiorczy), precision(zbiorczy)
        print(
            f"| **{nazwa}** | {zbiorczy.tp} | {zbiorczy.fp} | {zbiorczy.pn} | {zbiorczy.fn} "
            f"| {'n/d' if r is None else f'{r:.3f}'} | {'n/d' if p is None else f'{p:.3f}'} |"
        )


def wypisz_czasy(czasy: list[float]) -> None:
    posortowane = sorted(czasy)
    srednia = sum(czasy) / len(czasy) if czasy else 0.0
    mediana = posortowane[len(posortowane) // 2] if czasy else 0.0
    print(
        f"\nCzas na próbkę (CPU): średnia {srednia:.1f} ms, mediana {mediana:.1f} ms, "
        f"max {max(czasy, default=0.0):.1f} ms (próbek: {len(czasy)})"
    )
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KiB na Linux
        print(f"RAM procesu (szczyt RSS): {rss / 1024:.0f} MiB")
    except (ImportError, AttributeError):  # nie-POSIX
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pomiar detektora na korpusie Niewidki")
    parser.add_argument("--korpus", type=Path, default=Path("tests/korpus"))
    parser.add_argument(
        "--detektor",
        choices=(
            "pusty",
            "reguly",
            "poziom1",
            "poziom2",
            "lfm25",
            "poziom2-uzup",
            "poziom2-uzup-b",
        ),
        default="reguly",
    )
    parser.add_argument("--wariant", choices=("int8", "fp32"), default="int8")
    parser.add_argument(
        "--modele",
        type=Path,
        default=Path(os.environ["NIEWIDKA_MODELE_KATALOG"])
        if os.environ.get("NIEWIDKA_MODELE_KATALOG")
        else None,
        help="katalog wag (domyślnie z NIEWIDKA_MODELE_KATALOG)",
    )
    argumenty = parser.parse_args(argv)
    detektor = zbuduj_detektor(argumenty.detektor, argumenty.modele, wariant=argumenty.wariant)
    probki = wczytaj_probki(argumenty.korpus)
    print(f"Detektor: {argumenty.detektor}, próbki: {len(probki)}")
    wyniki, czasy = zmierz_z_czasem(probki, detektor)
    wypisz_raport(wyniki)
    wypisz_czasy(czasy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
