"""Walidacja korpusu testowego (K0).

Sprawdza format próbek, offsety, sumy kontrolne (przez python-stdnum i
algorytm dowodu) oraz wymagane pokrycie typów. Celowo NIE importuje pakietu
niewidka — korpus jest niezależny od implementacji detektorów.
"""

import json
from pathlib import Path

import pytest
import stdnum.iban
import stdnum.pl.nip
import stdnum.pl.pesel
import stdnum.pl.regon

from narzedzia.numery import waliduj_dowod

KORPUS = Path(__file__).parent / "korpus"
TYPY = {"OSOBA", "PESEL", "NIP", "REGON", "ADRES", "TELEFON", "EMAIL", "IBAN", "DOKUMENT", "DATA", "INNE"}
TYPY_Z_SUMA = {"PESEL", "NIP", "REGON", "IBAN", "DOKUMENT"}
NUMER_DO_WALIDATORA = {
    "PESEL": stdnum.pl.pesel.is_valid,
    "NIP": stdnum.pl.nip.is_valid,
    "REGON": stdnum.pl.regon.is_valid,
    "IBAN": stdnum.iban.is_valid,
    "DOKUMENT": waliduj_dowod,
}
KLUCZ_NUMEROW = {"PESEL": "pesel", "NIP": "nip", "REGON": "regon", "IBAN": "iban", "DOKUMENT": "dowod"}


def _numer_znormalizowany(zapis: str) -> str:
    return zapis.replace(" ", "").replace("-", "").upper()


def wczytaj_probki() -> list[dict]:
    probki = []
    for plik in sorted(KORPUS.glob("*.jsonl")):
        for numer, linia in enumerate(plik.read_text(encoding="utf-8").splitlines()):
            if linia.strip():
                probki.append({"plik": plik.name, "linia": numer + 1, **json.loads(linia)})
    return probki


@pytest.fixture(scope="session")
def probki() -> list[dict]:
    return wczytaj_probki()


def test_format_probek(probki: list[dict]):
    assert len(probki) >= 40, "korpus ma mieć ≥ 40 próbek (KAMIENIE K0)"
    identyfikatory = set()
    for probka in probki:
        etykieta = f"{probka['plik']}:{probka['linia']}"
        assert probka["id"] not in identyfikatory, f"{etykieta}: powtórzony id {probka['id']}"
        identyfikatory.add(probka["id"])
        assert probka.get("opis"), f"{etykieta}: brak opisu"
        tekst = probka["tekst"]
        assert tekst and isinstance(tekst, str), f"{etykieta}: pusty tekst"
        zakresy = []
        for encja in probka["encje"]:
            assert encja["typ"] in TYPY, f"{etykieta}: nieznany typ {encja['typ']}"
            start, koniec = encja["start"], encja["koniec"]
            assert 0 <= start < koniec <= len(tekst), f"{etykieta}: złe offsety {encja}"
            assert tekst[start:koniec] == encja["tekst"], (
                f"{etykieta}: tekst[{start}:{koniec}] != {encja['tekst']!r}"
            )
            if encja["typ"] in TYPY_Z_SUMA:
                assert encja.get("suma") in (True, False), f"{etykieta}: brak pola suma"
            else:
                assert "suma" not in encja, f"{etykieta}: pole suma tylko dla {TYPY_Z_SUMA}"
            for s2, k2 in zakresy:
                assert start >= k2 or koniec <= s2, f"{etykieta}: nakładające się encje {encja}"
            zakresy.append((start, koniec))


def test_sumy_kontrolne_probek(probki: list[dict]):
    for probka in probki:
        etykieta = f"{probka['plik']}:{probka['linia']} ({probka['id']})"
        for encja in probka["encje"]:
            if encja["typ"] not in TYPY_Z_SUMA:
                continue
            nr = _numer_znormalizowany(encja["tekst"])
            poprawny = NUMER_DO_WALIDATORA[encja["typ"]](nr)
            assert poprawny == encja["suma"], (
                f"{etykieta}: {encja['typ']} {nr} ma suma={encja['suma']}, a walidator mówi {poprawny}"
            )


def _pokrywajace(probka: dict, typ: str, pozycja: int, dlugosc: int) -> list[dict]:
    return [
        e
        for e in probka["encje"]
        if e["typ"] == typ and e["start"] <= pozycja and pozycja + dlugosc <= e["koniec"]
    ]


def test_pulapki_i_numery_z_numery_json(probki: list[dict]):
    """Numery „poprawne" z numery.json, jeśli użyte w tekstach, muszą mieć encję
    z suma=true; „błędne" (pułapki) nie mogą być przykryte encją swojego typu."""
    numery = json.loads((KORPUS / "numery.json").read_text(encoding="utf-8"))
    for typ, klucz in KLUCZ_NUMEROW.items():
        listy_poprawnych = [numery[klucz]["poprawne"]]
        if klucz == "regon":  # REGON 14-cyfrowy to ten sam typ
            listy_poprawnych.append(numery["regon14"]["poprawne"])
        for nr in [n for lista in listy_poprawnych for n in lista]:
            for probka in probki:
                pozycja = probka["tekst"].find(nr)
                if pozycja < 0:
                    continue
                pokrywajace = _pokrywajace(probka, typ, pozycja, len(nr))
                assert pokrywajace, f"{probka['id']}: poprawny {typ} {nr} bez encji"
                assert all(e["suma"] for e in pokrywajace), f"{probka['id']}: {nr} z suma!=true"
        for nr in numery[klucz]["bledne"]:
            for probka in probki:
                pozycja = probka["tekst"].find(nr)
                if pozycja < 0:
                    continue
                assert not _pokrywajace(probka, typ, pozycja, len(nr)), (
                    f"{probka['id']}: pułapka {typ} {nr} przykryta encją"
                )


def test_pokrycie_typow(probki: list[dict]):
    pozytywne: dict[str, int] = {}
    for probka in probki:
        for encja in probka["encje"]:
            pozytywne[encja["typ"]] = pozytywne.get(encja["typ"], 0) + 1
    for typ in TYPY - {"INNE"}:
        assert pozytywne.get(typ, 0) >= 3, f"typ {typ}: tylko {pozytywne.get(typ, 0)} encji pozytywnych (wymagane ≥ 3)"
    assert any(len(p["encje"]) == 0 for p in probki), "brak próbek negatywnych (encje: [])"


def test_pokrycie_pulapek_i_tagow(probki: list[dict]):
    numery = json.loads((KORPUS / "numery.json").read_text(encoding="utf-8"))
    wszystkie_teksty = [p["tekst"] for p in probki]
    wymagane_pulapki = {"pesel": 2, "nip": 2, "regon": 1, "regon14": 1, "iban": 1, "dowod": 1}
    for klucz, minimum in wymagane_pulapki.items():
        uzyte = sum(1 for nr in numery[klucz]["bledne"] if any(nr in t for t in wszystkie_teksty))
        assert uzyte >= minimum, f"pułapki {klucz}: {uzyte} (wymagane ≥ {minimum})"
    tagi = [t for p in probki for t in p.get("tagi", [])]
    for tag, minimum in (("homonim", 3), ("rzeczownik-nazwisko", 2), ("odmiana", 5)):
        assert tagi.count(tag) >= minimum, f"tag {tag}: {tagi.count(tag)} (wymagane ≥ {minimum})"
