"""Testy znaczników [TYP_N]."""

import pytest

from niewidka.formaty import adapter_formatu
from niewidka.model import Encja, TypEncji, Zakres
from niewidka.rdzen import zloz_wynik
from niewidka.znaczniki import DOPISEK, nadaj_oznaczenia, znacznik_encji


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
    # Stabilny wariant formy: każdy kształt powierzchniowy
    # osoby ma swój numer Fk; pozostale typy bez wariantu.
    assert encje[1].wariant == "F1"
    assert encje[2].wariant == "F2"
    assert encje[0].wariant is None and encje[3].wariant is None


def test_ta_sama_wartosc_ten_sam_znacznik():
    """Powtórzony PESEL albo telefon to jedna wartość: jeden znacznik, inaczej chmurowe AI
    widzi trzy różne numery (PESEL_1, PESEL_2, PESEL_3)."""
    encje = [
        _encja(TypEncji.PESEL, "44051401359", 0),
        _encja(TypEncji.TELEFON, "600 100 200", 20),
        _encja(TypEncji.PESEL, "44051401359", 40),
        _encja(TypEncji.TELEFON, "600  100 200", 60),
        _encja(TypEncji.PESEL, "55010101234", 80),
    ]
    nadaj_oznaczenia(encje)
    assert [e.oznaczenie for e in encje] == ["PESEL_1", "TELEFON_1", "PESEL_1", "TELEFON_1", "PESEL_2"]


def test_ta_sama_forma_dzieli_wariant():
    encje = [
        _encja(TypEncji.OSOBA, "Jan Kowalski", 0, klucz="jan|kowalsk"),
        _encja(TypEncji.OSOBA, "Jana Kowalskiego", 20, klucz="jan|kowalsk"),
        _encja(TypEncji.OSOBA, "Jana Kowalskiego", 50, klucz="jan|kowalsk"),
    ]
    nadaj_oznaczenia(encje)
    assert encje[1].wariant == encje[2].wariant == "F2"


def test_osoby_bez_klucza_to_osobne_grupy():
    encje = [_encja(TypEncji.OSOBA, "X Y", 0), _encja(TypEncji.OSOBA, "Z W", 10)]
    nadaj_oznaczenia(encje)
    assert [e.oznaczenie for e in encje] == ["OSOBA_1", "OSOBA_2"]
    assert encje[0].wariant == encje[1].wariant == "F1"


def _zloz(tekst: str, encje: list[Encja]):
    adapter = adapter_formatu("txt")
    dok = adapter.wczytaj(tekst.encode("utf-8"))
    wynik, mapa, _, _ = zloz_wynik(adapter, dok, [encje], 1)
    return wynik.decode("utf-8"), mapa


def test_zamiana_w_segmencie():
    tekst = "Jan Kowalski, PESEL 44051401359."
    encje = [
        _encja(TypEncji.OSOBA, "Jan Kowalski", 0, klucz="jan|kowalsk"),
        _encja(TypEncji.PESEL, "44051401359", 20),
    ]
    nadaj_oznaczenia(encje)
    nowy, mapa = _zloz(tekst, encje)
    assert "[OSOBA_1_F1], PESEL [PESEL_1]." in nowy
    assert [w.kolejny for w in mapa.wystapienia] == [0, 1]


def test_kolejny_ciagiem_dla_kolejnych_wystapien():
    tekst = "PESEL 44051401359 oraz PESEL 55010101234."
    encje = [
        _encja(TypEncji.PESEL, "44051401359", 6),
        _encja(TypEncji.PESEL, "55010101234", 29),
    ]
    nadaj_oznaczenia(encje)
    nowy, mapa = _zloz(tekst, encje)
    assert "PESEL [PESEL_1] oraz PESEL [PESEL_2]." in nowy
    assert [w.kolejny for w in mapa.wystapienia] == [0, 1]


def test_bez_oznaczen_jawny_blad():
    encja = _encja(TypEncji.PESEL, "44051401359", 0)
    with pytest.raises(ValueError):
        znacznik_encji(encja)


def test_dopisek_bez_nawiasow_kwadratowych():
    # literał [TYP_N] w dopisku zostałby złapany przez kontrolę wyniku.
    assert "[" not in DOPISEK and "]" not in DOPISEK
