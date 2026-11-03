"""Write check: the result is loaded like a foreign document and scanned by the detector at every
level; findings that are not markers = `Ostrzezenie`, a detector error = `BladDetektora`
(fail-closed). A second net independent of the adapter: ZIP archives are scanned raw, because the adapter
has the same blind spots on write as on read."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from itertools import chain

from lxml import etree

from niewidka.archiwum import wczytaj_czesci
from niewidka.detektory import Detektor, RegulyDetektor
from niewidka.formaty import adapter_dla
from niewidka.mapa import WZORZEC_ZNACZNIKA
from niewidka.model import TypEncji
from niewidka.odmiana import temat
from niewidka.osoby import sam_tytul
from niewidka.znaczniki import DOPISEK

_NAZWY_TYPOW = frozenset(typ.value for typ in TypEncji)
WZORZEC_DOPISKU = re.compile(re.escape(DOPISEK) + r" Identyfikator mapy: [a-p]+\.")

@dataclass(frozen=True)
class Ostrzezenie:
    typ: str
    fragment: str
    segment: int  # segment number in the result; -1 = finding from the raw scan
    czesc: str = ""  # archive part with the finding (raw scan)
    start: int = -1  # fragment offset in the result segment (-1 = unknown, raw scan)


def _parser() -> etree.XMLParser:
    # as in the DOCX adapter: no network, no external entities, interruptible
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def kontroluj(
    dane: bytes,
    nazwa_pliku: str,
    detektor: Detektor,
    oryginaly: list[str] | tuple[str, ...] = (),
    max_rozpakowane: int | None = None,
) -> list[Ostrzezenie]:
    adapter = adapter_dla(nazwa_pliku)
    dok = adapter.wczytaj(dane, max_rozpakowane=max_rozpakowane)
    uwagi = []
    for numer, segment in enumerate(dok.segmenty):
        # A [TYPE_N] marker is expected result content, not a leak: we remove it from
        # the scan (a space per character, offsets unchanged), because the ONNX model fires OSOBA on
        # the marker text itself, also on a fragment of it.
        tekst_bez_znacznikow = WZORZEC_ZNACZNIKA.sub(
            lambda m: " " * (m.end() - m.start()), segment.tekst
        )
        # A note with a RANDOM map identifier is removed too: it changed the model's
        # context on every run, so the same document once passed with a visible
        # surname and once not. A strict pattern (fixed text + letters a-p), it cannot hide data.
        tekst_bez_znacznikow = WZORZEC_DOPISKU.sub(
            lambda m: " " * (m.end() - m.start()), tekst_bez_znacznikow
        )
        for zakres in detektor.znajdz(tekst_bez_znacznikow):
            if tekst_bez_znacznikow[zakres.start : zakres.koniec].strip().upper() in _NAZWY_TYPOW:
                continue  # label "PESEL"/"NIP" before a masked number, not data
            if zakres.typ is TypEncji.OSOBA and sam_tytul(tekst_bez_znacznikow[zakres.start : zakres.koniec]):
                continue  # a bare "Pan" / "Pani" names nobody
            uwagi.append(
                Ostrzezenie(
                    zakres.typ.value,
                    tekst_bez_znacznikow[zakres.start : zakres.koniec],
                    numer,
                    start=zakres.start,
                )
            )
    # raw scan ONLY with the rules + originals from the map - the ONNX model on
    # every XML part took minutes (219 s on the sample, API timeout 120 s) and caused false
    # blocks from metadata; the model works on the adapter-read content, above.
    uwagi.extend(_skan_surowy(dane, RegulyDetektor(), oryginaly, max_rozpakowane))
    return uwagi


# A surname leaks in every case ("Kowalskim", "Kowalskiej", "Nowakowie"), while "Lis" inside the
# style name ListParagraph or the words "Lista" and "Listopad" is a different word.
_KONCOWKI = (
    "owskiego", "owskiemu", "owskiej", "owska", "owską", "owski", "owskim", "ówna", "ówny", "ównie",
    "ówną", "owie", "owej", "iemu", "iego", "ami", "ach", "owi", "owa", "ową", "owe", "iej", "iem",
    "ego", "emu", "ów", "om", "em", "im", "ie", "mi", "ch", "a", "e", "i", "m", "o", "u", "y", "ą", "ę",
)
_MALE = "a-ząćęłńóśźż"
_WIELKIE = "A-ZĄĆĘŁŃÓŚŹŻ"


def _dopasowanie_oryginalu(oryginal: str) -> tuple[bytes, re.Pattern[str] | None]:
    """(bytes for a fast exact pre-check, pattern or None). A number, an e-mail or other text that
        does not start with a capital leaks inside any string, so its bytes are enough. A name
        continues only with an inflection ending of the original or its stem, and no lower-case
        letter follows ("Kowalski2024" matches, "Listopad" does not). Anything may precede a name
        longer than 3 letters ("JNowak"); a short one ("Lis") must not follow a capital."""
    if not any(znak.isalpha() for znak in oryginal) or not oryginal[0].isupper():
        return oryginal.encode("utf-8"), None
    lewa = rf"(?<![{_WIELKIE}])" if len(oryginal) <= 3 else ""
    if not oryginal[-1].isalpha():
        prawa = r"(?!\d)" if oryginal[-1].isdigit() else ""
        return oryginal.encode("utf-8"), re.compile(lewa + re.escape(oryginal) + prawa)
    ostatnie = re.split(r"\W", oryginal)[-1]
    rdzen = oryginal[: len(oryginal) - len(ostatnie) + len(temat(ostatnie))]
    rdzenie = "|".join(re.escape(r) for r in sorted({oryginal, rdzen}, key=len, reverse=True))
    wzorzec = re.compile(rf"{lewa}(?:{rdzenie})(?:{'|'.join(_KONCOWKI)})?(?![{_MALE}])")
    return min(oryginal, rdzen, key=len).encode("utf-8"), wzorzec


def _skan_surowy(
    dane: bytes,
    detektor: Detektor,
    oryginaly,
    max_rozpakowane: int | None = None,
) -> list[Ostrzezenie]:
    """Scan each part independently of the adapter: XML value by value,
        the rest byte by byte (only originals from the map). Dedup per (type, fragment,
        part) - the same finding in two parts is two leaks. The DATA type is
        skipped: the date rule would shout at technical metadata (revisions, constant
        core.xml) - real sensitive dates are caught by the map-originals layer.
        The detector comes from outside so tests can
        inspect the run; callers do not plug a model in here."""
    czesci = _czesci(dane, max_rozpakowane)
    znaki_oryginalow = {o: _dopasowanie_oryginalu(o) for o in oryginaly if o}
    uwagi: list[Ostrzezenie] = []
    for nazwa, zawartosc in czesci:
        widziane_w_czesci: set[tuple[str, str]] = set()
        # PII can sit in the part NAME itself (the ZIP directory is read by
        # every recipient); DATA skipped as in the content (technical metadata)
        for zakres in detektor.znajdz(nazwa):
            if _techniczny(zakres):
                continue
            uwagi.append(
                Ostrzezenie("NAZWA_CZESCI", nazwa[zakres.start : zakres.koniec], -1, nazwa)
            )
        tekst_czesci: str | None = None
        for oryginal, (bajty, wzorzec) in znaki_oryginalow.items():
            if bajty not in zawartosc:  # fast and exact pre-check: every match contains these bytes
                continue
            if wzorzec is not None:
                if tekst_czesci is None:
                    tekst_czesci = zawartosc.decode("utf-8", errors="ignore")
                if wzorzec.search(tekst_czesci) is None:
                    continue
            uwagi.append(Ostrzezenie("ORYGINAL", oryginal, -1, nazwa))
        if not _xml(nazwa):
            continue
        try:
            korzen = etree.fromstring(zawartosc, _parser())
        except etree.XMLSyntaxError:
            # an XML part that cannot be parsed is not sent through
            # (fail-closed); a silent "continue" let unclosed traps through
            uwagi.append(Ostrzezenie("XML_NIEPRAWIDLOWY", "", -1, nazwa))
            continue
        wartosci = chain(
            # e.tail too - data after the tag bypassed the value scan
            (t for e in korzen.iter() for t in (e.text, e.tail) if t),
            (v for e in korzen.iter() for v in e.attrib.values()),
        )
        for wartosc in wartosci:
            if not wartosc:
                continue
            for zakres in detektor.znajdz(wartosc):
                if _techniczny(zakres):
                    continue
                fragment = wartosc[zakres.start : zakres.koniec]
                klucz = (zakres.typ.value, fragment)
                if klucz in widziane_w_czesci:
                    continue
                widziane_w_czesci.add(klucz)
                uwagi.append(Ostrzezenie(zakres.typ.value, fragment, -1, nazwa))
    return uwagi


def _techniczny(zakres) -> bool:
    """Types that shout at technical metadata in the raw scan (the DATA precedent).
        A card with a WRONG Luhn (font panose in fontTable.xml) - a typography string,
        not a leak; a card with a valid sum stays a warning."""
    return zakres.typ is TypEncji.DATA or (zakres.typ is TypEncji.KARTA and zakres.podejrzana)


def _czesci(dane: bytes, max_rozpakowane: int | None = None) -> list[tuple[str, bytes]]:
    if zipfile.is_zipfile(io.BytesIO(dane)):
        # read in chunks under a budget (ZIP headers can lie)
        return wczytaj_czesci(dane, limit_bajtow=max_rozpakowane)
    return [("plik", dane)]


def _xml(nazwa: str) -> bool:
    return nazwa.endswith((".xml", ".rels")) or nazwa == "[Content_Types].xml"
