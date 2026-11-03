"""Markers [TYP_N] / [OSOBA_N_Fk]: numbers per type in order of appearance, people with a stable
form variant, so restoring by (label, variant) does not depend on position or
paraphrase. The note has no square brackets, so the check does not mistake it for a marker.
"""

import re

from niewidka.model import Encja, TypEncji

DOPISEK = (
    "ZANONIMIZOWANY. Dane osobowe zastąpiono znacznikami (Niewidka). "
    "Oryginalne dane przywrócisz plikiem mapy."
)


_ALFABET_ID = "abcdefghijklmnop"

# numbers whose notation varies (hyphens, spaces, letter case) but whose value does not
_TYPY_NUMEROW = frozenset(
    {TypEncji.PESEL, TypEncji.NIP, TypEncji.REGON, TypEncji.IBAN, TypEncji.KARTA, TypEncji.DOKUMENT}
)


def _wartosc(encja: Encja) -> str:
    if encja.zakres.typ in _TYPY_NUMEROW:
        return re.sub(r"[\s\-]", "", encja.tekst).upper()
    return " ".join(encja.tekst.split())


def zakoduj_identyfikator(identyfikator: str) -> str:
    """Identifier as letters only (nibble -> a..p). Raw hex in the note produced
    random 9-11-character digit windows that tripped the PESEL/REGON rules in the
    result check and randomly blocked documents."""
    return "".join(_ALFABET_ID[int(znak, 16)] for znak in identyfikator)


def odkoduj_identyfikator(litery: str) -> str | None:
    """Inverse of `zakoduj_identyfikator`; None for text that is not an identifier."""
    try:
        return "".join(f"{_ALFABET_ID.index(znak):x}" for znak in litery)
    except ValueError:
        return None


def dopisek(identyfikator: str) -> str:
    """Result note with the map identifier: ties the map to a SPECIFIC
    document - restore checks that the map identifier equals the one
    written in the content; supplying the map of another job ends in 422."""
    return f"{DOPISEK} Identyfikator mapy: {zakoduj_identyfikator(identyfikator)}."


def nadaj_oznaczenia(encje: list[Encja]) -> None:
    """Sets encja.oznaczenie and encja.wariant; entities must be in document order.

    PEOPLE with the same klucz_grupy share a number; without a key each gets
    its own. Other types: the same value (text ignoring whitespace differences)
    shares a number, so a repeated PESEL is still one [PESEL_1]. Each unique surface form of a person has a stable
    variant number Fk (assigned by first occurrence; the same form = the same
    Fk). Numbers (PESEL, NIP, ...) compare without hyphens and spaces; the first notation
    has no variant ([NIP_1] = F1), each further notation gets F2, F3 ([NIP_1_F2]).
    """
    liczniki: dict[str, int] = {}
    numery: dict[str, str] = {}
    formy: dict[str, dict[str, str]] = {}  # group identifier -> form -> "Fk"
    for pozycja, encja in enumerate(encje):
        typ = encja.zakres.typ.value
        if encja.zakres.typ is TypEncji.OSOBA:
            grupa = encja.klucz_grupy or f"#{pozycja}"
        else:
            grupa = encja.klucz_grupy or "=" + _wartosc(encja)
        identyfikator = f"{typ}\x00{grupa}"
        if identyfikator not in numery:
            liczniki[typ] = liczniki.get(typ, 0) + 1
            numery[identyfikator] = f"{typ}_{liczniki[typ]}"
        encja.oznaczenie = numery[identyfikator]
        if encja.zakres.typ is TypEncji.OSOBA:
            formy_grupy = formy.setdefault(identyfikator, {})
            if encja.tekst not in formy_grupy:
                formy_grupy[encja.tekst] = f"F{len(formy_grupy) + 1}"
            encja.wariant = formy_grupy[encja.tekst]
        elif encja.zakres.typ in _TYPY_NUMEROW:
            formy_grupy = formy.setdefault(identyfikator, {})
            if encja.tekst not in formy_grupy:
                formy_grupy[encja.tekst] = f"F{len(formy_grupy) + 1}"
            wariant = formy_grupy[encja.tekst]
            encja.wariant = None if wariant == "F1" else wariant


def znacznik_encji(encja: Encja) -> str:
    """Entity marker text: [TYP_N] or [OSOBA_N_Fk]."""
    if encja.oznaczenie is None:
        raise ValueError("encja bez oznaczenia — najpierw nadaj_oznaczenia")
    return f"[{encja.oznaczenie}]" if encja.wariant is None else f"[{encja.oznaczenie}_{encja.wariant}]"
