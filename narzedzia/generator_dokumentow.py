"""Generator plików wzorcowych DOCX do testów round-trip (K3, python-docx).

Wzorce zawierają to, co adapter DOCX musi obsłużyć (zlecenie K3): runy z przeplotem
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pliki wzorcowe DOCX (K3)")
    parser.add_argument("--katalog", type=Path, default=Path("tests/wzorce"))
    parser.add_argument("pozycyjne", nargs="*", help=argparse.SUPPRESS)
    argumenty = parser.parse_args(argv)
    katalog = Path(argumenty.pozycyjne[0]) if argumenty.pozycyjne else argumenty.katalog
    print(zapisz_podstawowy(katalog / "wzorzec.docx"))
    print(zapisz_z_makrem(katalog / "z_makrem.docx"))
    print(zapisz_czesc_obca(katalog / "z_czescia_obca.docx"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
