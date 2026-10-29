"""Rdzeń ukryj/przywroc (K4): jedna para funkcji dla API i przyszłego desktopu (LLD §8/§12).

`ukryj(dane, format, poziom)` zwraca (wynik, mapa, raport); detektor idzie
wstrzyknięty albo buduje się z konfiguracji (poziomy 1-3 wg K2d: 1 = reguły +
bardsai, 2 = wariant A — próg OSOBA + okna półkrokowe, 3 = wariant B —
+słownik imion; LFM2.5 odrzucony pomiarem — `docs/WYNIK-K2b.md`). Kontrola
zapisu działa ZAWSZE (Astra pkt 8); nowe znaleziska blokują status „ukończony".
"""

from __future__ import annotations

import re
import secrets
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

from niewidka.archiwum import ArchiwumZaDuze  # re-eksport: API łapie po tej nazwie
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
    statystyki: dict[str, int]  # typ -> liczba zastąpionych encji
    ostrzezenia: list[Ostrzezenie] = field(default_factory=list)
    uwagi: list[str] = field(default_factory=list)  # nieblokujące (K4b pkt 2: usunięte obrazy)
    r95: dict[str, float | None] = field(default_factory=dict)
    status: str = "ukonczony"  # "zablokowany", gdy kontrola znalazła nowe znaleziska
    # wykrycia ostatniego przebiegu do poprawek w podglądzie (tylko RAM, nigdy w odpowiedzi)
    detekcje: Detekcje | None = field(default=None, repr=False, compare=False)


@dataclass
class Detekcje:
    """Wykrycia ostatniego przebiegu `ukryj` (zakresy, typy, grupy osób, numeracja):
    z nich `poprawki.popraw` liczy nowy wynik BEZ ponownego uruchamiania modelu
    (docs/MAPY-I-AKTUALIZACJE.md §4, §8 pkt 4). Zawierają oryginał dokumentu, więc
    żyją wyłącznie w pamięci procesu (`poprawki.PamiecWykryc`), nigdy na dysku ani w logach."""

    dane: bytes
    format: str
    poziom: int
    polityka_obrazow: str
    max_rozpakowane_bajtow: int | None
    encje: list[list[Encja]]  # per segment dokumentu, z oznaczeniami i wariantami
    # znaleziska kontroli z segmentów tekstu (model + reguły) w wyniku bazowym: poprawka
    # nie uruchamia modelu, więc to one pilnują, że każde miejsce dostanie decyzję
    ostrzezenia_tekstu: list[Ostrzezenie] = field(default_factory=list)


class _BezDaty:
    """Wrapper wyłączający typ DATA (konfiguracja `wykrywaj_date`, LLD §3)."""

    def __init__(self, wewnetrzny):
        self._wewnetrzny = wewnetrzny
        self.nazwa = wewnetrzny.nazwa
        self.typy = frozenset(wewnetrzny.typy) - {TypEncji.DATA}

    def znajdz(self, tekst: str):
        return [z for z in self._wewnetrzny.znajdz(tekst) if z.typ is not TypEncji.DATA]


class ZnacznikiWTresci(BladMapy):
    """Wejście zawiera już znacznik Niewidki: nadany znacznik mógłby się z nim
    zderzyć i przywrócenie po cichu wstawiłoby dane w obce miejsce (Codex 2026-10-29)."""


MAKS_PRZEBIEGOW = 5  # zmierzone 2026-10-28: pismo właściciela potrzebuje do 4 (model niedeterministyczny)
TYPY_ENCJI = {typ.value for typ in TypEncji}
# do osoby z kontroli doliczamy do 2 kolejnych wyrazów z wielkiej litery w tej samej
# linii: model raz łapie „Jan Marek", raz „Nowicki" (zmierzone 2026-10-28). Zawsze
# po pełnych słowach (przegląd Codex 2026-10-29: „ Mc" zostawiało „Donald" jawne).
_ODSTEP = "[ \t\u00a0\u202f]+"
_SLOWO_NAZWISKA = re.compile(rf"{_ODSTEP}([^\W\d_][\w'’\-]*)")
_W_SLOWIE = re.compile(r"[\w'’\-]*")


def _koniec_osoby(tekst: str, koniec: int) -> int:
    koniec = _W_SLOWIE.match(tekst, koniec).end()  # fragment urwany w środku słowa
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
    """Ta sama forma podstawowa po wspólnym początku: Zawadzki/Zawadzkiemu,
    Marek/Markowi (ruchome „e"), Anna/Annie. Krótki początek nie wystarcza,
    żeby „Nowak" nie łapało „Nowy"."""
    warianty = {znany}
    if len(znany) >= 4 and znany[-2] == "e" and znany[-1] in "kc":
        warianty.add(znany[:-2] + znany[-1])  # Marek → Mark-owi, Jacek → Jack-a
    for wzor in warianty:
        p = _wspolny_poczatek(wzor, kandydat)
        if len(wzor) <= 4:  # Anna/Annie, Jan/Jana: próg od długości ZNANEJ formy
            if p >= max(3, len(wzor) - 1):
                return True
        elif p >= 4 and p >= len(wzor) - 3:
            return True
    return False


