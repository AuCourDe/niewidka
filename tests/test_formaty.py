"""Testy adapterów formatów: rejestr, cięcia runów, txt, docx.

Round-trip: wczytaj → wykryj → znaczniki → zapisz → ponowne wczytanie i skan
(weryfikacja zapisu ZAWSZE).
"""

from __future__ import annotations

import pytest

from niewidka.formaty import (
    ElementNieobslugiwany,
    adapter_dla,
    nazwa_wyniku,
    podziel_segment,
)
from niewidka.model import Dokument, RunInfo, Segment


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

    def test_zamiana_przez_granice_runu_nie_przepisuje_koncowki(self):
        """Encja rozbita na dwa runy, granica runu WEWNĄTRZ zamiany —
        część za granicą nie może wrócić jako jawny tekst."""
        segment = Segment(
            tekst="Jan Kowalski",
            runs=[RunInfo("Jan ", element="a"), RunInfo("Kowalski", element="b")],
            starts=[0, 4],
        )
        fragmenty = podziel_segment(segment, [(0, 12, "[OSOBA_1_F1]")])
        assert fragmenty == [("[OSOBA_1_F1]", 0)]

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
        assert wynik.startswith("ZANONIMIZOWANY. Dane osobowe zastąpiono znacznikami (Niewidka).")
        assert "[OSOBA_1_F1]" in wynik
        assert "Jan Kowalski" not in wynik

    def test_nieobslugiwane_puste(self):
        dok = AdapterTekst().wczytaj(b"x")
        assert AdapterTekst().elementy_nieobslugiwane(dok) == []


# --- wstaw_znaczniki: wspólny przepływ segmentu (cięcie + kopiowanie runów) ---

from niewidka.formaty import wstaw_znaczniki


class TestWstawZnaczniki:
    def test_zamienia_runy_i_tekst_segmentu(self):
        segment = Segment(
            tekst="PESEL 44051401359 dalej.",
            runs=[RunInfo("PESEL 44051401359 dalej.", element="a")],
            starts=[0],
        )
        wstaw_znaczniki(segment, [(6, 17, "[PESEL_1]")], kopiuj_run=lambda e, t: ("klon", e, t))
        assert segment.tekst == "PESEL [PESEL_1] dalej."
        assert [r.tekst for r in segment.runs] == ["PESEL ", "[PESEL_1]", " dalej."]
        # fragment znacznika dziedziczy element runu lewego
        assert segment.runs[1].element == ("klon", "a", "[PESEL_1]")
        assert segment.starts == [0, 6, 15]  # 6 + len("[PESEL_1]")


# --- adapter DOCX -------------------------------------------------------

import io
import zipfile

from narzedzia.generator_dokumentow import (
    zapisz_czesc_obca,
    zapisz_podstawowy,
    zapisz_z_makrem,
)
from niewidka.formaty.docx_ import AdapterDocx
from niewidka.reguly import znajdz as znajdz_reguly
from niewidka.scalanie import scal


@pytest.fixture()
def wzorzec(tmp_path):
    return zapisz_podstawowy(tmp_path / "wzorzec.docx")


def _segment(dok: Dokument, fraza: str) -> Segment:
    for segment in dok.segmenty:
        if fraza in segment.tekst:
            return segment
    raise AssertionError(f"brak segmentu z {fraza!r}: {[s.tekst for s in dok.segmenty]}")


