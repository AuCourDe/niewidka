"""Adaptery formatów (LLD §9): rejestr rozszerzenie → adapter, wspólne cięcia runów.

Allowlista struktury per format (przegląd Astry pkt 5): części spoza allowlisty
adaptera blokują eksport (`ElementNieobslugiwany`) — nigdy nie przechodzą cicho.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Protocol

from niewidka.model import Dokument, RunInfo, Segment


class ElementNieobslugiwany(Exception):
    """Eksport blokowany z listą elementów (LLD §15: makra, części spoza allowlisty)."""

    def __init__(self, elementy: list[str]):
        self.elementy = elementy
        super().__init__(", ".join(elementy))


class NieznanyFormat(Exception):
    """Wejście w formacie spoza rejestru (LLD §15 → HTTP 415 z listą obsługiwanych)."""

    def __init__(self, format: str, wspierane: list[str]):
        self.format = format
        self.wspierane = wspierane
        super().__init__(f"nieznany format: {format!r}; obsługiwane: {', '.join(wspierane)}")


class AdapterFormatu(Protocol):
    rozszerzenia: frozenset[str]

    def wczytaj(self, dane: bytes, polityka_obrazow: str | None = None) -> Dokument: ...
    def zapisz(self, dok: Dokument, dopisek: bool | str = True) -> bytes: ...  # czyści metadane, dopisek (str = tekst z id mapy)
    def elementy_nieobslugiwane(self, dok: Dokument) -> list[str]: ...


def podziel_segment(
    segment: Segment, zamiany: list[tuple[int, int, str]]
) -> list[tuple[str, int]]:
    """Fragmenty (tekst, indeks runu źródłowego) po wstawieniu znaczników.

    `zamiany` to rozłączne (start, koniec, znacznik) w znakach segmentu; fragment
    znacznika dziedziczy styl LEWEGO fragmentu, części wytnięte z runu — styl swojego
    runu (LLD §9). Cięcie następuje w punktach granicznych zamian.
    """
    posortowane = sorted(zamiany)
    for (a_start, a_koniec, _), (b_start, b_koniec, _) in pairwise(posortowane):
        if b_start < a_koniec:
            raise ValueError(f"zamiany nakładają się: ({a_start},{a_koniec}) i ({b_start},{b_koniec})")

    granice = {0, len(segment.tekst), *segment.starts}
    for start, koniec, _ in posortowane:
        granice.update((start, koniec))
    punkty = sorted(granice)

    def run_na_pozycji(pozycja: int) -> int:
        for i in range(len(segment.starts) - 1, -1, -1):
            if pozycja >= segment.starts[i]:
                return i
        return 0

    fragmenty: list[tuple[str, int]] = []
    znaczniki = {start: (start, koniec, tekst) for start, koniec, tekst in posortowane}
    for poczatek, koniec in pairwise(punkty):
        if poczatek in znaczniki:
            _, _, tekst = znaczniki[poczatek]
            fragmenty.append((tekst, run_na_pozycji(poczatek)))
        elif _wewnatrz_zamiany(poczatek, posortowane):
            continue  # Gemini pkt 1: punkt podziału w środku zamiany — bez oryginału
        else:
            idx = run_na_pozycji(poczatek)
            fragmenty.append((segment.tekst[poczatek:koniec], idx))
    return fragmenty


def _wewnatrz_zamiany(pozycja: int, zamiany: list[tuple[int, int, str]]) -> bool:
    return any(start < pozycja < koniec for start, koniec, _ in zamiany)


def nazwa_wyniku(oryginalna: str, identyfikator: str) -> str:
    """ZANONIMIZOWANY_<krótki-id>.<ext> (LLD §17 / Astra pkt 5)."""
    rozszerzenie = Path(oryginalna).suffix
    return f"ZANONIMIZOWANY_{identyfikator}{rozszerzenie}"


def wstaw_znaczniki(segment: Segment, zamiany: list[tuple[int, int, str]], kopiuj_run) -> None:
    """Zamień segment wg `zamiany` (mutacja): nowe runy, starts, tekst.

    `kopiuj_run(element, tekst)` buduje element runu dla fragmentu (adapter zna
    swój format; znacznik dziedziczy styl lewego fragmentu, LLD §9).
    """
    fragmenty = podziel_segment(segment, zamiany)
    stare = segment.runs
    segment.runs = [RunInfo(tekst, kopiuj_run(stare[idx].element, tekst)) for tekst, idx in fragmenty]
    segment.starts = []
    biezacy = 0
    for run in segment.runs:
        segment.starts.append(biezacy)
        biezacy += len(run.tekst)
    segment.tekst = "".join(run.tekst for run in segment.runs)


def _fabryka_txt():
    from niewidka.formaty.tekst import AdapterTekst

    return AdapterTekst()


def _fabryka_docx():
    from niewidka.formaty.docx_ import AdapterDocx

    return AdapterDocx()


_FABRYKI: dict[str, object] = {"txt": _fabryka_txt, "docx": _fabryka_docx}


def rozszerzenia_wspierane() -> frozenset[str]:
    return frozenset(_FABRYKI)


def adapter_formatu(format: str):
    """Adapter wg nazwy formatu (rozszerzenia); nieznany = `ElementNieobslugiwany`."""
    fabryka = _FABRYKI.get(format.lower().strip("."))
    if fabryka is None:
        raise ElementNieobslugiwany([f"nieznany format: {format!r}"])
    return fabryka()


def adapter_dla(nazwa_pliku: str):
    """Adapter wg rozszerzenia pliku; nieznane = `ElementNieobslugiwany` (415/422)."""
    return adapter_formatu(Path(nazwa_pliku).suffix.lstrip(".").lower())
