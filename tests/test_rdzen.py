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
from niewidka.znaczniki import DOPISEK

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
    assert wynik.startswith(DOPISEK.encode())
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
    assert "ZANONIMIZOWANY" not in teksty  # dopisek znika po przywróceniu
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


def test_kontrola_oryginal_z_mapy_w_czesci_nieczytanej_blokuje(tmp_path):
    """K3b: PESEL schowany w części, której adapter nie parsuje i nie czyści
    (media), omija wykrywanie i zamianę — kontrola z oryginałami mapy go zgłasza.
    (Pierwotna pułapka w settings.xml przestała wyciekać po naprawie Gemini pkt 8.)"""
    import io
    import zipfile

    wzorzec = zapisz_podstawowy(tmp_path / "w.docx").read_bytes()
    zrodlo = zipfile.ZipFile(io.BytesIO(wzorzec))
    czesci = {n: zrodlo.read(n) for n in zrodlo.namelist()}
    zrodlo.close()
    czesci["word/media/skrytka.png"] = b"\x00\x01 PESEL 44051401359 \xff"
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
        for nazwa, zawartosc in czesci.items():
            paczka.writestr(nazwa, zawartosc)

    # polityka "zostaw": od K4b pkt 2 domyślnie obrazy są usuwane (wyciek znikałby
    # zanim kontrola zdąży go zgłosić); testujemy tu SKAN SUROWY części nie-XML,
    # więc obraz świadomie zostaje w wyniku
    _wynik, mapa, raport = ukryj(
        bufor.getvalue(), "docx", 1, detektor=RegulyDetektor(), polityka_obrazow="zostaw"
    )

    oryginaly = [w.oryginal for w in mapa.wystapienia]
    assert "44051401359" in oryginaly
    # K4b pkt 5: część ma neutralną nazwę (skrytka.png → obrazN.png), a kontrola
    # i tak zgłasza ORYGINAL w części media
    assert any(
        o.typ == "ORYGINAL" and o.fragment == "44051401359" and o.czesc.startswith("word/media/")
        for o in raport.ostrzezenia
    )
    assert raport.status == "zablokowany"


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


@pytest.mark.model
def test_zbuduj_detektor_poziomy_2_i_3_roznia_sie_od_1(katalog_modeli):
    """Suwak: 1 = bez progu i półkroku; 2 = wariant A (próg OSOBA + półkrok); 3 = B (+słownik)."""
    from niewidka.detektory import DetektorUzupełniający

    konfig = Konfig(modele_katalog=katalog_modeli)
    d1, d2, d3 = (zbuduj_detektor(poziom, konfig) for poziom in (1, 2, 3))
    assert (d1.nazwa, d2.nazwa, d3.nazwa) == ("poziom1", "poziom2", "poziom3")
    assert d1.czesci[1]._próg is None and not d1.czesci[1]._pół_krok  # poziom 1 jak dotychczas
    assert d2.czesci[1]._próg == 0.2 and d2.czesci[1]._pół_krok  # wariant A
    assert isinstance(d3, DetektorUzupełniający) and d3.uzup.nazwa == "slownik-imion"  # B
    assert d3.podstawa[1]._próg == 0.2


@pytest.mark.model
def test_poziom2_lapie_co_poziom1_przeoczy(katalog_modeli):
    """WYNIK-K2d, próbka osoba-011: poziom 1 zostawia „Piotrowi", poziom 2 łapie całą osobę."""
    konfig = Konfig(modele_katalog=katalog_modeli)
    tekst = "Przekazano akt do Piotrowi Wiśniewskiemu."
    d1, d2 = zbuduj_detektor(1, konfig), zbuduj_detektor(2, konfig)
    trafienia = {
        poziom: {(z.start, z.koniec) for z in d.znajdz(tekst) if z.typ is TypEncji.OSOBA}
        for poziom, d in ((1, d1), (2, d2))
    }
    assert trafienia[1] == {(18, 26)}  # sam „Piotrowi"
    assert trafienia[2] == {(18, 40)}  # pełne „Piotrowi Wiśniewskiemu"


def test_filtr_bez_daty():
    detektor = _BezDaty(RegulyDetektor())
    znaleziska = detektor.znajdz("PESEL 44051401359 z dnia 13.05.1982")
    assert {z.typ for z in znaleziska} == {TypEncji.PESEL}


def test_zbuduj_detektor_przekazuje_stan_pakietu_rozszerzonego(monkeypatch, tmp_path):
    """K7c pkt 1: rdzeń przekazuje zweryfikowany stan pakietu Rozszerzonego do
    budowy poziomu (bez tego zainstalowany LFM2.5 nigdy nie uczestniczy w detekcji)."""
    from niewidka import rdzen

    otrzymane: dict = {}

    def atrapa_poziom(poziom, katalog, **kwargs):
        otrzymane.update(kwargs, poziom=poziom)
        return RegulyDetektor()

    monkeypatch.setattr(rdzen, "zbuduj_poziom", atrapa_poziom)
    rdzen.zbuduj_detektor(3, Konfig(modele_katalog=tmp_path), pakiet_rozszerzony=True)
    assert otrzymane["pakiet_rozszerzony"] is True
    rdzen.zbuduj_detektor(3, Konfig(modele_katalog=tmp_path))
    assert otrzymane["pakiet_rozszerzony"] is False