class TestAdapterDocxWczytaj:
    def test_segmenty_akapity_i_tabela(self, wzorzec):
        dok = AdapterDocx().wczytaj(wzorzec.read_bytes())
        teksty = [s.tekst for s in dok.segmenty]
        assert any("Umowa z Janem Kowalskim" in t for t in teksty)
        assert any("Anna Nowak" in t for t in teksty)  # tabela
        # komórki tabeli = osobne akapity = osobne segmenty
        assert any(t == "NIP" for t in teksty)
        assert any("1234563218" in t for t in teksty)

    def test_runy_i_starts_przeplot_styli(self, wzorzec):
        dok = AdapterDocx().wczytaj(wzorzec.read_bytes())
        segment = _segment(dok, "Umowa z Janem")
        assert [r.tekst for r in segment.runs] == [
            "Umowa z ",
            "Janem Kowalskim",
            ", PESEL 44051401359, telefon +48 601 234 567.",
        ]
        assert segment.starts == [0, 8, 23]

    def test_tekst_naglowka_i_komentarza_nie_wchodzi_do_segmentow(self, wzorzec):
        dok = AdapterDocx().wczytaj(wzorzec.read_bytes())
        calosc = "\n".join(s.tekst for s in dok.segmenty)
        assert "Kancelaria Nowak" not in calosc  # nagłówek czyszczony
        assert "Sprawdziła Anna" not in calosc  # komentarz czyszczony
        assert "ul. Lipowa 13/5" not in calosc  # przypis czyszczony

    def test_track_changes_del_usuniety_ins_zostaje(self, wzorzec):
        dok = AdapterDocx().wczytaj(wzorzec.read_bytes())
        calosc = "\n".join(s.tekst for s in dok.segmenty)
        assert "stary numer 700 800 900" not in calosc  # w:del usunięty
        assert "nowy numer 111 222 333" in calosc  # w:ins = treść
        assert "ZMIENIONY" in calosc

    def test_makro_blokuje_wczytanie(self, tmp_path):
        sciezka = zapisz_z_makrem(tmp_path / "z_makrem.docx")
        with pytest.raises(ElementNieobslugiwany, match="vbaProject"):
            AdapterDocx().wczytaj(sciezka.read_bytes())

    def test_czesc_spoza_allowlisty_blokuje(self, tmp_path):
        sciezka = zapisz_czesc_obca(tmp_path / "z_obca.docx")
        with pytest.raises(ElementNieobslugiwany, match="embeddings"):
            AdapterDocx().wczytaj(sciezka.read_bytes())

    def test_obraz_ostrzezenie_na_liscie(self, wzorzec):
        adapter = AdapterDocx()
        dok = adapter.wczytaj(wzorzec.read_bytes())
        lista = adapter.elementy_nieobslugiwane(dok)
        assert any("obraz" in e.lower() for e in lista)


