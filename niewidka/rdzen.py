"""Rdzeń ukryj/przywroc (K4): jedna para funkcji dla API i przyszłego desktopu (LLD §8/§12).

`ukryj(dane, format, poziom)` zwraca (wynik, mapa, raport); detektor idzie
wstrzyknięty albo buduje się z konfiguracji (poziomy 1-3 wg K2d: 1 = reguły +
bardsai, 2 = wariant A — próg OSOBA + okna półkrokowe, 3 = wariant B —
+słownik imion; LFM2.5 odrzucony pomiarem — `docs/WYNIK-K2b.md`). Kontrola
zapisu działa ZAWSZE (Astra pkt 8); nowe znaleziska blokują status „ukończony".
"""

from __future__ import annotations

import secrets
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

from niewidka.detektory import BladDetektora, RegulyDetektor, zbuduj_poziom
from niewidka.formaty import NieznanyFormat, adapter_formatu, rozszerzenia_wspierane
from niewidka.jakosc import r95_z_kalibracji
from niewidka.kontrola import Ostrzezenie, kontroluj
from niewidka.mapa import (
    WARIANT_DOMYSLNY,
    BladMapy,
    Mapa,
    Rozbieznosc,
    Wpis,
    Wystapienie,
    przygotuj_zamiany,
    rozbieznosci_wpisow,
)
from niewidka.model import Encja, TypEncji
from niewidka.osoby import pogrupuj
from niewidka.znaczniki import dopisek, nadaj_oznaczenia, zakoduj_identyfikator, znacznik_encji


class ArchiwumZaDuze(Exception):
    """Suma rozpakowanych strumieni archiwum ponad limit (zip bomb, LLD §16 → 413)."""


@dataclass
class Raport:
    identyfikator: str
    poziom: int
    statystyki: dict[str, int]  # typ -> liczba zastąpionych encji
    ostrzezenia: list[Ostrzezenie] = field(default_factory=list)
    uwagi: list[str] = field(default_factory=list)  # nieblokujące (K4b pkt 2: usunięte obrazy)
    r95: dict[str, float | None] = field(default_factory=dict)
    status: str = "ukonczony"  # "zablokowany", gdy kontrola znalazła nowe znaleziska


class _BezDaty:
    """Wrapper wyłączający typ DATA (konfiguracja `wykrywaj_date`, LLD §3)."""

    def __init__(self, wewnetrzny):
        self._wewnetrzny = wewnetrzny
        self.nazwa = wewnetrzny.nazwa
        self.typy = frozenset(wewnetrzny.typy) - {TypEncji.DATA}

    def znajdz(self, tekst: str):
        return [z for z in self._wewnetrzny.znajdz(tekst) if z.typ is not TypEncji.DATA]


def zbuduj_detektor(poziom: int, konfig):
    """Detektor dla poziomu 1-3; błąd budowy = `BladDetektora` (fail-closed, LLD §15).

    Skład poziomu (1 = reguły+bardsai; 2 = wariant A; 3 = wariant B, K2d) robi
    `detektory.zbuduj_poziom` — ta sama funkcja co w pomiarze.
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
    """Dokument -> wynik ze znacznikami + mapa + raport (kontrola zapisu zawsze).

    `polityka_obrazow` (K4b pkt 2): usun | blokuj | zostaw — domyślnie usuwamy
    obrazy (bez OCR nie dają się zweryfikować) i zostawiamy uwagę w raporcie.
    """
    _sprawdz_format(format)
    if detektor is None:
        if konfig is None:
            raise ValueError("ukryj wymaga detektora albo konfiguracji do jego zbudowania")
        detektor = zbuduj_detektor(poziom, konfig)
    _sprawdz_rozpakowane(dane, max_rozpakowane_bajtow)
    adapter = adapter_formatu(format)
    dok = adapter.wczytaj(dane, polityka_obrazow=polityka_obrazow)

    segmenty_encji = [
        [Encja(zakres=z, tekst=segment.tekst[z.start : z.koniec]) for z in detektor.znajdz(segment.tekst)]
        for segment in dok.segmenty
    ]
    wszystkie = [encja for encje in segmenty_encji for encja in encje]
    pogrupuj(wszystkie)
    nadaj_oznaczenia(wszystkie)

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
        # K4b pkt 7: 128 bitów — 24-bitowy id pozwalał wygrać kolizję ze starymi
        # mapami (~77,5% dla 5000×5000) i przyjąć szyfrogram z wcześniejszej sesji
        identyfikator=secrets.token_hex(16),
        utworzono=datetime.now().astimezone().isoformat(timespec="seconds"),
        poziom=poziom,
        wpisy=list(wpisy.values()),
        wystapienia=wystapienia,
    )
    wynik = adapter.zapisz(dok, dopisek(mapa.identyfikator))  # id w treści wiąże mapę z dokumentem
    # K3b: oryginały mapy = druga siatka kontroli (każda część archiwum)
    oryginaly = {wyst.oryginal for wyst in wystapienia} | {
        forma for wpis in wpisy.values() for forma in wpis.formy.values()
    }
    ostrzezenia = kontroluj(wynik, f"wynik.{format}", detektor, oryginaly=sorted(oryginaly))
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
    raport = Raport(
        identyfikator=mapa.identyfikator,
        poziom=poziom,
        statystyki=statystyki,
        ostrzezenia=ostrzezenia,
        uwagi=uwagi,
        r95={typ: r95_z_kalibracji(poziom, typ) for typ in statystyki},
        status="zablokowany" if ostrzezenia and kontrola_blokada else "ukonczony",
    )
    return wynik, mapa, raport


def przywroc(
    dane: bytes, format: str, mapa: Mapa, *, max_rozpakowane_bajtow: int | None = None
) -> tuple[bytes, list[Rozbieznosc]]:
    """Zamiana znaczników na oryginały wg (oznaczenie, wariant); dopisek wyniku znika.

    Przywrócenie odtwarza wyłącznie dane zastąpione znacznikami — elementy usunięte
    przy czyszczeniu (metadane, komentarze) nie wracają (LLD §7/§8).
    """
    _sprawdz_format(format)
    _sprawdz_rozpakowane(dane, max_rozpakowane_bajtow)
    adapter = adapter_formatu(format)
    dok = adapter.wczytaj(dane)
    # K4b pkt 6: mapa jest związana z KONKRETNYM dokumentem — identyfikator zapisany
    # w dopisku wyniku (jako litery, bez cyfr) musi równać się identyfikatorowi mapy
    if not any(
        zakoduj_identyfikator(mapa.identyfikator) in segment.tekst for segment in dok.segmenty
    ):
        raise BladMapy(
            "wynik nie zawiera identyfikatora tej mapy — dokument i mapa pochodzą z różnych zadań"
        )
    rozbieznosci: list[Rozbieznosc] = []
    uzyte: set[str] = set()
    for segment in dok.segmenty:
        zamiany, braki, uzyte_w_segmencie = przygotuj_zamiany(segment.tekst, mapa)
        rozbieznosci.extend(braki)
        uzyte |= uzyte_w_segmencie
        if zamiany:
            adapter.wstaw_znaczniki(segment, zamiany)
    rozbieznosci.extend(rozbieznosci_wpisow(mapa, uzyte))
    return adapter.zapisz(dok, dopisek=False), rozbieznosci
