"""Generator plików wzorcowych DOCX do testów round-trip.

Wzorce zawierają to, co adapter DOCX musi obsłużyć: runy z przeplotem
stylów, tabelę, nagłówek/stopkę z treścią, komentarz, śledzone zmiany (w:ins/w:del),
hiperłącza http i mailto, przypis (część footnotes), obraz (mały PNG, tekst
alternatywny), właściwości dokumentu oraz wariant z makrem (vbaProject.bin).

    .venv/bin/python -m narzedzia.generator_dokumentow tests/wzorce
"""

from __future__ import annotations

import argparse
import struct
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

from docx import Document
from lxml import etree


def _png_1x1() -> bytes:
    """Minimalny poprawny PNG 1×1 (szary piksel), składany struct+zlib."""
    sygnatura = b"\x89PNG\r\n\x1a\n"

    def kawalek(typ: bytes, dane: bytes) -> bytes:
        return struct.pack(">I", len(dane)) + typ + dane + struct.pack(">I", zlib.crc32(typ + dane))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)  # 1×1, 8-bit, skala szarości
    idat = zlib.compress(b"\x00\x88")  # filtr 0 + piksel
    return sygnatura + kawalek(b"IHDR", ihdr) + kawalek(b"IDAT", idat) + kawalek(b"IEND", b"")


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _doc_podstawowy() -> Document:
    """Treść podstawowa: runy z przeplotem stylów + tabela + właściwości."""
    dok = Document()
    dok.core_properties.author = "Jan Kowalski"
    dok.core_properties.last_modified_by = "Anna Zielińska"
    dok.core_properties.title = "Tajna umowa"
    dok.core_properties.comments = "Notatka wewnętrzna HR"

    p1 = dok.add_paragraph()
    p1.add_run("Umowa z ")
    p1.add_run("Janem Kowalskim").bold = True
    p1.add_run(", PESEL 44051401359, telefon +48 601 234 567.")
    dok.add_paragraph("Poufne: karta pacjenta nr 12345678901 w archiwum.")  # 11 cyfr — pułapka PESEL
    p3 = dok.add_paragraph()
    p3.add_run("Kontakt e-mail: ")
    p3.add_run("biuro@firma-example.pl")

    tabela = dok.add_table(rows=2, cols=2)
    tabela.cell(0, 0).paragraphs[0].add_run("Pracownik")
    tabela.cell(0, 1).paragraphs[0].add_run("Anna Nowak")
    tabela.cell(1, 0).paragraphs[0].add_run("NIP")
    tabela.cell(1, 1).paragraphs[0].add_run("1234563218")
    return dok


def _dodaj_naglowek_stopke(dok: Document) -> None:
    sekcja = dok.sections[0]
    sekcja.header.paragraphs[0].text = "Kancelaria Nowak i Wspólnicy — tajne"
    sekcja.footer.paragraphs[0].text = "Strona: przygotował Jan Kowalski"


def _dodaj_komentarz(dok: Document) -> None:
    dok.add_comment(
        runs=dok.paragraphs[0].runs[:1],
        text="Sprawdziła Anna Zielińska, tel. 602 345 678",
    )


def _dodaj_hiperlacza(dok: Document) -> None:
    from docx.oxml.ns import qn

    def hyperlink(paragraf, url: str, tekst: str) -> None:
        id_relacji = dok.part.relate_to(
            url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
            is_external=True,
        )
        link = paragraf.part.element.makeelement(qn("w:hyperlink"), {qn("r:id"): id_relacji})
        run = paragraf.add_run(tekst)
        link.append(run._element)
        paragraf._element.append(link)

    p = dok.add_paragraph()
    hyperlink(p, "https://example.com/oferta", "Oferta na stronie")
    p2 = dok.add_paragraph()
    hyperlink(p2, "mailto:jan.kowalski@firma-example.pl", "napisz do Jana")


