"""Znaczniki [TYP_N] — nadawanie numerów i zamiana w segmentach (LLD §7).

„N" liczy się per typ w kolejności wystąpienia w dokumencie; [OSOBA_1] wspólne
dla wszystkich form tej osoby (klucz_grupy z osoby.py). Dopisek celowo nie
zawiera nawiasów kwadratowych — kontrola wyniku szuka wzorca [TYP_N]
(przegląd Gemini pkt 7).
"""

from niewidka.model import Encja

DOPISEK = (
    "ZANONIMIZOWANO w Niewidka. Dokument zawiera znaczniki anonimizacji; "
    "oryginał odtworzysz plikiem mapy i kluczem."
)


def nadaj_oznaczenia(encje: list[Encja]) -> None:
    """Ustawia encja.oznaczenie; encje muszą być w kolejności dokumentu.

    OSOBY o tym samym klucz_grupy dzielą numer; bez klucza każda dostaje
    własny.
    """
    liczniki: dict[str, int] = {}
    numery: dict[str, str] = {}
    for pozycja, encja in enumerate(encje):
        typ = encja.zakres.typ.value
        identyfikator = f"{typ}\x00{encja.klucz_grupy or f'#{pozycja}'}"
        if identyfikator not in numery:
            liczniki[typ] = liczniki.get(typ, 0) + 1
            numery[identyfikator] = f"{typ}_{liczniki[typ]}"
        encja.oznaczenie = numery[identyfikator]


def zamien_w_segment(
    segment_tekst: str, encje: list[Encja], poczatek_kolejnego: int = 0
) -> tuple[str, list[int]]:
    """Tekst ze znacznikami + numery „kolejny" wystąpień dla mapy (LLD §8).

    Zamiana od końca segmentu, żeby offsety nie uciekały. `poczatek_kolejnego`
    kontynuuje globalną numerację między segmentami.
    """
    wynik = segment_tekst
    kolejne: list[int] = []
    posortowane = sorted(encje, key=lambda e: e.zakres.start)
    for numer, encja in enumerate(posortowane):
        if encja.oznaczenie is None:
            raise ValueError("encja bez oznaczenia — najpierw nadaj_oznaczenia")
        kolejne.append(poczatek_kolejnego + numer)
    for encja in reversed(posortowane):
        wynik = wynik[: encja.zakres.start] + f"[{encja.oznaczenie}]" + wynik[encja.zakres.koniec :]
    return wynik, kolejne
