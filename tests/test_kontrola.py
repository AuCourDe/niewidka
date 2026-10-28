"""Kontrola zapisu (LLD §10): weryfikacja ZAWSZE, każdy poziom suwaka (Astra pkt 8)."""

from __future__ import annotations

import time

import pytest

from niewidka.formaty import adapter_dla, podziel_segment
from niewidka.formaty.tekst import AdapterTekst
from niewidka.kontrola import kontroluj
from niewidka.model import RunInfo
from niewidka.reguly import znajdz as znajdz_reguly


def _zakryj(dane: bytes) -> bytes:
    """Wklejony tekst → reguły → znaczniki (uproszczony przebieg ukryj)."""
    adapter = AdapterTekst()
    dok = adapter.wczytaj(dane)
    segment = dok.segmenty[0]
    licznik: dict[str, int] = {}
    zamiany = []
    for z in znajdz_reguly(segment.tekst):
        licznik[z.typ.value] = licznik.get(z.typ.value, 0) + 1
        zamiany.append((z.start, z.koniec, f"[{z.typ.value}_{licznik[z.typ.value]}]"))
    fragmenty = podziel_segment(segment, zamiany)
    segment.runs = [RunInfo(t, None) for t, _ in fragmenty]
    segment.tekst = "".join(r.tekst for r in segment.runs)
    return adapter.zapisz(dok)


class TestKontroluj:
    def test_czysty_wynik_zero_ostrzezen(self):
        wynik = _zakryj(b"Jan Kowalski, PESEL 44051401359.")
        assert kontroluj(wynik, "wynik.txt", RegulyAtrapa()) == []

    def test_wyciek_w_wyniku_daje_ostrzezenie(self):
        wynik = _zakryj(b"Jan Kowalski, PESEL 44051401359.")
        brudny = wynik.replace(b"[PESEL_1]", b"PESEL 79020853217")  # wyciek w środku
        uwagi = kontroluj(brudny, "wynik.txt", RegulyAtrapa())
        assert len(uwagi) == 1
        assert uwagi[0].typ == "PESEL"
        assert uwagi[0].fragment == "79020853217"
        assert uwagi[0].segment == 0  # TXT = jeden segment (dopisek + treść)

    def test_weryfikacja_wczytuje_jak_obcy_format(self):
        # DOCX: kontrola przez ten sam adapter (ponowne wczytanie i skan)
        from narzedzia.generator_dokumentow import zapisz_podstawowy

        wzorzec = zapisz_podstawowy(Path_tmp() / "w.docx")
        adapter = adapter_dla("w.docx")
        dok = adapter.wczytaj(wzorzec.read_bytes())
        czysty = adapter.zapisz(dok)  # bez detekcji — PESEL zostaje!
        uwagi = kontroluj(czysty, "w.docx", RegulyAtrapa())
        assert any(u.typ == "PESEL" for u in uwagi)  # kontrola ZAWSZE wyłapuje


def Path_tmp():
    import tempfile
    from pathlib import Path

    return Path(tempfile.gettempdir())


class RegulyAtrapa:
    """Reguły bez modeli — kontrola działa na każdym poziomie suwaka."""

    nazwa = "reguly"
    typy = frozenset()

    def znajdz(self, tekst):
        from niewidka.scalanie import scal

        return scal(tekst, znajdz_reguly(tekst))


# --- skan surowy archiwum (K3b): kontrola NIEZALEŻNA od adaptera --------------

import io
import zipfile

from narzedzia.generator_dokumentow import zapisz_podstawowy


def _docx_przebuduj(dane: bytes, podmien: dict[str, bytes] | None = None, dodaj: dict[str, bytes] | None = None) -> bytes:
    """DOCX po przebudowie: podmiana istniejących części + dołożenie nowych."""
    zrodlo = zipfile.ZipFile(io.BytesIO(dane))
    czesci = {n: zrodlo.read(n) for n in zrodlo.namelist()}
    zrodlo.close()
    czesci.update(podmien or {})
    czesci.update(dodaj or {})
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
        for nazwa, zawartosc in czesci.items():
            paczka.writestr(nazwa, zawartosc)
    return bufor.getvalue()


def _settings_z_pesel() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:writeProtection w:author="{PESEL}"/></w:settings>'
    ).encode()


PESEL = "44051401359"


def _fonttable_z_karta(numer: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:fonts xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:font w:name="Lato"><w:panose1 w:val="{numer}"/></w:font></w:fonts>'
    ).encode()


def _fonttable_z_panose() -> bytes:
    """Typowa wartość panose z żywego DOCX (K7b): 16 cyfr, Luhn błędny."""
    return _fonttable_z_karta("0502020204030204")


