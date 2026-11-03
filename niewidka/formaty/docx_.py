"""DOCX adapter: runs, cleaning, structure allowlist, blocks.

Cleaned from the result (they do not come back - the note promises only data from markers):
comments, footnotes, headers/footers, thumbnail, app properties, deleted tracked
changes (w:del); w:ins stays as content. External hyperlinks (http/https,
mailto, file) are unwrapped: the text stays, the relation with the address goes. Parts outside the allowlist
and macros -> `ElementNieobslugiwany` (a block, never silent)."""

from __future__ import annotations

import copy
import io
import posixpath
import re
import zipfile
from typing import Any
from urllib.parse import urlsplit

from lxml import etree

from niewidka.archiwum import wczytaj_czesci
from niewidka.formaty import ElementNieobslugiwany, podziel_segment
from niewidka.model import Dokument, RunInfo, Segment
from niewidka.znaczniki import DOPISEK

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
VML = "urn:schemas-microsoft-com:vml"

# without OCR the image content cannot be verified. Extensions we
# treat as images; anything else under word/media/ is an unverified
# binary part = a block.
OBRAZY_ROZSZERZENIA = frozenset({"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "emf", "wmf"})
TEKST_USUNIETEGO_OBRAZU = "[OBRAZ USUNIĘTY]"


def _q(nazwa: str) -> str:
    return f"{{{W}}}{nazwa}"


_TEKSTOWE = frozenset({_q("t"), _q("tab"), _q("noBreakHyphen")})


def _lamanie_tekstu(element: etree._Element) -> bool:
    """A plain line break (`w:br` without a page/column type)."""
    return element.tag == _q("br") and element.get(_q("type"), "textWrapping") == "textWrapping"


def _wlasny(element: etree._Element, przodek: etree._Element) -> bool:
    """The nearest ancestor of `element` with the tag of `przodek` is `przodek` itself: runs and
    text of a text box nested in a run belong to the text box paragraph, not the outer one."""
    rodzic = element.getparent()
    while rodzic is not None and rodzic.tag != przodek.tag:
        rodzic = rodzic.getparent()
    return rodzic is przodek


def _tekst_runu(run: etree._Element) -> str:
    """Run text in document order; a tab is `\\t`, a line break `\\n`, a non-breaking hyphen `-`."""
    czesci = []
    for element in run.iter(_q("t"), _q("tab"), _q("br"), _q("noBreakHyphen")):
        if not _wlasny(element, run):
            continue
        if element.tag == _q("t"):
            czesci.append(element.text or "")
        elif element.tag == _q("tab"):
            czesci.append("\t")
        elif element.tag == _q("noBreakHyphen"):
            czesci.append("-")
        elif _lamanie_tekstu(element):
            czesci.append("\n")
    return "".join(czesci)


def _media(nazwa: str) -> bool:
    return nazwa.startswith("word/media/")


def _rozszerzenie(nazwa: str) -> str:
    return nazwa.rsplit(".", 1)[-1].lower() if "." in nazwa.rpartition("/")[2] else ""


# Package parts the adapter removes from the result (with their Content_Types/rels entries).
USUWANE = (
    "word/comments",  # comments
    "word/footnotes",  # footnotes
    "word/endnotes",  # endnotes
    "word/header",  # headers
    "word/footer",  # footers
    "docProps/app",  # application properties (company etc.)
    "docProps/thumbnail",  # first-page thumbnail
    "customXml/",  # custom XML - a data injection vector
    "word/people",  # comment authors with e-mails
    "docProps/custom",  # custom properties of workflow systems
    "word/glossary",  # Quick Parts / AutoText
)


def _dozwolona(nazwa: str) -> bool:
    """OOXML structure allowlist; the rest = a block.

        Cleaned parts (`_usuwana`) are handled - they are loaded and
        disappear on save; a block applies only to UNKNOWN parts.
        `<part>.rels` relations inherit the fate of the part: relations of
        header/footer/comments are removed with the part and do not block.
        """
    if _usuwana(nazwa):
        return True
    czesc = _czesc_rels(nazwa)
    if czesc is not None:
        return _dozwolona(czesc)
    if nazwa in {
        "[Content_Types].xml",
        "_rels/.rels",
        "docProps/core.xml",
        "word/document.xml",
        "word/_rels/document.xml.rels",
        "word/styles.xml",
        "word/stylesWithEffects.xml",
        "word/numbering.xml",
        "word/settings.xml",
        "word/webSettings.xml",
        "word/fontTable.xml",
    }:
        return True
    return nazwa.startswith(("word/theme/", "word/media/"))


def _czesc_rels(nazwa: str) -> str | None:
    """`word/_rels/header1.xml.rels` -> `word/header1.xml`; non-relations -> None."""
    if nazwa == "_rels/.rels" or not nazwa.endswith(".rels") or "/_rels/" not in nazwa:
        return None
    katalog, _, plik = nazwa.rpartition("/_rels/")
    return f"{katalog}/{plik[: -len('.rels')]}"


def _parser() -> etree.XMLParser:
    # no network, no external entities, interruptible
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


class AdapterDocx:
    rozszerzenia = frozenset({"docx"})

    # --- loading ----------------------------------------------------------

    def wczytaj(
        self,
        dane: bytes,
        polityka_obrazow: str | None = None,
        max_rozpakowane: int | None = None,
    ) -> Dokument:
        """`polityka_obrazow`: "usun" removes images from the content (no OCR),
                "blokuj" rejects a document with images, "zostaw" and None keep them.
                `max_rozpakowane` = decompression budget, enforced while reading."""
        czesci_lista = wczytaj_czesci(dane, limit_bajtow=max_rozpakowane)
        czesci = dict(czesci_lista)
        nazwy = [n for n, _ in czesci_lista]
        problemy = [n for n in nazwy if not _dozwolona(n)]
        if problemy:
            raise ElementNieobslugiwany(problemy)

        obce_binarnie = [n for n in nazwy if _media(n) and _rozszerzenie(n) not in OBRAZY_ROZSZERZENIA]
        if obce_binarnie:
            # unverified binary part - we do not know what it carries
            raise ElementNieobslugiwany(obce_binarnie)
        _przemianuj_media(czesci)  # neutral names + relation update
        obrazy = [n for n in czesci if _media(n)]
        if polityka_obrazow == "blokuj" and obrazy:
            raise ElementNieobslugiwany([f"obrazy ({len(obrazy)} szt.)"])

        drzewo = etree.fromstring(czesci["word/document.xml"], _parser())
        zasoby: dict[str, Any] = {
            "czesci": czesci,
            "drzewo": drzewo,
            "usun_relacje": set(),
            "obrazy": {"usuniete": 0, "pozostale": len(obrazy)},
        }
        if polityka_obrazow == "usun" and obrazy:
            for nazwa in obrazy:
                czesci.pop(nazwa, None)
            zasoby["obrazy"]["usuniete"] = self._usun_obrazy(drzewo, zasoby)
            zasoby["obrazy"]["pozostale"] = 0
        self._wyczysc_drzewo(drzewo, czesci["word/_rels/document.xml.rels"], zasoby)
        dok = Dokument("docx", self._segmenty(drzewo))
        dok.zasoby = zasoby
        return dok

    def _usun_obrazy(self, drzewo: etree._Element, zasoby: dict) -> int:
        """A run with an image (w:drawing or w:pict) replaced by a neutral
                text; image relations added to `usun_relacje` (they disappear from .rels on save)."""
        usuniete = 0
        grafiki = list(drzewo.iter(_q("drawing"))) + list(drzewo.iter(_q("pict")))
        for grafika in filter(_obraz, grafiki):  # a text box without a picture stays
            for element in grafika.iter():
                for atrybut in (f"{{{R}}}embed", f"{{{R}}}id", f"{{{R}}}link"):
                    if atrybut in element.attrib:
                        zasoby["usun_relacje"].add(element.attrib[atrybut])
            run = grafika.getparent()
            while run is not None and run.tag != _q("r"):
                run = run.getparent()
            nowy = etree.Element(_q("r"))
            t = etree.SubElement(nowy, _q("t"))
            t.text = TEKST_USUNIETEGO_OBRAZU
            if run is not None and run.getparent() is not None:
                run.addprevious(nowy)
                run.getparent().remove(run)
            else:  # graphic without a parent run (pathological document) - replace in place
                grafika.getparent().replace(grafika, nowy)
            usuniete += 1
        return usuniete

    def _wyczysc_drzewo(self, drzewo: etree._Element, rels_xml: bytes, zasoby: dict) -> None:
        """Clean the content of document.xml before reading segments."""
        # tracked changes are accepted: deleted text (w:del, the source of a move) is not
        # content, inserted text (w:ins, the target of a move) is unwrapped into the
        # segments, and records of the old formatting disappear
        for element in list(drzewo.iter(*map(_q, _ZMIANY_USUWANE))):
            element.getparent().remove(element)
        for element in list(drzewo.iter(_q("ins"), _q("moveTo"))):
            _rozpakuj(element)
        # identity from revisions: no date or initials, the author (required by the schema)
        # stays empty
        for element in drzewo.iter():
            if f"{{{W}}}author" in element.attrib:
                element.set(f"{{{W}}}author", "")
            for atrybut in (f"{{{W}}}date", f"{{{W}}}initials"):
                element.attrib.pop(atrybut, None)
        # fields: the instruction disappears and the field result (w:t) stays as plain text.
        # The field characters go too: Word hides the result of a field whose code is empty,
        # and form field data (w:ffData in w:fldChar) holds names and default texts.
        for element in list(drzewo.iter(_q("instrText"), _q("fldChar"))):
            run = element.getparent()
            run.remove(element)
            if run.tag == _q("r") and all(dziecko.tag == _q("rPr") for dziecko in run):
                run.getparent().remove(run)
        for fld in list(drzewo.iter(_q("fldSimple"))):  # w:instr is required: unwrap instead
            for dane_pola in fld.findall(_q("fldData")):
                fld.remove(dane_pola)
            _rozpakuj(fld)
        # orphaned w:t (e.g. w:ins without w:r) -> wrap in w:r, otherwise the
        # text bypasses segments and detection
        for t in list(drzewo.iter(_q("t"))):
            rodzic = t.getparent()
            if rodzic is None or rodzic.tag == _q("r"):
                continue
            run = rodzic.makeelement(_q("r"), {})
            rodzic.insert(list(rodzic).index(t), run)
            run.append(t)
        for nazwa in (
            "commentRangeStart", "commentRangeEnd", "commentReference", "footnoteReference",
            "endnoteReference",
        ):
            for element in list(drzewo.iter(_q(nazwa))):
                rodzic = element.getparent()
                rodzic.remove(element)
                # the reference run stays empty - remove it so it does not litter the segments
                if (
                    rodzic.tag == _q("r")
                    and not rodzic.findall(_q("t"))
                    and not rodzic.findall(_q("drawing"))
                ):
                    rodzic.getparent().remove(rodzic)
        for odniesienie in list(drzewo.iter(_q("headerReference"), _q("footerReference"))):
            odniesienie.getparent().remove(odniesienie)
        # image alt texts may carry PII - cleaned (image policy)
        WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
        for doc_pr in drzewo.iter(f"{{{WP}}}docPr"):
            doc_pr.set("descr", "")
            doc_pr.set("name", "")
            doc_pr.set("title", "")
        for link in list(drzewo.iter(_q("hyperlink"))):
            id_relacji = link.get(f"{{{R}}}id")
            cel = _cel_relacji(rels_xml, id_relacji)
            if cel is not None:  # the link target (http/https too) may carry data in the path
                rodzic = link.getparent()
                for dziecko in list(link):
                    link.addprevious(dziecko)  # the text stays, the wrapper disappears
                rodzic.remove(link)
                zasoby["usun_relacje"].add(id_relacji)
        # bookmarks: names with PII -> neutral _Bm1..; system _* ones stay
        zakladki: dict[str, str] = {}
        for bm in drzewo.iter(_q("bookmarkStart")):
            nazwa = bm.get(_q("name"), "")
            if not nazwa or nazwa.startswith("_"):
                continue
            zakladki.setdefault(nazwa, f"_Bm{len(zakladki) + 1}")
            bm.set(_q("name"), zakladki[nazwa])
        # hyperlink anchors - the same neutralization;
        # an anchor to an unknown bookmark -> _Bm0
        for link in drzewo.iter(_q("hyperlink")):
            anchor = link.get(_q("anchor"))
            if anchor:
                link.set(_q("anchor"), zakladki.get(anchor, "_Bm0"))
            for atrybut in ("tooltip", "docLocation"):  # free text no segment reads
                link.attrib.pop(_q(atrybut), None)
        # permission ranges name their editors (logins, e-mails); content control lists keep every
        # choice and the last one as text: the shown text stays in the content
        for element in list(drzewo.iter(_q("permStart"), _q("permEnd"), _q("listItem"))):
            element.getparent().remove(element)
        for lista in drzewo.iter(_q("dropDownList"), _q("comboBox")):
            lista.attrib.pop(_q("lastValue"), None)
        # content controls: alias/tag with PII - the nodes disappear
        for nazwa in ("alias", "tag"):
            for element in list(drzewo.iter(_q(nazwa))):
                element.getparent().remove(element)
        # smart tags: w:attr metadata is dropped with w:smartTagPr, the content stays
        for pr in list(drzewo.iter(_q("smartTagPr"))):
            pr.getparent().remove(pr)
        for st in list(drzewo.iter(_q("smartTag"))):
            rodzic = st.getparent()
            for dziecko in list(st):
                st.addprevious(dziecko)
            rodzic.remove(st)
        # VML graphic metadata: title/alt/descr on shapes and images
        for element in drzewo.iter():
            if not element.tag.startswith(f"{{{VML}"):
                continue
            for atrybut in list(element.attrib):
                if atrybut.rsplit("}", 1)[-1] in ("title", "alt", "descr"):
                    del element.attrib[atrybut]

    def _segmenty(self, drzewo: etree._Element) -> list[Segment]:
        segmenty = []
        for akapit in drzewo.iter(_q("p")):  # body, tables, text boxes
            runy, teksty, starts = [], [], []
            biezacy = 0
            for run_element in akapit.iter(_q("r")):
                if not _wlasny(run_element, akapit):
                    continue  # a text box paragraph is a segment of its own
                tekst = _tekst_runu(run_element)
                runy.append(RunInfo(tekst, run_element))
                starts.append(biezacy)
                biezacy += len(tekst)
                teksty.append(tekst)
            segmenty.append(Segment("".join(teksty), runy, starts))
        return segmenty

    # --- replacement ------------------------------------------------------------

    def wstaw_znaczniki(self, segment: Segment, zamiany: list[tuple[int, int, str]]) -> None:
        """Split a segment and insert markers INTO the tree (cloned runs, left style)."""
        stare = list(segment.runs)
        fragmenty = podziel_segment(segment, zamiany)
        pierwsze = {idx: nr for nr, (_, idx) in reversed(list(enumerate(fragmenty)))}
        nowe = [
            RunInfo(tekst, self._kopiuj_run(stare[idx].element, tekst, pierwsze[idx] == nr))
            for nr, (tekst, idx) in enumerate(fragmenty)
        ]
        for i, stary in enumerate([r.element for r in stare]):
            nowe_runu = [n.element for n, (_, idx) in zip(nowe, fragmenty) if idx == i]
            if not nowe_runu:
                # no text of this run is left (an empty run or one swallowed by a marker):
                # what is not text stays (symbol, page break, field character, drawing)
                reszta = self._kopiuj_run(stary, "")
                if any(dziecko.tag != _q("rPr") for dziecko in reszta):
                    nowe_runu = [reszta]
            for nowy in nowe_runu:
                stary.addprevious(nowy)
            stary.getparent().remove(stary)
        segment.runs = nowe
        segment.starts = []
        biezacy = 0
        for run in nowe:
            segment.starts.append(biezacy)
            biezacy += len(run.tekst)
        segment.tekst = "".join(r.tekst for r in nowe)

    def _kopiuj_run(self, element: etree._Element, tekst: str, z_reszta: bool = True) -> etree._Element:
        """A run clone with style (rPr). Text, tabs and line breaks are rebuilt from `tekst`;
                the remaining non-text content is MOVED to the first fragment of the run
                (`z_reszta`), so the paragraphs of a text box inside stay the segments they are."""
        klon = element.makeelement(element.tag, dict(element.attrib))
        styl = element.find(_q("rPr"))
        if styl is not None:
            klon.append(copy.deepcopy(styl))
        if z_reszta:
            for dziecko in list(element):
                if dziecko is not styl and dziecko.tag not in _TEKSTOWE and not _lamanie_tekstu(dziecko):
                    klon.append(dziecko)
        for czesc in re.split(r"([\t\n])", tekst):
            if czesc == "\t":
                etree.SubElement(klon, _q("tab"))
            elif czesc == "\n":
                etree.SubElement(klon, _q("br"))
            elif czesc:
                t = etree.SubElement(klon, _q("t"))
                t.text = czesc
                if czesc != czesc.strip():
                    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        return klon

    # --- saving ------------------------------------------------------------

    def zapisz(self, dok: Dokument, dopisek: bool | str = True) -> bytes:
        zasoby = dok.zasoby
        czesci: dict[str, bytes] = dict(zasoby["czesci"])

        body = zasoby["drzewo"].find(_q("body"))
        if dopisek:
            baner = etree.SubElement(body, _q("p"))
            run_dopisku = etree.SubElement(baner, _q("r"))
            t = etree.SubElement(run_dopisku, _q("t"))
            t.text = DOPISEK if dopisek is True else dopisek  # with the map id
            body.insert(0, baner)  # note at the START of the document
        else:
            # restored document: the note paragraph disappears from the result
            # (the note may have the map id appended)
            for segment in list(dok.segmenty):
                if segment.tekst.startswith(DOPISEK) and segment.runs:
                    akapit = segment.runs[0].element.getparent()
                    if akapit is not None and akapit.getparent() is not None:
                        akapit.getparent().remove(akapit)

        # OOXML schema guarantee: every cell has a paragraph (after
        # cleaning w:del a cell must not stay empty)
        for tc in zasoby["drzewo"].iter(_q("tc")):
            if tc.find(_q("p")) is None:
                etree.SubElement(tc, _q("p"))

        czesci["word/document.xml"] = etree.tostring(
            zasoby["drzewo"], xml_declaration=True, encoding="UTF-8", standalone=True
        )
        if "word/settings.xml" in czesci:
            czesci["word/settings.xml"] = _wyczysc_settings(czesci["word/settings.xml"])
            plik_rels = "word/_rels/settings.xml.rels"
            if plik_rels in czesci:
                przefiltrowane = _przefiltruj_settings_rels(
                    czesci["word/settings.xml"], czesci[plik_rels]
                )
                if przefiltrowane is None:  # without relations the relations file is not needed
                    czesci.pop(plik_rels)
                else:
                    czesci[plik_rels] = przefiltrowane
        if "docProps/core.xml" in czesci:  # optional in a package
            czesci["docProps/core.xml"] = _wyczysc_core(czesci["docProps/core.xml"])
        do_usuniecia = [n for n in czesci if n != "word/document.xml" and _usuwana(n)]
        do_usuniecia += [n for n in czesci if n == "word/_rels/document.xml.rels"]
        # relations of removed parts go together with them
        do_usuniecia += [n for n in czesci if (czesc := _czesc_rels(n)) is not None and _usuwana(czesc)]
        for nazwa in do_usuniecia:
            czesci.pop(nazwa, None)
        czesci["word/_rels/document.xml.rels"] = _przefiltruj_rels(
            zasoby["czesci"]["word/_rels/document.xml.rels"],
            zasoby["usun_relacje"],
            set(do_usuniecia),
        )
        czesci["_rels/.rels"] = _przefiltruj_root_rels(zasoby["czesci"]["_rels/.rels"], set(do_usuniecia))
        czesci["[Content_Types].xml"] = _przefiltruj_content_types(
            zasoby["czesci"]["[Content_Types].xml"],
            set(do_usuniecia),
            pozostale=set(czesci),
        )

        bufor = io.BytesIO()
        with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
            for nazwa, zawartosc in czesci.items():
                paczka.writestr(nazwa, zawartosc)
        return bufor.getvalue()

    def elementy_nieobslugiwane(self, dok: Dokument) -> list[str]:
        obrazy = sum(1 for _ in dok.zasoby["drzewo"].iter("{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}inline"))
        if obrazy:
            return [f"obraz ({obrazy} szt.): bez OCR pozostawiony z ostrzeżeniem (LLD §9)"]
        return []


def _usuwana(nazwa: str) -> bool:
    return nazwa.startswith(USUWANE)


# Accepting tracked changes: deleted content, move ranges and old formatting records go.
_ZMIANY_USUWANE = (
    "del", "moveFrom",
    "moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd",
    "customXmlInsRangeStart", "customXmlInsRangeEnd", "customXmlDelRangeStart",
    "customXmlDelRangeEnd", "customXmlMoveFromRangeStart", "customXmlMoveFromRangeEnd",
    "customXmlMoveToRangeStart", "customXmlMoveToRangeEnd",
    "rPrChange", "pPrChange", "sectPrChange", "tblPrChange", "tblPrExChange", "tblGridChange",
    "trPrChange", "tcPrChange", "numberingChange",
)


def _rozpakuj(element: etree._Element) -> None:
    """The children take the place of the element (the wrapper disappears, the content stays)."""
    for dziecko in list(element):
        element.addprevious(dziecko)
    element.getparent().remove(element)


_RELACJE_GRAFIKI = (f"{{{R}}}embed", f"{{{R}}}id", f"{{{R}}}link")


def _obraz(grafika: etree._Element) -> bool:
    """A graphic that points at a picture part; a shape with only a text box is not an image,
    and a picture INSIDE its text box is a graphic of its own."""
    for element in grafika.iter():
        if not any(atrybut in element.attrib for atrybut in _RELACJE_GRAFIKI):
            continue
        rodzic = element
        while rodzic is not grafika and rodzic.tag != _q("txbxContent"):
            rodzic = rodzic.getparent()
        if rodzic is grafika:
            return True
    return False


# --- neutralizing media names ---------------------------------------


def _przemianuj_media(czesci: dict[str, bytes]) -> None:
    """Names of word/media/* parts to neutral obraz1.ext, obraz2.ext, ... - a PESEL
        can sit in a file name, and the ZIP directory is read by every recipient of the document.
        Relations and [Content_Types] get updated targets."""
    CT = "http://schemas.openxmlformats.org/package/2006/content-types"
    REL = "http://schemas.openxmlformats.org/package/2006/relationships"
    zajete = set(czesci)
    numer = 0
    for stara in sorted(n for n in czesci if _media(n)):
        rozszerzenie = _rozszerzenie(stara) or "bin"
        numer += 1
        nowa = f"word/media/obraz{numer}.{rozszerzenie}"
        while nowa in zajete and nowa != stara:
            numer += 1
            nowa = f"word/media/obraz{numer}.{rozszerzenie}"
        if nowa == stara:
            continue
        czesci[nowa] = czesci.pop(stara)
        zajete.discard(stara)
        zajete.add(nowa)
        # relations: the target is relative to the source part's directory (.../_rels/ ...)
        for nazwa_rels, zawartosc in list(czesci.items()):
            if not nazwa_rels.endswith(".rels"):
                continue
            try:
                korzen = etree.fromstring(zawartosc, _parser())
            except etree.XMLSyntaxError:
                continue
            baza = nazwa_rels.rpartition("/_rels/")[0]
            zmieniono = False
            for relacja in korzen.iter(f"{{{REL}}}Relationship"):
                cel = relacja.get("Target") or ""
                kandydat = cel.lstrip("/") if cel.startswith("/") else posixpath.normpath(f"{baza}/{cel}")
                if kandydat == stara:
                    relacja.set("Target", posixpath.relpath(nowa, baza or "."))
                    zmieniono = True
            if zmieniono:
                czesci[nazwa_rels] = etree.tostring(
                    korzen, xml_declaration=True, encoding="UTF-8", standalone=True
                )
        # [Content_Types]: Override with a PartName pointing at the old part
        xml_ct = czesci.get("[Content_Types].xml")
        if xml_ct:
            korzen_ct = etree.fromstring(xml_ct, _parser())
            zmieniono = False
            for override in korzen_ct.iter(f"{{{CT}}}Override"):
                if (override.get("PartName") or "").lstrip("/") == stara:
                    override.set("PartName", f"/{nowa}")
                    zmieniono = True
            if zmieniono:
                czesci["[Content_Types].xml"] = etree.tostring(
                    korzen_ct, xml_declaration=True, encoding="UTF-8", standalone=True
                )


def _cel_relacji(rels_xml: bytes, id_relacji: str | None) -> str | None:
    if not id_relacji:
        return None
    korzen = etree.fromstring(rels_xml, _parser())
    for relacja in korzen:
        if relacja.get("Id") == id_relacji:
            return relacja.get("Target")
    return None


def _przefiltruj_rels(rels_xml: bytes, usun_id: set[str], usun_czesci: set[str]) -> bytes:
    korzen = etree.fromstring(rels_xml, _parser())
    for relacja in list(korzen):
        cel = relacja.get("Target") or ""
        if cel.lower().startswith(("http://", "https://")):
            # remaining external target (not a link): only the domain, no login, path or query
            adres = urlsplit(cel)
            czysty = f"{adres.scheme}://{adres.netloc.rpartition('@')[2]}/"
            if czysty != cel:
                relacja.set("Target", czysty)
        if relacja.get("Id") in usun_id or _relacja_celu_w(relacja.get("Target"), usun_czesci):
            korzen.remove(relacja)
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)


def _relacja_celu_w(cel: str | None, usun_czesci: set[str]) -> bool:
    if not cel:
        return False
    if cel.startswith("/"):
        sciezka = cel.lstrip("/")
    else:
        # a relation Target is relative to the source part: ../customXml/x -> customXml/x
        sciezka = posixpath.normpath(f"word/{cel}")
    return any(sciezka == u or sciezka.startswith(u) for u in usun_czesci)


def _przefiltruj_root_rels(rels_xml: bytes, usun_czesci: set[str]) -> bytes:
    korzen = etree.fromstring(rels_xml, _parser())
    for relacja in list(korzen):
        cel = (relacja.get("Target") or "").lstrip("/")
        if any(cel == u or cel.startswith(u) for u in usun_czesci):
            korzen.remove(relacja)
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)


