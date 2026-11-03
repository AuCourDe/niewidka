import json
from pathlib import Path

import pytest

from niewidka.odmiana import jest_imieniem, rdzen, temat

PARY = json.loads((Path(__file__).parent / "korpus" / "pary_odmiany.json").read_text(encoding="utf-8"))

# known ceiling of the rule stemmer (documented in odmiana.py)
ZNANE_ROZBIEZNOSCI = {
    ("Koźle", "Kozioł"),  # ź/z alternation before -e is not undone
}
ZNANE_ZLEPIENIA = {
    ("Stanisław", "Stanisławów"),  # place name equal to a plural surname form
    ("Kozioł", "Kozłów"),
}


@pytest.mark.parametrize(("a", "b"), [tuple(p) for p in PARY["pozytywne"]])
def test_formy_jednego_nazwiska_maja_wspolny_rdzen(a, b):
    if (a, b) in ZNANE_ROZBIEZNOSCI:
        pytest.xfail("known stemmer ceiling")
    assert rdzen(a) == rdzen(b)


@pytest.mark.parametrize(("a", "b"), [tuple(p) for p in PARY["negatywne"]])
def test_rozne_slowa_maja_rozne_rdzenie(a, b):
    if (a, b) in ZNANE_ZLEPIENIA:
        pytest.xfail("known stemmer ceiling")
    assert rdzen(a) != rdzen(b)


@pytest.mark.parametrize("imie", ["Andrzej", "Maciej", "Maksym", "Hieronim"])
def test_imie_z_koncowka_przypadka_zostaje_cale(imie):
    assert temat(imie) == imie
    assert jest_imieniem(imie)


def test_nazwisko_dwuczlonowe_odmieniane_czlonami():
    assert rdzen("Nowak-Jeziorańska") == rdzen("Nowak-Jeziorańskiej")


def test_temat_zachowuje_litery_oryginalu():
    assert temat("Kowalskiej") == "Kowalsk"