class TestSkanSurowy:
    """Kontrola skanuje SUROWO każdą część archiwum, także tę, której adapter
    nie parsuje (Gemini: notka pod przeglądem — kontrola przez ten sam adapter
    ma te same martwe punkty)."""

    def test_pesel_w_atrybucie_czesci_nieczytanej_przez_adapter(self):
        dane = zapisz_podstawowy(Path_tmp() / "w.docx").read_bytes()
        brudny = _docx_przebuduj(dane, podmien={"word/settings.xml": _settings_z_pesel()})

        uwagi = kontroluj(brudny, "w.docx", RegulyAtrapa())

        peselowe = [u for u in uwagi if u.typ == "PESEL"]
        assert peselowe, f"kontrola nie widzi PESEL w settings.xml: {uwagi}"
        assert any(u.czesc == "word/settings.xml" for u in peselowe)

    def test_podejrzana_karta_w_metadanych_nie_blokuje(self):
        """Panose w fontTable.xml (16 cyfr, błędny Luhn) to typografia, nie wyciek:
        karta z błędną sumą pomijana w skanie surowym jak DATA (żywy bieg K7b:
        wzorcowy DOCX padał zablokowany przez word/fontTable.xml)."""
        dane = zapisz_podstawowy(Path_tmp() / "w.docx").read_bytes()
        brudny = _docx_przebuduj(dane, podmien={"word/fontTable.xml": _fonttable_z_panose()})

        uwagi = kontroluj(brudny, "w.docx", RegulyAtrapa())

        assert not [u for u in uwagi if u.typ == "KARTA"], uwagi

    def test_pewna_karta_w_skane_surowym_nadal_ostrzega(self):
        """16 cyfr z POPRAWNYM Luhnem w części XML to realny kandydat karty:
        ostrzeżenie zostaje, niezależnie od części."""
        dane = zapisz_podstawowy(Path_tmp() / "w.docx").read_bytes()
        brudny = _docx_przebuduj(
            dane, podmien={"word/fontTable.xml": _fonttable_z_karta("4556778899012232")}
        )

        uwagi = kontroluj(brudny, "w.docx", RegulyAtrapa())

        karty = [u for u in uwagi if u.typ == "KARTA"]
        assert karty and karty[0].fragment == "4556778899012232"

    def test_oryginal_z_mapy_w_archiwum_ostrzezenie_krytyczne(self):
        dane = zapisz_podstawowy(Path_tmp() / "w.docx").read_bytes()
        brudny = _docx_przebuduj(dane, podmien={"word/settings.xml": _settings_z_pesel()})

        uwagi = kontroluj(brudny, "w.docx", RegulyAtrapa(), oryginaly=[PESEL])

        assert any(u.typ == "ORYGINAL" and u.fragment == PESEL for u in uwagi)

    def test_oryginal_w_czesci_nie_xml(self):
        dane = zapisz_podstawowy(Path_tmp() / "w.docx").read_bytes()
        brudny = _docx_przebuduj(dane, dodaj={"word/media/skrytka.png": f"losowe dane {PESEL} koniec".encode()})

        uwagi = kontroluj(brudny, "w.docx", RegulyAtrapa(), oryginaly=[PESEL])

        assert any(u.typ == "ORYGINAL" and u.czesc == "word/media/skrytka.png" for u in uwagi)

    def test_czysty_wynik_z_oryginalami_zero_ostrzezen(self):
        """PESEL zamieniony na znacznik i nigdzie w archiwum nieobecny = bez alarmu."""
        dane = zapisz_podstawowy(Path_tmp() / "w.docx").read_bytes()
        wynik = _zakryj_docx_regulami(dane)

        uwagi = kontroluj(wynik, "w.docx", RegulyAtrapa(), oryginaly=[PESEL, "601 234 567"])

        assert uwagi == [], uwagi


def _zakryj_docx_regulami(dane: bytes) -> bytes:
    """DOCX → reguły → znaczniki (uproszczony przebieg ukryj, bez modeli)."""
    from niewidka.formaty import adapter_dla

    adapter = adapter_dla("w.docx")
    dok = adapter.wczytaj(dane)
    for segment in dok.segmenty:
        licznik: dict[str, int] = {}
        zamiany = []
        for z in znajdz_reguly(segment.tekst):
            licznik[z.typ.value] = licznik.get(z.typ.value, 0) + 1
            zamiany.append((z.start, z.koniec, f"[{z.typ.value}_{licznik[z.typ.value]}]"))
        if zamiany:
            adapter.wstaw_znaczniki(segment, zamiany)
    return adapter.zapisz(dok)


