"""Grouping people by inflected forms (stems from `odmiana`).

A different first name + the same surname = different people. An initial joins only
the single person with that surname. A bare surname or a bare first name joins the
single person it can belong to; without such a person every occurrence of the same
stem is one group, and with several candidates the bare occurrences form one shared
ambiguous group (never merged with any of the candidates).
"""

import re

from niewidka.model import Encja, TypEncji
from niewidka.odmiana import jest_imieniem, rdzen

_TYTUŁY = frozenset({
    "pan", "pani", "pana", "panu", "panem", "panią", "panie", "państwo", "państwa", "p",
    "mgr", "dr", "hab", "inz", "inż", "prof", "doc", "mec", "mecenas", "adw", "adwokat",
    "ks", "ksiądz", "dyr", "płk", "kpt", "sierż", "asp", "st",
})
_RDZENIE_TYTUŁÓW = frozenset(rdzen(t) for t in _TYTUŁY if len(t) > 3)

# Adjectival surname endings - they settle the "Kowalski Jan" word order.
_PRZYMIOTNIKOWE = ("ski", "ska", "cki", "cka", "dzki", "dzka", "żki", "żka", "zki", "zka")


def jest_tytulem(slowo: str) -> bool:
    slowo = slowo.strip(",.").lower()
    return slowo in _TYTUŁY or (len(slowo) > 3 and rdzen(slowo) in _RDZENIE_TYTUŁÓW)


def sam_tytul(tekst: str) -> bool:
    """Text made only of titles ("Pan", "Pani dr") names nobody, so it is no personal data."""
    slowa = re.findall(r"\w+", tekst)
    return bool(slowa) and all(jest_tytulem(slowo) for slowo in slowa)


def _rozbij(tekst: str) -> tuple[str, str]:
    """(first-name/initial key, surname key) from surface text.

    A first name is the first capitalised word before the surname; common words
    ("wniosek", "najemca") and titles are not. A single word = the surname alone.
    """
    słowa = [s.strip(",.") for s in tekst.split() if not jest_tytulem(s)]
    słowa = [s for s in słowa if s]
    if not słowa:
        return "", rdzen(tekst.strip())
    if len(słowa) == 1:
        return "", rdzen(słowa[0])
    if (
        len(słowa) == 2
        and _przymiotnikowe(słowa[0])
        and not _przymiotnikowe(słowa[1])
        and not jest_imieniem(słowa[0])
    ):
        return rdzen(słowa[1]), rdzen(słowa[0])
    imię = next((s for s in słowa[:-1] if s[:1].isupper()), "")
    return (rdzen(imię) if imię else ""), rdzen(słowa[-1])


def _przymiotnikowe(słowo: str) -> bool:
    return słowo.lower().endswith(_PRZYMIOTNIKOWE)


def pogrupuj(encje: list[Encja]) -> None:
    """Sets klucz_grupy on OSOBA entities: "first name|surname stem"."""
    osoby = [e for e in encje if e.zakres.typ is TypEncji.OSOBA]
    rozbiory = [_rozbij(e.tekst) for e in osoby]
    imiona_po_rdzeniu: dict[str, set[str]] = {}
    nazwiska_po_imieniu: dict[str, set[str]] = {}
    for imię, rdzeń in rozbiory:
        if imię:
            imiona_po_rdzeniu.setdefault(rdzeń, set()).add(imię)
            if len(imię) > 1:
                nazwiska_po_imieniu.setdefault(imię, set()).add(rdzeń)
    for encja, (imię, rdzeń) in zip(osoby, rozbiory):
        if imię:
            encja.klucz_grupy = f"{imię}|{rdzeń}"
            continue
        imiona = imiona_po_rdzeniu.get(rdzeń, set())
        nazwiska = nazwiska_po_imieniu.get(rdzeń, set())
        if len(imiona) == 1:
            encja.klucz_grupy = f"{next(iter(imiona))}|{rdzeń}"
        elif imiona:
            encja.klucz_grupy = f"|{rdzeń}?"
        elif len(nazwiska) == 1:  # a bare first name ("Panie Janie") of the only such person
            encja.klucz_grupy = f"{rdzeń}|{next(iter(nazwiska))}"
        else:
            encja.klucz_grupy = f"|{rdzeń}"
