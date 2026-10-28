"""Adapter TXT (LLD §9): jeden segment, jeden run; trywialny celowo."""

from __future__ import annotations

from niewidka.formaty import wstaw_znaczniki as wspolne_wstawianie
from niewidka.model import Dokument, RunInfo, Segment
from niewidka.znaczniki import DOPISEK


class AdapterTekst:
    rozszerzenia = frozenset({"txt"})

    def wczytaj(self, dane: bytes) -> Dokument:
        tekst = dane.decode("utf-8-sig")
        return Dokument("txt", [Segment(tekst, [RunInfo(tekst, element=None)], [0])])

    def wstaw_znaczniki(self, segment: Segment, zamiany: list[tuple[int, int, str]]) -> None:
        wspolne_wstawianie(segment, zamiany, kopiuj_run=lambda element, tekst: None)

    def zapisz(self, dok: Dokument, dopisek: bool = True) -> bytes:
        tresc = "\n".join("".join(run.tekst for run in segment.runs) for segment in dok.segmenty)
        if not dopisek:
            # dokument przywrócony: dopisek wyniku znika (odtwarzamy dane zastąpione)
            if tresc == DOPISEK:
                tresc = ""
            elif tresc.startswith(DOPISEK + "\n"):
                tresc = tresc[len(DOPISEK) + 1 :]
            return tresc.encode()
        return f"{DOPISEK}\n{tresc}".encode()

    def elementy_nieobslugiwane(self, dok: Dokument) -> list[str]:
        return []
