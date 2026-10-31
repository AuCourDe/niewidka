"""Tests of the ukryj/przywroc core: one pair of functions for API and desktop.

The detector is injected through a dependency: tests without weights use rules or a stub.
"""

from __future__ import annotations

import pytest

from narzedzia.generator_dokumentow import zapisz_podstawowy, zapisz_z_makrem
from niewidka.detektory import BladDetektora, RegulyDetektor
from niewidka.formaty import ElementNieobslugiwany, NieznanyFormat, adapter_formatu
from niewidka.konfig import Konfig
from niewidka.mapa import BladMapy, odszyfruj, zaszyfruj
from niewidka.model import TypEncji, Zakres
from niewidka.rdzen import (
    ArchiwumZaDuze,
    Raport,
    _BezDaty,
    przywroc,
    ukryj,
    zbuduj_detektor,
)
from niewidka.znaczniki import DOPISEK, zakoduj_identyfikator

TEKST = b"Jan Kowalski, PESEL 44051401359. Telefon +48 601 234 567, e-mail jan@example.com."
KLUCZ = bytes(range(32))


class DetektorOsob:
    """OSOBA stub: finds only the given phrases (no model weights)."""

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
    # 2 x PESEL: valid + a trap with a wrong checksum (a suspect one is masked too)
    assert raport.statystyki["PESEL"] == 2
    przywrocony, rozbieznosci = przywroc(wynik, "docx", mapa)
    assert rozbieznosci == []
    teksty = "\n".join(s.tekst for s in adapter_formatu("docx").wczytaj(przywrocony).segmenty)
    assert "44051401359" in teksty
    assert "601 234 567" in teksty
    assert "12345678901" in teksty  # the trap returns to its place
    assert "ZANONIMIZOWANY" not in teksty  # the note disappears after restoring
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
    dopisek, tresc = wynik.decode().split("\n", 1)  # the note stays in place
    zdania = tresc.strip().split(". ")
    przestawione = f"{dopisek}\n{zdania[1]} {zdania[0]}.\n".encode()
    przywrocony, rozbieznosci = przywroc(przestawione, "txt", mapa)
    assert rozbieznosci == []
    assert "Sprawa Jana Kowalskiego wraca. Jan Kowalski wniósł.".encode() in przywrocony


def test_przywroc_mapa_zaszyfrowana():
    """Restore accepts an encrypted map, as from the API."""
    wynik, mapa, _ = ukryj(TEKST, "txt", 1, detektor=RegulyDetektor())
    mapa_z = odszyfruj(zaszyfruj(mapa, KLUCZ), KLUCZ)
    przywrocony, rozbieznosci = przywroc(wynik, "txt", mapa_z)
    assert przywrocony == TEKST and rozbieznosci == []


def test_przywroc_znacznik_bez_wpisu_i_wpis_niewykorzystany():
    wynik, mapa, _ = ukryj(TEKST, "txt", 1, detektor=RegulyDetektor())
    okrojony = wynik.replace(b"[PESEL_1]", b"[OSOBA_9_F1]")  # a foreign marker instead of a known one
    _, rozbieznosci = przywroc(okrojony, "txt", mapa)
    typy = {(r.typ, r.opis) for r in rozbieznosci}
    assert ("znacznik_bez_wpisu", "[OSOBA_9_F1]") in typy
    assert ("wpis_niewykorzystany", "PESEL_1") in typy


def test_przywroc_odpowiedz_ai_bez_dopisku_z_ostrzezeniem():
    # an AI chat reply usually does not repeat the note with the map identifier
    wynik, mapa, _ = ukryj(TEKST, "txt", 1, detektor=RegulyDetektor())
    _, tresc = wynik.decode().split("\n", 1)
    odpowiedz_ai = f"Oto odpowiedź na pismo. Numer {tresc.strip()}".encode()
    przywrocony, rozbieznosci = przywroc(odpowiedz_ai, "txt", mapa)
    assert b"44051401359" in przywrocony
    assert [r.typ for r in rozbieznosci] == ["brak_identyfikatora"]


def test_przywroc_odrzuca_dopisek_innej_mapy():
    _, mapa, _ = ukryj(TEKST, "txt", 1, detektor=RegulyDetektor())
    wynik_innego, _, _ = ukryj(TEKST, "txt", 1, detektor=RegulyDetektor())
    with pytest.raises(BladMapy):
        przywroc(wynik_innego, "txt", mapa)


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


class DetektorZaleznyOdKontekstu:
    """Like bardsai: 'Anna Kwiatkowska' is visible
        only once 'Jan Nowak' is already masked (different context/model window)."""

    nazwa = "atrapa-kontekst"
    typy = frozenset({TypEncji.OSOBA})

    def znajdz(self, tekst: str) -> list[Zakres]:
        frazy = ("Jan Nowak",) if "Jan Nowak" in tekst else ("Anna Kwiatkowska",)
        return DetektorOsob(frazy).znajdz(tekst)


