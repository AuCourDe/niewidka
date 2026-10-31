"""Core ukryj/przywroc for the API and desktop. `ukryj(dane, format, poziom)` returns
(result, map, report); the detector is injected or built from configuration. The write check
always runs, and new findings block the "completed" status.
"""

from __future__ import annotations

import re
import secrets
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

from niewidka.archiwum import ArchiwumZaDuze  # re-export: the API picks it up under this name
from niewidka.detektory import BladDetektora, RegulyDetektor, zbuduj_poziom
from niewidka.formaty import NieznanyFormat, adapter_formatu, rozszerzenia_wspierane
from niewidka.jakosc import r95_z_kalibracji
from niewidka.kontrola import Ostrzezenie, kontroluj
from niewidka.mapa import (
    WARIANT_DOMYSLNY,
    WZORZEC_ZNACZNIKA,
    BladMapy,
    Mapa,
    Rozbieznosc,
    Wpis,
    Wystapienie,
    przygotuj_zamiany,
    rozbieznosci_wpisow,
)
from niewidka.model import Encja, TypEncji, Zakres
from niewidka.osoby import _TYTUŁY as _TYTULY_OSOB
from niewidka.osoby import pogrupuj
from niewidka.scalanie import scal
from niewidka.znaczniki import (
    dopisek,
    nadaj_oznaczenia,
    odkoduj_identyfikator,
    zakoduj_identyfikator,
    znacznik_encji,
)


@dataclass
class Raport:
    identyfikator: str
    poziom: int
    statystyki: dict[str, int]  # type -> number of replaced entities
    ostrzezenia: list[Ostrzezenie] = field(default_factory=list)
    uwagi: list[str] = field(default_factory=list)  # non-blocking
    r95: dict[str, float | None] = field(default_factory=dict)
    status: str = "ukonczony"  # "zablokowany" when the check found new findings
    # detections of the last run for corrections in the preview (RAM only, never in a response)
    detekcje: Detekcje | None = field(default=None, repr=False, compare=False)


@dataclass
class Detekcje:
    """Detections of the last `ukryj` run (spans, types, person groups, numbering):
    `poprawki.popraw` computes a new result from them WITHOUT running the model again.
    They contain the original document, so
    they live only in process memory (`poprawki.PamiecWykryc`), never on disk or in logs."""

    dane: bytes
    format: str
    poziom: int
    polityka_obrazow: str
    max_rozpakowane_bajtow: int | None
    encje: list[list[Encja]]  # per document segment, with labels and variants
    # check findings from text segments (model + rules) in the base result: a correction
    # does not run the model, so these make sure every place gets a decision
    ostrzezenia_tekstu: list[Ostrzezenie] = field(default_factory=list)


class _BezDaty:
    """Wrapper that disables the DATA type (config `wykrywaj_date`)."""

    def __init__(self, wewnetrzny):
        self._wewnetrzny = wewnetrzny
        self.nazwa = wewnetrzny.nazwa
        self.typy = frozenset(wewnetrzny.typy) - {TypEncji.DATA}

    def znajdz(self, tekst: str):
        return [z for z in self._wewnetrzny.znajdz(tekst) if z.typ is not TypEncji.DATA]


class ZnacznikiWTresci(BladMapy):
    """The input already contains a Niewidka marker: an assigned marker could
    collide with it and restore would silently insert data in the wrong place."""


MAKS_PRZEBIEGOW = 5  # measured 2026-10-28: the sample letter needs up to 4 (the model is non-deterministic)
TYPY_ENCJI = {typ.value for typ in TypEncji}
# to a person from the check we add up to 2 following capitalised words on the same
# line: the model catches "Jan Marek" once and "Nowicki" another time (measured 2026-10-28).
# Always whole words.
_ODSTEP = "[ \t\u00a0\u202f]+"
_SLOWO_NAZWISKA = re.compile(rf"{_ODSTEP}([^\W\d_][\w'’\-]*)")
_W_SLOWIE = re.compile(r"[\w'’\-]*")


