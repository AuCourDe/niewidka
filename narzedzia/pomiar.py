"""Pomiar recall/precision detektora na korpusie (K0, zasady w KRYTERIA.md).

Dopasowanie dokładne: TP = identyczne (start, koniec, typ); pokrycie częściowe
liczy się jednocześnie jako FN i FP. Uruchomienie z katalogu repo:

    .venv/bin/python -m narzedzia.pomiar --detektor reguly
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from niewidka.model import Zakres
from niewidka.reguly import znajdz
from niewidka.scalanie import scal


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


class DetektorPusty:
    """Sanity pomiaru: zero detekcji → recall 0 (KRYTERIA.md §1.5)."""

    def znajdz(self, tekst: str) -> list[Zakres]:
        return []


class DetektorReguly:
    """Reguły + scalanie — warstwa detekcji kamienia K1."""

    def znajdz(self, tekst: str) -> list[Zakres]:
        return scal(tekst, znajdz(tekst))


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
            probki.append(Probka(id=surowa["id"], opis=surowa["opis"], tekst=surowa["tekst"], encje=encje))
    return probki


def zmierz(probki: list[Probka], detektor) -> dict[str, WynikTypu]:
    wyniki: dict[str, WynikTypu] = {}

    def wynik(typ: str) -> WynikTypu:
        return wyniki.setdefault(typ, WynikTypu())

    for probka in probki:
        detekcje = {(z.start, z.koniec, z.typ.value) for z in detektor.znajdz(probka.tekst)}
        oczekiwane = {(e.start, e.koniec, e.typ) for e in probka.encje}
        for trafienie in detekcje:
            wynik(trafienie[2]).tp += trafienie in oczekiwane
            wynik(trafienie[2]).fp += trafienie not in oczekiwane
        for brak in oczekiwane - detekcje:
            wynik(brak[2]).fn += 1
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
    return suma


def wypisz_raport(wyniki: dict[str, WynikTypu]) -> None:
    print("| typ | TP | FP | FN | recall | precision |")
    print("|---|---|---|---|---|---|")
    for typ in sorted(wyniki):
        w = wyniki[typ]
        r = recall(w)
        p = precision(w)
        print(
            f"| {typ} | {w.tp} | {w.fp} | {w.fn} "
            f"| {'n/d' if r is None else f'{r:.3f}'} | {'n/d' if p is None else f'{p:.3f}'} |"
        )
    bez_osoby = {t for t in wyniki if t != "OSOBA"}
    calosc = _mikro(wyniki)
    k1 = _mikro(wyniki, bez_osoby)
    for nazwa, zbiorczy in (("łącznie (K1, bez OSOBA)", k1), ("łącznie (wszystkie)", calosc)):
        r, p = recall(zbiorczy), precision(zbiorczy)
        print(
            f"| **{nazwa}** | {zbiorczy.tp} | {zbiorczy.fp} | {zbiorczy.fn} "
            f"| {'n/d' if r is None else f'{r:.3f}'} | {'n/d' if p is None else f'{p:.3f}'} |"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pomiar detektora na korpusie Niewidki")
    parser.add_argument("--korpus", type=Path, default=Path("tests/korpus"))
    parser.add_argument("--detektor", choices=("pusty", "reguly"), default="reguly")
    argumenty = parser.parse_args(argv)
    detektor = DetektorPusty() if argumenty.detektor == "pusty" else DetektorReguly()
    probki = wczytaj_probki(argumenty.korpus)
    print(f"Detektor: {argumenty.detektor}, próbki: {len(probki)}")
    wypisz_raport(zmierz(probki, detektor))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
