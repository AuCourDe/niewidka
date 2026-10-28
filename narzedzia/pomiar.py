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
    OnnxDetektor,
    RegulyDetektor,
    mapuj_typ_lfm25,
    wczytaj_bardsai,
    wczytaj_lfm25,
    wczytaj_poziom2_uzupelniajacy,
    zbuduj_poziom,
)
from niewidka.konfig import PROG_OSOBA_DOMYSLNY
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


PLIK_NOWE_TYPOW = "probki_nowe_typy.jsonl"

# K7b: klasy LFM2.5 z korpusu nowych typów, które rdzeń (reguły albo pakiet
# Rozszerzony LFM2.5) zwraca jako typy Niewidki; reszta zostaje surową nazwą.
TYPY_KORPUSU_NA_RDZEN = {
    "contact.ip_address": "IP",
    "financial.credit_card": "KARTA",
    "financial.swift_bic": "SWIFT",
    "online.username": "LOGIN",
}


class Lfm25SoloDetektor:
    """LFM2.5 z PELNĄ mapą klas (pomiar K2e — nie produkt).

    Klasa `national_id` rozstrzyga się kształtem zapisu na spanie
    (detektory.mapuj_typ_lfm25); klasy bez odpowiednika w Niewidce wypisują
    surową nazwę LFM2.5 (scoring str, nie TypEncji).
    """

    def __init__(self, katalog: Path, wariant: str = "fp32"):
        podkatalog = katalog / "lfm25" / wariant
        config = json.loads((podkatalog / "config.json").read_text(encoding="utf-8"))
        schemat = json.loads((katalog / "lfm25" / "label_schema.json").read_text(encoding="utf-8"))
        klasa_umarowana = "identity.national_id"  # rozstrzygnięcie kształtem na spanie
        etykiety = {
            (klasa,): klasa_umarowana if klasa == klasa_umarowana else mapuj_typ_lfm25(klasa, "")
            for klasa in schemat["types_in_order"]
        }
        self._wewnętrzny = OnnxDetektor(
            nazwa="onnx:lfm25-solo",
            model=podkatalog / "model.onnx",
            tokenizer=podkatalog / "tokenizer.json",
            etykiety=etykiety,
            id2etykieta=config.get("id2label", {}),
            provider="CPUExecutionProvider",
        )
        self.nazwa = self._wewnętrzny.nazwa
        self.typy = frozenset(
            mapuj_typ_lfm25(klasa, "44051401359") for klasa in schemat["types_in_order"]
        )

    def znajdz(self, tekst: str) -> list[Zakres]:
        wynik = []
        for z in self._wewnętrzny.znajdz(tekst):
            if isinstance(z.typ, str):  # klasa LFM2.5 -> rozstrzygnięcie na spanie
                wynik.append(
                    Zakres(z.start, z.koniec, mapuj_typ_lfm25(z.typ, tekst[z.start : z.koniec]),
                           z.pewnosc, z.zrodlo)
                )
            else:
                wynik.append(z)
        return wynik