def _koniec_osoby(tekst: str, koniec: int) -> int:
    koniec = _W_SLOWIE.match(tekst, koniec).end()  # fragment cut off mid-word
    for _ in range(2):
        slowo = _SLOWO_NAZWISKA.match(tekst, koniec)
        if not slowo or not slowo.group(1)[0].isupper():
            break
        koniec = slowo.end()
    return koniec


_SLOWO_Z_WIELKIEJ = re.compile(r"[^\W\d_][\w'’\-]*")


def _wspolny_poczatek(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _czlon_pasuje(znany: str, kandydat: str) -> bool:
    """Same base form after a common prefix: Zawadzki/Zawadzkiemu,
    Marek/Markowi (movable "e"), Anna/Annie. A short prefix is not enough,
    so that "Nowak" does not match "Nowy"."""
    warianty = {znany}
    if len(znany) >= 4 and znany[-2] == "e" and znany[-1] in "kc":
        warianty.add(znany[:-2] + znany[-1])  # Marek → Mark-owi, Jacek → Jack-a
    for wzor in warianty:
        p = _wspolny_poczatek(wzor, kandydat)
        if len(wzor) <= 4:  # Anna/Annie, Jan/Jana: threshold based on the length of the KNOWN form
            if p >= max(3, len(wzor) - 1):
                return True
        elif p >= 4 and p >= len(wzor) - 3:
            return True
    return False


def _formy_znanych_osob(teksty: list[str], zajete: list[list[Zakres]], osoby: list[str]) -> set[str]:
    """Other forms of people already detected in the document (API tests 2026-10-29: "Marek
    Zawadzki-Herbert" hidden, "Markowi Zawadzkiemu-Herbertowi" visible). A person detected
    once must disappear in every inflected form, at every level."""
    znane = {
        slowo.lower()
        for osoba in osoby
        for slowo in _SLOWO_Z_WIELKIEJ.findall(osoba)
        if len(slowo) >= 3 and slowo.lower().strip(".") not in _TYTULY_OSOB
    }
    wynik: set[str] = set()
    for tekst, zakresy in zip(teksty, zajete):
        for m in _SLOWO_Z_WIELKIEJ.finditer(tekst):
            slowo = m.group()
            if len(slowo) < 3 or not slowo[0].isupper() or slowo.lower() in _TYTULY_OSOB:
                continue
            if any(z.start < m.end() and m.start() < z.koniec for z in zakresy):
                continue
            czlony = slowo.lower().split("-")
            for znany in znane:
                zczlony = znany.split("-")
                if len(zczlony) == len(czlony) and all(map(_czlon_pasuje, zczlony, czlony)):
                    wynik.add(slowo)
                    break
    return wynik


class _ZDopelnieniem:
    """Detector + fragments that the check found in the result (2026-10-28).

    The model sees a different context once part of the data is masked and can
    only then recognise a person missed in the first pass ("Anna Kwiatkowska"
    in the sample letter). Instead of blocking the whole result, we also hide
    those fragments everywhere they appear in the original.
    """

    def __init__(self, wewnetrzny, fragmenty: dict[str, TypEncji]):
        self._wewnetrzny = wewnetrzny
        self._fragmenty = fragmenty
        self.nazwa = wewnetrzny.nazwa
        self.typy = frozenset(wewnetrzny.typy) | frozenset(fragmenty.values())

    def znajdz(self, tekst: str):
        dodatkowe = []
        for fragment, typ in self._fragmenty.items():
            start = tekst.find(fragment)
            while start != -1:
                koniec = start + len(fragment)
                if typ is TypEncji.OSOBA:
                    koniec = _koniec_osoby(tekst, koniec)
                dodatkowe.append(Zakres(start, koniec, typ, 1.0, "kontrola"))
                start = tekst.find(fragment, start + 1)
        bazowe = self._wewnetrzny.znajdz(tekst)
        return scal(tekst, bazowe + dodatkowe) if dodatkowe else bazowe


def zbuduj_detektor(poziom: int, konfig, pakiet_rozszerzony: bool = False, katalog_pakietow=None):
    """Detector for level 1-3; a build error = `BladDetektora` (fail-closed).

    The level composition (1 = rules+bardsai; 2 = variant A; 3 = variant B) is done by
    `detektory.zbuduj_poziom` - the same function as in measurement.
    `pakiet_rozszerzony` = verified state of the Extended package (the API passes
    it from the package manager state); without it level 3 does not use LFM2.5.
    `katalog_pakietow` = trusted definitions of installed packages (after an update
    they differ from the built-in ones); without it the built-in catalog applies.
    """
    if poziom not in (1, 2, 3):
        raise ValueError(f"poziom poza 1-3: {poziom}")
    if konfig.modele_katalog is None:
        raise BladDetektora(
            "brak wag modelu: ustaw NIEWIDKA_MODELE_KATALOG — warstwa detekcji modelowej "
            "jest obowiązkowa, nie zwracamy wyniku bez pełnej warstwy (fail-closed)"
        )
    baza: object = RegulyDetektor()
    if not konfig.wykrywaj_date:
        baza = _BezDaty(baza)
    return zbuduj_poziom(
        poziom,
        konfig.modele_katalog,
        provider=konfig.provider,
        próg_osoba=konfig.prog_osoba,
        reguly=baza,
        pakiet_rozszerzony=pakiet_rozszerzony,
        watki=getattr(konfig, "watki", 0),
        katalog_pakietow=katalog_pakietow,
    )


def _sprawdz_format(format: str) -> None:
    if format.lower() not in rozszerzenia_wspierane():
        raise NieznanyFormat(format, sorted(rozszerzenia_wspierane()))


def _sprawdz_rozpakowane(dane: bytes, limit_bajtow: int | None) -> None:
    if not limit_bajtow or not zipfile.is_zipfile(BytesIO(dane)):
        return
    with zipfile.ZipFile(BytesIO(dane)) as paczka:
        suma = sum(info.file_size for info in paczka.infolist())
    if suma > limit_bajtow:
        raise ArchiwumZaDuze(f"rozpakowana treść archiwum {suma} B przekracza limit {limit_bajtow} B")


def uwagi_obrazow(dok) -> list[str]:
    """Non-blocking notes about images, shared by `ukryj` and corrections."""
    uwagi: list[str] = []
    obrazy = (dok.zasoby or {}).get("obrazy", {})
    if obrazy.get("usuniete"):
        uwagi.append(
            f"OBRAZ USUNIĘTY ({obrazy['usuniete']} szt.): bez OCR treść obrazu nie daje się sprawdzić"
        )
    if obrazy.get("pozostale"):
        uwagi.append(
            f"OBRAZ BEZ OCR ({obrazy['pozostale']} szt.): treść obrazu pozostała w wyniku i nie daje się sprawdzić"
        )
    return uwagi


def zloz_wynik(
    adapter, dok, segmenty_encji: list[list[Encja]], poziom: int
) -> tuple[bytes, Mapa, dict[str, int], dict[str, Wpis]]:
    """Markers in the document + a new map from the detections (entities with labels). Shared by
    `ukryj` and `poprawki.popraw`, so both build the result and the map the same way."""
    statystyki: dict[str, int] = {}
    wystapienia: list[Wystapienie] = []
    wpisy: dict[str, Wpis] = {}
    for segment, encje in zip(dok.segmenty, segmenty_encji):
        if not encje:
            continue
        posortowane = sorted(encje, key=lambda e: e.zakres.start)
        adapter.wstaw_znaczniki(
            segment, [(e.zakres.start, e.zakres.koniec, znacznik_encji(e)) for e in posortowane]
        )
        for encja in posortowane:
            typ = encja.zakres.typ.value
            statystyki[typ] = statystyki.get(typ, 0) + 1
            wariant = encja.wariant or WARIANT_DOMYSLNY
            wystapienia.append(Wystapienie(len(wystapienia), encja.oznaczenie, wariant, encja.tekst))
            wpis = wpisy.setdefault(encja.oznaczenie, Wpis(typ, encja.oznaczenie, {}))
            wpis.formy.setdefault(wariant, encja.tekst)

    mapa = Mapa(
        # 128 bits - a 24-bit id allowed winning a collision against old
        # maps (~77.5% for 5000x5000) and accepting ciphertext from an earlier session
        identyfikator=secrets.token_hex(16),
        utworzono=datetime.now().astimezone().isoformat(timespec="seconds"),
        poziom=poziom,
        wpisy=list(wpisy.values()),
        wystapienia=wystapienia,
    )
    # the id in the content ties the map to the document
    return adapter.zapisz(dok, dopisek(mapa.identyfikator)), mapa, statystyki, wpisy


def ukryj(
    dane: bytes,
    format: str,
    poziom: int,
    *,
    detektor=None,
    konfig=None,
    kontrola_blokada: bool = True,
    max_rozpakowane_bajtow: int | None = None,
    polityka_obrazow: str = "usun",
) -> tuple[bytes, Mapa, Raport]:
    """Document -> result with markers + map + report (write check always on).

    `polityka_obrazow`: usun | blokuj | zostaw - by default we remove
    images (they cannot be verified without OCR) and leave a note in the report.
    """
    _sprawdz_format(format)
    if detektor is None:
        if konfig is None:
            raise ValueError("ukryj wymaga detektora albo konfiguracji do jego zbudowania")
        detektor = zbuduj_detektor(poziom, konfig)
    _sprawdz_rozpakowane(dane, max_rozpakowane_bajtow)
    # 2026-10-28: a check finding in the content is data missed in the previous
    # pass; we hide it and check again. The block stays when the next
    # pass has nothing left to add (e.g. a leak in a part the adapter does not read).
    dok_wejscia = adapter_formatu(format).wczytaj(
        dane, polityka_obrazow=polityka_obrazow, max_rozpakowane=max_rozpakowane_bajtow
    )
    if any(WZORZEC_ZNACZNIKA.search(segment.tekst) for segment in dok_wejscia.segmenty):
        raise ZnacznikiWTresci(
            "dokument zawiera już znaczniki Niewidki (np. [OSOBA_1]); ukryj oryginał, "
            "a nie wynik wcześniejszego ukrywania"
        )
    fragmenty: dict[str, TypEncji] = {}
    # union of originals from ALL passes: a merge in a later pass yields
    # a longer original, and the shorter one from an earlier pass must still be searched for in the result
    oryginaly: set[str] = set()
    for _ in range(MAKS_PRZEBIEGOW):
        detektor_przebiegu = _ZDopelnieniem(detektor, fragmenty) if fragmenty else detektor
        adapter = adapter_formatu(format)
        dok = adapter.wczytaj(
            dane, polityka_obrazow=polityka_obrazow, max_rozpakowane=max_rozpakowane_bajtow
        )
        teksty_wejscia = [segment.tekst for segment in dok.segmenty]

        segmenty_encji = [
            [
                Encja(zakres=z, tekst=segment.tekst[z.start : z.koniec])
                for z in detektor_przebiegu.znajdz(segment.tekst)
            ]
            for segment in dok.segmenty
        ]
        wszystkie = [encja for encje in segmenty_encji for encja in encje]
        pogrupuj(wszystkie)
        nadaj_oznaczenia(wszystkie)

        wynik, mapa, statystyki, wpisy = zloz_wynik(adapter, dok, segmenty_encji, poziom)
        wystapienia = mapa.wystapienia
        # map originals = second check grid (every part of the archive)
        oryginaly |= {wyst.oryginal for wyst in wystapienia} | {
            forma for wpis in wpisy.values() for forma in wpis.formy.values()
        }
        ostrzezenia = kontroluj(
            wynik,
            f"wynik.{format}",
            detektor,
            oryginaly=sorted(oryginaly),
            max_rozpakowane=max_rozpakowane_bajtow,
        )
        # ORIGINAL = a map value the model missed elsewhere: we hide it
        # everywhere with the type from the map (API tests 2026-10-29). It stays only where the adapter
        # does not read (styles, metadata) - then the next pass adds nothing and the block applies.
        typ_oryginalu = {
            forma: TypEncji(wpis.typ) for wpis in wpisy.values() for forma in wpis.formy.values()
        }
        nowe: dict[str, TypEncji] = {}
        for o in ostrzezenia:
            fragment = o.fragment.strip()
            if not fragment or fragment in fragmenty:
                continue
            if o.typ in TYPY_ENCJI:
                nowe[fragment] = TypEncji(o.typ)
            elif o.typ == "ORYGINAL" and fragment in typ_oryginalu:
                nowe[fragment] = typ_oryginalu[fragment]
        for forma in _formy_znanych_osob(
            teksty_wejscia,
            [[e.zakres for e in encje] for encje in segmenty_encji],
            [e.tekst for e in wszystkie if e.zakres.typ is TypEncji.OSOBA],
        ):
            if forma not in fragmenty:
                nowe[forma] = TypEncji.OSOBA
        if not nowe:
            break
        fragmenty.update(nowe)
    uwagi = uwagi_obrazow(dok)
    raport = Raport(
        identyfikator=mapa.identyfikator,
        poziom=poziom,
        statystyki=statystyki,
        ostrzezenia=ostrzezenia,
        uwagi=uwagi,
        r95={typ: r95_z_kalibracji(poziom, typ) for typ in statystyki},
        status="zablokowany" if ostrzezenia and kontrola_blokada else "ukonczony",
        detekcje=Detekcje(
            dane=dane,
            format=format,
            poziom=poziom,
            polityka_obrazow=polityka_obrazow,
            max_rozpakowane_bajtow=max_rozpakowane_bajtow,
            encje=segmenty_encji,
            ostrzezenia_tekstu=[o for o in ostrzezenia if o.segment >= 0],
        ),
    )
    return wynik, mapa, raport


_ID_W_DOPISKU = re.compile(r"Identyfikator mapy: ([a-p]+)")


def identyfikator_z_dopisku(
    dane: bytes, format: str, *, max_rozpakowane_bajtow: int | None = None
) -> str | None:
    """First map identifier from the note in the document body; None when there is
    no note (e.g. the AI chat did not repeat it). Reused by /api/przywroc
    to find the map in the store without a .nwidka file."""
    _sprawdz_format(format)
    _sprawdz_rozpakowane(dane, max_rozpakowane_bajtow)
    dok = adapter_formatu(format).wczytaj(dane, max_rozpakowane=max_rozpakowane_bajtow)
    znalezione = {m.group(1) for s in dok.segmenty for m in _ID_W_DOPISKU.finditer(s.tekst)}
    for litery in sorted(znalezione):
        identyfikator = odkoduj_identyfikator(litery)
        if identyfikator is not None:
            return identyfikator
    return None


def przywroc(
    dane: bytes, format: str, mapa: Mapa, *, max_rozpakowane_bajtow: int | None = None
) -> tuple[bytes, list[Rozbieznosc]]:
    """Replace markers with originals by (label, variant); the result note disappears.

    Restore recreates only data replaced by markers - elements removed
    during cleanup (metadata, comments) do not come back.
    """
    _sprawdz_format(format)
    _sprawdz_rozpakowane(dane, max_rozpakowane_bajtow)
    adapter = adapter_formatu(format)
    dok = adapter.wczytaj(dane, max_rozpakowane=max_rozpakowane_bajtow)
    # the map is tied to a SPECIFIC document. A note with the identifier of
    # another map = refusal. A missing note is a normal AI chat reply (it does not repeat it),
    # so we restore, but with a warning that map consistency cannot be checked.
    znalezione = {m.group(1) for s in dok.segmenty for m in _ID_W_DOPISKU.finditer(s.tekst)}
    rozbieznosci: list[Rozbieznosc] = []
    if znalezione and zakoduj_identyfikator(mapa.identyfikator) not in znalezione:
        raise BladMapy("tekst pochodzi z innego zadania niż ta mapa (inny identyfikator mapy)")
    if not znalezione:
        rozbieznosci.append(
            Rozbieznosc(
                "brak_identyfikatora",
                "W tekście nie ma identyfikatora mapy, więc program nie sprawdzi, czy mapa"
                " pasuje. Upewnij się, że to mapa z tego samego zadania",
            )
        )
    uzyte: set[str] = set()
    for segment in dok.segmenty:
        zamiany, braki, uzyte_w_segmencie = przygotuj_zamiany(segment.tekst, mapa)
        rozbieznosci.extend(braki)
        uzyte |= uzyte_w_segmencie
        if zamiany:
            adapter.wstaw_znaczniki(segment, zamiany)
    rozbieznosci.extend(rozbieznosci_wpisow(mapa, uzyte))
    return adapter.zapisz(dok, dopisek=False), rozbieznosci