class TestAdapterDocxRoundTrip:
    def _zakryj_regulami(self, adapter: AdapterDocx, dok: Dokument) -> None:
        """Wykryj regułami per segment, wstaw znaczniki [TYP_N]."""
        licznik: dict[str, int] = {}
        for segment in dok.segmenty:
            zamiany = []
            for z in scal(segment.tekst, znajdz_reguly(segment.tekst)):
                licznik[z.typ.value] = licznik.get(z.typ.value, 0) + 1
                zamiany.append((z.start, z.koniec, f"[{z.typ.value}_{licznik[z.typ.value]}]"))
            adapter.wstaw_znaczniki(segment, zamiany)

    def test_round_trip_znaczniki_na_pozycjach_i_skan_czysty(self, wzorzec):
        adapter = AdapterDocx()
        dok = adapter.wczytaj(wzorzec.read_bytes())
        self._zakryj_regulami(adapter, dok)
        wynik = adapter.zapisz(dok)

        # weryfikacja zapisu ZAWSZE: ponowne wczytanie i skan
        dok2 = adapter.wczytaj(wynik)
        nowe = [
            z
            for segment in dok2.segmenty
            for z in scal(segment.tekst, znajdz_reguly(segment.tekst))
        ]
        assert nowe == [], f"nowe znaleziska w wyniku: {[dok2.segmenty[0].tekst for z in []]}"
        calosc = "\n".join(s.tekst for s in dok2.segmenty)
        assert "[PESEL_1]" in calosc
        assert "[TELEFON_1]" in calosc
        assert "[EMAIL_1]" in calosc
        assert "44051401359" not in calosc
        assert "601 234 567" not in calosc
        assert "1234563218" not in calosc  # NIP z tabeli
        # pułapka (11 cyfr bez poprawnej sumy) zostaje zamaskowana jako podejrzana
        assert "12345678901" not in calosc
        # dopisek na początku dokumentu
        assert dok2.segmenty[0].tekst.startswith("ZANONIMIZOWANY. Dane osobowe")

    def test_round_trip_styl_bold_na_znaczniku(self, wzorzec):
        adapter = AdapterDocx()
        dok = adapter.wczytaj(wzorzec.read_bytes())
        self._zakryj_regulami(adapter, dok)
        wynik = adapter.zapisz(dok)
        dok2 = adapter.wczytaj(wynik)
        segment = next(s for s in dok2.segmenty if "[PESEL_1]" in s.tekst)
        # PESEL stoi w runie zwykłym; znacznik dziedziczy styl lewego fragmentu
        run_ze_znacznikiem = next(r for r in segment.runs if "[PESEL_1]" in r.tekst)
        from docx.oxml.ns import qn

        bold = run_ze_znacznikiem.element.findall(f"{qn('w:rPr')}/{qn('w:b')}")
        assert bold == []  # run lewy ("Umowa z ") nie jest pogrubiony

    def test_czyszczone_czesci_i_wlasciwosci(self, wzorzec):
        adapter = AdapterDocx()
        dok = adapter.wczytaj(wzorzec.read_bytes())
        wynik = adapter.zapisz(dok)
        z = zipfile.ZipFile(io.BytesIO(wynik))
        nazwy = z.namelist()
        for usunieta in (
            "word/comments.xml",
            "word/footnotes.xml",
            "word/header1.xml",
            "word/footer1.xml",
            "docProps/thumbnail.jpeg",
            "docProps/app.xml",
        ):
            assert usunieta not in nazwy, usunieta
        core = z.read("docProps/core.xml").decode("utf-8")
        assert "Jan Kowalski" not in core
        assert "Anna Zielińska" not in core
        assert "Tajna umowa" not in core
        doc_xml = z.read("word/document.xml").decode("utf-8")
        assert "<w:del" not in doc_xml
        assert "commentReference" not in doc_xml
        assert "footnoteReference" not in doc_xml
        assert "headerReference" not in doc_xml

    def test_hiperlacza_zewnetrzne_rozpakowane_tekst_zostaje(self, wzorzec):
        adapter = AdapterDocx()
        dok = adapter.wczytaj(wzorzec.read_bytes())
        wynik = adapter.zapisz(dok)
        z = zipfile.ZipFile(io.BytesIO(wynik))
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
        assert "example.com" not in rels
        assert "mailto:" not in rels
        doc_xml = z.read("word/document.xml").decode("utf-8")
        assert "napisz do Jana" in doc_xml  # tekst z rozpakowanego mailto zostaje
        calosc_tekst = "\n".join(
            s.tekst for s in adapter.wczytaj(wynik).segmenty
        )
        assert "napisz do Jana" in calosc_tekst

    def test_sciezka_celu_hiperlacza_nie_przechodzi_a_plik_sie_otwiera(self, wzorzec):
        docx = pytest.importorskip("docx")
        wejscie = zipfile.ZipFile(io.BytesIO(wzorzec.read_bytes()))
        bufor = io.BytesIO()
        with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
            for nazwa in wejscie.namelist():
                tresc = wejscie.read(nazwa)
                if nazwa == "word/_rels/document.xml.rels":
                    assert b"https://example.com/oferta" in tresc
                    tresc = tresc.replace(b"https://example.com/oferta", b"https://example.org/Jan%20Kowalski")
                paczka.writestr(nazwa, tresc)
        adapter = AdapterDocx()
        wynik = adapter.zapisz(adapter.wczytaj(bufor.getvalue()))
        z = zipfile.ZipFile(io.BytesIO(wynik))
        for nazwa in (n for n in z.namelist() if n.endswith(".rels")):
            assert b"Kowalski" not in z.read(nazwa) and b"example.org" not in z.read(nazwa), nazwa
        assert docx.Document(io.BytesIO(wynik)).paragraphs

    def test_tabulator_i_lamanie_w_runie_nie_powielaja_sie(self, tmp_path):
        docx = pytest.importorskip("docx")
        sciezka = tmp_path / "tab.docx"
        dokument = docx.Document()
        akapit = dokument.add_paragraph()
        akapit.add_run("PESEL: 44051401359\tKwota: 100\nKoniec")
        dokument.save(sciezka)
        adapter = AdapterDocx()
        dok = adapter.wczytaj(sciezka.read_bytes())
        segment = next(s for s in dok.segmenty if "PESEL" in s.tekst)
        assert segment.tekst == "PESEL: 44051401359\tKwota: 100\nKoniec"
        adapter.wstaw_znaczniki(segment, [(7, 18, "[PESEL_1]")])
        wynik = adapter.zapisz(dok)
        xml = zipfile.ZipFile(io.BytesIO(wynik)).read("word/document.xml").decode("utf-8")
        assert xml.count("<w:tab/>") == 1 and xml.count("<w:br/>") == 1
        ponownie = adapter.wczytaj(wynik)
        assert any(s.tekst == "PESEL: [PESEL_1]\tKwota: 100\nKoniec" for s in ponownie.segmenty)

    def test_nazwa_wyniku_docx(self, wzorzec):
        assert nazwa_wyniku("wzorzec.docx", "a1b2c3") == "ZANONIMIZOWANY_a1b2c3.docx"


