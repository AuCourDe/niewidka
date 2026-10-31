"""Preview corrections: "Ukryj wszędzie" and "To nie dane".

The server keeps in memory (RAM) the detections of recent jobs (`PamiecWykryc`: 4 jobs by default
for 15 minutes, nothing on disk, nothing in logs). `popraw` computes a new result from them WITHOUT re-running
the model: numbers of existing markers do not change, new ones get the next numbers.
The check after a correction is the rules, the originals from the map and the model findings from the base result
that are still in the text (the model is not called a second time).

SIMPLIFICATION: inflection matching uses the same ending stem as person grouping
(`osoby.rdzen_nazwiska`), so short words (up to 3 letters) inflect invisibly
("Ewa"/"Ewy" are different words to the program). When to extend: once lemmatization (Morfeusz) is available."""

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

# types with a checksum: a certain detection, so "To nie dane" is blocked for them
TYPY_Z_SUMA = frozenset(
    {TypEncji.PESEL, TypEncji.NIP, TypEncji.REGON, TypEncji.IBAN, TypEncji.KARTA, TypEncji.DOKUMENT}
)
MAKS_POZYCJI = 200
MAKS_ZNAKOW = 200

_TOKEN = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*")
_ZNACZNIK = re.compile(r"[A-Z]+_\d+")


class BladPoprawki(ValueError):
    """A bad correction (list, fragment, marker or a type with a checksum) -> 422.
        The message never quotes the submitted fragments."""


class PamiecWykryc:
    """Detections of recent jobs in RAM; key = job id (of the base map).
        The clock is injected (tests of expiry without waiting)."""

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
                del self._wpisy[next(iter(self._wpisy))]  # oldest
            self._wpisy[zadanie] = (self.zegar() + self.ttl_s, detekcje)

    def pobierz(self, zadanie: str) -> Detekcje | None:
        with self._blokada:
            self._wygas()
            wpis = self._wpisy.get(zadanie)
            return wpis[1] if wpis else None


def _normalizuj(tekst: str) -> str:
    return " ".join(tekst.split())


def sprawdz_liste(nazwa: str, wartosc: object) -> list[str]:
    """A list of texts with limits (200 entries of 200 characters); empty ones and duplicates are dropped."""
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
    """Ranges of whole words equal to the fragment in any inflection (word boundaries with Polish
        letters: "Lis" does not touch "Listopad"). A multi-word fragment: the same words in the same
        order and with the same separators (spaces do not matter)."""
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
    """The rule type when one detection covers the whole fragment; otherwise INNE."""
    zakresy = RegulyDetektor().znajdz(fragment)
    if len(zakresy) == 1 and _normalizuj(fragment[zakresy[0].start : zakresy[0].koniec]) == fragment:
        return zakresy[0].typ
    return TypEncji.INNE


def _numer(oznaczenie: str) -> tuple[str, int]:
    typ, _, numer = oznaczenie.rpartition("_")
    return typ, int(numer)


def _nachodza(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _z_wykryciami(zakres: tuple[int, int], encje: list[Encja]) -> tuple[int, int]:
    """Union of the range with all overlapping detections (indirectly too)."""
    start, koniec = zakres
    zmiana = True
    while zmiana:
        zmiana = False
        for e in encje:
            if _nachodza((start, koniec), (e.zakres.start, e.zakres.koniec)) and (
                e.zakres.start < start or e.zakres.koniec > koniec
            ):
                start, koniec = min(start, e.zakres.start), max(koniec, e.zakres.koniec)
                zmiana = True
    return start, koniec


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
    """Result from the remembered detections after the user's decisions, without the model.

        `ukryj`: fragments to hide everywhere (whole words, every inflection). `nie_dane`: markers
        removed entirely (all occurrences of that person/value in this result); "ukryj"
        wins. `zostaw`: doubtful places from the check accepted as non-data. Types with a checksum
        are not removed (BladPoprawki). `na_inne`: markers that change kind to INNE (e.g. a
        department name taken by the model for a person); they get a new INNE number, other numbers
        unchanged (the gap in numbering is deliberate). Returns (result, map, report, wlasne), where `wlasne` is
        marker -> number of the `ukryj` entry it came from.
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

    # ranges from the "ukryj" list in every segment, separately for each entry
    trafienia = [
        [(start, koniec, i) for i, fragment in enumerate(ukryj) for start, koniec in znajdz_wystapienia(t, fragment)]
        for t in teksty
    ]
    # "ukryj" wins over "To nie dane": a group touched by a selection stays
    zdjete = set(nie_dane)
    for encje, nowe in zip(stare, trafienia):
        for encja in encje:
            if encja.oznaczenie in zdjete and any(
                _nachodza((encja.zakres.start, encja.zakres.koniec), (s, k)) for s, k, _ in nowe
            ):
                zdjete.discard(encja.oznaczenie)
    wyjatki = {_normalizuj(e.tekst) for encje in stare for e in encje if e.oznaczenie in zdjete}
    wyjatki |= set(zostaw)

    # numbering: the highest number of the type among base detections (removed ones too), new ones continue
    najwyzszy: dict[str, int] = {}
    for oznaczenie in typy_znacznikow:
        typ, numer = _numer(oznaczenie)
        najwyzszy[typ] = max(najwyzszy.get(typ, 0), numer)

    zachowane: list[list[Encja]] = []
    dodane: list[list[tuple[int, int, int]]] = []
    for encje, nowe in zip(stare, trafienia):
        kept = [e for e in encje if e.oznaczenie not in zdjete]
        # new ones entirely inside an existing detection add nothing
        nowe = [
            n for n in nowe
            if not any(e.zakres.start <= n[0] and n[1] <= e.zakres.koniec for e in kept)
        ]
        # partially overlapping: the new range covers the whole earlier detection so nothing is exposed
        nowe = [(*_z_wykryciami(n[:2], kept), n[2]) for n in nowe]
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

    # kind change to INNE after "ukryj", so the user's fragment numbers do not shift
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

    # check after the correction: rules + originals from the map + doubtful places from the base result
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
        # user fragments are whole words: "Lis" is not a leak in "Listopad"
        pelne_slowa=frozenset(f for o in wlasne for f in wpisy[o].formy.values()),
    )
    tekst_wyniku = "\n".join(
        s.tekst
        for s in adapter_formatu(detekcje.format)
        .wczytaj(wynik, max_rozpakowane=detekcje.max_rozpakowane_bajtow)
        .segmenty
    )
    # the check sees the text with markers replaced by spaces (offsets unchanged)
    tekst_jak_w_kontroli = WZORZEC_ZNACZNIKA.sub(lambda m: " " * len(m.group()), tekst_wyniku)
    znane = {(o.typ, o.fragment) for o in ostrzezenia}
    for o in detekcje.ostrzezenia_tekstu:
        if o.fragment and o.fragment in tekst_jak_w_kontroli and (o.typ, o.fragment) not in znane:
            ostrzezenia.append(replace(o, start=-1))  # the position from the base result is already stale
    suma = {t.value for t in TYPY_Z_SUMA}
    pozostale = []
    for o in ostrzezenia:
        fragment = _normalizuj(o.fragment)
        if o.typ in suma:  # a certain detection is not removed, and asking to remove it is an error
            if fragment in zostaw:
                raise BladPoprawki("dla numerów z sumą kontrolną nie ma opcji „To nie dane”")
        elif fragment and any(fragment in wyjatek for wyjatek in wyjatki):
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
