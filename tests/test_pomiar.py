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
    detektor = DetektorStałozakresowy(
        [Zakres(6, 17, TypEncji.PESEL, 0.5, "regula", False, True)]
    )
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
