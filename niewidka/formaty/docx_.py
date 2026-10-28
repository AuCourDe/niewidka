"""Adapter DOCX (LLD §9): runy, czyszczenie, allowlista struktury, blokady (K3).

Czyszczone z wyniku (nie wracają — dopisek obiecuje tylko dane ze znaczników):
komentarze, przypisy, nagłówki/stopki, miniatura, właściwości app, śledzone
zmiany usunięte (w:del); w:ins zostaje jako treść. Hiperłącza http(s) zostają,
mailto/file rozpakowane (tekst zostaje, relacja znika). Części spoza allowlisty
i makra → `ElementNieobslugiwany` (blokada, nigdy cicho — przegląd Astry pkt 5).
"""

from __future__ import annotations

import copy
import io
import zipfile
from typing import Any

from lxml import etree

from niewidka.formaty import ElementNieobslugiwany, podziel_segment
from niewidka.model import Dokument, RunInfo, Segment
from niewidka.znaczniki import DOPISEK

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _q(nazwa: str) -> str:
    return f"{{{W}}}{nazwa}"


# Części paczki, które adapter usuwa z wyniku (z ich wpisami w Content_Types/rels).
USUWANE = (
    "word/comments",  # komentarze
    "word/footnotes",  # przypisy
    "word/header",  # nagłówki
    "word/footer",  # stopki
    "docProps/app",  # właściwości aplikacji (firma itd.)
    "docProps/thumbnail",  # miniatura pierwszej strony
    "customXml/",  # custom XML — wektor wstrzyknięcia danych (Astra pkt 5)
)


def _dozwolona(nazwa: str) -> bool:
    """Allowlista struktury OOXML (LLD §9); reszta = blokada.

    Części czyszczone (`_usuwana`) są obsługiwane — wchodzą do wczytania i
    znikają przy zapisie; blokada dotyczy wyłącznie części NIEZNANYCH.
    """
    if _usuwana(nazwa):
        return True
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


def _parser() -> etree.XMLParser:
    # Gemini pkt 6: bez sieci, bez encji zewnętrznych, prerywalny
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


