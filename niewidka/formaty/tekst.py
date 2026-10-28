"""Adapter TXT (LLD §9): jeden segment, jeden run; trywialny celowo."""

from __future__ import annotations

from niewidka.formaty import wstaw_znaczniki as wspolne_wstawianie
from niewidka.model import Dokument, RunInfo, Segment
from niewidka.znaczniki import DOPISEK


class AdapterTekst:
    rozszerzenia = frozenset({"txt"})

    def wczytaj(self, dane: bytes, polityka_obrazow: str | None = None) -> Dokument:
        tekst = dane.decode("utf-8-sig")  # polityka_obrazow dotyczy tylko DOCX
        return Dokument("txt", [Segment(tekst, [RunInfo(tekst, element=None)], [0])])

    def wstaw_znaczniki(self, segment: Segment, zamiany: list[tuple[int, int, str]]) -> None:
        wspolne_wstawianie(segment, zamiany, kopiuj_run=lambda element, tekst: None)

    def zapisz(self, dok: Dokument, dopisek: bool | str = True) -> bytes:
        tresc = "\n".join("".join(run.tekst for run in segment.runs) for segment in dok.segmenty)
        if not dopisek:
            # dokument przywrócony: dopisek wyniku znika (odtwarzamy dane zastąpione);
            # dopisek może mieć doklejony identyfikator mapy (K4b pkt 6)
            linie = tresc.split("\n")
            if linie and linie[0].startswith(DOPISEK):
                tresc = "\n".join(linie[1:])
            return tresc.encode()
        tekst_dopisku = DOPISEK if dopisek is True else dopisek
        return f"{tekst_dopisku}\n{tresc}".encode()

    def elementy_nieobslugiwane(self, dok: Dokument) -> list[str]:
        return []
