"""Detektory (LLD §4): wspólny interfejs, okna przesuwne, adaptery modeli ONNX.

Adapter per model (przegląd Astry pkt 14): schemat etykiet (BIO/BIOES), tokeny
specjalne i normalizacja różnią się między modelami — konwersja do `Zakres`
żyje w adapterze modelu, nie we wspólnym kodzie.
"""

from __future__ import annotations

from niewidka.model import TypEncji


def okna_tokenow(n: int, okno: int, krok: int) -> list[tuple[int, int]]:
    """Przesuwne okna tokenów (zakładka = okno - krok); ostatnie dociągnięte do końca."""
    if n <= 0:
        return []
    if n <= okno:
        return [(0, n)]
    wynik = [(start, start + okno) for start in range(0, n - okno + 1, krok)]
    if wynik[-1][1] < n:
        wynik.append((n - okno, n))
    return wynik


def zdekoduj_bio(
    tokeny: list[tuple[str, tuple[int, int], float]],
    mapa: dict[tuple[str, ...], TypEncji],
) -> list[tuple[int, int, TypEncji, float]]:
    """BIO -> zakresy znakowe (start, koniec, typ, pewność = min. tokenów).

    `tokeny` to (etykieta, offsety znakowe, pewność); etykiety nieobecne w `mapa`
    są pomijane (adapter modelu decyduje, które typy model dostarcza). I- po
    B/I tego samego typu kontynuuje encję; I innego typu albo bez B kończy bieżącą.
    """
    wynik: list[tuple[int, int, TypEncji, float]] = []
    biezaca: tuple[int, int, TypEncji, float] | None = None
    biezaca_klasa: tuple[str, ...] | None = None
    for etykieta, (start, koniec), pewnosc in tokeny:
        if start == koniec:  # token specjalny/wypadek
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            continue
        if not etykieta.startswith(("B-", "I-")):
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            continue
        schemat, klasa = etykieta[:1], etykieta[2:]
        klucz = (klasa,)
        if klucz not in mapa:
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            continue
        if schemat == "B" or klucz != biezaca_klasa:
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            if schemat == "I":
                continue  # I bez swojego B — fragment niepełny, pomijany
            typ = mapa[klucz]
            biezaca, biezaca_klasa = (start, koniec, typ, pewnosc), klucz
        else:  # I kontynuuje bieżącą encję
            assert biezaca is not None
            biezaca = (biezaca[0], koniec, biezaca[2], min(biezaca[3], pewnosc))
    _zamknij(biezaca, wynik)
    return wynik


def _zamknij(
    biezaca: tuple[int, int, TypEncji, float] | None,
    wynik: list[tuple[int, int, TypEncji, float]],
) -> None:
    if biezaca is not None:
        wynik.append(biezaca)
