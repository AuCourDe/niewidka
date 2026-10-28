"""Testy rdzenia ukryj/przywroc (K4): jedna para funkcji dla API i desktopu.

Detektor wstrzykiwany przez zależność — testy bez wag używają reguł albo atrapy.
"""

from __future__ import annotations

import pytest

from narzedzia.generator_dokumentow import zapisz_podstawowy, zapisz_z_makrem
from niewidka.detektory import BladDetektora, RegulyDetektor
from niewidka.formaty import ElementNieobslugiwany, NieznanyFormat, adapter_formatu
from niewidka.konfig import Konfig
from niewidka.mapa import odszyfruj, zaszyfruj
from niewidka.model import TypEncji, Zakres
from niewidka.rdzen import (
    ArchiwumZaDuze,
    Raport,
    _BezDaty,
    przywroc,
    ukryj,
    zbuduj_detektor,
)

TEKST = b"Jan Kowalski, PESEL 44051401359. Telefon +48 601 234 567, e-mail jan@example.com."
KLUCZ = bytes(range(32))


class DetektorOsob:
    """Atrapa OSOBA: znajduje tylko wskazane frazy (bez wag modelu)."""

    nazwa = "atrapa-osoby"
    typy = frozenset({TypEncji.OSOBA})

    def __init__(self, frazy: tuple[str, ...]):
        self.frazy = frazy

    def znajdz(self, tekst: str) -> list[Zakres]:
        wynik = []
        for fraza in self.frazy:
            start = tekst.find(fraza)
            while start != -1:
                wynik.append(Zakres(start, start + len(fraza), TypEncji.OSOBA, 0.99, self.nazwa))
                start = tekst.find(fraza, start + len(fraza))
        return wynik


def test_ukryj_txt_zwraca_wynik_mape_i_raport():
    wynik, mapa, raport = ukryj(TEKST, "txt", 1, detektor=RegulyDetektor())
    assert b"[PESEL_1]" in wynik
    assert b"44051401359" not in wynik
    assert wynik.startswith(b"ZANONIMIZOWANO w Niewidka")
    assert [w.typ for w in mapa.wpisy] == ["PESEL", "TELEFON", "EMAIL"]
    assert raport.identyfikator == mapa.identyfikator
    assert raport.poziom == 1
    assert raport.statystyki == {"PESEL": 1, "TELEFON": 1, "EMAIL": 1}
    assert raport.status == "ukonczony"
    assert isinstance(raport.r95.get("PESEL"), float)
    assert isinstance(raport, Raport)


def test_ukryj_txt_osoby_warianty_form():
    tekst = "Jan Kowalski wniósł. Sprawa Jana Kowalskiego wraca. Jan Kowalski wygrał.".encode()
    detektor = DetektorOsob(("Jan Kowalski", "Jana Kowalskiego"))
    wynik, mapa, raport = ukryj(tekst, "txt", 1, detektor=detektor)
    assert b"[OSOBA_1_F1]" in wynik
    assert b"[OSOBA_1_F2]" in wynik
    assert b"Jan Kowalski" not in wynik
    wpis = next(w for w in mapa.wpisy if w.oznaczenie == "OSOBA_1")
    assert wpis.formy == {"F1": "Jan Kowalski", "F2": "Jana Kowalskiego"}
    assert raport.statystyki == {"OSOBA": 3}


def test_ukryj_docx_roundtrip(tmp_path):
    dane = zapisz_podstawowy(tmp_path / "wzorzec.docx").read_bytes()
    wynik, mapa, raport = ukryj(dane, "docx", 1, detektor=RegulyDetektor())
    # 2 × PESEL: poprawny + pułapka z błędną sumą (podejrzana też wchodzi do maskowania)
    assert raport.statystyki["PESEL"] == 2
    przywrocony, rozbieznosci = przywroc(wynik, "docx", mapa)
    assert rozbieznosci == []
    teksty = "\n".join(s.tekst for s in adapter_formatu("docx").wczytaj(przywrocony).segmenty)
    assert "44051401359" in teksty
    assert "601 234 567" in teksty
    assert "12345678901" in teksty  # pułapka wraca w swoje miejsce
    assert "ZANONIMIZOWANO" not in teksty  # dopisek znika po przywróceniu
    assert "[PESEL_1]" not in teksty


def test_przywroc_txt_odtwarza_i_zdejmuje_dopisek():
    wynik, mapa, _ = ukryj(TEKST, "txt", 1, detektor=RegulyDetektor())
    przywrocony, rozbieznosci = przywroc(wynik, "txt", mapa)
    assert przywrocony == TEKST
    assert rozbieznosci == []


