"""Polish inflection of names: one stemmer for grouping people, corrections, lists and the check.

`rdzen(slowo)` is a canonical key: two forms of the same name give the same key
("Annie Kowalskiej" and "Anna Kowalska", "Markiem" and "Marek", "Dębem" and "Dąb").
It is meant for equality only; it is not always a prefix of the word.
`temat(slowo)` is the literal surface stem (endings removed, nothing rewritten), for
patterns that must match the original text.

SIMPLIFICATION: rules instead of lemmatization (Morfeusz 2 is a native dependency that the
Windows build and the offline environment cannot carry). Known ceiling: irregular stems
(Kwiecień/Kwietnia), plural place names equal to a surname form (Mazury, Tomaszów).
Extend with a form dictionary when measurement shows wrong merges or splits.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PLIK_IMION = Path(__file__).resolve().parent / "dane" / "imiona_gus.txt"

# longest first; each needs a stem of at least 3 letters (2 for the short vowel endings)
_KONCOWKI = (
    "owie", "iego", "iemu", "ego", "emu", "iej", "ami", "ach", "owi", "iem",
    "ej", "ym", "im", "em", "om", "ów", "ie", "a", "i", "ą", "ę", "u", "y", "o", "e",
)
_KRÓTKIE = frozenset({"a", "i", "ą", "ę", "u", "y", "o", "e", "ie"})
# endings that are never part of a nominative first name: "Maksym", "Hieronim", "Andrzej",
# "Maciej" keep their ending when the word itself is a first name from the list
_NIE_MIANOWNIK = frozenset({"ym", "im", "ej", "iej", "em", "om", "iem", "ów", "ach", "ami"})

# consonant alternations before the locative/dative -e / -ie, undone on the stem
_PRZED_E = (("rz", "r"), ("dz", "g"), ("sz", "ch"), ("c", "k"), ("l", "ł"))
_PRZED_IE = (("dz", "d"), ("c", "t"))
# movable e: Marek/Marka, Paweł/Pawła, Jacek/Jacka, Wróbel/Wróbla, Grabiec/Grabca, Kozioł/Kozła
_RUCHOME_E = (("iec", "c"), ("ec", "c"), ("ek", "k"), ("ioł", "ł"), ("eł", "ł"), ("el", "l"))
_SPOLGLOSKI = frozenset("bcćdfghjklłmnńprsśtwzźż")


@lru_cache(maxsize=1)
def imiona() -> frozenset[str]:
    """Lower-case nominative first names from the bundled list (empty when the file is missing)."""
    if not PLIK_IMION.is_file():
        return frozenset()
    wynik = set()
    for linia in PLIK_IMION.read_text(encoding="utf-8").splitlines():
        imie = linia.split("\t", 1)[0].strip()
        if imie and not imie.startswith("#") and imie.isalpha():
            wynik.add(imie.lower())
    return frozenset(wynik)


def _zdejmij(slowo: str) -> tuple[str, str]:
    """(stem, removed ending) of one lower-case word without a hyphen."""
    for koncowka in _KONCOWKI:
        if not slowo.endswith(koncowka):
            continue
        reszta = len(slowo) - len(koncowka)
        if reszta < 2 or (reszta == 2 and koncowka not in _KRÓTKIE):
            continue
        if koncowka in _NIE_MIANOWNIK and slowo in imiona():
            return slowo, ""
        return slowo[:reszta], koncowka
    return slowo, ""


def temat(slowo: str) -> str:
    """Literal stem: the word without its inflectional ending, case and letters kept."""
    czesci = []
    for czlon in slowo.split("-"):
        stem, _ = _zdejmij(czlon.lower())
        czesci.append(czlon[: len(stem)])
    return "-".join(czesci)


@lru_cache(maxsize=4096)
def _rdzen_czlonu(czlon: str) -> str:
    stem, koncowka = _zdejmij(czlon)
    zamiany = _PRZED_IE if koncowka == "ie" else _PRZED_E if koncowka == "e" else ()
    for koniec, zamiana in zamiany:
        if stem.endswith(koniec):
            stem = stem[: -len(koniec)] + zamiana
            break
    # soft stem: Kasia/Kasi, Maria/Marii, Zofia/Zofii
    if len(stem) >= 4 and stem.endswith("i") and stem[-2] in _SPOLGLOSKI:
        stem = stem[:-1]
    for koniec, zamiana in _RUCHOME_E:
        if stem.endswith(koniec) and len(stem) - len(koniec) >= 2:
            stem = stem[: -len(koniec)] + zamiana
            break
    return stem.replace("ę", "ą").replace("ó", "o")


def rdzen(slowo: str) -> str:
    """Canonical key of a name form; hyphenated names are stemmed member by member."""
    return "-".join(_rdzen_czlonu(czlon) for czlon in slowo.lower().split("-"))


# common diminutives (nominative and genitive) -> full first name; a bare "Kasia" then joins
# the only Katarzyna in the text
_ZDROBNIENIA = {
    "Anna": "Ania Ani Anka Anki Anusia Anusi",
    "Katarzyna": "Kasia Kasi Kaśka Kaśki",
    "Barbara": "Basia Basi Baśka Baśki",
    "Małgorzata": "Gosia Gosi Małgosia Małgosi",
    "Agnieszka": "Aga Agi Agusia Agusi",
    "Joanna": "Asia Asi Joasia Joasi",
    "Magdalena": "Magda Magdy Madzia Madzi",
    "Aleksandra": "Ola Oli Olka",
    "Zuzanna": "Zuzia Zuzi",
    "Elżbieta": "Ela Eli",
    "Dorota": "Dorotka Dorotki",
    "Jan": "Janek Janka Jaś Jasia Jasio",
    "Tomasz": "Tomek Tomka Tomuś Tomusia",
    "Bartosz": "Bartek Bartka Bartuś Bartusia",
    "Franciszek": "Franek Franka Franio Frania",
    "Aleksander": "Olek Olka Alek Alka",
    "Jakub": "Kuba Kuby",
    "Krzysztof": "Krzyś Krzysia Krzysiek Krzyśka",
    "Mateusz": "Mateuszek Mateuszka",
    "Michał": "Michałek Michałka",
    "Piotr": "Piotrek Piotrka Piotruś Piotrusia",
    "Paweł": "Pawełek Pawełka",
    "Wojciech": "Wojtek Wojtka",
    "Stanisław": "Staszek Staszka Stasiek Staśka",
    "Józef": "Józek Józka",
    "Andrzej": "Jędrek Jędrka",
}


def _klucz_zdrobnienia(slowo: str) -> str:
    return rdzen(slowo).replace("ś", "s")


@lru_cache(maxsize=1)
def _pelne_imiona() -> dict[str, str]:
    return {
        _klucz_zdrobnienia(zdrobnienie): rdzen(imie)
        for imie, zdrobnienia in _ZDROBNIENIA.items()
        for zdrobnienie in zdrobnienia.split()
    }


def rdzen_imienia(slowo: str) -> str:
    """Stem of a first name with common diminutives mapped to the full name ("Kasi" -> "katarzyn")."""
    return _pelne_imiona().get(_klucz_zdrobnienia(slowo), rdzen(slowo))


def jest_zdrobnieniem(slowo: str) -> bool:
    return _klucz_zdrobnienia(slowo) in _pelne_imiona()


def jest_imieniem(slowo: str) -> bool:
    """Whether the word is a form of a first name from the bundled list."""
    return rdzen(slowo) in _rdzenie_imion()


@lru_cache(maxsize=1)
def _rdzenie_imion() -> frozenset[str]:
    return frozenset(rdzen(imie) for imie in imiona())
