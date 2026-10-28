"""Kontrola zapisu (LLD §10): weryfikacja ZAWSZE, na każdym poziomie suwaka.

Zapisany plik wczytany jak obcy dokument (ten sam adapter) i przeskanowany
detektorem; znaleziska niebędące znacznikami = `Ostrzezenie` (przegląd Astry
pkt 8: nowe znaleziska blokują status „ukończony" — decyzja blokady w API, K4).
Błąd detektora przelatuje jako `BladDetektora` — fail-closed (LLD §15).

K3b: druga siatka NIEZALEŻNA od adaptera — archiwa ZIP skanowane surowo
(węzły tekstowe i wartości atrybutów każdej części XML bezpiecznym parserem,
bez encji zewnętrznych; w częściach binarnych bajt po bajcie). Adapter ma te
same martwe punkty przy zapisie co przy odczycie, więc kontrola przez niego
sama przeoczyłaby to, co on (notka pod przeglądem DOCX, Gemini).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from itertools import chain

from lxml import etree

from niewidka.detektory import Detektor
from niewidka.formaty import adapter_dla
from niewidka.model import TypEncji


@dataclass(frozen=True)
class Ostrzezenie:
    typ: str
    fragment: str
    segment: int  # numer segmentu w wyniku; -1 = znalezisko skanu surowego
    czesc: str = ""  # część archiwum ze znaleziskiem (skan surowy)


def _parser() -> etree.XMLParser:
    # jak w adapterze DOCX: bez sieci, bez encji zewnętrznych, prerywalny
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def kontroluj(
    dane: bytes,
    nazwa_pliku: str,
    detektor: Detektor,
    oryginaly: list[str] | tuple[str, ...] = (),
) -> list[Ostrzezenie]:
    adapter = adapter_dla(nazwa_pliku)
    dok = adapter.wczytaj(dane)
    uwagi = []
    for numer, segment in enumerate(dok.segmenty):
        for zakres in detektor.znajdz(segment.tekst):
            uwagi.append(
                Ostrzezenie(
                    zakres.typ.value,
                    segment.tekst[zakres.start : zakres.koniec],
                    numer,
                )
            )
    uwagi.extend(_skan_surowy(dane, detektor, oryginaly))
    return uwagi


def _skan_surowy(
    dane: bytes, detektor: Detektor, oryginaly
) -> list[Ostrzezenie]:
    """Skan każdej części niezależnie od adaptera: XML wartość po wartości,
    reszta bajt po bajcie (tylko oryginały z mapy). Dedup per (typ, fragment,
    część) — to samo znalezisko w dwóch częściach to dwa wycieki. Typ DATA
    pomijany: reguła daty krzyczałaby na metadane techniczne (rewizje, stała
    core.xml) — prawdziwe daty wrażliwe łapie warstwa oryginałów z mapy."""
    czesci = _czesci(dane)
    znaki_oryginalow = {o: o.encode("utf-8") for o in oryginaly if o}
    uwagi: list[Ostrzezenie] = []
    for nazwa, zawartosc in czesci:
        widziane_w_czesci: set[tuple[str, str]] = set()
        for oryginal, bajty in znaki_oryginalow.items():
            if bajty in zawartosc:
                uwagi.append(Ostrzezenie("ORYGINAL", oryginal, -1, nazwa))
        if not _xml(nazwa):
            continue
        try:
            korzen = etree.fromstring(zawartosc, _parser())
        except etree.XMLSyntaxError:
            continue  # część binarna o mylącej nazwie — łapie ją skan bajtowy
        wartosci = chain(
            # K4b pkt 3: także e.tail — dane za znacznikiem omijały skan wartości
            (t for e in korzen.iter() for t in (e.text, e.tail) if t),
            (v for e in korzen.iter() for v in e.attrib.values()),
        )
        for wartosc in wartosci:
            if not wartosc:
                continue
            for zakres in detektor.znajdz(wartosc):
                if zakres.typ is TypEncji.DATA:
                    continue
                fragment = wartosc[zakres.start : zakres.koniec]
                klucz = (zakres.typ.value, fragment)
                if klucz in widziane_w_czesci:
                    continue
                widziane_w_czesci.add(klucz)
                uwagi.append(Ostrzezenie(zakres.typ.value, fragment, -1, nazwa))
    return uwagi


def _czesci(dane: bytes) -> list[tuple[str, bytes]]:
    if zipfile.is_zipfile(io.BytesIO(dane)):
        with zipfile.ZipFile(io.BytesIO(dane)) as paczka:
            return [(n, paczka.read(n)) for n in paczka.namelist()]
    return [("plik", dane)]


def _xml(nazwa: str) -> bool:
    return nazwa.endswith((".xml", ".rels")) or nazwa == "[Content_Types].xml"