class AdapterDocx:
    rozszerzenia = frozenset({"docx"})

    # --- wczytanie ----------------------------------------------------------

    def wczytaj(self, dane: bytes) -> Dokument:
        with zipfile.ZipFile(io.BytesIO(dane)) as paczka:
            nazwy = paczka.namelist()
            problemy = [n for n in nazwy if not _dozwolona(n)]
            if problemy:
                raise ElementNieobslugiwany(problemy)
            czesci = {n: paczka.read(n) for n in nazwy}

        drzewo = etree.fromstring(czesci["word/document.xml"], _parser())
        zasoby: dict[str, Any] = {
            "czesci": czesci,
            "drzewo": drzewo,
            "usun_relacje": set(),
        }
        self._wyczysc_drzewo(drzewo, czesci["word/_rels/document.xml.rels"], zasoby)
        dok = Dokument("docx", self._segmenty(drzewo))
        dok.zasoby = zasoby
        return dok

    def _wyczysc_drzewo(self, drzewo: etree._Element, rels_xml: bytes, zasoby: dict) -> None:
        """Usuń elementy śledzonych zmian/komentarzy/przypisów, rozpakuj mailto."""
        for del_element in list(drzewo.iter(_q("del"))):
            del_element.getparent().remove(del_element)  # usunięty tekst ≠ treść
        for nazwa in ("commentRangeStart", "commentRangeEnd", "commentReference", "footnoteReference"):
            for element in list(drzewo.iter(_q(nazwa))):
                rodzic = element.getparent()
                rodzic.remove(element)
                # run referencyjny zostaje pusty — usuń, żeby nie śmiecił segmentów
                if (
                    rodzic.tag == _q("r")
                    and not rodzic.findall(_q("t"))
                    and not rodzic.findall(_q("drawing"))
                ):
                    rodzic.getparent().remove(rodzic)
        for odniesienie in list(drzewo.iter(_q("headerReference"), _q("footerReference"))):
            odniesienie.getparent().remove(odniesienie)
        # teksty alternatywne obrazów mogą nieść PII — czyszczone (polityka obrazów, LLD §9)
        WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
        for doc_pr in drzewo.iter(f"{{{WP}}}docPr"):
            doc_pr.set("descr", "")
        for link in list(drzewo.iter(_q("hyperlink"))):
            id_relacji = link.get(f"{{{R}}}id")
            cel = _cel_relacji(rels_xml, id_relacji)
            if cel is not None and not cel.lower().startswith(("http://", "https://")):
                rodzic = link.getparent()
                for dziecko in list(link):
                    link.addprevious(dziecko)  # tekst zostaje, opakowanie znika
                rodzic.remove(link)
                zasoby["usun_relacje"].add(id_relacji)

    def _segmenty(self, drzewo: etree._Element) -> list[Segment]:
        segmenty = []
        for akapit in drzewo.iter(_q("p")):  # body, tabele, pola tekstowe
            runy, teksty, starts = [], [], []
            biezacy = 0
            for run_element in akapit.iter(_q("r")):
                tekst = "".join(t.text or "" for t in run_element.iter(_q("t")))
                runy.append(RunInfo(tekst, run_element))
                starts.append(biezacy)
                biezacy += len(tekst)
                teksty.append(tekst)
            segmenty.append(Segment("".join(teksty), runy, starts))
        return segmenty

    # --- zamiana ------------------------------------------------------------

    def wstaw_znaczniki(self, segment: Segment, zamiany: list[tuple[int, int, str]]) -> None:
        """Podziel segment i wstaw znaczniki DO drzewa (klony runów, styl lewy)."""
        stare = list(segment.runs)
        fragmenty = podziel_segment(segment, zamiany)
        nowe = [RunInfo(tekst, self._kopiuj_run(stare[idx].element, tekst)) for tekst, idx in fragmenty]
        for i, stary in enumerate([r.element for r in stare]):
            for nowy in [n.element for n, (t, idx) in zip(nowe, fragmenty) if idx == i]:
                stary.addprevious(nowy)
            stary.getparent().remove(stary)
        segment.runs = nowe
        segment.starts = []
        biezacy = 0
        for run in nowe:
            segment.starts.append(biezacy)
            biezacy += len(run.tekst)
        segment.tekst = "".join(r.tekst for r in nowe)

    def _kopiuj_run(self, element: etree._Element, tekst: str) -> etree._Element:
        klon = copy.deepcopy(element)  # styl (rPr) i zawartość nie-tekstowa zostają
        for t in klon.findall(_q("t")):
            klon.remove(t)
        if tekst:
            t = etree.SubElement(klon, _q("t"))
            t.text = tekst
            if tekst != tekst.strip():
                t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        return klon

    # --- zapis --------------------------------------------------------------

    def zapisz(self, dok: Dokument, dopisek: bool = True) -> bytes:
        zasoby = dok.zasoby
        czesci: dict[str, bytes] = dict(zasoby["czesci"])

        body = zasoby["drzewo"].find(_q("body"))
        if dopisek:
            baner = etree.SubElement(body, _q("p"))
            run_dopisku = etree.SubElement(baner, _q("r"))
            t = etree.SubElement(run_dopisku, _q("t"))
            t.text = DOPISEK
            body.insert(0, baner)  # dopisek na POCZĄTKU dokumentu
        else:
            # dokument przywrócony: akapit dopisku z wyniku znika
            for segment in list(dok.segmenty):
                if segment.tekst == DOPISEK and segment.runs:
                    akapit = segment.runs[0].element.getparent()
                    if akapit is not None and akapit.getparent() is not None:
                        akapit.getparent().remove(akapit)

        czesci["word/document.xml"] = etree.tostring(
            zasoby["drzewo"], xml_declaration=True, encoding="UTF-8", standalone=True
        )
        czesci["docProps/core.xml"] = _wyczysc_core(czesci["docProps/core.xml"])
        do_usuniecia = [n for n in czesci if n != "word/document.xml" and _usuwana(n)]
        do_usuniecia += [n for n in czesci if n == "word/_rels/document.xml.rels"]
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
        if relacja.get("Id") in usun_id or _relacja_celu_w(relacja.get("Target"), usun_czesci):
            korzen.remove(relacja)
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)


def _relacja_celu_w(cel: str | None, usun_czesci: set[str]) -> bool:
    if not cel:
        return False
    sciezka = f"word/{cel}" if not cel.startswith("/") else cel.lstrip("/")
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
    """Default bez części = uszkodzona paczka; Default rozszerzeń miniatury znika
    tylko, gdy ŻADNA pozostała część (np. media/*.jpeg) go nie używa."""
    korzen = etree.fromstring(xml, _parser())
    CT = "http://schemas.openxmlformats.org/package/2006/content-types"
    pozostale = pozostale if pozostale is not None else set()
    for override in list(korzen.iter(f"{{{CT}}}Override")):
        czesc = (override.get("PartName") or "").lstrip("/")
        if any(czesc == u or czesc.startswith(u) for u in usun_czesci):
            korzen.remove(override)
    for default in list(korzen.iter(f"{{{CT}}}Default")):
        rozszerzenie = (default.get("Extension") or "").lower()
        if rozszerzenie in {"jpeg", "jpg", "emf", "wmf"} and not any(
            nazwa.lower().endswith(f".{rozszerzenie}") for nazwa in pozostale
        ):
            korzen.remove(default)
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
            element.text = "1980-01-01T00:00:00Z"  # stała zamiast śladu pracy
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)