class TestTekstyAlternatywne:
    def test_descr_obrazu_czyszczony(self, wzorzec):
        # tekst alternatywny może nieść PII ("Logo z adresem ul. Lipowa 13/5")
        adapter = AdapterDocx()
        dok = adapter.wczytaj(wzorzec.read_bytes())
        wynik = adapter.zapisz(dok)
        doc_xml = zipfile.ZipFile(io.BytesIO(wynik)).read("word/document.xml").decode("utf-8")
        assert "ul. Lipowa 13/5" not in doc_xml


class TestContentTypesIPola:
    def test_default_zostaje_gdy_czesc_z_tym_rozszerzeniem_jest_w_media(self):
        from niewidka.formaty.docx_ import _przefiltruj_content_types

        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="jpeg" ContentType="image/jpeg"/>'
            "</Types>"
        )
        wynik = _przefiltruj_content_types(
            xml.encode(), set(), pozostale={"word/media/zdjecie.jpeg"}
        )
        assert b'Extension="jpeg"' in wynik  # część istnieje — Default musi zostać

    def test_default_znika_gdy_brak_czesci(self):
        from niewidka.formaty.docx_ import _przefiltruj_content_types

        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="jpeg" ContentType="image/jpeg"/>'
            "</Types>"
        )
        wynik = _przefiltruj_content_types(xml.encode(), set(), pozostale={"word/media/logo.png"})
        assert b"jpeg" not in wynik

    def test_core_czysci_kategorie_i_status(self):
        from niewidka.formaty.docx_ import _wyczysc_core

        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">'
            "<cp:category>Klienci VIP</cp:category><cp:contentStatus>Robocza</cp:contentStatus>"
            "</cp:coreProperties>"
        )
        wynik = _wyczysc_core(xml.encode()).decode("utf-8")
        assert "Klienci VIP" not in wynik
        assert "Robocza" not in wynik


# --- pułapki DOCX -------------

from lxml import etree

from narzedzia.generator_dokumentow import dokument_pulapki, zapisz_pulapki

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture()
def pulapki():
    bufor = io.BytesIO()
    dokument_pulapki().save(bufor)
    return bufor.getvalue()


def _zakryj(dane: bytes) -> bytes:
    """Pełny przebieg: reguły → znaczniki → zapis (bez modeli)."""
    adapter = AdapterDocx()
    dok = adapter.wczytaj(dane)
    licznik: dict[str, int] = {}
    for segment in dok.segmenty:
        zamiany = []
        for z in scal(segment.tekst, znajdz_reguly(segment.tekst)):
            licznik[z.typ.value] = licznik.get(z.typ.value, 0) + 1
            zamiany.append((z.start, z.koniec, f"[{z.typ.value}_{licznik[z.typ.value]}]"))
        if zamiany:
            adapter.wstaw_znaczniki(segment, zamiany)
    return adapter.zapisz(dok)


