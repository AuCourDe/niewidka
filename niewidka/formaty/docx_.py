"""Adapter DOCX: runy, czyszczenie, allowlista struktury, blokady.

Czyszczone z wyniku (nie wracają — dopisek obiecuje tylko dane ze znaczników):
komentarze, przypisy, nagłówki/stopki, miniatura, właściwości app, śledzone
zmiany usunięte (w:del); w:ins zostaje jako treść. Hiperłącza http(s) zostają,
mailto/file rozpakowane (tekst zostaje, relacja znika). Części spoza allowlisty
i makra → `ElementNieobslugiwany` (blokada, nigdy cicho).
"""

from __future__ import annotations

import copy
import io
import posixpath
import zipfile
from typing import Any

from lxml import etree

from niewidka.archiwum import wczytaj_czesci
from niewidka.formaty import ElementNieobslugiwany, podziel_segment
from niewidka.model import Dokument, RunInfo, Segment
from niewidka.znaczniki import DOPISEK

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
VML = "urn:schemas-microsoft-com:vml"

# bez OCR treść obrazu nie daje się zweryfikować. Rozszerzenia, które
# traktujemy jako obrazy; wszystko inne pod word/media/ to niezweryfikowana
# część binarna = blokada.
OBRAZY_ROZSZERZENIA = frozenset({"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "emf", "wmf"})
TEKST_USUNIETEGO_OBRAZU = "[OBRAZ USUNIĘTY]"


def _q(nazwa: str) -> str:
    return f"{{{W}}}{nazwa}"


def _media(nazwa: str) -> bool:
    return nazwa.startswith("word/media/")


def _rozszerzenie(nazwa: str) -> str:
    return nazwa.rsplit(".", 1)[-1].lower() if "." in nazwa.rpartition("/")[2] else ""


# Części paczki, które adapter usuwa z wyniku (z ich wpisami w Content_Types/rels).
USUWANE = (
    "word/comments",  # komentarze
    "word/footnotes",  # przypisy
    "word/header",  # nagłówki
    "word/footer",  # stopki
    "docProps/app",  # właściwości aplikacji (firma itd.)
    "docProps/thumbnail",  # miniatura pierwszej strony
    "customXml/",  # custom XML — wektor wstrzyknięcia danych
    "word/people",  # autorzy komentarzy z e-mailami
    "docProps/custom",  # właściwości niestandardowe systemów obiegu
    "word/glossary",  # Szybkie części / AutoTekst
)


def _dozwolona(nazwa: str) -> bool:
    """Allowlista struktury OOXML; reszta = blokada.

    Części czyszczone (`_usuwana`) są obsługiwane — wchodzą do wczytania i
    znikają przy zapisie; blokada dotyczy wyłącznie części NIEZNANYCH.
    Relacje `<część>.rels` dziedziczą los części: relacje
    nagłówka/stopki/komentarzy są usuwane razem z częścią, nie blokują.
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
    """`word/_rels/header1.xml.rels` → `word/header1.xml`; nie-relacje → None."""
    if nazwa == "_rels/.rels" or not nazwa.endswith(".rels") or "/_rels/" not in nazwa:
        return None
    katalog, _, plik = nazwa.rpartition("/_rels/")
    return f"{katalog}/{plik[: -len('.rels')]}"


def _parser() -> etree.XMLParser:
    # bez sieci, bez encji zewnętrznych, prerywalny
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


class AdapterDocx:
    rozszerzenia = frozenset({"docx"})

    # --- wczytanie ----------------------------------------------------------

    def wczytaj(
        self,
        dane: bytes,
        polityka_obrazow: str | None = None,
        max_rozpakowane: int | None = None,
    ) -> Dokument:
        """`polityka_obrazow`: „usun" usuwa obrazy z treści (brak OCR),
        „blokuj" odrzuca dokument z obrazami, „zostaw" i None zostawiają je.
        `max_rozpakowane` = budżet dekompresji, egzekwowany przy odczycie."""
        czesci_lista = wczytaj_czesci(dane, limit_bajtow=max_rozpakowane)
        czesci = dict(czesci_lista)
        nazwy = [n for n, _ in czesci_lista]
        problemy = [n for n in nazwy if not _dozwolona(n)]
        if problemy:
            raise ElementNieobslugiwany(problemy)

        obce_binarnie = [n for n in nazwy if _media(n) and _rozszerzenie(n) not in OBRAZY_ROZSZERZENIA]
        if obce_binarnie:
            # niezweryfikowana część binarna — nie wiemy, co niesie
            raise ElementNieobslugiwany(obce_binarnie)
        _przemianuj_media(czesci)  # neutralne nazwy + aktualizacja relacji
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
        """run z obrazem (w:drawing albo w:pict) zamieniony na neutralny
        tekst; relacje obrazu dołączone do `usun_relacje` (znikną z .rels przy zapisie)."""
        usuniete = 0
        grafiki = list(drzewo.iter(_q("drawing"))) + list(drzewo.iter(_q("pict")))
        for grafika in grafiki:
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
            else:  # grafika bez runu-rodzica (patologiczny dokument) — podmień w miejscu
                grafika.getparent().replace(grafika, nowy)
            usuniete += 1
        return usuniete

    def _wyczysc_drzewo(self, drzewo: etree._Element, rels_xml: bytes, zasoby: dict) -> None:
        """Czyszczenie treści dokument.xml przed odczytem segmentów."""
        # śledzone zmiany: usunięte w:del znika (usunięty tekst ≠ treść),
        # w:ins rozpakowane = akceptacja zmiany (treść wchodzi do segmentów)
        for del_element in list(drzewo.iter(_q("del"))):
            del_element.getparent().remove(del_element)
        for ins_element in list(drzewo.iter(_q("ins"))):
            rodzic = ins_element.getparent()
            for dziecko in list(ins_element):
                ins_element.addprevious(dziecko)
            rodzic.remove(ins_element)
        # tożsamość z rewizji/pól: author/date/initials nigdzie nie zostaje
        for element in drzewo.iter():
            for atrybut in (f"{{{W}}}author", f"{{{W}}}date", f"{{{W}}}initials"):
                if atrybut in element.attrib:
                    del element.attrib[atrybut]
        # pola: instrukcja znika, wynik pola (w:t) zostaje jako tekst
        for instrukcja in list(drzewo.iter(_q("instrText"))):
            instrukcja.getparent().remove(instrukcja)
        for fld in list(drzewo.iter(_q("fldSimple"))):
            fld.attrib.pop(f"{{{W}}}instr", None)
        # osierocone w:t (np. w:ins bez w:r) → opakuj w w:r, inaczej
        # tekst omija segmenty i detekcję
        for t in list(drzewo.iter(_q("t"))):
            rodzic = t.getparent()
            if rodzic is None or rodzic.tag == _q("r"):
                continue
            run = rodzic.makeelement(_q("r"), {})
            rodzic.insert(list(rodzic).index(t), run)
            run.append(t)
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
        # teksty alternatywne obrazów mogą nieść PII — czyszczone (polityka obrazów)
        WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
        for doc_pr in drzewo.iter(f"{{{WP}}}docPr"):
            doc_pr.set("descr", "")
            doc_pr.set("name", "")
            doc_pr.set("title", "")
        for link in list(drzewo.iter(_q("hyperlink"))):
            id_relacji = link.get(f"{{{R}}}id")
            cel = _cel_relacji(rels_xml, id_relacji)
            if cel is not None and not cel.lower().startswith(("http://", "https://")):
                rodzic = link.getparent()
                for dziecko in list(link):
                    link.addprevious(dziecko)  # tekst zostaje, opakowanie znika
                rodzic.remove(link)
                zasoby["usun_relacje"].add(id_relacji)
        # zakładki: nazwy z PII → neutralne _Bm1..; systemowe _* zostają
        zakladki: dict[str, str] = {}
        for bm in drzewo.iter(_q("bookmarkStart")):
            nazwa = bm.get(_q("name"), "")
            if not nazwa or nazwa.startswith("_"):
                continue
            zakladki.setdefault(nazwa, f"_Bm{len(zakladki) + 1}")
            bm.set(_q("name"), zakladki[nazwa])
        # kotwice hiperłączy — ta sama neutralizacja;
        # kotwica na nieznaną zakładkę → _Bm0
        for link in drzewo.iter(_q("hyperlink")):
            anchor = link.get(_q("anchor"))
            if anchor:
                link.set(_q("anchor"), zakladki.get(anchor, "_Bm0"))
        # kontrolki treści: alias/tag z PII — węzły znikają
        for nazwa in ("alias", "tag"):
            for element in list(drzewo.iter(_q(nazwa))):
                element.getparent().remove(element)
        # smart tagi: metadane w:attr lecą z w:smartTagPr, treść zostaje
        for pr in list(drzewo.iter(_q("smartTagPr"))):
            pr.getparent().remove(pr)
        for st in list(drzewo.iter(_q("smartTag"))):
            rodzic = st.getparent()
            for dziecko in list(st):
                st.addprevious(dziecko)
            rodzic.remove(st)
        # metadane grafiki VML: title/alt/descr na kształtach i obrazach
        for element in drzewo.iter():
            if not element.tag.startswith(f"{{{VML}"):
                continue
            for atrybut in list(element.attrib):
                if atrybut.rsplit("}", 1)[-1] in ("title", "alt", "descr"):
                    del element.attrib[atrybut]

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

    def zapisz(self, dok: Dokument, dopisek: bool | str = True) -> bytes:
        zasoby = dok.zasoby
        czesci: dict[str, bytes] = dict(zasoby["czesci"])

        body = zasoby["drzewo"].find(_q("body"))
        if dopisek:
            baner = etree.SubElement(body, _q("p"))
            run_dopisku = etree.SubElement(baner, _q("r"))
            t = etree.SubElement(run_dopisku, _q("t"))
            t.text = DOPISEK if dopisek is True else dopisek  # z id mapy
            body.insert(0, baner)  # dopisek na POCZĄTKU dokumentu
        else:
            # dokument przywrócony: akapit dopisku z wyniku znika
            # (dopisek może mieć doklejony identyfikator mapy)
            for segment in list(dok.segmenty):
                if segment.tekst.startswith(DOPISEK) and segment.runs:
                    akapit = segment.runs[0].element.getparent()
                    if akapit is not None and akapit.getparent() is not None:
                        akapit.getparent().remove(akapit)

        # gwarancja schematu OOXML: każda komórka ma akapit (
        # po czyszczeniu w:del komórka nie może zostać pusta)
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
                if przefiltrowane is None:  # bez relacji plik relacji nie jest potrzebny
                    czesci.pop(plik_rels)
                else:
                    czesci[plik_rels] = przefiltrowane
        czesci["docProps/core.xml"] = _wyczysc_core(czesci["docProps/core.xml"])
        do_usuniecia = [n for n in czesci if n != "word/document.xml" and _usuwana(n)]
        do_usuniecia += [n for n in czesci if n == "word/_rels/document.xml.rels"]
        # relacje usuwanych części lecą razem z nimi
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


# --- neutralizacja nazw media ---------------------------------------


def _przemianuj_media(czesci: dict[str, bytes]) -> None:
    """Nazwy części word/media/* na neutralne obraz1.ext, obraz2.ext, … — PESEL
    potrafi siedzieć w nazwie pliku, a katalog ZIP czyta każdy odbiorca dokumentu.
    Relacje i [Content_Types] dostają zaktualizowane cele."""
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
        # relacje: cel względny wobec katalogu części źródłowej (…/_rels/ …)
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
        # [Content_Types]: Override z PartName na starą część
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
            # zewnętrzny URL bez query stringa i fragmentu (PII)
            czysty = cel.split("?", 1)[0].split("#", 1)[0]
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
        # Target relacji jest względny wobec części źródłowej: ../customXml/x → customXml/x
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
        # ogólnie — Default bez części o tym rozszerzeniu znika
        # (po usunięciu obrazów paczka nie może deklarować pustych typów)
        if not any(nazwa.lower().endswith(f".{rozszerzenie}") for nazwa in pozostale):
            korzen.remove(default)
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)


def _wyczysc_settings(settings_xml: bytes) -> bytes:
    """ślad szablonu, ochrony i sesji edycji znika z settings.xml."""
    korzen = etree.fromstring(settings_xml, _parser())
    for nazwa in ("attachedTemplate", "documentProtection", "writeProtection", "mailMerge", "rsids"):
        for element in list(korzen.iter(_q(nazwa))):
            element.getparent().remove(element)
    for element in korzen.iter():
        for atrybut in [a for a in element.attrib if a.startswith(f"{{{W}}}rsid")]:
            del element.attrib[atrybut]
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)


def _przefiltruj_settings_rels(settings_xml: bytes, rels_xml: bytes) -> bytes | None:
    """Relacje, na które czyszczony settings już nie wskazuje (np. szablon), znikają."""
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
            element.text = "1980-01-01T00:00:00Z"  # stała zamiast śladu pracy
    return etree.tostring(korzen, xml_declaration=True, encoding="UTF-8", standalone=True)
