"""Testy znaczników [TYP_N] (LLD §7, przegląd Gemini pkt 7)."""

import pytest

from niewidka.model import Encja, TypEncji, Zakres
from niewidka.znaczniki import DOPISEK, nadaj_oznaczenia, zamien_w_segment


def _encja(typ: TypEncji, tekst: str, start: int, klucz: str | None = None) -> Encja:
    return Encja(
        zakres=Zakres(start, start + len(tekst), typ, 0.9, "regula"),
        tekst=tekst,
        klucz_grupy=klucz,
    )


def test_numeracja_per_typ_a_osoby_wspolnie():
    encje = [
        _encja(TypEncji.PESEL, "44051401359", 0),
        _encja(TypEncji.OSOBA, "Jan Kowalski", 12, klucz="jan|kowalsk"),
        _encja(TypEncji.OSOBA, "Jana Kowalskiego", 30, klucz="jan|kowalsk"),
        _encja(TypEncji.PESEL, "44051401358", 60),
    ]
    nadaj_oznaczenia(encje)
    assert [e.oznaczenie for e in encje] == ["PESEL_1", "OSOBA_1", "OSOBA_1", "PESEL_2"]


def test_osoby_bez_klucza_to_osobne_grupy():
    encje = [_encja(TypEncji.OSOBA, "X Y", 0), _encja(TypEncji.OSOBA, "Z W", 10)]
    nadaj_oznaczenia(encje)
    assert [e.oznaczenie for e in encje] == ["OSOBA_1", "OSOBA_2"]


def test_zamiana_w_segmencie():
    tekst = "Jan Kowalski, PESEL 44051401359."
    encje = [
        _encja(TypEncji.OSOBA, "Jan Kowalski", 0, klucz="jan|kowalsk"),
        _encja(TypEncji.PESEL, "44051401359", 16),
    ]
    nadaj_oznaczenia(encje)
    nowy, kolejne = zamien_w_segment(tekst, encje)
    assert nowy == "[OSOBA_1], PESEL [PESEL_1]."
    assert kolejne == [0, 1]


def test_poczatek_kolejnego_ciągiem_miedzy_segmentami():
    tekst = "PESEL 44051401359 oraz PESEL 55010101234."
    encje = [
        _encja(TypEncji.PESEL, "44051401359", 6),
        _encja(TypEncji.PESEL, "55010101234", 27),
    ]
    nadaj_oznaczenia(encje)
    nowy, kolejne = zamien_w_segment(tekst, encje, poczatek_kolejnego=5)
    assert nowy == "PESEL [PESEL_1] oraz PESEL [PESEL_2]."
    assert kolejne == [5, 6]


def test_bez_oznaczen_jawny_blad():
    encja = _encja(TypEncji.PESEL, "44051401359", 0)
    with pytest.raises(ValueError):
        zamien_w_segment("PESEL 44051401359.", [encja])


def test_dopisek_bez_nawiasow_kwadratowych():
    # Gemini #7: literał [TYP_N] w dopisku zostałby złapany przez kontrolę wyniku.
    assert "[" not in DOPISEK and "]" not in DOPISEK
