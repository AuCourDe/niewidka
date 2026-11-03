"""Format adapter tests: registry, run cuts, txt, docx.

Round-trip: load → detect → markers → save → reload and scan
(save verification ALWAYS).
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
        # all fragments from one source run (left style)
        assert {i for _, i in fragmenty} == {0}

    def test_zamiana_na_granicy_runow(self):
        segment = Segment(
            tekst="Jan Kowalski wrócił",
            runs=[RunInfo("Jan Kowalski", element="a"), RunInfo(" wrócił", element="b")],
            starts=[0, 12],
        )
        fragmenty = podziel_segment(segment, [(0, 12, "[OSOBA_1_F1]")])
        assert [t for t, _ in fragmenty] == ["[OSOBA_1_F1]", " wrócił"]
        # the marker inherits the left fragment's style (run 0), the rest stays in run 1
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
        """Entity split across two runs, run boundary INSIDE the replacement —
        the part beyond the boundary must not return as plain text."""
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


# --- TXT adapter ---

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

    # Windows Notepad and older systems save Polish text in other encodings than UTF-8
    POLSKI = "Zażółć gęślą jaźń. Pismo z Łodzi, Śródmieście, „cudzysłów”."

    @pytest.mark.parametrize("kodowanie", ["cp1250", "iso8859_2", "utf-16", "utf-16-be"])
    def test_wczytaj_inne_kodowania_polskiego_tekstu(self, kodowanie):
        tekst = self.POLSKI if kodowanie != "iso8859_2" else self.POLSKI.replace("„", '"').replace("”", '"')
        dane = tekst.encode(kodowanie)
        if kodowanie == "utf-16-be":
            dane = b"\xfe\xff" + dane  # Notepad writes the byte order mark
        assert AdapterTekst().wczytaj(dane).segmenty[0].tekst == tekst

    def test_utf32_czytany_a_utf16_bez_znacznika_to_blad(self):
        # the UTF-32 mark starts with the UTF-16 one; decoded as UTF-16 the text had a NUL between
        # characters and the rules missed every number
        from niewidka.formaty import BladKodowania

        tekst = "PESEL 44051401359"
        assert AdapterTekst().wczytaj(tekst.encode("utf-32")).segmenty[0].tekst == tekst
        for kodowanie in ("utf-16-le", "utf-16-be", "utf-32-le"):
            with pytest.raises(BladKodowania):
                AdapterTekst().wczytaj(tekst.encode(kodowanie))

    def test_plik_binarny_to_czytelny_blad(self):
        from niewidka.formaty import BladKodowania

        for dane in (b"\x81\x83\x88 bez znaczenia", b"PK\x03\x04\x00\x00\xff\xfe\x00"):
            with pytest.raises(BladKodowania):
                AdapterTekst().wczytaj(dane)


# --- wstaw_znaczniki: shared segment flow (cut + run copy) ---

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
        # the marker fragment inherits the left run's element
        assert segment.runs[1].element == ("klon", "a", "[PESEL_1]")
        assert segment.starts == [0, 6, 15]  # 6 + len("[PESEL_1]")


# --- DOCX adapter ---

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
        assert any("Anna Nowak" in t for t in teksty)  # table
        # table cells = separate paragraphs = separate segments
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
        assert "Kancelaria Nowak" not in calosc  # header cleaned
        assert "Sprawdziła Anna" not in calosc  # comment cleaned
        assert "ul. Lipowa 13/5" not in calosc  # footnote cleaned

    def test_track_changes_del_usuniety_ins_zostaje(self, wzorzec):
        dok = AdapterDocx().wczytaj(wzorzec.read_bytes())
        calosc = "\n".join(s.tekst for s in dok.segmenty)
        assert "stary numer 700 800 900" not in calosc  # w:del removed
        assert "nowy numer 111 222 333" in calosc  # w:ins = content
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
        """Detect with rules per segment, insert [TYP_N] markers."""
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

        # save verification ALWAYS: reload and scan
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
        assert "1234563218" not in calosc  # NIP from the table
        # trap (11 digits without a valid checksum) stays masked as suspicious
        assert "12345678901" not in calosc
        # note at the start of the document
        assert dok2.segmenty[0].tekst.startswith("ZANONIMIZOWANY. Dane osobowe")

    def test_round_trip_styl_bold_na_znaczniku(self, wzorzec):
        adapter = AdapterDocx()
        dok = adapter.wczytaj(wzorzec.read_bytes())
        self._zakryj_regulami(adapter, dok)
        wynik = adapter.zapisz(dok)
        dok2 = adapter.wczytaj(wynik)
        segment = next(s for s in dok2.segmenty if "[PESEL_1]" in s.tekst)
        # PESEL sits in a plain run; the marker inherits the left fragment's style
        run_ze_znacznikiem = next(r for r in segment.runs if "[PESEL_1]" in r.tekst)
        from docx.oxml.ns import qn

        bold = run_ze_znacznikiem.element.findall(f"{qn('w:rPr')}/{qn('w:b')}")
        assert bold == []  # left run ("Umowa z ") is not bold

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
        assert "napisz do Jana" in doc_xml  # text from the unwrapped mailto stays
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
        # alt text may carry PII ("Logo z adresem ul. Lipowa 13/5")
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
        assert b'Extension="jpeg"' in wynik  # the part exists: Default must stay

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


# --- DOCX traps ---

from lxml import etree

from narzedzia.generator_dokumentow import dokument_pulapki, zapisz_pulapki

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture()
def pulapki():
    bufor = io.BytesIO()
    dokument_pulapki().save(bufor)
    return bufor.getvalue()


def _zakryj(dane: bytes) -> bytes:
    """Full flow: rules → markers → save (no models)."""
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
        """Instruction of a complex field with PII — removed; the field result stays."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "instrText" not in xml, "instrukcja pola z PII wycieka"
        assert "Jan Kowalski" in xml  # field result (w:t) stays as text

    def test_fldSimple_bez_instr(self, pulapki):
        """The w:instr attribute of a simple field is cleaned."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert 'w:instr="' not in xml, "w:instr pola prostego wycieka"
        assert "Anna Nowak" in xml  # field result stays

    def test_ins_osierocone_wt_wchodzi_do_segmentow(self, pulapki):
        """W:t without w:r inside w:ins — after normalization goes into segments."""
        dok = AdapterDocx().wczytaj(pulapki)
        calosc = "\n".join(s.tekst for s in dok.segmenty)
        assert "PESEL 44051401359 poza runem" in calosc, "osierocone w:t omija detekcję"
        wynik = _zakryj(pulapki)
        assert "44051401359 poza runem" not in _document_xml(wynik)

    def test_atrybuty_rewizji_czyste(self, pulapki):
        """W:author/w:date/w:initials from tracked changes removed."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "w:author=" not in xml, "tożsamość autora rewizji wycieka"
        assert "w:date=" not in xml
        assert "w:initials=" not in xml
        assert "Anna Zielińska" not in xml

    def test_komorka_po_del_ma_akapit_i_plik_poprawny(self, pulapki):
        """A cell with only w:del must not remain an empty w:tc."""
        wynik = _zakryj(pulapki)
        drzewo = etree.fromstring(_document_xml(wynik).encode())
        puste = [tc for tc in drzewo.iter(f"{W_NS}tc") if tc.find(f"{W_NS}p") is None]
        assert puste == [], f"komórki bez w:p: {len(puste)}"
        from docx import Document as Otworz

        Otworz(io.BytesIO(wynik))  # file opens without "unreadable content"

    def test_rels_usuwanych_czesci_nie_blokuja_i_znikaja(self, tmp_path):
        """Word/_rels/header1.xml.rels — handled, not a block."""
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
        assert "jan.kowalski" not in settings  # template path from the relation
        rels_nazwy = paczka.namelist()
        assert "word/_rels/settings.xml.rels" not in rels_nazwy or "rIdTpl" not in paczka.read(
            "word/_rels/settings.xml.rels"
        ).decode()

    def test_zakladki_i_anchor_neutralne(self, pulapki):
        """Bookmark names and anchors → neutral _Bm1.."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "Jan_Kowalski_PESEL_44051401359" not in xml, "nazwa zakładki wycieka"
        assert "_Bm1" in xml
        assert xml.count('"_Bm1"') >= 2  # bookmark + anchor point to the same one

    def test_sdt_alias_tag_czyste(self, pulapki):
        """Content control alias/tag removed."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "w:alias" not in xml, "alias SDT wycieka"
        assert "w:tag" not in xml, "tag SDT wycieka"
        assert "44051401359" not in xml

    def test_adresy_hiperlaczy_w_rels_usuniete(self, pulapki):
        """Link target (path, query, fragment) does not leave the document."""
        wynik = _zakryj(pulapki)
        rels = zipfile.ZipFile(io.BytesIO(wynik)).read("word/_rels/document.xml.rels").decode("utf-8")
        assert "44051401359" not in rels, "query string z PESEL wycieka"
        assert "Kowalski" not in rels
        assert "portal.firma.pl" not in rels

    def test_docpr_i_vml_czyste(self, pulapki):
        """Name/title of docPr and title/alt of VML cleaned."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "Skan_Jan_Kowalski" not in xml, "docPr name wycieka"
        assert "Podpis Jan Kowalski" not in xml, "VML title/alt wycieka"
        assert "44051401359.png" not in xml

    def test_people_custom_glossary_usuwane(self, tmp_path):
        """People.xml, docProps/custom.xml, word/glossary — removed."""
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
        """SmartTag unwrapped, smartTagPr with w:attr removed."""
        wynik = _zakryj(pulapki)
        xml = _document_xml(wynik)
        assert "smartTagPr" not in xml, "atrybuty smart taga wycieka"
        assert "GivenName" not in xml
        assert 'w:val="Jan"' not in xml


# --- result correctness: file opens, XML valid, w:tc has w:p ---


class TestPoprawnoscWyniku:
    def _sprawdz(self, wynik: bytes) -> None:
        from docx import Document as Otworz

        Otworz(io.BytesIO(wynik))  # opens without "unreadable content"
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


# --- raw packages: content outside plain paragraphs ---

import re

from niewidka.model import TypEncji, Zakres

_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
)
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_TYP = "application/vnd.openxmlformats-officedocument.wordprocessingml"


def _paczka(
    body: str, czesci: dict[str, str | bytes] | None = None, relacje: str = "", core: bool = True
) -> bytes:
    """A minimal package around `body`; `czesci` = extra parts, `relacje` = document relations."""
    czesci = dict(czesci or {})
    nadpisania = "".join(
        f'<Override PartName="/{nazwa}" ContentType="{_TYP}.{nazwa.rsplit("/", 1)[1][:-4]}+xml"/>'
        for nazwa in czesci
        if nazwa.endswith(".xml")
    )
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w") as paczka:
        paczka.writestr(
            "[Content_Types].xml",
            f'{_XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
            f'<Override PartName="/word/document.xml" ContentType="{_TYP}.document.main+xml"/>{nadpisania}</Types>',
        )
        paczka.writestr(
            "_rels/.rels",
            f'{_XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="word/document.xml"/></Relationships>',
        )
        paczka.writestr(
            "word/_rels/document.xml.rels",
            f'{_XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{relacje}</Relationships>",
        )
        if core:
            paczka.writestr(
                "docProps/core.xml",
                f'{_XML}<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
                'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                "<dc:creator>x</dc:creator></cp:coreProperties>",
            )
        paczka.writestr("word/document.xml", f"{_XML}<w:document {_NS}><w:body>{body}</w:body></w:document>")
        for nazwa, tresc in czesci.items():
            paczka.writestr(nazwa, tresc)
    return bufor.getvalue()


class _Frazy:
    """Stub person detector: every occurrence of the given phrases."""

    nazwa = "frazy"
    typy = frozenset({TypEncji.OSOBA})

    def __init__(self, *frazy: str):
        self.frazy = frazy

    def znajdz(self, tekst: str) -> list[Zakres]:
        return [
            Zakres(m.start(), m.end(), TypEncji.OSOBA, 0.99, self.nazwa)
            for fraza in self.frazy
            for m in re.finditer(re.escape(fraza), tekst)
        ]


def _teksty(dane: bytes) -> list[str]:
    return [s.tekst for s in AdapterDocx().wczytaj(dane).segmenty]


def _ukryj_i_przywroc(dane: bytes, *frazy: str):
    from niewidka.rdzen import przywroc, ukryj

    wynik, mapa, raport = ukryj(dane, "docx", 1, detektor=_Frazy(*frazy))
    przywrocony, rozbieznosci = przywroc(wynik, "docx", mapa)
    assert rozbieznosci == []
    return wynik, raport, przywrocony


_POLE_VML = (
    '<w:r><w:pict><v:shape id="s1"><v:textbox><w:txbxContent>'
    "<w:p><w:r><w:t>Adresat: Jan Nowak</w:t></w:r></w:p>"
    "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
)


class TestTrescPozaAkapitem:
    def test_pole_tekstowe_to_osobny_segment_bez_powtorzen(self):
        body = f'<w:p><w:r><w:t xml:space="preserve">Pismo do </w:t></w:r>{_POLE_VML}</w:p>'
        assert _teksty(_paczka(body)) == ["Pismo do ", "Adresat: Jan Nowak"]

    def test_pole_tekstowe_ukryte_i_przywrocone(self):
        body = f'<w:p><w:r><w:t xml:space="preserve">Pismo do Maria Lis </w:t></w:r>{_POLE_VML}</w:p>'
        wynik, raport, przywrocony = _ukryj_i_przywroc(_paczka(body), "Jan Nowak", "Maria Lis")
        assert raport.status == "ukonczony"
        assert _teksty(wynik)[1:] == ["Pismo do [OSOBA_1_F1] ", "Adresat: [OSOBA_2_F1]"]
        assert "txbxContent" in _document_xml(wynik)
        assert _teksty(przywrocony) == ["Pismo do Maria Lis ", "Adresat: Jan Nowak"]

    def test_pole_tekstowe_zostaje_gdy_obrazy_sa_usuwane(self):
        obraz = (
            '<w:r><w:drawing><wp:inline><wp:docPr id="1" name="x"/><a:graphic><a:graphicData>'
            '<pic:pic><pic:blipFill><a:blip r:embed="rIdObraz"/></pic:blipFill></pic:pic>'
            "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
        )
        pole = (
            '<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor>'
            '<wp:docPr id="2" name="y"/><a:graphic><a:graphicData><wps:wsp><wps:txbx><w:txbxContent>'
            "<w:p><w:r><w:t>Adresat: Jan Nowak</w:t></w:r></w:p></w:txbxContent></wps:txbx></wps:wsp>"
            "</a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>"
            f"<mc:Fallback>{_POLE_VML[5:-6]}</mc:Fallback></mc:AlternateContent></w:r>"
        )
        relacja = (
            '<Relationship Id="rIdObraz" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/image" Target="media/image1.png"/>'
        )
        dane = _paczka(
            f"<w:p>{obraz}</w:p><w:p>{pole}</w:p>",
            {"word/media/image1.png": b"\x89PNG\r\n\x1a\n"},
            relacje=relacja,
        )
        wynik, raport, przywrocony = _ukryj_i_przywroc(dane, "Jan Nowak")
        assert raport.status == "ukonczony"
        assert _teksty(wynik)[1:] == ["[OBRAZ USUNIĘTY]", "", "Adresat: [OSOBA_1_F1]", "Adresat: [OSOBA_1_F1]"]
        assert _teksty(przywrocony) == ["[OBRAZ USUNIĘTY]", "", "Adresat: Jan Nowak", "Adresat: Jan Nowak"]

    def test_symbol_i_podzial_strony_zostaja_w_akapicie_ze_znacznikiem(self):
        body = (
            '<w:p><w:r><w:t xml:space="preserve">Wnioskodawca Jan Nowak </w:t></w:r>'
            '<w:r><w:sym w:font="Wingdings" w:char="F0FE"/></w:r>'
            '<w:r><w:t xml:space="preserve"> zgoda</w:t></w:r><w:r><w:br w:type="page"/></w:r>'
            "<w:r><w:t>Dalej</w:t></w:r></w:p>"
        )
        wynik, _, przywrocony = _ukryj_i_przywroc(_paczka(body), "Jan Nowak")
        for dane in (wynik, przywrocony):
            xml = _document_xml(dane)
            assert re.search(r"zgoda.*w:type=\"page\".*Dalej", xml)
            assert re.search(r"\]?</w:t></w:r>.*<w:sym [^>]*/>.*zgoda", xml)

    def test_twardy_lacznik_zostaje_na_miejscu(self):
        body = (
            '<w:p><w:r><w:t xml:space="preserve">Wnioskodawczyni Anna Nowak</w:t><w:noBreakHyphen/>'
            '<w:t xml:space="preserve">Kowalska prosi.</w:t></w:r></w:p>'
        )
        dane = _paczka(body)
        assert _teksty(dane) == ["Wnioskodawczyni Anna Nowak-Kowalska prosi."]
        wynik, _, przywrocony = _ukryj_i_przywroc(dane, "Anna Nowak-Kowalska")
        assert _teksty(wynik)[1:] == ["Wnioskodawczyni [OSOBA_1_F1] prosi."]
        assert _teksty(przywrocony) == ["Wnioskodawczyni Anna Nowak-Kowalska prosi."]

    def test_pole_proste_rozpakowane_bez_utraty_tekstu(self):
        body = '<w:p><w:fldSimple w:instr=" MERGEFIELD Nazwisko "><w:r><w:t>Jan Nowak</w:t></w:r></w:fldSimple></w:p>'
        wynik, _, przywrocony = _ukryj_i_przywroc(_paczka(body), "Jan Nowak")
        assert "fldSimple" not in _document_xml(wynik)
        assert _teksty(przywrocony) == ["Jan Nowak"]

    def test_pole_zlozone_zostaje_zwyklym_tekstem(self):
        # the instruction may carry data and is removed; Word hides the result of a field whose
        # code is empty, so the field characters go too and the result is plain text
        body = (
            '<w:p><w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:name w:val="Tekst1"/>'
            '<w:textInput><w:default w:val="Maria Lis"/></w:textInput></w:ffData></w:fldChar></w:r>'
            '<w:r><w:instrText xml:space="preserve"> FORMTEXT </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>Maria Lis</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
        )
        wynik, _, przywrocony = _ukryj_i_przywroc(_paczka(body), "Maria Lis")
        for dane in (wynik, przywrocony):
            xml = _document_xml(dane)
            assert not re.search(r"fldChar|instrText|ffData|Tekst1", xml), xml
        assert "Maria Lis" not in _document_xml(wynik)
        assert _teksty(przywrocony) == ["Maria Lis"]

    def test_sledzone_zmiany_formatowania_i_przeniesienia_przyjete(self):
        body = (
            '<w:p><w:r><w:rPr><w:b/><w:rPrChange w:id="5" w:author="Anna Zielińska" '
            'w:date="2026-01-01T00:00:00Z"><w:rPr/></w:rPrChange></w:rPr><w:t>tekst</w:t></w:r></w:p>'
            '<w:p><w:moveFrom w:id="6" w:author="Anna Zielińska"><w:r><w:t>stare miejsce</w:t></w:r></w:moveFrom>'
            '<w:moveTo w:id="7" w:author="Anna Zielińska"><w:r><w:t>nowe miejsce</w:t></w:r></w:moveTo></w:p>'
        )
        wynik, _, _ = _ukryj_i_przywroc(_paczka(body))
        xml = _document_xml(wynik)
        assert "<w:b/>" in xml
        assert not re.search(r"rPrChange|moveFrom|moveTo|w:author|Zielińska", xml)
        assert _teksty(wynik)[1:] == ["tekst", "nowe miejsce"]

    def test_tekst_w_atrybutach_wyczyszczony(self):
        # a hyperlink tooltip and target location, the editor of a permission range and the list
        # items of a content control are free text that no segment reads
        body = (
            '<w:p><w:hyperlink w:anchor="sekcja" w:tooltip="Kontakt: Jan Nowak" w:docLocation="Jan Nowak">'
            '<w:r><w:t>Zobacz</w:t></w:r></w:hyperlink><w:permStart w:id="1" w:ed="jan.nowak@example.com"/>'
            '<w:r><w:t xml:space="preserve"> tekst</w:t></w:r><w:permEnd w:id="1"/></w:p>'
            '<w:sdt><w:sdtPr><w:dropDownList w:lastValue="Maria Lis">'
            '<w:listItem w:displayText="Maria Lis" w:value="Maria Lis"/></w:dropDownList></w:sdtPr>'
            "<w:sdtContent><w:p><w:r><w:t>Wybór</w:t></w:r></w:p></w:sdtContent></w:sdt>"
        )
        wynik, raport, _ = _ukryj_i_przywroc(_paczka(body))
        xml = _document_xml(wynik)
        assert not re.search(r"Nowak|nowak|Maria Lis|tooltip|docLocation|permStart|listItem|lastValue", xml), xml
        assert raport.status == "ukonczony"
        assert _teksty(wynik)[1:] == ["Zobacz tekst", "Wybór"]

    def test_zmienne_dokumentu_usuniete(self):
        settings = (
            f"{_XML}<w:settings {_NS}><w:docVars>"
            '<w:docVar w:name="Klient" w:val="Bartłomiej Wierzbicki, ul. Lipowa 5"/></w:docVars></w:settings>'
        )
        dane = _paczka("<w:p><w:r><w:t>Treść pisma.</w:t></w:r></w:p>", {"word/settings.xml": settings})
        wynik, raport, _ = _ukryj_i_przywroc(dane)
        tresc = zipfile.ZipFile(io.BytesIO(wynik)).read("word/settings.xml").decode()
        assert "docVar" not in tresc and "Wierzbicki" not in tresc
        assert raport.status == "ukonczony"

    def test_przypisy_koncowe_usuwane_jak_dolne(self):
        przypisy = (
            f'{_XML}<w:endnotes {_NS}><w:endnote w:id="1"><w:p><w:r><w:t>Jan Nowak</w:t></w:r></w:p>'
            "</w:endnote></w:endnotes>"
        )
        relacja = (
            '<Relationship Id="rIdKonc" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/endnotes" Target="endnotes.xml"/>'
        )
        body = '<w:p><w:r><w:t>Pismo.</w:t></w:r><w:r><w:endnoteReference w:id="1"/></w:r></w:p>'
        dane = _paczka(body, {"word/endnotes.xml": przypisy}, relacje=relacja)
        wynik, _, _ = _ukryj_i_przywroc(dane)
        paczka = zipfile.ZipFile(io.BytesIO(wynik))
        assert "word/endnotes.xml" not in paczka.namelist()
        assert "endnoteReference" not in _document_xml(wynik)
        for nazwa in ("[Content_Types].xml", "word/_rels/document.xml.rels"):
            assert b"endnotes" not in paczka.read(nazwa), nazwa

    def test_paczka_bez_core_xml(self):
        dane = _paczka("<w:p><w:r><w:t>Pismo do Jan Nowak.</w:t></w:r></w:p>", core=False)
        wynik, _, przywrocony = _ukryj_i_przywroc(dane, "Jan Nowak")
        assert _teksty(wynik)[1:] == ["Pismo do [OSOBA_1_F1]."]
        assert _teksty(przywrocony) == ["Pismo do Jan Nowak."]
