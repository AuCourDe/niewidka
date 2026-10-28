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

from niewidka.archiwum import wczytaj_czesci
from niewidka.detektory import Detektor, RegulyDetektor
from niewidka.formaty import adapter_dla
from niewidka.mapa import WZORZEC_ZNACZNIKA
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
    max_rozpakowane: int | None = None,
) -> list[Ostrzezenie]:
    adapter = adapter_dla(nazwa_pliku)
    dok = adapter.wczytaj(dane, max_rozpakowane=max_rozpakowane)
    uwagi = []
    for numer, segment in enumerate(dok.segmenty):
        # Znacznik [TYP_N] to oczekiwana treść wyniku, nie wyciek: wyjmujemy go ze
        # skanu (spacja za znak, offsety bez zmian), bo model ONNX odpala OSOBA na
        # samym tekście znacznika, także na jego fragmencie (znalezione E2E K5b).
        tekst_bez_znacznikow = WZORZEC_ZNACZNIKA.sub(
            lambda m: " " * (m.end() - m.start()), segment.tekst
        )
        for zakres in detektor.znajdz(tekst_bez_znacznikow):
            uwagi.append(
                Ostrzezenie(
                    zakres.typ.value,
                    tekst_bez_znacznikow[zakres.start : zakres.koniec],
                    numer,
                )
            )
    # K5b: skan surowy WYŁĄCZNIE na regułach + oryginałach z mapy — model ONNX na
    # każdej części XML to były minuty (219 s na wzorcu, timeout API 120 s) i fałszywe
    # blokady z metadanych; model działa na treści czytanej adapterem, wyżej.
    uwagi.extend(_skan_surowy(dane, RegulyDetektor(), oryginaly, max_rozpakowane))
    return uwagi


def _skan_surowy(
    dane: bytes, detektor: Detektor, oryginaly, max_rozpakowane: int | None = None
) -> list[Ostrzezenie]:
    """Skan każdej części niezależnie od adaptera: XML wartość po wartości,
    reszta bajt po bajcie (tylko oryginały z mapy). Dedup per (typ, fragment,
    część) — to samo znalezisko w dwóch częściach to dwa wycieki. Typ DATA
    pomijany: reguła daty krzyczałaby na metadane techniczne (rewizje, stała
    core.xml) — prawdziwe daty wrażliwe łapie warstwa oryginałów z mapy.
    Detektor przychodzi z zewnątrz (K5b: zawsze reguły), by testy mogły
    podejrzeć przebieg; wołający nie podpinają tu modelu."""
    czesci = _czesci(dane, max_rozpakowane)
    znaki_oryginalow = {o: o.encode("utf-8") for o in oryginaly if o}
    uwagi: list[Ostrzezenie] = []
    for nazwa, zawartosc in czesci:
        widziane_w_czesci: set[tuple[str, str]] = set()
        # K4b pkt 5: PII potrafi siedzieć w samej NAZWIE części (katalog ZIP czyta
        # każdy odbiorca); DATA pomijana jak w treści (metadane techniczne)
        for zakres in detektor.znajdz(nazwa):
            if zakres.typ is TypEncji.DATA:
                continue
            uwagi.append(
                Ostrzezenie("NAZWA_CZESCI", nazwa[zakres.start : zakres.koniec], -1, nazwa)
            )
        for oryginal, bajty in znaki_oryginalow.items():
            if bajty in zawartosc:
                uwagi.append(Ostrzezenie("ORYGINAL", oryginal, -1, nazwa))
        if not _xml(nazwa):
            continue
        try:
            korzen = etree.fromstring(zawartosc, _parser())
        except etree.XMLSyntaxError:
            # K4b pkt 4: części XML, której nie da się sparsować, nie wysyłamy
            # (fail-closed); ciche „continue" przepuszczało niedomknięte pułapki
            uwagi.append(Ostrzezenie("XML_NIEPRAWIDLOWY", "", -1, nazwa))
            continue
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


def _czesci(dane: bytes, max_rozpakowane: int | None = None) -> list[tuple[str, bytes]]:
    if zipfile.is_zipfile(io.BytesIO(dane)):
        # K4b pkt 10: odczyt porcjami pod budżetem (nagłówki ZIP bywają kłamliwe)
        return wczytaj_czesci(dane, limit_bajtow=max_rozpakowane)
    return [("plik", dane)]


def _xml(nazwa: str) -> bool:
    return nazwa.endswith((".xml", ".rels")) or nazwa == "[Content_Types].xml"
