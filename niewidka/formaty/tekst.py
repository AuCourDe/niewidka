"""Adapter TXT (LLD §9): jeden segment, jeden run; trywialny celowo."""

from __future__ import annotations

from niewidka.model import Dokument, RunInfo, Segment
from niewidka.znaczniki import DOPISEK


class AdapterTekst:
    rozszerzenia = frozenset({"txt"})

    def wczytaj(self, dane: bytes) -> Dokument:
        tekst = dane.decode("utf-8-sig")
        return Dokument("txt", [Segment(tekst, [RunInfo(tekst, element=None)], [0])])

    def zapisz(self, dok: Dokument) -> bytes:
        tresc = "\n".join("".join(run.tekst for run in segment.runs) for segment in dok.segmenty)
        return f"{DOPISEK}\n{tresc}".encode()

    def elementy_nieobslugiwane(self, dok: Dokument) -> list[str]:
        return []
