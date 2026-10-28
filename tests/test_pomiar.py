"""Testy narzędzia pomiaru recall/precision (K0, KRYTERIA.md §1)."""

from pathlib import Path

from narzedzia.pomiar import (
    DetektorPusty,
    Oczekiwana,
    Probka,
    WynikTypu,
    precision,
    recall,
    wczytaj_probki,
    zmierz,
)
from niewidka.model import TypEncji, Zakres

PROBKA_PESEL = Probka(
    id="x",
    opis="o",
    tekst="PESEL 44051401359.",
    encje=[Oczekiwana(typ="PESEL", start=6, koniec=17, tekst="44051401359", suma=True)],
)

# Pułapka: numer z błędną sumą kontrolną, bez oczekiwanej encji (KRYTERIA §5).
PROBKA_PULAPKA = Probka(id="y", opis="pułapka", tekst="PESEL 44051401358.", encje=[])


class DetektorStałozakresowy:
    def __init__(self, zakresy):
        self.zakresy = zakresy

    def znajdz(self, tekst):
        return self.zakresy


def test_detektor_pusty_daje_zero_trafién():
    wyniki = zmierz([PROBKA_PESEL], DetektorPusty())
    assert wyniki["PESEL"] == WynikTypu(tp=0, fp=0, fn=1)
    assert recall(wyniki["PESEL"]) == 0.0
    assert precision(wyniki["PESEL"]) is None  # zero trafficień = brak licznika


def test_dokładne_dopasowanie_to_tp():
    detektor = DetektorStałozakresowy([Zakres(6, 17, TypEncji.PESEL, 1.0, "regula", True)])
    wyniki = zmierz([PROBKA_PESEL], detektor)
    assert wyniki["PESEL"] == WynikTypu(tp=1, fp=0, fn=0)


def test_pokrycie_częściowe_to_fn_i_fp():
    detektor = DetektorStałozakresowy([Zakres(6, 15, TypEncji.PESEL, 1.0, "regula", True)])
    wyniki = zmierz([PROBKA_PESEL], detektor)
    assert wyniki["PESEL"] == WynikTypu(tp=0, fp=1, fn=1)


def test_detekcja_złego_typu_to_fp_oraz_fn():
    detektor = DetektorStałozakresowy([Zakres(6, 17, TypEncji.NIP, 1.0, "regula", True)])
    wyniki = zmierz([PROBKA_PESEL], detektor)
    assert wyniki["PESEL"] == WynikTypu(tp=0, fp=0, fn=1)
    assert wyniki["NIP"] == WynikTypu(tp=0, fp=1, fn=0)


def test_detekcja_podejrzana_nie_jest_fp():
    # KRYTERIA §1.3: podejrzane nadmaskowanie (PN) liczone osobno, nie jako FP.
    detektor = DetektorStałozakresowy([Zakres(6, 17, TypEncji.PESEL, 0.5, "regula", False, True)])
    wyniki = zmierz([PROBKA_PULAPKA], detektor)
    assert wyniki["PESEL"] == WynikTypu(tp=0, fp=0, fn=0, pn=1)
    assert precision(wyniki["PESEL"]) is None  # PN nie zaniża precision


def test_wczytywanie_jsonl(tmp_path: Path):
    plik = tmp_path / "probki.jsonl"
    plik.write_text(
        '{"id":"a","opis":"o","tekst":"PESEL 44051401359.","encje":'
        '[{"typ":"PESEL","start":6,"koniec":17,"tekst":"44051401359","suma":true}]}\n',
        encoding="utf-8",
    )
    probki = wczytaj_probki(tmp_path)
    assert len(probki) == 1
    assert probki[0].encje[0].typ == "PESEL"
    assert probki[0].encje[0].suma is True


# --- K2: budowa detektorów + czas na próbkę ---

import pytest

from narzedzia.pomiar import zbuduj_detektor, zmierz_z_czasem


def test_zbuduj_detektor_reguly():
    assert zbuduj_detektor("reguly", None).nazwa == "reguly"


def test_zbuduj_detektor_nieznany_pad():
    with pytest.raises(SystemExit):
        zbuduj_detektor("czarodziej", None)


def test_zbuduj_detektor_poziom1_bez_katalogu_blad():
    with pytest.raises(Exception, match="NIEWIDKA_MODELE_KATALOG"):
        zbuduj_detektor("poziom1", None)


@pytest.mark.model
def test_zbuduj_detektor_poziom1(katalog_modeli):
    d = zbuduj_detektor("poziom1", katalog_modeli)
    assert d.nazwa == "poziom1"
    assert TypEncji.OSOBA in d.typy  # model
    assert TypEncji.PESEL in d.typy  # reguły


def test_zmierz_z_czasem_zwraca_czasy():
    wyniki, czasy = zmierz_z_czasem([PROBKA_PESEL, PROBKA_PULAPKA], DetektorPusty())
    assert len(czasy) == 2
    assert all(c >= 0 for c in czasy)
    assert wyniki["PESEL"].fn == 1


# --- K2b: poziom 2 (reguły + bardsai + LFM2.5) ---

def test_zbuduj_detektor_poziom2_bez_katalogu_blad():
    with pytest.raises(Exception, match="NIEWIDKA_MODELE_KATALOG"):
        zbuduj_detektor("poziom2", None)


@pytest.mark.model
def test_zbuduj_detektor_poziom2(wagi_lfm25):
    d = zbuduj_detektor("poziom2", wagi_lfm25)
    assert d.nazwa == "poziom2"
    assert [c.nazwa for c in d.czesci] == ["reguly", "onnx:bardsai", "onnx:lfm25"]


@pytest.mark.model
def test_zbuduj_detektor_lfm25_wariant_fp32(wagi_lfm25):
    d = zbuduj_detektor("lfm25", wagi_lfm25, wariant="fp32")
    assert d.nazwa == "onnx:lfm25"


# --- K2d: warianty A (próg + półkrok) i B (+ słownik imion) ---

def test_zbuduj_detektor_poziom2_a_bez_katalogu_blad():
    with pytest.raises(Exception, match="NIEWIDKA_MODELE_KATALOG"):
        zbuduj_detektor("poziom2-a", None)


def test_zbuduj_detektor_poziom2_b_bez_katalogu_blad():
    with pytest.raises(Exception, match="NIEWIDKA_MODELE_KATALOG"):
        zbuduj_detektor("poziom2-b", None)


@pytest.mark.model
def test_zbuduj_detektor_poziom2_a(katalog_modeli):
    d = zbuduj_detektor("poziom2-a", katalog_modeli)
    assert d.nazwa == "poziom2-a"
    assert [c.nazwa for c in d.czesci] == ["reguly", "onnx:bardsai"]


@pytest.mark.model
def test_zbuduj_detektor_poziom2_b(katalog_modeli):
    d = zbuduj_detektor("poziom2-b", katalog_modeli)
    assert d.nazwa == "poziom2-b"
    assert [c.nazwa for c in d.podstawa] == ["reguly", "onnx:bardsai"]
    assert d.uzup.nazwa == "slownik-imion"
