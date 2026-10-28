"""Grupowanie osób po odmianach (LLD §6, decyzje z KONSULTACJE i przeglądów).

SIMPLIFICATION: heurystyka końcówek zamiast lematyzacji (Morfeusz 2) —
rozbudować, gdy pomiar pokaże błędne łączenia/rozdzielenia. Różne imię
+ to samo nazwisko = różne osoby; niejednoznaczne (inicjał, samo nazwisko
przy kilku kandydatach) domyślnie NIE są łączone (przegląd Astry pkt 10).
"""

from niewidka.model import Encja, TypEncji

_TYTUŁY = frozenset({"pan", "pani", "pana", "p", "mgr", "dr", "hab", "inz", "inż", "prof", "doc", "mec"})

# Najdłuższe końcówki pierwsze; tylko fleksja, nie część rdzenia (-sk- zostaje).
# „ie" obsługuje formy miejscownika („o Janie", „Annie").
_KOŃCÓWKI = ("iemu", "iego", "ami", "owi", "ów", "ach", "em", "om", "im", "ie", "a", "i", "ą", "ę", "u", "y", "o")

# Przymiotnikowe zakończenia nazwiska — rozstrzygają szyk „Kowalski Jan".
_PRZYMIOTNIKOWE = ("ski", "ska", "cki", "cka", "dzki", "dzka", "żki", "żka", "zki", "zka")


def rdzen_nazwiska(nazwisko: str) -> str:
    nazwisko = nazwisko.lower()
    for końcówka in _KOŃCÓWKI:
        if nazwisko.endswith(końcówka) and len(nazwisko) > len(końcówka) + 2:
            return nazwisko[: -len(końcówka)]
    return nazwisko


def _rozbij(tekst: str) -> tuple[str, str]:
    """(rdzeń imienia/inicjałów, rdzeń nazwiska) z tekstu powierzchniowego.

    Imię musi zaczynać się wielką literą — słowa pospolite przed nazwiskiem
    („wniosek", „najemca") nim nie są. Jedno słowo = samo nazwisko.
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
    """Ustawia klucz_grupy encji OSOBA: „imię|rdzeń". Samo nazwisko dołącza
    do jedynej osoby o danym rdzeniu (przegląd Gemini pkt 13); przy kilku
    kandydatach każde takie wystąpienie zostaje osobną grupą."""
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
