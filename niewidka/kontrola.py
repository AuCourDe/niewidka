"""Kontrola zapisu (LLD §10): weryfikacja ZAWSZE, na każdym poziomie suwaka.

Zapisany plik wczytany jak obcy dokument (ten sam adapter) i przeskanowany
detektorem; znaleziska niebędące znacznikami = `Ostrzezenie` (przegląd Astry
pkt 8: nowe znaleziska blokują status „ukończony" — decyzja blokady w API, K4).
Błąd detektora przelatuje jako `BladDetektora` — fail-closed (LLD §15).
"""

from __future__ import annotations

from dataclasses import dataclass

from niewidka.detektory import Detektor
from niewidka.formaty import adapter_dla


@dataclass(frozen=True)
class Ostrzezenie:
    typ: str
    fragment: str
    segment: int  # numer segmentu w wyniku


def kontroluj(dane: bytes, nazwa_pliku: str, detektor: Detektor) -> list[Ostrzezenie]:
    adapter = adapter_dla(nazwa_pliku)
    dok = adapter.wczytaj(dane)
    uwagi = []
    for numer, segment in enumerate(dok.segmenty):
        for zakres in detektor.znajdz(segment.tekst):
            uwagi.append(
                Ostrzezenie(
                    zakres.typ.value,
                    segment.tekst[zakres.start : zakres.koniec],
                    numer,
                )
            )
    return uwagi