def test_przywroc_txt_po_przestawieniu_zdan():
    wynik, mapa, _ = ukryj(
        "Jan Kowalski wniósł. Sprawa Jana Kowalskiego wraca.".encode(), "txt", 1,
        detektor=DetektorOsob(("Jan Kowalski", "Jana Kowalskiego")),
    )
    assert b"[OSOBA_1_F1]" in wynik and b"[OSOBA_1_F2]" in wynik
    dopisek, tresc = wynik.decode().split("\n", 1)  # dopisek zostaje na miejscu
    zdania = tresc.strip().split(". ")
    przestawione = f"{dopisek}\n{zdania[1]} {zdania[0]}.\n".encode()
    przywrocony, rozbieznosci = przywroc(przestawione, "txt", mapa)
    assert rozbieznosci == []
    assert "Sprawa Jana Kowalskiego wraca. Jan Kowalski wniósł.".encode() in przywrocony


def test_przywroc_mapa_zaszyfrowana():
    """Przywrócenie przyjmuje mapę zaszyfrowaną — jak z API."""
    wynik, mapa, _ = ukryj(TEKST, "txt", 1, detektor=RegulyDetektor())
    mapa_z = odszyfruj(zaszyfruj(mapa, KLUCZ), KLUCZ)
    przywrocony, rozbieznosci = przywroc(wynik, "txt", mapa_z)
    assert przywrocony == TEKST and rozbieznosci == []


def test_przywroc_znacznik_bez_wpisu_i_wpis_niewykorzystany():
    wynik, mapa, _ = ukryj(TEKST, "txt", 1, detektor=RegulyDetektor())
    okrojony = wynik.replace(b"[PESEL_1]", b"[OSOBA_9_F1]")  # marker obcy zamiast znanego
    _, rozbieznosci = przywroc(okrojony, "txt", mapa)
    typy = {(r.typ, r.opis) for r in rozbieznosci}
    assert ("znacznik_bez_wpisu", "[OSOBA_9_F1]") in typy
    assert ("wpis_niewykorzystany", "PESEL_1") in typy


def test_ukryj_nieznany_format():
    with pytest.raises(NieznanyFormat) as blad:
        ukryj(TEKST, "pdf", 1, detektor=RegulyDetektor())
    assert "txt" in ", ".join(blad.value.wspierane)


def test_przywroc_nieznany_format():
    wynik, mapa, _ = ukryj(TEKST, "txt", 1, detektor=RegulyDetektor())
    with pytest.raises(NieznanyFormat):
        przywroc(wynik, "pptx", mapa)


def test_ukryj_docx_makro_blokuje(tmp_path):
    dane = zapisz_z_makrem(tmp_path / "makro.docx").read_bytes()
    with pytest.raises(ElementNieobslugiwany, match="vbaProject"):
        ukryj(dane, "docx", 1, detektor=RegulyDetektor())


def test_ukryj_zip_bomb_limit_rozpakowanych(tmp_path):
    dane = zapisz_podstawowy(tmp_path / "w.docx").read_bytes()
    with pytest.raises(ArchiwumZaDuze):
        ukryj(dane, "docx", 1, detektor=RegulyDetektor(), max_rozpakowane_bajtow=10)


def test_przywroc_zip_bomb_limit(tmp_path):
    docx_wynik, mapa, _ = ukryj(
        zapisz_podstawowy(tmp_path / "w.docx").read_bytes(), "docx", 1, detektor=RegulyDetektor()
    )
    with pytest.raises(ArchiwumZaDuze):
        przywroc(docx_wynik, "docx", mapa, max_rozpakowane_bajtow=10)


def test_kontrola_nowe_znajdziska_blokuja_status():
    class DetektorZawsze:
        nazwa = "atrapa-zawsze"
        typy = frozenset({TypEncji.INNE})

        def znajdz(self, tekst: str) -> list[Zakres]:
            return [Zakres(0, min(4, len(tekst)), TypEncji.INNE, 0.9, self.nazwa)] if tekst else []

    _, _, raport = ukryj(TEKST, "txt", 1, detektor=DetektorZawsze(), kontrola_blokada=True)
    assert raport.ostrzezenia
    assert raport.status == "zablokowany"
    _, _, raport2 = ukryj(TEKST, "txt", 1, detektor=DetektorZawsze(), kontrola_blokada=False)
    assert raport2.ostrzezenia and raport2.status == "ukonczony"


def test_ukryj_bez_detektora_i_konfiguracji_blad():
    with pytest.raises(ValueError):
        ukryj(TEKST, "txt", 1)


def test_ukryj_bez_wag_fail_closed():
    konfig = Konfig(modele_katalog=None)
    with pytest.raises(BladDetektora):
        ukryj(TEKST, "txt", 1, konfig=konfig)


@pytest.mark.model
def test_zbuduj_detektor_poziom1_z_wagami(katalog_modeli):
    konfig = Konfig(modele_katalog=katalog_modeli)
    detektor = zbuduj_detektor(1, konfig)
    assert {c.nazwa for c in detektor.czesci} == {"reguly", "onnx:bardsai"}


def test_filtr_bez_daty():
    detektor = _BezDaty(RegulyDetektor())
    znaleziska = detektor.znajdz("PESEL 44051401359 z dnia 13.05.1982")
    assert {z.typ for z in znaleziska} == {TypEncji.PESEL}