def test_kontrola_ukrywa_to_co_znalazla_zamiast_blokowac_caly_wynik():
    tekst = "Pismo podpisał Jan Nowak. Informacji udziela Anna Kwiatkowska.".encode()
    wynik, mapa, raport = ukryj(tekst, "txt", 1, detektor=DetektorZaleznyOdKontekstu())
    assert raport.status == "ukonczony", raport.ostrzezenia
    assert b"Jan Nowak" not in wynik and b"Anna Kwiatkowska" not in wynik
    assert raport.statystyki == {"OSOBA": 2}
    assert {w.formy[next(iter(w.formy))] for w in mapa.wpisy} == {"Jan Nowak", "Anna Kwiatkowska"}
    przywrocony, rozbieznosci = przywroc(wynik, "txt", mapa)
    assert przywrocony == tekst and not rozbieznosci


def test_kontrola_osoba_obejmuje_nazwisko_za_imionami():
    """The check reports 'Jan Marek', while the surname 'Nowicki' would stay visible."""

    class TylkoImiona(DetektorZaleznyOdKontekstu):
        def znajdz(self, tekst: str) -> list[Zakres]:
            if "Jan Nowak" in tekst:
                return DetektorOsob(("Jan Nowak",)).znajdz(tekst)
            return DetektorOsob(("Jan Marek",)).znajdz(tekst)

    tekst = "Podpisał Jan Nowak.\nZ poważaniem\nJan Marek Nowicki\nKierownik".encode()
    wynik, _, raport = ukryj(tekst, "txt", 1, detektor=TylkoImiona())
    assert raport.status == "ukonczony"
    assert b"Nowicki" not in wynik and b"Kierownik" in wynik


def test_kontrola_nie_pokazuje_modelowi_losowego_identyfikatora_mapy():
    """A random identifier in the note changed the model context on
        every run, so the same document sometimes passed with a visible surname and sometimes not."""

    class Zapisujacy:
        nazwa = "atrapa-zapis"
        typy = frozenset({TypEncji.OSOBA})

        def __init__(self):
            self.teksty: list[str] = []

        def znajdz(self, tekst: str) -> list[Zakres]:
            self.teksty.append(tekst)
            return []

    detektor = Zapisujacy()
    _, mapa, _ = ukryj(TEKST, "txt", 1, detektor=detektor)
    zakodowany = zakoduj_identyfikator(mapa.identyfikator)
    assert len(detektor.teksty) >= 2  # detection + check
    assert not any(zakodowany in t or "ZANONIMIZOWANY" in t for t in detektor.teksty)


@pytest.mark.parametrize(
    "podpis,nazwisko",
    [("Jan Marek McDonald", "Donald"), ("Jan Marek NOWICKI", "NOWICKI"), ("Jan Marek Müller", "Müller"),
     ("Jan Marek O’Neill", "Neill"), ("Jan Marek Nowak-Jeziorańska", "Jeziorańska")],
)
def test_kontrola_dopelnienie_osoby_po_pelnych_slowach(podpis, nazwisko):
    """'Jan Marek' + ' Mc' left 'Donald' visible."""

    class TylkoImiona(DetektorZaleznyOdKontekstu):
        def znajdz(self, tekst: str) -> list[Zakres]:
            if "Jan Nowak." in tekst:
                return DetektorOsob(("Jan Nowak",)).znajdz(tekst)
            return DetektorOsob(("Jan Marek",)).znajdz(tekst)

    tekst = f"Podpisał Jan Nowak.\n{podpis}\nKierownik".encode()
    wynik, _, raport = ukryj(tekst, "txt", 1, detektor=TylkoImiona())
    assert raport.status == "ukonczony"
    assert nazwisko.encode() not in wynik and b"Kierownik" in wynik


def test_znaczniki_w_tresci_wejscia_odrzucone():
    """'[PESEL_1]' in the input collided with an assigned marker
        and restore silently put a PESEL in place of the text."""
    from niewidka.rdzen import ZnacznikiWTresci

    with pytest.raises(ZnacznikiWTresci):
        ukryj(b"Przyklad [PESEL_1]. PESEL 44051401359.", "txt", 1, detektor=RegulyDetektor())


def test_oryginal_z_mapy_ukryty_takze_tam_gdzie_model_go_przeoczyl():
    """'Anna Nowak' hidden in one place, in another the model
        did not see her -> the raw scan reported ORYGINAL and the whole result was blocked."""

    class RazTak:
        nazwa = "atrapa-raz"
        typy = frozenset({TypEncji.OSOBA})

        def znajdz(self, tekst: str) -> list[Zakres]:
            i = tekst.find("Wynajmująca: Anna Nowak")
            if i < 0:
                return []
            s = i + len("Wynajmująca: ")
            return [Zakres(s, s + len("Anna Nowak"), TypEncji.OSOBA, 0.99, self.nazwa)]

    tekst = "Wynajmująca: Anna Nowak.\nPodpis: Anna Nowak".encode()
    wynik, _, raport = ukryj(tekst, "txt", 1, detektor=RazTak())
    assert raport.status == "ukonczony", raport.ostrzezenia
    assert b"Anna Nowak" not in wynik