def _przefiltruj_content_types(
    xml: bytes, usun_czesci: set[str], pozostale: set[str] | None = None
) -> bytes:
    """A Default without parts = a broken package; the thumbnail extension Default disappears
        only when NO remaining part (e.g. media/*.jpeg) uses it."""
    korzen = etree.fromstring(xml, _parser())
    CT = "http://schemas.openxmlformats.org/package/2006/content-types"
    pozostale = pozostale if pozostale is not None else set()
    for override in list(korzen.iter(f"{{{CT}}}Override")):
        czesc = (override.get("PartName") or "").lstrip("/")
        if any(czesc == u or czesc.startswith(u) for u in usun_czesci):
            korzen.remove(override)
    for default in list(korzen.iter(f"{{{CT}}}Default")):
        rozszerzenie = (default.get("Extension") or "").lower()
        # in general - a Default without parts of that extension disappears
        # (after removing images the package must not declare empty types)
        if not any(nazwa.lower().endswith(f".{rozszerzenie}") for nazwa in pozostale):
            korzen.remove(default)
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)


def _wyczysc_settings(settings_xml: bytes) -> bytes:
    """the trace of the template, protection and editing session disappears from settings.xml, and
    so do document variables (templates and mail merge keep names and addresses there) and the
    separators of the removed footnote and endnote parts."""
    korzen = etree.fromstring(settings_xml, _parser())
    for nazwa in (
        "attachedTemplate", "documentProtection", "writeProtection", "mailMerge", "rsids",
        "docVars", "footnote", "endnote",
    ):
        for element in list(korzen.iter(_q(nazwa))):
            element.getparent().remove(element)
    for element in korzen.iter():
        for atrybut in [a for a in element.attrib if a.startswith(f"{{{W}}}rsid")]:
            del element.attrib[atrybut]
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)