def _formy_znanych_osob(teksty: list[str], zajete: list[list[Zakres]], osoby: list[str]) -> set[str]:
    """Inne formy osób już wykrytych w dokumencie (testy API 2026-10-29: „Marek
    Zawadzki-Herbert" ukryty, „Markowi Zawadzkiemu-Herbertowi" jawny). Osoba wykryta
    raz ma zniknąć w każdej odmianie, na każdym poziomie."""
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
    """Detektor + fragmenty, które kontrola znalazła w wyniku (2026-10-28).

    Model widzi inny kontekst po zamaskowaniu części danych i potrafi dopiero
    wtedy rozpoznać osobę pominiętą w pierwszym przejściu („Anna Kwiatkowska"
    w piśmie właściciela). Zamiast blokować cały wynik, ukrywamy także te
    fragmenty, wszędzie gdzie występują w oryginale.
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


def zbuduj_detektor(poziom: int, konfig, pakiet_rozszerzony: bool = False):
    """Detektor dla poziomu 1-3; błąd budowy = `BladDetektora` (fail-closed, LLD §15).

    Skład poziomu (1 = reguły+bardsai; 2 = wariant A; 3 = wariant B, K2d) robi
    `detektory.zbuduj_poziom` — ta sama funkcja co w pomiarze. K7c (audyt #1):
    `pakiet_rozszerzony` = zweryfikowany stan pakietu Rozszerzonego (API podaje
    go ze stanu menedżera pakietów); bez niego poziom 3 nie używa LFM2.5.
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
    """Nieblokujące uwagi o obrazach (K4b pkt 2), wspólne dla `ukryj` i poprawek."""
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
    """Znaczniki w dokumencie + nowa mapa z wykryć (encje z oznaczeniami). Wspólne dla
    `ukryj` i `poprawki.popraw`, więc oba składają wynik i mapę tak samo."""
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
    # id w treści wiąże mapę z dokumentem
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
    # 2026-10-28: znalezisko kontroli w treści = dane pominięte w poprzednim
    # przejściu; ukrywamy je i sprawdzamy ponownie. Blokada zostaje, gdy kolejne
    # przejście nie ma już czego dołożyć (np. wyciek w części, której adapter nie czyta).
    dok_wejscia = adapter_formatu(format).wczytaj(
        dane, polityka_obrazow=polityka_obrazow, max_rozpakowane=max_rozpakowane_bajtow
    )
    if any(WZORZEC_ZNACZNIKA.search(segment.tekst) for segment in dok_wejscia.segmenty):
        raise ZnacznikiWTresci(
            "dokument zawiera już znaczniki Niewidki (np. [OSOBA_1]); ukryj oryginał, "
            "a nie wynik wcześniejszego ukrywania"
        )
    fragmenty: dict[str, TypEncji] = {}
    # suma oryginałów ze WSZYSTKICH przejść: scalenie w późniejszym przejściu daje
    # dłuższy oryginał, a krótszy z wcześniejszego dalej musi być szukany w wyniku
    # (przegląd Codex 2026-10-29: inaczej wyciek w styles.xml znikał z ostrzeżeń)
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
        # K3b: oryginały mapy = druga siatka kontroli (każda część archiwum)
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
        # ORYGINAL = wartość z mapy, którą model przeoczył w innym miejscu: ukrywamy ją
        # wszędzie z typem z mapy (testy API 2026-10-29). Zostaje tylko tam, gdzie adapter
        # nie czyta (style, metadane) — wtedy kolejne przejście nic nie wnosi i jest blokada.
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
    """Pierwszy identyfikator mapy z dopisku w treści dokumentu; None, gdy dopisku
    nie ma (np. czat AI go nie powtórzył, K4b pkt 6). Reużyte przez /api/przywroc
    do wskazania mapy w magazynie bez pliku .nwidka."""
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
    """Zamiana znaczników na oryginały wg (oznaczenie, wariant); dopisek wyniku znika.

    Przywrócenie odtwarza wyłącznie dane zastąpione znacznikami — elementy usunięte
    przy czyszczeniu (metadane, komentarze) nie wracają (LLD §7/§8).
    """
    _sprawdz_format(format)
    _sprawdz_rozpakowane(dane, max_rozpakowane_bajtow)
    adapter = adapter_formatu(format)
    dok = adapter.wczytaj(dane, max_rozpakowane=max_rozpakowane_bajtow)
    # K4b pkt 6: mapa jest związana z KONKRETNYM dokumentem. Dopisek z identyfikatorem
    # innej mapy = odmowa. Brak dopisku to zwykła odpowiedź czatu AI (nie powtarza go),
    # więc przywracamy, ale z ostrzeżeniem, że zgodności mapy nie da się sprawdzić.
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