def _dodaj_track_changes(dok: Document) -> None:
    """Śledzone zmiany: w:del>w:r>w:delText + w:ins>w:r>w:t (poprawny OOXML)."""
    paragraf = dok.add_paragraph()

    def zmiana(tag: str, id_: str, tekst: str, tag_tekstu: str) -> etree._Element:
        zewnetrzny = etree.SubElement(paragraf._element, f"{W}{tag}")
        zewnetrzny.set(f"{W}id", id_)
        zewnetrzny.set(f"{W}author", "Anna Zielińska")
        zewnetrzny.set(f"{W}date", "2026-10-28T10:00:00Z")
        run = etree.SubElement(zewnetrzny, f"{W}r")
        t = etree.SubElement(run, f"{W}{tag_tekstu}")
        t.text = tekst
        return zewnetrzny

    zmiana("del", "1", "stary numer 700 800 900", "delText")
    zmiana("ins", "2", "nowy numer 111 222 333", "t")
    paragraf.add_run("ZMIENIONY")


def _dodaj_obraz(dok: Document) -> None:
    strumien = BytesIO(_png_1x1())
    obraz = dok.add_picture(strumien, width=914400 // 4)  # 0.25"
    dok.inline_shapes[-1]._inline.docPr.set("descr", "Logo z adresem ul. Lipowa 13/5")
    assert obraz is not None


def _dodaj_przypis(dok: Document) -> None:
    """Część footnotes.xml + odniesienie w treści (wstawione ręcznie)."""
    paragraf = dok.add_paragraph()
    run = paragraf.add_run("Pełne dane w przypisie")
    odnosnik = run._element.makeelement(f"{W}footnoteReference", {f"{W}id": "1"})
    run._element.append(odnosnik)

    czesc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
        '<w:footnote w:id="1"><w:p><w:r><w:t>Jan Kowalski, ul. Lipowa 13/5, 00-001 Warszawa'
        "</w:t></w:r></w:p></w:footnote></w:footnotes>"
    )
    nazwa = "word/footnotes.xml"
    pakiet = dok.part.package
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part

    uri = PackURI("/" + nazwa)
    czesc_part = Part(uri, "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml", czesc.encode(), pakiet)
    pakiet.main_document_part.relate_to(czesc_part, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes")


def zapisz_podstawowy(sciezka: Path) -> Path:
    dok = _doc_podstawowy()
    _dodaj_naglowek_stopke(dok)
    _dodaj_komentarz(dok)
    _dodaj_hiperlacza(dok)
    _dodaj_track_changes(dok)
    _dodaj_obraz(dok)
    _dodaj_przypis(dok)
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    dok.save(sciezka)
    return sciezka


def zapisz_z_makrem(sciezka: Path) -> Path:
    """Plik z vbaProject.bin (fałszywa zawartość) — adapter ma BLOKOWAĆ."""
    zapisz_podstawowy(sciezka)
    zrodlo = zipfile.ZipFile(sciezka, "r")
    czesci = {n: zrodlo.read(n) for n in zrodlo.namelist()}
    zrodlo.close()
    czesci["word/vbaProject.bin"] = b"\xd0\xcf\x11\xe0fa\x15s\x01\x00\x00\xffFFake OLE"
    with zipfile.ZipFile(sciezka, "w", zipfile.ZIP_DEFLATED) as cel:
        for nazwa, zawartosc in czesci.items():
            cel.writestr(nazwa, zawartosc)
    return sciezka


def zapisz_czesc_obca(sciezka: Path) -> Path:
    """Część spoza allowlisty (custom XML) — adapter ma BLOKOWAĆ."""
    zapisz_podstawowy(sciezka)
    zrodlo = zipfile.ZipFile(sciezka, "r")
    czesci = {n: zrodlo.read(n) for n in zrodlo.namelist()}
    zrodlo.close()
    czesci["word/embeddings/obiekt.bin"] = b"\xd0\xcf\x11\xe0 osadzony obiekt"
    with zipfile.ZipFile(sciezka, "w", zipfile.ZIP_DEFLATED) as cel:
        for nazwa, zawartosc in czesci.items():
            cel.writestr(nazwa, zawartosc)
    return sciezka


# --- wzorzec pułapek: pułapki DOCX ---

R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
DATA_REWIZJI = "2026-10-28T10:00:00Z"


def _run(paragraf_el, tag: str, tekst: str = ""):
    run = etree.SubElement(paragraf_el, f"{W}{tag}")
    if tekst:
        t = etree.SubElement(run, f"{W}t")
        t.text = tekst
    return run


def _dodaj_pola(dok: Document) -> None:
    """Pkt 2+3: instrukcja pola złożonego (w:instrText) i prostego (w:fldSimple
    w:instr) z PII; wynik pola w w:t zostaje legalnie."""
    el = dok.add_paragraph()._element
    begin = _run(el, "r")
    etree.SubElement(begin, f"{W}fldChar").set(f"{W}fldCharType", "begin")
    instr = _run(el, "r")
    instr_t = etree.SubElement(instr, f"{W}instrText")
    instr_t.text = ' AUTHOR "Jan Kowalski" '
    sep = _run(el, "r")
    etree.SubElement(sep, f"{W}fldChar").set(f"{W}fldCharType", "separate")
    _run(el, "r", "Jan Kowalski")  # wynik pola — zostaje jako tekst
    end = _run(el, "r")
    etree.SubElement(end, f"{W}fldChar").set(f"{W}fldCharType", "end")
    fld = etree.SubElement(el, f"{W}fldSimple")
    fld.set(f"{W}instr", 'AUTHOR "Anna Nowak"')
    _run(fld, "r", "Anna Nowak")


def _dodaj_ins_osierocony(dok: Document) -> None:
    """Pkt 4: w:t bezpośrednio w w:ins, bez w:r — poza segmentami adaptera."""
    ins = etree.SubElement(dok.add_paragraph()._element, f"{W}ins")
    ins.set(f"{W}id", "30")
    ins.set(f"{W}author", "Jan Kowalski")
    ins.set(f"{W}date", DATA_REWIZJI)
    t = etree.SubElement(ins, f"{W}t")
    t.text = "Awaria: PESEL 44051401359 poza runem"


def _dodaj_rpr_change(dok: Document) -> None:
    """Pkt 5: rewizja formatowania z tożsamością autora."""
    run = dok.add_paragraph("Robocze sformułowanie").runs[0]
    rpr = run._element.get_or_add_rPr()
    change = etree.SubElement(rpr, f"{W}rPrChange")
    change.set(f"{W}id", "31")
    change.set(f"{W}author", "Anna Nowak")
    change.set(f"{W}date", DATA_REWIZJI)


def _dodaj_tabele_z_del(dok: Document) -> None:
    """Pkt 6: komórka, której cała treść to śledzone usunięcie — po czyszczeniu
    w:del komórka nie może zostać pusta (bez w:p plik jest uszkodzony)."""
    tabela = dok.add_table(rows=1, cols=1)
    tc = tabela.cell(0, 0)._tc
    for p in tc.findall(f"{W}p"):
        tc.remove(p)
    usuniete = etree.SubElement(tc, f"{W}del")
    usuniete.set(f"{W}id", "32")
    usuniete.set(f"{W}author", "Anna Zielińska")
    usuniete.set(f"{W}date", DATA_REWIZJI)
    p = etree.SubElement(usuniete, f"{W}p")
    _run(p, "r", "usunięty numer 700 800 900").find(f"{W}t").tag = f"{W}delText"


def _dodaj_zakladke_i_anchor(dok: Document) -> None:
    """Pkt 9+14: nazwa zakładki i kotwica hiperłącza z PII."""
    paragraf = dok.add_paragraph()
    el = paragraf._element
    start = etree.SubElement(el, f"{W}bookmarkStart")
    start.set(f"{W}id", "40")
    start.set(f"{W}name", "Jan_Kowalski_PESEL_44051401359")
    paragraf.add_run("Profil klienta")
    koniec = etree.SubElement(el, f"{W}bookmarkEnd")
    koniec.set(f"{W}id", "40")
    link = etree.SubElement(el, f"{W}hyperlink")
    link.set(f"{W}anchor", "Jan_Kowalski_PESEL_44051401359")
    _run(link, "r", "skok do sekcji")


def _dodaj_sdt(dok: Document) -> None:
    """Pkt 10: kontrolka treści z PII w alias/tag; sama treść neutralna."""
    sdt = etree.SubElement(dok.add_paragraph()._element, f"{W}sdt")
    sdt_pr = etree.SubElement(sdt, f"{W}sdtPr")
    alias = etree.SubElement(sdt_pr, f"{W}alias")
    alias.set(f"{W}val", "Jan Kowalski")
    tag = etree.SubElement(sdt_pr, f"{W}tag")
    tag.set(f"{W}val", "PESEL 44051401359")
    tresc = etree.SubElement(sdt, f"{W}sdtContent")
    p = etree.SubElement(tresc, f"{W}p")
    _run(p, "r", "PL")


def _dodaj_link_query(dok: Document) -> None:
    """Pkt 11: zewnętrzny URL z danymi osobowymi w query stringu."""
    id_relacji = dok.part.relate_to(
        "https://portal.firma.pl/ankieta?pesel=44051401359&nazwisko=Kowalski",
        f"{R}hyperlink",
        is_external=True,
    )
    link = etree.SubElement(dok.add_paragraph()._element, f"{W}hyperlink")
    link.set(f"{R}id", id_relacji)
    _run(link, "r", "Formularz")


def _dodaj_docpr_i_vml(dok: Document) -> None:
    """Pkt 12: metadane grafiki — DrawingML docPr name/title i VML title/alt."""
    _dodaj_obraz(dok)
    inline = dok.inline_shapes[-1]._inline
    inline.docPr.set("name", "Skan_Jan_Kowalski_PESEL_44051401359.png")
    inline.docPr.set("title", "Jan Kowalski")
    V = "urn:schemas-microsoft-com:vml"
    run = _run(dok.add_paragraph()._element, "r")
    pict = etree.SubElement(run, f"{W}pict")
    shape = etree.SubElement(pict, f"{{{V}}}shape")
    shape.set("title", "Podpis Jan Kowalski")
    shape.set("alt", "Podpis Jan Kowalski")


def _dodaj_smarttag(dok: Document) -> None:
    """Pkt 15: smart tag z PII w w:attr; treść runu zostaje."""
    st = etree.SubElement(dok.add_paragraph()._element, f"{W}smartTag")
    st.set(f"{W}element", "urn:contact:PersonName")
    st.set(f"{W}uri", "urn:schemas-microsoft-com:office:smarttags")
    pr = etree.SubElement(st, f"{W}smartTagPr")
    for nazwa, wartosc in (("GivenName", "Jan"), ("FamilyName", "Kowalski")):
        atrybut = etree.SubElement(pr, f"{W}attr")
        atrybut.set(f"{W}name", nazwa)
        atrybut.set(f"{W}val", wartosc)
    _run(st, "r", "Jan Kowalski")


PEOPLE_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:people xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:person w:author="Anna Zielińska"><w:presenceInfo userId="anna@firma-example.pl"/>'
    "</w:person></w:people>"
)
CUSTOM_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties">'
    '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="Klient">'
    "<vt:lpwstr>Jan Kowalski</vt:lpwstr></property></Properties>"
)
GLOSSARY_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:glossaryDocument xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:docParts><w:docPart><w:docPartGallery w:val=\"Szybkie części Jan Kowalski\"/>"
    "</w:docPart></w:docParts></w:glossaryDocument>"
)
SETTINGS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<w:zoom w:percent="100"/><w:attachedTemplate r:id="rIdTpl"/>'
    '<w:documentProtection w:edit="readOnly" w:enforcement="1"/>'
    '<w:writeProtection w:author="Jan Kowalski"/>'
    '<w:rsids><w:rsidRoot w:val="4405140A"/><w:rsid w:val="4405140A"/></w:rsids>'
    "</w:settings>"
)
SETTINGS_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rIdTpl" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
    'Target="file:///C:/Users/jan.kowalski/Szablony/umowa.dotx" TargetMode="External"/>'
    "</Relationships>"
)
HEADER_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
    'Target="media/logo.png"/></Relationships>'
)