def zbuduj_detektor(
    nazwa: str,
    katalog_modeli: Path | None,
    wariant: str = "int8",
    próg_osoba: float = PROG_OSOBA_DOMYSLNY,
):
    """Detektor pomiaru wg nazwy CLI.

    Poziomy produktu składa `detektory.zbuduj_poziom` (ta sama funkcja co rdzeń,
    K2d): poziom1 = reguły+bardsai, poziom2-a = produktowy poziom 2 (wariant A,
    próg `próg_osoba` + okna półkrokowe), poziom2-b = produktowy poziom 3 (wariant
    B, +słownik imion). Nazwy `poziom2` (z LFM2.5, K2b) i `poziom2-uzup*` (K2c)
    zostają wyłącznie dla reprodukcji starych pomiarów.
    """
    if nazwa == "pusty":
        return DetektorPusty()
    if nazwa == "reguly":
        return RegulyDetektor()
    if nazwa in ("poziom1", "poziom2-a", "poziom2-b", "poziom3-rozszerzony"):
        if katalog_modeli is None:
            raise ValueError(
                f"{nazwa} wymaga katalogu wag: NIEWIDKA_MODELE_KATALOG albo --modele"
            )
        poziom = {"poziom1": 1, "poziom2-a": 2, "poziom2-b": 3, "poziom3-rozszerzony": 3}[nazwa]
        return zbuduj_poziom(
            poziom,
            katalog_modeli,
            próg_osoba=próg_osoba,
            pakiet_rozszerzony=(nazwa == "poziom3-rozszerzony"),
        )
    if nazwa == "lfm25-solo":
        if katalog_modeli is None:
            raise ValueError(
                f"{nazwa} wymaga katalogu wag: NIEWIDKA_MODELE_KATALOG albo --modele"
            )
        return Lfm25SoloDetektor(katalog_modeli, wariant=wariant)
    if nazwa in ("poziom2", "lfm25"):
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
            klucz = (z.start, z.koniec, getattr(z.typ, "value", z.typ))
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


def wczytaj_probki(
    katalog: Path, pliki: set[str] | None = None, typy_rdz: bool = False
) -> list[Probka]:
    probki = []
    for plik in sorted(katalog.glob("*.jsonl")):
        if pliki is not None and plik.name not in pliki:
            continue
        for linia in plik.read_text(encoding="utf-8").splitlines():
            if not linia.strip():
                continue
            surowa = json.loads(linia)
            encje = [
                Oczekiwana(
                    typ=TYPY_KORPUSU_NA_RDZEN.get(e["typ"], e["typ"]) if typy_rdz else e["typ"],
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
            "lfm25-solo",
            "poziom2-a",
            "poziom2-b",
            "poziom3-rozszerzony",
            "poziom2-uzup",
            "poziom2-uzup-b",
        ),
        default="reguly",
    )
    parser.add_argument(
        "--plik",
        action="append",
        help="ograniczenie pomiaru do wskazanych plików korpusu (nazwa, powtarzalne)",
    )
    parser.add_argument(
        "--typy-rdz",
        action="store_true",
        help="typy korpusu nowych (contact.ip_address itd.) liczone jako typy rdzenia "
        "(IP, KARTA, SWIFT, LOGIN) — dla detektorów rdzenia; lfm25-solo zostaje surowy (K2e)",
    )
    parser.add_argument(
        "--wariant",
        choices=("int8", "fp32", "q4-bl32", "q4-bl128"),  # K7a: kwantyzacja int4
        default="int8",
    )
    parser.add_argument(
        "--prog-osoba",
        type=float,
        default=PROG_OSOBA_DOMYSLNY,
        help="próg pewności OSOBA poziomów produktu 2/3 (warianty K2d; "
        f"domyślnie {PROG_OSOBA_DOMYSLNY}, jak NIEWIDKA_PROG_OSOBA w produkcie)",
    )
    parser.add_argument(
        "--modele",
        type=Path,
        default=Path(os.environ["NIEWIDKA_MODELE_KATALOG"])
        if os.environ.get("NIEWIDKA_MODELE_KATALOG")
        else None,
        help="katalog wag (domyślnie z NIEWIDKA_MODELE_KATALOG)",
    )
    argumenty = parser.parse_args(argv)
    detektor = zbuduj_detektor(
        argumenty.detektor, argumenty.modele, wariant=argumenty.wariant, próg_osoba=argumenty.prog_osoba
    )
    probki = wczytaj_probki(
        argumenty.korpus, set(argumenty.plik) if argumenty.plik else None, typy_rdz=argumenty.typy_rdz
    )
    print(
        f"Detektor: {argumenty.detektor}, próbki: {len(probki)}"
        + (f", próg OSOBA: {argumenty.prog_osoba}" if argumenty.detektor in ("poziom2-a", "poziom2-b") else "")
    )
    wyniki, czasy = zmierz_z_czasem(probki, detektor)
    wypisz_raport(wyniki)
    wypisz_czasy(czasy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
