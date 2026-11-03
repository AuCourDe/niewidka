"""Merging candidates into entities.

Overlapping ranges form a group; the masked area of a group is the UNION of ranges
(picking a single winner would leave holes), and only the label is chosen:
checksum > inner one on full coverage > length > confidence >
source (rule > model). Deterministic regardless of input order. Exception: a person inside an
address (the street patron) does not take the address label."""

from niewidka.model import TypEncji, Zakres


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
    """Returns the entities after merging overlap groups, sorted by position."""
    del tekst_segmentu   # character union is not needed here
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
    """A candidate fully contained in another candidate with a checksum is dropped.

        A number with a valid checksum is authoritative: its fragment is not
        a separate datum (a Luhn window inside an IBAN is not a card). A fragment range is a
        subset of the carrier's range, so the masked union does not change.
        """
    # an account number carries its checksum even when mistyped: a Luhn window inside it is not a card
    nosniki = [z for z in kandydaci if z.suma_kontrolna or z.typ is TypEncji.IBAN]
    return [
        z
        for z in kandydaci
        if not any(
            p is not z
            and (p.start, p.koniec) != (z.start, z.koniec)
            and p.start <= z.start
            and z.koniec <= p.koniec
            and (p.suma_kontrolna or z.typ is TypEncji.KARTA)
            for p in nosniki
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
                and not (z.typ is TypEncji.OSOBA and inny.typ is TypEncji.ADRES)
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
