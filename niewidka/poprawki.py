"""Poprawki w podglądzie: „Ukryj wszędzie” i „To nie dane”.

Serwer trzyma w pamięci (RAM) wykrycia ostatnich zadań (`PamiecWykryc`: domyślnie 4 zadania
przez 15 minut, nic na dysk, nic w logach). `popraw` liczy z nich nowy wynik BEZ ponownego
uruchamiania modelu: numery istniejących znaczników się nie zmieniają, nowe dostają kolejne.
Kontrola wyniku po poprawce to reguły, oryginały z mapy i znaleziska modelu z wyniku bazowego,
które nadal są w tekście (model nie jest wołany drugi raz).

SIMPLIFICATION: dopasowanie odmian to ten sam rdzeń końcówkowy co grupowanie osób
(`osoby.rdzen_nazwiska`), więc krótkie słowa (do 3 liter) odmieniają się niewidocznie
(„Ewa”/„Ewy” to dla programu różne słowa). Kiedy rozbudować: gdy pojawi się lematyzacja (Morfeusz).
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import replace
from itertools import pairwise

from niewidka.detektory import RegulyDetektor
from niewidka.formaty import adapter_formatu
from niewidka.jakosc import r95_z_kalibracji
from niewidka.kontrola import Ostrzezenie, kontroluj
from niewidka.mapa import WZORZEC_ZNACZNIKA, Mapa
from niewidka.model import Encja, TypEncji, Zakres
from niewidka.osoby import rdzen_nazwiska
from niewidka.rdzen import Detekcje, Raport, _BezDaty, uwagi_obrazow, zloz_wynik

# typy z sumą kontrolną: pewne wykrycie, więc „To nie dane” jest dla nich zablokowane
TYPY_Z_SUMA = frozenset(
    {TypEncji.PESEL, TypEncji.NIP, TypEncji.REGON, TypEncji.IBAN, TypEncji.KARTA, TypEncji.DOKUMENT}
)
MAKS_POZYCJI = 200
MAKS_ZNAKOW = 200

_TOKEN = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*")
_ZNACZNIK = re.compile(r"[A-Z]+_\d+")


class BladPoprawki(ValueError):
    """Zła poprawka (lista, fragment, znacznik albo typ z sumą kontrolną) → 422.
    Komunikat nigdy nie cytuje przysłanych fragmentów."""


class PamiecWykryc:
    """Wykrycia ostatnich zadań w RAM; klucz = identyfikator zadania (mapy bazowej).
    Zegar wstrzykiwany (testy wygasania bez czekania)."""

    def __init__(self, maks: int = 4, ttl_s: int = 900, zegar: Callable[[], float] = time.monotonic):
        self.maks = maks
        self.ttl_s = ttl_s
        self.zegar = zegar
        self._wpisy: dict[str, tuple[float, Detekcje]] = {}
        self._blokada = threading.Lock()

    def _wygas(self) -> None:
        teraz = self.zegar()
        for klucz in [k for k, (do, _) in self._wpisy.items() if do <= teraz]:
            del self._wpisy[klucz]

    def zapamietaj(self, zadanie: str, detekcje: Detekcje) -> None:
        with self._blokada:
            self._wygas()
            if self.maks <= 0 or self.ttl_s <= 0:
                return
            self._wpisy.pop(zadanie, None)
            while len(self._wpisy) >= self.maks:
                del self._wpisy[next(iter(self._wpisy))]  # najstarsze
            self._wpisy[zadanie] = (self.zegar() + self.ttl_s, detekcje)

    def pobierz(self, zadanie: str) -> Detekcje | None:
        with self._blokada:
            self._wygas()
            wpis = self._wpisy.get(zadanie)
            return wpis[1] if wpis else None


def _normalizuj(tekst: str) -> str:
    return " ".join(tekst.split())


def sprawdz_liste(nazwa: str, wartosc: object) -> list[str]:
    """Lista tekstów z limitami (200 pozycji po 200 znaków); puste i duplikaty odpadają."""
    if wartosc is None:
        return []
    if not isinstance(wartosc, list) or not all(isinstance(p, str) for p in wartosc):
        raise BladPoprawki(f"pole {nazwa}: oczekiwano listy tekstów")
    if len(wartosc) > MAKS_POZYCJI:
        raise BladPoprawki(f"pole {nazwa}: najwyżej {MAKS_POZYCJI} pozycji")
    wynik: list[str] = []
    for pozycja in wartosc:
        czysta = _normalizuj(pozycja)
        if len(czysta) > MAKS_ZNAKOW:
            raise BladPoprawki(f"pole {nazwa}: pozycja dłuższa niż {MAKS_ZNAKOW} znaków")
        if czysta and czysta not in wynik:
            wynik.append(czysta)
    return wynik


def _klucz(slowo: str) -> str:
    return "-".join(rdzen_nazwiska(czlon) for czlon in slowo.split("-"))


def znajdz_wystapienia(tekst: str, fragment: str) -> list[tuple[int, int]]:
    """Zakresy całych słów równych fragmentowi w dowolnej odmianie (granice słów z polskimi
    literami: „Lis” nie rusza „Listopad”). Fragment wielowyrazowy: te same słowa w tej
    kolejności i z tymi samymi separatorami (spacje bez znaczenia)."""
    w_fragmencie = list(_TOKEN.finditer(fragment))
    if not w_fragmencie:
        raise BladPoprawki("fragment bez liter i cyfr")
    klucze = [_klucz(m.group()) for m in w_fragmencie]
    separatory = [
        _normalizuj(fragment[a.end() : b.start()]) for a, b in pairwise(w_fragmencie)
    ]
    w_tekscie = list(_TOKEN.finditer(tekst))
    klucze_tekstu = [_klucz(m.group()) for m in w_tekscie]
    n = len(klucze)
    wynik = []
    for i in range(len(w_tekscie) - n + 1):
        if klucze_tekstu[i : i + n] != klucze:
            continue
        if any(
            _normalizuj(tekst[w_tekscie[i + j].end() : w_tekscie[i + j + 1].start()]) != separatory[j]
            for j in range(n - 1)
        ):
            continue
        wynik.append((w_tekscie[i].start(), w_tekscie[i + n - 1].end()))
    return wynik


def _typ_z_regul(fragment: str) -> TypEncji:
    """Typ z reguł, gdy jedno wykrycie obejmuje cały fragment; inaczej INNE."""
    zakresy = RegulyDetektor().znajdz(fragment)
    if len(zakresy) == 1 and _normalizuj(fragment[zakresy[0].start : zakresy[0].koniec]) == fragment:
        return zakresy[0].typ
    return TypEncji.INNE


def _numer(oznaczenie: str) -> tuple[str, int]:
    typ, _, numer = oznaczenie.rpartition("_")
    return typ, int(numer)


def _nachodza(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def popraw(
    detekcje: Detekcje,
    ukryj: Iterable[str],
    nie_dane: Iterable[str],
    zostaw: Iterable[str] = (),
    na_inne: Iterable[str] = (),
    *,
    kontrola_blokada: bool = True,
    wykrywaj_date: bool = True,
) -> tuple[bytes, Mapa, Raport, dict[str, int]]:
    """Wynik z zapamiętanych wykryć po decyzjach użytkownika, bez modelu.

    `ukryj`: fragmenty do ukrycia wszędzie (całe słowa, każda odmiana). `nie_dane`: znaczniki
    zdejmowane w całości (wszystkie wystąpienia tej osoby/wartości w tym wyniku); „ukryj”
    wygrywa. `zostaw`: miejsca wątpliwe z kontroli uznane za nie-dane. Typy z sumą kontrolną
    nie schodzą (BladPoprawki). `na_inne`: znaczniki, które zmieniają rodzaj na INNE (np. nazwa
    referatu uznana przez model za osobę); dostają nowy numer INNE, pozostałe numery bez zmian
    (luka w numeracji jest celowa). Zwraca (wynik, mapa, raport, wlasne), gdzie `wlasne` to
    znacznik → numer pozycji `ukryj`, z której powstał.
    """
    ukryj, nie_dane, zostaw, na_inne = list(ukryj), list(nie_dane), list(zostaw), list(na_inne)
    adapter = adapter_formatu(detekcje.format)
    dok = adapter.wczytaj(
        detekcje.dane,
        polityka_obrazow=detekcje.polityka_obrazow,
        max_rozpakowane=detekcje.max_rozpakowane_bajtow,
    )
    teksty = [s.tekst for s in dok.segmenty]
    stare = detekcje.encje
    if len(stare) != len(teksty):
        raise BladPoprawki("dokument zmienił się od ukrycia; ukryj go ponownie")

    typy_znacznikow = {e.oznaczenie: e.zakres.typ for encje in stare for e in encje}
    for znacznik in nie_dane:
        if not _ZNACZNIK.fullmatch(znacznik) or znacznik not in typy_znacznikow:
            raise BladPoprawki("nieznany znacznik w polu nie_dane")
        if typy_znacznikow[znacznik] in TYPY_Z_SUMA:
            raise BladPoprawki(
                "dla numerów z sumą kontrolną (PESEL, NIP, REGON, IBAN, karta, dowód) "
                "nie ma opcji „To nie dane”"
            )

    for znacznik in na_inne:
        if not _ZNACZNIK.fullmatch(znacznik) or znacznik not in typy_znacznikow:
            raise BladPoprawki("nieznany znacznik w polu na_inne")
        if typy_znacznikow[znacznik] in TYPY_Z_SUMA or typy_znacznikow[znacznik] is TypEncji.INNE:
            raise BladPoprawki("tego znacznika nie można oznaczyć jako inne dane")

    # zakresy z listy „ukryj” w każdym segmencie, osobno dla każdej pozycji
    trafienia = [
        [(start, koniec, i) for i, fragment in enumerate(ukryj) for start, koniec in znajdz_wystapienia(t, fragment)]
        for t in teksty
    ]
    # „ukryj” wygrywa z „To nie dane”: grupa dotknięta zaznaczeniem zostaje
    zdjete = set(nie_dane)
    for encje, nowe in zip(stare, trafienia):
        for encja in encje:
            if encja.oznaczenie in zdjete and any(
                _nachodza((encja.zakres.start, encja.zakres.koniec), (s, k)) for s, k, _ in nowe
            ):
                zdjete.discard(encja.oznaczenie)
    wyjatki = {_normalizuj(e.tekst) for encje in stare for e in encje if e.oznaczenie in zdjete}
    wyjatki |= set(zostaw)

    # numeracja: najwyższy numer typu z wykryć bazowych (także zdjętych), nowe idą dalej
    najwyzszy: dict[str, int] = {}
    for oznaczenie in typy_znacznikow:
        typ, numer = _numer(oznaczenie)
        najwyzszy[typ] = max(najwyzszy.get(typ, 0), numer)

    zachowane: list[list[Encja]] = []
    dodane: list[list[tuple[int, int, int]]] = []
    for encje, nowe in zip(stare, trafienia):
        kept = [e for e in encje if e.oznaczenie not in zdjete]
        # nowe w całości wewnątrz istniejącego wykrycia nic nie wnoszą
        nowe = [
            n for n in nowe
            if not any(e.zakres.start <= n[0] and n[1] <= e.zakres.koniec for e in kept)
        ]
        kept = [e for e in kept if not any(_nachodza((e.zakres.start, e.zakres.koniec), n[:2]) for n in nowe)]
        przyjete: list[tuple[int, int, int]] = []
        for n in sorted(nowe, key=lambda n: (n[0], -(n[1] - n[0]))):
            if not any(_nachodza(n[:2], p[:2]) for p in przyjete):
                przyjete.append(n)
        zachowane.append(kept)
        dodane.append(przyjete)

    wlasne: dict[str, int] = {}
    nowe_encje: list[list[Encja]] = [list(k) for k in zachowane]
    for i, fragment in enumerate(ukryj):
        miejsca = [(s, n) for s, przyjete in enumerate(dodane) for n in przyjete if n[2] == i]
        if not miejsca:
            continue
        typ = _typ_z_regul(fragment)
        najwyzszy[typ.value] = najwyzszy.get(typ.value, 0) + 1
        oznaczenie = f"{typ.value}_{najwyzszy[typ.value]}"
        wlasne[oznaczenie] = i
        formy: dict[str, str] = {}
        for s, (start, koniec, _) in miejsca:
            tekst = teksty[s][start:koniec]
            formy.setdefault(tekst, None if not formy else f"F{len(formy) + 1}")
            nowe_encje[s].append(
                Encja(Zakres(start, koniec, typ, 1.0, "poprawka"), tekst, oznaczenie, None, formy[tekst])
            )

    # zmiana rodzaju na INNE po „ukryj”, więc numery fragmentów użytkownika się nie przesuwają
    nowe_oznaczenia: dict[str, str] = {}
    for znacznik in na_inne:
        if any(e.oznaczenie == znacznik for encje in nowe_encje for e in encje):
            najwyzszy[TypEncji.INNE.value] = najwyzszy.get(TypEncji.INNE.value, 0) + 1
            nowe_oznaczenia[znacznik] = f"{TypEncji.INNE.value}_{najwyzszy[TypEncji.INNE.value]}"
    if nowe_oznaczenia:
        nowe_encje = [
            [
                replace(e, zakres=replace(e.zakres, typ=TypEncji.INNE), oznaczenie=nowe_oznaczenia[e.oznaczenie])
                if e.oznaczenie in nowe_oznaczenia
                else e
                for e in encje
            ]
            for encje in nowe_encje
        ]

    wynik, mapa, statystyki, wpisy = zloz_wynik(adapter, dok, nowe_encje, detekcje.poziom)

    # kontrola po poprawce: reguły + oryginały z mapy + wątpliwe miejsca z wyniku bazowego
    detektor_kontroli = RegulyDetektor() if wykrywaj_date else _BezDaty(RegulyDetektor())
    oryginaly = sorted(
        {w.oryginal for w in mapa.wystapienia} | {f for w in wpisy.values() for f in w.formy.values()}
    )
    ostrzezenia: list[Ostrzezenie] = kontroluj(
        wynik,
        f"wynik.{detekcje.format}",
        detektor_kontroli,
        oryginaly=oryginaly,
        max_rozpakowane=detekcje.max_rozpakowane_bajtow,
        # fragmenty od użytkownika to całe słowa: „Lis” nie jest wyciekiem w „Listopad”
        pelne_slowa=frozenset(f for o in wlasne for f in wpisy[o].formy.values()),
    )
    tekst_wyniku = "\n".join(
        s.tekst
        for s in adapter_formatu(detekcje.format)
        .wczytaj(wynik, max_rozpakowane=detekcje.max_rozpakowane_bajtow)
        .segmenty
    )
    # kontrola widzi tekst ze znacznikami zastąpionymi spacjami (offsety bez zmian)
    tekst_jak_w_kontroli = WZORZEC_ZNACZNIKA.sub(lambda m: " " * len(m.group()), tekst_wyniku)
    znane = {(o.typ, o.fragment) for o in ostrzezenia}
    for o in detekcje.ostrzezenia_tekstu:
        if o.fragment and o.fragment in tekst_jak_w_kontroli and (o.typ, o.fragment) not in znane:
            ostrzezenia.append(replace(o, start=-1))  # pozycja z wyniku bazowego już nieaktualna
    suma = {t.value for t in TYPY_Z_SUMA}
    pozostale = []
    for o in ostrzezenia:
        fragment = _normalizuj(o.fragment)
        if o.typ in suma:  # pewne wykrycie nie schodzi, a prośba o zdjęcie go to błąd
            if fragment in zostaw:
                raise BladPoprawki("dla numerów z sumą kontrolną nie ma opcji „To nie dane”")
        elif any(fragment in wyjatek for wyjatek in wyjatki):
            continue
        pozostale.append(o)
    raport = Raport(
        identyfikator=mapa.identyfikator,
        poziom=detekcje.poziom,
        statystyki=statystyki,
        ostrzezenia=pozostale,
        uwagi=uwagi_obrazow(dok),
        r95={typ: r95_z_kalibracji(detekcje.poziom, typ) for typ in statystyki},
        status="zablokowany" if pozostale and kontrola_blokada else "ukonczony",
    )
    return wynik, mapa, raport, wlasne
