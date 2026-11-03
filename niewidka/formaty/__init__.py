"""Format adapters: registry extension -> adapter, shared run cuts.

Per-format structure allowlist: parts outside the adapter's
allowlist block export (`ElementNieobslugiwany`) - they never pass silently."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Protocol

from niewidka.model import Dokument, RunInfo, Segment


class ElementNieobslugiwany(Exception):
    """Export blocked with a list of elements."""

    def __init__(self, elementy: list[str]):
        self.elementy = elementy
        super().__init__(", ".join(elementy))


class NieznanyFormat(Exception):
    """Input in a format outside the registry."""

    def __init__(self, format: str, wspierane: list[str]):
        self.format = format
        self.wspierane = wspierane
        super().__init__(f"nieznany format: {format!r}; obsługiwane: {', '.join(wspierane)}")


class BladKodowania(Exception):
    """A text file in no encoding we can read with certainty (binary or an unknown code page)."""

    def __init__(self) -> None:
        super().__init__(
            "Nie umiem odczytać tego pliku tekstowego. Otwórz go w Notatniku, zapisz jako UTF-8 "
            "i spróbuj ponownie."
        )


class AdapterFormatu(Protocol):
    rozszerzenia: frozenset[str]

    def wczytaj(
        self, dane: bytes, polityka_obrazow: str | None = None, max_rozpakowane: int | None = None
    ) -> Dokument: ...
    def zapisz(self, dok: Dokument, dopisek: bool | str = True) -> bytes: ...  # cleans metadata, note (str = text with the map id)
    def elementy_nieobslugiwane(self, dok: Dokument) -> list[str]: ...


def podziel_segment(
    segment: Segment, zamiany: list[tuple[int, int, str]]
) -> list[tuple[str, int]]:
    """Fragments (text, source run index) after inserting markers.

        `zamiany` are disjoint (start, end, marker) in segment characters; the marker
        fragment inherits the style of the LEFT fragment, parts cut out of a run keep the style of their
        run. Cutting happens at the replacement boundary points.
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
            continue  # split point in the middle of a replacement - no original
        else:
            idx = run_na_pozycji(poczatek)
            fragmenty.append((segment.tekst[poczatek:koniec], idx))
    return fragmenty


def _wewnatrz_zamiany(pozycja: int, zamiany: list[tuple[int, int, str]]) -> bool:
    return any(start < pozycja < koniec for start, koniec, _ in zamiany)


def nazwa_wyniku(oryginalna: str, identyfikator: str) -> str:
    """ZANONIMIZOWANY_<short-id>.<ext>."""
    rozszerzenie = Path(oryginalna).suffix
    return f"ZANONIMIZOWANY_{identyfikator}{rozszerzenie}"


def wstaw_znaczniki(segment: Segment, zamiany: list[tuple[int, int, str]], kopiuj_run) -> None:
    """Replace a segment per `zamiany` (mutation): new runs, starts, text.

        `kopiuj_run(element, tekst)` builds the run element for a fragment (the adapter knows
        its format; the marker inherits the style of the left fragment).
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
    """Adapter by format name (extension); unknown = `ElementNieobslugiwany`."""
    fabryka = _FABRYKI.get(format.lower().strip("."))
    if fabryka is None:
        raise ElementNieobslugiwany([f"nieznany format: {format!r}"])
    return fabryka()


def adapter_dla(nazwa_pliku: str):
    """Adapter by file extension; unknown = `ElementNieobslugiwany` (415/422)."""
    return adapter_formatu(Path(nazwa_pliku).suffix.lstrip(".").lower())