def dokument_pulapki() -> Document:
    """Treść z pułapkami punktów 2-6, 9-12, 15 (bez wstrzyknięć paczkowych)."""
    dok = _doc_podstawowy()
    _dodaj_naglowek_stopke(dok)
    _dodaj_komentarz(dok)
    _dodaj_hiperlacza(dok)
    _dodaj_track_changes(dok)
    _dodaj_przypis(dok)
    _dodaj_pola(dok)
    _dodaj_ins_osierocony(dok)
    _dodaj_rpr_change(dok)
    _dodaj_tabele_z_del(dok)
    _dodaj_zakladke_i_anchor(dok)
    _dodaj_sdt(dok)
    _dodaj_link_query(dok)
    _dodaj_docpr_i_vml(dok)
    _dodaj_smarttag(dok)
    return dok


def zapisz_pulapki(sciezka: Path, paczkowe: str = "wszystko") -> Path:
    """Wzorzec z pułapkami treściowymi + wstrzyknięte części paczkowe.

    `paczkowe`: "wszystko", "header" (7), "settings" (8), "usuwane" (13).
    """
    dok = dokument_pulapki()
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    dok.save(sciezka)
    zrodlo = zipfile.ZipFile(sciezka, "r")
    czesci = {n: zrodlo.read(n) for n in zrodlo.namelist()}
    zrodlo.close()
    if paczkowe in ("wszystko", "settings"):
        czesci["word/settings.xml"] = SETTINGS_XML.encode()
        czesci["word/_rels/settings.xml.rels"] = SETTINGS_RELS_XML.encode()
    if paczkowe in ("wszystko", "header"):
        czesci["word/_rels/header1.xml.rels"] = HEADER_RELS_XML.encode()
    if paczkowe in ("wszystko", "usuwane"):
        czesci["word/people.xml"] = PEOPLE_XML.encode()
        czesci["docProps/custom.xml"] = CUSTOM_XML.encode()
        czesci["word/glossary/document.xml"] = GLOSSARY_XML.encode()
        czesci["word/glossary/_rels/document.xml.rels"] = HEADER_RELS_XML  # relacje galerii też lecą
        typy = czesci["[Content_Types].xml"].decode()
        typy = typy.replace(
            "</Types>",
            '<Override PartName="/word/people.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.people+xml"/>'
            '<Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-props+xml"/>'
            '<Override PartName="/word/glossary/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.template.docParts+xml"/>'
            "</Types>",
        )
        czesci["[Content_Types].xml"] = typy.encode()
        czesci["_rels/.rels"] = czesci["_rels/.rels"].decode().replace(
            "</Relationships>",
            '<Relationship Id="rIdCustom" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" '
            'Target="docProps/custom.xml"/></Relationships>',
        ).encode()
    with zipfile.ZipFile(sciezka, "w", zipfile.ZIP_DEFLATED) as cel:
        for nazwa, zawartosc in czesci.items():
            cel.writestr(nazwa, zawartosc)
    return sciezka


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pliki wzorcowe DOCX (K3)")
    parser.add_argument("--katalog", type=Path, default=Path("tests/wzorce"))
    parser.add_argument("pozycyjne", nargs="*", help=argparse.SUPPRESS)
    argumenty = parser.parse_args(argv)
    katalog = Path(argumenty.pozycyjne[0]) if argumenty.pozycyjne else argumenty.katalog
    print(zapisz_podstawowy(katalog / "wzorzec.docx"))
    print(zapisz_pulapki(katalog / "pulapki.docx"))
    print(zapisz_z_makrem(katalog / "z_makrem.docx"))
    print(zapisz_czesc_obca(katalog / "z_czescia_obca.docx"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
