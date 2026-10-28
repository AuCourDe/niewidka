"""Kontrola zapisu (LLD §10): weryfikacja ZAWSZE, każdy poziom suwaka (Astra pkt 8)."""

from __future__ import annotations

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

    def test_oryginal_z_mapy_w_archiwum_ostrzezenie_krytyczne(self):
        dane = zapisz_podstawowy(Path_tmp() / "w.docx").read_bytes()
        brudny = _docx_przebuduj(dane, podmien={"word/settings.xml": _settings_z_pesel()})

        uwagi = kontroluj(brudny, "w.docx", RegulyAtrapa(), oryginaly=[PESEL])

        assert any(u.typ == "ORYGINAL" and u.fragment == PESEL for u in uwagi)

    def test_oryginal_w_czesci_nie_xml(self):
        dane = zapisz_podstawowy(Path_tmp() / "w.docx").read_bytes()
        brudny = _docx_przebuduj(dane, dodaj={"word/media/skrytka.bin": f"losowe dane {PESEL} koniec".encode()})

        uwagi = kontroluj(brudny, "w.docx", RegulyAtrapa(), oryginaly=[PESEL])

        assert any(u.typ == "ORYGINAL" and u.czesc == "word/media/skrytka.bin" for u in uwagi)

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