def test_inne_formy_znanej_osoby_ukryte_na_kazdym_poziomie():
    """'Marek Zawadzki-Herbert' hidden, while 'Markowi
        Zawadzkiemu-Herbertowi' and 'z Beatą Sokołowską' stayed visible."""
    tekst = (
        "Najemca: Marek Zawadzki-Herbert. Obecna Beata Sokołowska z lokalu 7.\n"
        "Klucze przekazano Markowi Zawadzkiemu-Herbertowi. Rozmawiano z Beatą Sokołowską.\n"
        "Adres: ul. Polna 3, 05-100 Nowy Dwór. Pan Nowak nieobecny."
    ).encode()
    detektor = DetektorOsob(("Marek Zawadzki-Herbert", "Beata Sokołowska", "Nowak"))
    wynik, _, raport = ukryj(tekst, "txt", 1, detektor=detektor)
    assert raport.status == "ukonczony"
    for jawne in (b"Markowi", b"Zawadzkiemu", b"Herbertowi", "Beatą".encode(), "Sokołowską".encode()):
        assert jawne not in wynik, jawne
    assert "Nowy Dwór".encode() in wynik  # 'Nowak' does not catch 'Nowy'


def test_kontrola_oryginal_z_mapy_w_czesci_nieczytanej_blokuje(tmp_path):
    """A PESEL hidden in a part the adapter neither parses nor cleans
        (media) bypasses detection and replacement; the check against the map originals reports it."""
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

    # policy 'zostaw': by default images are removed (the leak would vanish
    # before the check can report it); here we test the RAW scan of non-XML parts,
    # so the image deliberately stays in the result
    _wynik, mapa, raport = ukryj(
        bufor.getvalue(), "docx", 1, detektor=RegulyDetektor(), polityka_obrazow="zostaw"
    )

    oryginaly = [w.oryginal for w in mapa.wystapienia]
    assert "44051401359" in oryginaly
    # the part has a neutral name (skrytka.png -> obrazN.png), and the check
    # still reports ORYGINAL in the media part
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
    """Slider: 1 = no threshold or half-step; 2 = variant A (OSOBA threshold + half-step); 3 = B (+dictionary)."""
    from niewidka.detektory import DetektorUzupełniający

    konfig = Konfig(modele_katalog=katalog_modeli)
    d1, d2, d3 = (zbuduj_detektor(poziom, konfig) for poziom in (1, 2, 3))
    assert (d1.nazwa, d2.nazwa, d3.nazwa) == ("poziom1", "poziom2", "poziom3")
    assert d1.czesci[1]._próg is None and not d1.czesci[1]._pół_krok  # level 1 as before
    assert d2.czesci[1]._próg == 0.2 and d2.czesci[1]._pół_krok  # variant A
    assert isinstance(d3, DetektorUzupełniający) and d3.uzup.nazwa == "slownik-imion"  # B
    assert d3.podstawa[1]._próg == 0.2


@pytest.mark.model
def test_poziom3_lapie_co_poziom1_przeoczy(katalog_modeli):
    """The slider changes detection. On Q4 levels 1 and 2 detect osoba-011
        identically, and the real difference comes from the
        level 3 first-name dictionary on the inst-061 corpus sample."""
    konfig = Konfig(modele_katalog=katalog_modeli)
    tekst = "Muzeum im. Adama Mickiewicza zaprasza."
    d1, d3 = zbuduj_detektor(1, konfig), zbuduj_detektor(3, konfig)
    trafienia = {
        poziom: {(z.start, z.koniec) for z in d.znajdz(tekst) if z.typ is TypEncji.OSOBA}
        for poziom, d in ((1, d1), (3, d3))
    }
    assert trafienia[1] == set()  # level 1 skips it
    assert trafienia[3] == {(11, 28)}  # level 3: the first-name dictionary catches 'Adama Mickiewicza'


def test_filtr_bez_daty():
    detektor = _BezDaty(RegulyDetektor())
    znaleziska = detektor.znajdz("PESEL 44051401359 z dnia 13.05.1982")
    assert {z.typ for z in znaleziska} == {TypEncji.PESEL}


def test_zbuduj_detektor_przekazuje_stan_pakietu_rozszerzonego(monkeypatch, tmp_path):
    """The core passes the verified state of the Extended package to
        level building (without it an installed LFM2.5 never takes part in detection)."""
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