def _przefiltruj_settings_rels(settings_xml: bytes, rels_xml: bytes) -> bytes | None:
    """Relations that the cleaned settings no longer point to (e.g. the template) disappear."""
    uzywane = {
        wartosc
        for element in etree.fromstring(settings_xml, _parser()).iter()
        for klucz, wartosc in element.attrib.items()
        if klucz == f"{{{R}}}id"
    }
    korzen = etree.fromstring(rels_xml, _parser())
    for relacja in list(korzen):
        if relacja.get("Id") not in uzywane:
            korzen.remove(relacja)
    if len(korzen) == 0:
        return None
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)


def _wyczysc_core(core_xml: bytes) -> bytes:
    DC = "http://purl.org/dc/elements/1.1/"
    CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    DCTERMS = "http://purl.org/dc/terms/"
    korzen = etree.fromstring(core_xml, _parser())
    for tag in (f"{{{DC}}}creator", f"{{{DC}}}title", f"{{{DC}}}subject",
                f"{{{DC}}}description", f"{{{CP}}}lastModifiedBy", f"{{{CP}}}keywords",
                f"{{{CP}}}category", f"{{{CP}}}contentStatus"):
        for element in korzen.iter(tag):
            element.text = ""
    for tag in (f"{{{DCTERMS}}}created", f"{{{DCTERMS}}}modified"):
        for element in korzen.iter(tag):
            element.text = "1980-01-01T00:00:00Z"  # a constant instead of a work trace
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)