def _document_xml(wynik: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(wynik)).read("word/document.xml").decode("utf-8")


class TestPulapkiK3b:
    def test_instrText_usuniete_wynik_pola_zostaje(self, pulapki):
        """Instrukcja pola złożonego z PII — usuwana; wynik pola zostaje."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "instrText" not in xml, "instrukcja pola z PII wycieka"
        assert "Jan Kowalski" in xml  # wynik pola (w:t) zostaje jako tekst

    def test_fldSimple_bez_instr(self, pulapki):
        """Atrybut w:instr pola prostego czyszczony."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert 'w:instr="' not in xml, "w:instr pola prostego wycieka"
        assert "Anna Nowak" in xml  # wynik pola zostaje

    def test_ins_osierocone_wt_wchodzi_do_segmentow(self, pulapki):
        """W:t bez w:r w w:ins — po normalizacji trafia do segmentów."""
        dok = AdapterDocx().wczytaj(pulapki)
        calosc = "\n".join(s.tekst for s in dok.segmenty)
        assert "PESEL 44051401359 poza runem" in calosc, "osierocone w:t omija detekcję"
        wynik = _zakryj(pulapki)
        assert "44051401359 poza runem" not in _document_xml(wynik)

    def test_atrybuty_rewizji_czyste(self, pulapki):
        """W:author/w:date/w:initials ze śledzonych zmian usunięte."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "w:author=" not in xml, "tożsamość autora rewizji wycieka"
        assert "w:date=" not in xml
        assert "w:initials=" not in xml
        assert "Anna Zielińska" not in xml

    def test_komorka_po_del_ma_akapit_i_plik_poprawny(self, pulapki):
        """Komórka z samym w:del nie może zostać pustą w:tc."""
        wynik = _zakryj(pulapki)
        drzewo = etree.fromstring(_document_xml(wynik).encode())
        puste = [tc for tc in drzewo.iter(f"{W_NS}tc") if tc.find(f"{W_NS}p") is None]
        assert puste == [], f"komórki bez w:p: {len(puste)}"
        from docx import Document as Otworz

        Otworz(io.BytesIO(wynik))  # plik otwiera się bez "unreadable content"

    def test_rels_usuwanych_czesci_nie_blokuja_i_znikaja(self, tmp_path):
        """Word/_rels/header1.xml.rels — obsłużone, nie blokada."""
        sciezka = zapisz_pulapki(tmp_path / "p.docx", paczkowe="header")
        adapter = AdapterDocx()
        dok = adapter.wczytaj(sciezka.read_bytes())
        wynik = adapter.zapisz(dok)
        assert "word/_rels/header1.xml.rels" not in zipfile.ZipFile(io.BytesIO(wynik)).namelist()

    def test_settings_czyste(self, tmp_path):
        """AttachedTemplate, documentProtection, writeProtection, rsids."""
        sciezka = zapisz_pulapki(tmp_path / "p.docx", paczkowe="settings")
        wynik = _zakryj(sciezka.read_bytes())
        paczka = zipfile.ZipFile(io.BytesIO(wynik))
        settings = paczka.read("word/settings.xml").decode("utf-8")
        assert "attachedTemplate" not in settings
        assert "documentProtection" not in settings
        assert "writeProtection" not in settings
        assert "rsids" not in settings
        assert "jan.kowalski" not in settings  # ścieżka szablonu z relacji
        rels_nazwy = paczka.namelist()
        assert "word/_rels/settings.xml.rels" not in rels_nazwy or "rIdTpl" not in paczka.read(
            "word/_rels/settings.xml.rels"
        ).decode()

    def test_zakladki_i_anchor_neutralne(self, pulapki):
        """Nazwy zakładek i kotwice → neutralne _Bm1.."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "Jan_Kowalski_PESEL_44051401359" not in xml, "nazwa zakładki wycieka"
        assert "_Bm1" in xml
        assert xml.count('"_Bm1"') >= 2  # zakładka + kotwica wskazują tę samą

    def test_sdt_alias_tag_czyste(self, pulapki):
        """Alias/tag kontrolki treści usunięte."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "w:alias" not in xml, "alias SDT wycieka"
        assert "w:tag" not in xml, "tag SDT wycieka"
        assert "44051401359" not in xml

    def test_adresy_hiperlaczy_w_rels_usuniete(self, pulapki):
        """Cel odnośnika (ścieżka, query, fragment) nie opuszcza dokumentu."""
        wynik = _zakryj(pulapki)
        rels = zipfile.ZipFile(io.BytesIO(wynik)).read("word/_rels/document.xml.rels").decode("utf-8")
        assert "44051401359" not in rels, "query string z PESEL wycieka"
        assert "Kowalski" not in rels
        assert "portal.firma.pl" not in rels

    def test_docpr_i_vml_czyste(self, pulapki):
        """Name/title docPr i title/alt VML czyszczone."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "Skan_Jan_Kowalski" not in xml, "docPr name wycieka"
        assert "Podpis Jan Kowalski" not in xml, "VML title/alt wycieka"
        assert "44051401359.png" not in xml

    def test_people_custom_glossary_usuwane(self, tmp_path):
        """People.xml, docProps/custom.xml, word/glossary — usuwane."""
        sciezka = zapisz_pulapki(tmp_path / "p.docx", paczkowe="usuwane")
        adapter = AdapterDocx()
        dok = adapter.wczytaj(sciezka.read_bytes())
        wynik = adapter.zapisz(dok)
        paczka = zipfile.ZipFile(io.BytesIO(wynik))
        nazwy = paczka.namelist()
        for usunieta in (
            "word/people.xml",
            "docProps/custom.xml",
            "word/glossary/document.xml",
            "word/glossary/_rels/document.xml.rels",
        ):
            assert usunieta not in nazwy, usunieta
        for czesc in (nazwy, [paczka.read(n) for n in nazwy]):
            pass
        calosc = b"".join(paczka.read(n) for n in nazwy)
        assert b"anna@firma-example.pl" not in calosc
        assert b"custom-properties" not in paczka.read("_rels/.rels")
        typy = paczka.read("[Content_Types].xml").decode()
        assert "people.xml" not in typy
        assert "custom.xml" not in typy
        assert "glossary" not in typy

    def test_smarttag_rozpakowany(self, pulapki):
        """SmartTag rozpakowany, smartTagPr z w:attr usunięty."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "smartTagPr" not in xml, "atrybuty smart taga wycieka"
        assert "GivenName" not in xml
        assert 'w:val="Jan"' not in xml


# --- poprawność wyników: plik otwiera się, XML poprawny, w:tc ma w:p


class TestPoprawnoscWyniku:
    def _sprawdz(self, wynik: bytes) -> None:
        from docx import Document as Otworz

        Otworz(io.BytesIO(wynik))  # otwarcie bez "unreadable content"
        drzewo = etree.fromstring(
            zipfile.ZipFile(io.BytesIO(wynik)).read("word/document.xml")
        )
        for tc in drzewo.iter(f"{W_NS}tc"):
            assert tc.find(f"{W_NS}p") is not None, "komórka tabeli bez akapitu"

    def test_wynik_pelnych_pulapek(self, tmp_path):
        sciezka = zapisz_pulapki(tmp_path / "p.docx")
        self._sprawdz(_zakryj(sciezka.read_bytes()))

    def test_wynik_podstawowego_wzorca(self, wzorzec):
        adapter = AdapterDocx()
        self._sprawdz(adapter.zapisz(adapter.wczytaj(wzorzec.read_bytes())))

    def test_wynik_po_przywroceniu(self, tmp_path):
        from niewidka.detektory import RegulyDetektor
        from niewidka.rdzen import przywroc, ukryj

        sciezka = zapisz_pulapki(tmp_path / "p.docx")
        wynik, mapa, _ = ukryj(sciezka.read_bytes(), "docx", 1, detektor=RegulyDetektor())
        przywrocony, _ = przywroc(wynik, "docx", mapa)
        self._sprawdz(przywrocony)