class DetektorTylkoModel:
    """Atrapa detektora czysto modelowego (jak bardsai): widzi tylko OSOBA w treści,
    nie zna reguł ani numerów z sumą kontrolną. Skan surowy ma działać i z takim."""

    nazwa = "atrapa-model"
    typy = frozenset()

    def znajdz(self, tekst):
        return []


import re

from niewidka.model import TypEncji, Zakres

_WZORZEC_ATRAPY = re.compile(r"\[[^\]]*\]|\d{8,}")


class DetektorNaZnacznikach:
    """Atrapa modelu, który odpala OSOBA na tekście znacznika (znalezione E2E K5b:
    bardsai klasyfikuje „[OSOBA_1_F1]" jako osobę) i na długich liczbach. Kontrola
    ma znaczniki POMIJAĆ („znaleziska niebędące znacznikami", LLD §10), bo w
    znaczniku nie ma oryginału; prawdziwe wycieki mają zostać."""

    nazwa = "atrapa-znaczniki"
    typy = frozenset({TypEncji.OSOBA})

    def znajdz(self, tekst):
        return [Zakres(m.start(), m.end(), TypEncji.OSOBA, 1.0, self.nazwa) for m in _WZORZEC_ATRAPY.finditer(tekst)]


class TestKontrolaZnaczniki:
    def test_znaczniki_w_wyniku_nie_sa_ostrzezeniem(self):
        wynik = _zakryj(b"Jan Kowalski, PESEL 44051401359.")

        uwagi = kontroluj(wynik, "wynik.txt", DetektorNaZnacznikach())

        assert uwagi == [], f"znacznik potraktowany jak wyciek: {uwagi}"

    def test_wyciek_obok_znacznikow_nadal_blokuje(self):
        wynik = _zakryj(b"Jan Kowalski, PESEL 44051401359.")
        brudny = wynik.replace(b"[PESEL_1]", b"PESEL 79020853217")

        uwagi = kontroluj(brudny, "wynik.txt", DetektorNaZnacznikach())

        assert {u.fragment for u in uwagi} == {"79020853217"}, uwagi


class TestSkanSurowyReguly:
    """K5b: skan surowy używa WYŁĄCZNIE reguł + oryginałów z mapy, niezależnie od
    przekazanego detektora. Model ONNX na każdej części XML = 219 s na wzorcu
    (timeout API 120 s, 500 fail-closed) i fałszywe blokady z metadanych XML."""

    def test_pesel_w_surowej_czesci_widoczny_bez_regul_w_detektorze(self):
        dane = zapisz_podstawowy(Path_tmp() / "w.docx").read_bytes()
        brudny = _docx_przebuduj(dane, podmien={"word/settings.xml": _settings_z_pesel()})

        uwagi = kontroluj(brudny, "w.docx", DetektorTylkoModel())

        peselowe = [u for u in uwagi if u.typ == "PESEL"]
        assert peselowe, "skan surowy musi stosować reguły nawet z detektorem bez reguł"
        assert any(u.czesc == "word/settings.xml" for u in peselowe)

    def test_oryginaly_z_mapy_skanowane_niezaleznie_od_detektora(self):
        dane = zapisz_podstawowy(Path_tmp() / "w.docx").read_bytes()
        brudny = _docx_przebuduj(dane, podmien={"word/settings.xml": _settings_z_pesel()})

        uwagi = kontroluj(brudny, "w.docx", DetektorTylkoModel(), oryginaly=[PESEL])

        assert any(u.typ == "ORYGINAL" and u.fragment == PESEL for u in uwagi)


class TestWydajnoscKontroli:
    @pytest.mark.model
    def test_ukrycie_docx_poziom3_ponizej_timeoutu_api(self, katalog_modeli, tmp_path):
        """Zlecenie K5b: ukrycie wzorcowego DOCX na poziomie 3 trwa < 10 s
        (limit API 120 s). Przed naprawą: 219 s."""
        from narzedzia.generator_dokumentow import zapisz_podstawowy
        from niewidka.konfig import Konfig
        from niewidka.rdzen import ukryj

        wzorzec = zapisz_podstawowy(tmp_path / "w.docx").read_bytes()
        konfig = Konfig(modele_katalog=katalog_modeli)

        start = time.monotonic()
        _, _, raport = ukryj(wzorzec, "docx", 3, konfig=konfig)
        czas = time.monotonic() - start

        assert raport.status == "ukonczony", f"wynik zablokowany: {raport.ostrzezenia}"
        assert czas < 10.0, f"ukrycie DOCX na poziomie 3 trwa {czas:.1f} s (limit 10 s)"
