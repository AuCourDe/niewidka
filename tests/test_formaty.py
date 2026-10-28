"""Testy adapterów formatów (K3, LLD §9): rejestr, cięcia runów, txt, docx.

Round-trip: wczytaj → wykryj → znaczniki → zapisz → ponowne wczytanie i skan
(weryfikacja zapisu ZAWSZE, przegląd Astry pkt 8).
"""

from __future__ import annotations

import pytest

from niewidka.formaty import (
    ElementNieobslugiwany,
    adapter_dla,
    nazwa_wyniku,
    podziel_segment,
)
from niewidka.model import RunInfo, Segment


class TestPodzielSegment:
    def jeden_run(self) -> Segment:
        return Segment(
            tekst="Klient Jan Kowalski, PESEL 44051401359, obecny.",
            runs=[RunInfo("Klient Jan Kowalski, PESEL 44051401359, obecny.", element=None)],
            starts=[0],
        )

    def test_zamiana_w_srodku_jednego_runu(self):
        segment = self.jeden_run()
        fragmenty = podziel_segment(
            segment,
            [(7, 19, "[OSOBA_1_F1]"), (27, 38, "[PESEL_1]")],
        )
        assert [t for t, _ in fragmenty] == [
            "Klient ",
            "[OSOBA_1_F1]",
            ", PESEL ",
            "[PESEL_1]",
            ", obecny.",
        ]
        # wszystkie fragmenty z jednego runu źródłowego (styl lewy)
        assert {i for _, i in fragmenty} == {0}

    def test_zamiana_na_granicy_runow(self):
        segment = Segment(
            tekst="Jan Kowalski wrócił",
            runs=[RunInfo("Jan Kowalski", element="a"), RunInfo(" wrócił", element="b")],
            starts=[0, 12],
        )
        fragmenty = podziel_segment(segment, [(0, 12, "[OSOBA_1_F1]")])
        assert [t for t, _ in fragmenty] == ["[OSOBA_1_F1]", " wrócił"]
        # znacznik dziedziczy styl lewego fragmentu (run 0), reszta zostaje w runie 1
        assert fragmenty[0] == ("[OSOBA_1_F1]", 0)
        assert fragmenty[1] == (" wrócił", 1)

    def test_runy_wwnetrzne_zachowuja_styl(self):
        segment = Segment(
            tekst="AB CD",
            runs=[RunInfo("AB ", element="a"), RunInfo("CD", element="b")],
            starts=[0, 3],
        )
        fragmenty = podziel_segment(segment, [(0, 2, "[X]")])
        assert fragmenty == [("[X]", 0), (" ", 0), ("CD", 1)]

    def test_bez_zamian_zwraca_wejscie(self):
        segment = self.jeden_run()
        assert podziel_segment(segment, []) == [("Klient Jan Kowalski, PESEL 44051401359, obecny.", 0)]

    def test_zamiany_nierozlaczne_blad(self):
        segment = self.jeden_run()
        with pytest.raises(ValueError):
            podziel_segment(segment, [(0, 10, "[A]"), (5, 15, "[B]")])


class TestRejestr:
    def test_txt(self):
        adapter = adapter_dla("list.txt")
        assert "txt" in adapter.rozszerzenia

    def test_docx(self):
        adapter = adapter_dla("umowa.docx")
        assert "docx" in adapter.rozszerzenia

    def test_nieznany_format_blad(self):
        with pytest.raises(ElementNieobslugiwany):
            adapter_dla("prezentacja.pptx")


class TestNazwaWyniku:
    def test_zanonimizowany_z_krotkim_id(self):
        assert nazwa_wyniku("umowa-o-dzielo.docx", "a3f9c2") == "ZANONIMIZOWANY_a3f9c2.docx"

    def test_txt(self):
        assert nazwa_wyniku("notatka.txt", "b12ee3") == "ZANONIMIZOWANY_b12ee3.txt"


# --- adapter TXT -------------------------------------------------------------

from niewidka.formaty.tekst import AdapterTekst


class TestAdapterTekst:
    def test_wczytaj_jeden_segment(self):
        dok = AdapterTekst().wczytaj(b"PESEL 44051401359\nDruga linia")
        assert dok.format == "txt"
        assert len(dok.segmenty) == 1
        assert dok.segmenty[0].tekst == "PESEL 44051401359\nDruga linia"

    def test_wczytaj_bom_tolerowany(self):
        dok = AdapterTekst().wczytaj(b"\xef\xbb\xbfTekst z BOM")
        assert dok.segmenty[0].tekst == "Tekst z BOM"

    def test_zapis_dopisek_i_tekst_ze_znacznikami(self):
        adapter = AdapterTekst()
        dok = adapter.wczytaj(b"Jan Kowalski")
        fragmenty = podziel_segment(dok.segmenty[0], [(0, 12, "[OSOBA_1_F1]")])
        segment = dok.segmenty[0]
        segment.runs = [
            RunInfo(tekst, segment.runs[i].element)
            for tekst, i in [(t, i) for t, i in fragmenty]
        ]
        segment.tekst = "".join(r.tekst for r in segment.runs)
        wynik = adapter.zapisz(dok).decode("utf-8")
        assert wynik.startswith("ZANONIMIZOWANO w Niewidka")
        assert "[OSOBA_1_F1]" in wynik
        assert "Jan Kowalski" not in wynik

    def test_nieobslugiwane_puste(self):
        dok = AdapterTekst().wczytaj(b"x")
        assert AdapterTekst().elementy_nieobslugiwane(dok) == []
