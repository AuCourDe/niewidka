"""TXT adapter: one segment, one run; trivial on purpose."""

from __future__ import annotations

import codecs

from niewidka.formaty import BladKodowania
from niewidka.formaty import wstaw_znaczniki as wspolne_wstawianie
from niewidka.model import Dokument, RunInfo, Segment
from niewidka.znaczniki import DOPISEK

_ZNACZNIKI_KOLEJNOSCI = (
    (codecs.BOM_UTF32_LE, "utf-32"),  # before UTF-16: its mark starts with the UTF-16 one
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
_POLSKIE_LITERY = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def _dekoduj(dane: bytes) -> str:
    """UTF-8, or UTF-16/UTF-32 with a byte order mark; otherwise the Polish single-byte code page
    (Windows-1250 or ISO 8859-2) that gives more Polish letters. Anything else is an error,
    never guessed text. A NUL in the result (UTF-16 without a mark, a binary file) is an error
    too: the rules would not see a number with a NUL between its digits."""
    tekst = _dekoduj_kodowanie(dane)
    if "\x00" in tekst:
        raise BladKodowania()
    return tekst


def _dekoduj_kodowanie(dane: bytes) -> str:
    for znacznik, kodowanie in _ZNACZNIKI_KOLEJNOSCI:
        if dane.startswith(znacznik):
            try:
                return dane.decode(kodowanie)
            except UnicodeDecodeError:
                raise BladKodowania() from None
    try:
        return dane.decode("utf-8")
    except UnicodeDecodeError:
        pass
    kandydaci = []
    for kodowanie in ("cp1250", "iso8859_2"):
        try:
            tekst = dane.decode(kodowanie)
        except UnicodeDecodeError:
            continue
        # a letter has no C1 control characters: they mean the wrong code page
        if any("\x80" <= znak <= "\x9f" for znak in tekst):
            continue
        kandydaci.append((sum(znak in _POLSKIE_LITERY for znak in tekst), tekst))
    if not kandydaci:
        raise BladKodowania()
    return max(kandydaci, key=lambda kandydat: kandydat[0])[1]  # equal: Windows-1250 first


class AdapterTekst:
    rozszerzenia = frozenset({"txt"})

    def wczytaj(
        self, dane: bytes, polityka_obrazow: str | None = None, max_rozpakowane: int | None = None
    ) -> Dokument:
        tekst = _dekoduj(dane)  # image policy and limit apply only to archives
        return Dokument("txt", [Segment(tekst, [RunInfo(tekst, element=None)], [0])])

    def wstaw_znaczniki(self, segment: Segment, zamiany: list[tuple[int, int, str]]) -> None:
        wspolne_wstawianie(segment, zamiany, kopiuj_run=lambda element, tekst: None)

    def zapisz(self, dok: Dokument, dopisek: bool | str = True) -> bytes:
        tresc = "\n".join("".join(run.tekst for run in segment.runs) for segment in dok.segmenty)
        if not dopisek:
            # restored document: the result's note disappears (we restore the replaced data);
            # the note may have the map id appended
            linie = tresc.split("\n")
            if linie and linie[0].startswith(DOPISEK):
                tresc = "\n".join(linie[1:])
            return tresc.encode()
        tekst_dopisku = DOPISEK if dopisek is True else dopisek
        return f"{tekst_dopisku}\n{tresc}".encode()

    def elementy_nieobslugiwane(self, dok: Dokument) -> list[str]:
        return []
