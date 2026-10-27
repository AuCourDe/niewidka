"""Testy reguł detekcji (LLD §3): wyrażenia regularne + sumy kontrolne."""

from niewidka.model import TypEncji
from niewidka.reguly import znajdz


def _zakresy(tekst: str):
    return [(z.start, z.koniec, z.typ) for z in znajdz(tekst)]


# --- cykl A: PESEL ----------------------------------------------------------

def test_pesel_poprawny_znaleziony():
    tekst = "PESEL: 44051401359, wniosek."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.PESEL]
    assert [(z.start, z.koniec) for z in wynik] == [(7, 18)]
    assert wynik[0].pewnosc == 1.0
    assert wynik[0].suma_kontrolna is True
    assert wynik[0].zrodlo == "regula"


def test_pesel_bledna_suma_nie_znaleziony():
    assert _zakresy("PESEL: 44051401358, wniosek.") == []


def test_pesel_w_dluzszej_liczbie_nie_znaleziony():
    assert _zakresy("Id transakcji 1234405140135977 end.") == []
