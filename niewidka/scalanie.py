"""Scalanie kandydatów w encje (LLD §5, przegląd Astry pkt 1).

Nakładające się zakresy tworzą grupę; maskowany obszar grupy to UNIA zakresów
(wybór jednego zwycięzcy zostawiałby dziury), a wybierana jest tylko etykieta:
suma kontrolna > wewnętrzny przy pełnym pokryciu > długość > pewność >
źródło (reguła > model). Deterministyczne niezależnie od kolejności wejścia.
"""

from niewidka.model import Zakres


def _priorytet(kandydat: Zakres, wewnętrzny: bool) -> tuple:
    return (
        kandydat.suma_kontrolna,
        wewnętrzny,
        kandydat.koniec - kandydat.start,
        kandydat.pewnosc,
        kandydat.zrodlo == "regula",
        kandydat.typ.value,
    )


def scal(tekst_segmentu: str, kandydaci: list[Zakres]) -> list[Zakres]:
    """Zwraca encje po scaleniu grup nakładań, sortowane wg pozycji."""
    del tekst_segmentu  # argument z kontraktu LLD; unia znaków nie jest tu potrzebna
    kandydaci = _bez_fragmentow_pewnych(kandydaci)
    wyniki: list[Zakres] = []
    grupa: list[Zakres] = []
    koniec_grupy = -1
    for kandydat in sorted(kandydaci, key=lambda z: (z.start, z.koniec)):
        if grupa and kandydat.start < koniec_grupy:
            grupa.append(kandydat)
            koniec_grupy = max(koniec_grupy, kandydat.koniec)
        else:
            if grupa:
                wyniki.append(_zwyciezca(grupa))
            grupa = [kandydat]
            koniec_grupy = kandydat.koniec
    if grupa:
        wyniki.append(_zwyciezca(grupa))
    return sorted(wyniki, key=lambda z: z.start)


def _bez_fragmentow_pewnych(kandydaci: list[Zakres]) -> list[Zakres]:
    """Kandydat w pełni zawarty w innym kandydacie z sumą kontrolną odpada (K7b).

    Numer z poprawną sumą kontrolną jest autorytatywny: jego fragment nie jest
    osobną daną (okno Luhna wewnątrz IBAN-u to nie karta). Zakres-fragment to
    podzbiór zakresu nosiciela, więc maskowana unia się nie zmienia.
    """
    pewne = [z for z in kandydaci if z.suma_kontrolna]
    return [
        z
        for z in kandydaci
        if not any(
            p is not z
            and (p.start, p.koniec) != (z.start, z.koniec)
            and p.start <= z.start
            and z.koniec <= p.koniec
            for p in pewne
        )
    ]


def _zwyciezca(grupa: list[Zakres]) -> Zakres:
    start = min(z.start for z in grupa)
    koniec = max(z.koniec for z in grupa)
    etykieta = max(
        grupa,
        key=lambda z: _priorytet(
            z,
            wewnętrzny=any(
                inny is not z
                and (inny.start, inny.koniec) != (z.start, z.koniec)
                and inny.start <= z.start
                and z.koniec <= inny.koniec
                for inny in grupa
            ),
        ),
    )
    return Zakres(
        start=start,
        koniec=koniec,
        typ=etykieta.typ,
        pewnosc=etykieta.pewnosc,
        zrodlo=etykieta.zrodlo,
        suma_kontrolna=etykieta.suma_kontrolna,
        podejrzana=etykieta.podejrzana,
    )
