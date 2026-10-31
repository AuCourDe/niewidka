"""Grouping people by inflected forms.

SIMPLIFICATION: an ending heuristic instead of lemmatisation (Morfeusz 2) -
extend when measurement shows wrong merges/splits. A different first name
+ the same surname = different people; ambiguous cases (an initial, a bare surname
with several candidates) are NOT merged by default.
"""

from niewidka.model import Encja, TypEncji

_TYTUŁY = frozenset({"pan", "pani", "pana", "p", "mgr", "dr", "hab", "inz", "inż", "prof", "doc", "mec"})

# Longest endings first; inflection only, not part of the stem (-sk- stays).
# "ie" handles locative forms ("o Janie", "Annie").
_KOŃCÓWKI = ("iemu", "iego", "ami", "owi", "ów", "ach", "em", "om", "im", "ie", "a", "i", "ą", "ę", "u", "y", "o")

# Adjectival surname endings - they settle the "Kowalski Jan" word order.
_PRZYMIOTNIKOWE = ("ski", "ska", "cki", "cka", "dzki", "dzka", "żki", "żka", "zki", "zka")


def rdzen_nazwiska(nazwisko: str) -> str:
    nazwisko = nazwisko.lower()
    for końcówka in _KOŃCÓWKI:
        if nazwisko.endswith(końcówka) and len(nazwisko) > len(końcówka) + 2:
            return nazwisko[: -len(końcówka)]
    return nazwisko


def _rozbij(tekst: str) -> tuple[str, str]:
    """(first-name/initials stem, surname stem) from surface text.

    A first name must start with a capital letter - common words before a surname
    ("wniosek", "najemca") are not one. A single word = the surname alone.
    """
    słowa = [s.strip(",.") for s in tekst.split() if s.rstrip(".").lower() not in _TYTUŁY]
    if not słowa:
        return "", tekst.lower()
    if len(słowa) == 1:
        return "", rdzen_nazwiska(słowa[0])
    if len(słowa) == 2 and _przymiotnikowe(słowa[0]) and not _przymiotnikowe(słowa[1]):
        return rdzen_nazwiska(słowa[1]), rdzen_nazwiska(słowa[0])
    imię = słowa[0] if słowa[0][:1].isupper() else ""
    return rdzen_nazwiska(imię), rdzen_nazwiska(słowa[-1])


def _przymiotnikowe(słowo: str) -> bool:
    return słowo.lower().endswith(_PRZYMIOTNIKOWE)


def pogrupuj(encje: list[Encja]) -> None:
    """Sets klucz_grupy on OSOBA entities: "first name|stem". A bare surname joins
    the only person with that stem; with several
    candidates each such occurrence stays its own group."""
    osoby = [e for e in encje if e.zakres.typ is TypEncji.OSOBA]
    rozbiory = [_rozbij(e.tekst) for e in osoby]
    imiona_po_rdzeniu: dict[str, set[str]] = {}
    for imię, rdzeń in rozbiory:
        if imię:
            imiona_po_rdzeniu.setdefault(rdzeń, set()).add(imię)
    niejednoznaczne: dict[str, int] = {}
    for encja, (imię, rdzeń) in zip(osoby, rozbiory):
        if imię:
            encja.klucz_grupy = f"{imię}|{rdzeń}"
        elif len(imiona_po_rdzeniu.get(rdzeń, set())) == 1:
            encja.klucz_grupy = f"{next(iter(imiona_po_rdzeniu[rdzeń]))}|{rdzeń}"
        else:
            numer = niejednoznaczne.get(rdzeń, 0)
            niejednoznaczne[rdzeń] = numer + 1
            encja.klucz_grupy = f"|{rdzeń}#{numer}"
