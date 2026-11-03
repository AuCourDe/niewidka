"""Tests of candidate merging."""

import random
from itertools import pairwise

from niewidka.model import TypEncji, Zakres
from niewidka.scalanie import scal


def _zakres(start, koniec, typ=TypEncji.INNE, pewnosc=0.9, suma=False, zrodlo="regula", podejrzana=False):
    return Zakres(start, koniec, typ, pewnosc, zrodlo, suma, podejrzana)


def test_rozlaczne_przechodza_bez_zmian():
    kandydaci = [_zakres(0, 5), _zakres(10, 20)]
    wynik = scal("abcdefghijk", kandydaci)
    assert [(z.start, z.koniec) for z in wynik] == [(0, 5), (10, 20)]


def test_dotykajace_sie_nie_lacza():
    kandydaci = [_zakres(0, 10), _zakres(10, 20)]
    assert len(scal("x", kandydaci)) == 2


def test_nakladajace_sie_maskowane_unia_bez_dziury():
    # picking a single winner from [0,12) and [8,20)
    # would leave 12-20 visible: the whole union is masked.
    kandydaci = [
        _zakres(0, 12, TypEncji.PESEL, 1.0, suma=True),
        _zakres(8, 20, TypEncji.INNE, 0.9),
    ]
    wynik = scal("x" * 30, kandydaci)
    assert len(wynik) == 1
    assert (wynik[0].start, wynik[0].koniec) == (0, 20)
    assert wynik[0].typ is TypEncji.PESEL  # the checksum wins the label


def test_dluzszy_wygrywa_gdy_bez_sum():
    kandydaci = [
        _zakres(10, 15, TypEncji.TELEFON),
        _zakres(12, 30, TypEncji.ADRES),
    ]
    wynik = scal("x" * 40, kandydaci)
    assert len(wynik) == 1
    assert (wynik[0].start, wynik[0].koniec) == (10, 30)
    assert wynik[0].typ is TypEncji.ADRES


def test_pelne_pokrycie_roznych_typow_etykieta_wewnetrznego():
    # the more specific inner type wins the label; the whole union is masked anyway
    kandydaci = [
        _zakres(0, 20, TypEncji.INNE),
        _zakres(4, 14, TypEncji.TELEFON),
    ]
    wynik = scal("x" * 30, kandydaci)
    assert (wynik[0].start, wynik[0].koniec) == (0, 20)
    assert wynik[0].typ is TypEncji.TELEFON


def test_patron_ulicy_nie_przejmuje_adresu():
    # "ul. Józefa Piłsudskiego 12": a person inside an address stays part of the address,
    # otherwise the city in it would be searched for as a person's name
    kandydaci = [
        _zakres(0, 20, TypEncji.ADRES),
        _zakres(4, 14, TypEncji.OSOBA),
    ]
    wynik = scal("x" * 30, kandydaci)
    assert (wynik[0].start, wynik[0].koniec) == (0, 20)
    assert wynik[0].typ is TypEncji.ADRES


def test_karta_w_rachunku_z_literowka_nie_przejmuje_etykiety():
    # "PL61 1090 1014 0000 0712 1981 2875": wrong IBAN sum, a 20-digit window passes Luhn
    kandydaci = [
        Zakres(0, 34, TypEncji.IBAN, 0.5, "regula", suma_kontrolna=False, podejrzana=True),
        Zakres(5, 34, TypEncji.KARTA, 1.0, "regula", suma_kontrolna=True),
    ]
    (wynik,) = scal("x" * 34, kandydaci)
    assert (wynik.start, wynik.koniec, wynik.typ) == (0, 34, TypEncji.IBAN)
    assert wynik.podejrzana and not wynik.suma_kontrolna


def test_identyczne_zakresy_rozne_typy_suma_wygrywa():
    kandydaci = [
        _zakres(0, 9, TypEncji.TELEFON),
        _zakres(0, 9, TypEncji.REGON, suma=True),
    ]
    wynik = scal("x" * 9, kandydaci)
    assert wynik[0].typ is TypEncji.REGON


def test_wyzej_pewnosc_przy_rownych_dlugosciach():
    kandydaci = [
        _zakres(0, 10, TypEncji.INNE, pewnosc=0.9),
        _zakres(0, 10, TypEncji.DATA, pewnosc=0.95),
    ]
    assert scal("x" * 10, kandydaci)[0].typ is TypEncji.DATA


def test_determinizm_wzgledem_kolejnosci_wejscia():
    kandydaci = [
        _zakres(8, 20, TypEncji.INNE),
        _zakres(0, 12, TypEncji.PESEL, 1.0, suma=True),
    ]
    odwróceni = scal("x" * 30, list(reversed(kandydaci)))
    assert [(z.start, z.koniec, z.typ) for z in odwróceni] == [(0, 20, TypEncji.PESEL)]


def test_wynik_sortowany_wg_pozycji():
    kandydaci = [_zakres(20, 30), _zakres(0, 5)]
    wynik = scal("x" * 30, kandydaci)
    assert [z.start for z in wynik] == [0, 20]


def test_własność_maskowanie_to_unia_wejścia():
    # Property: for any set of candidates the masked
    # characters = the sum of input characters; no overlap group leaves a hole,
    # the result is disjoint and sorted. The edge case [0,12)+[8,20) -> [0,20)
    # is covered by test_nakladajace_sie_maskowane_unia_bez_dziury.
    los = random.Random(20261028)
    for _ in range(200):
        kandydaci = []
        for _ in range(los.randint(0, 8)):
            start = los.randint(0, 45)
            kandydaci.append(
                Zakres(
                    start,
                    start + los.randint(1, 15),
                    los.choice(list(TypEncji)),
                    los.random(),
                    los.choice(("regula", "onnx:bardsai")),
                    los.random() < 0.3,
                )
            )
        wynik = scal("x" * 70, kandydaci)
        wejście: set[int] = set()
        wyjście: set[int] = set()
        pozycje = []
        for z in kandydaci:
            wejście.update(range(z.start, z.koniec))
        for z in wynik:
            wyjście.update(range(z.start, z.koniec))
            pozycje.append((z.start, z.koniec))
        assert wyjście == wejście  # neither a hole nor an excess
        assert pozycje == sorted(pozycje)
        assert all(k1 <= s2 for (_, k1), (s2, _) in pairwise(pozycje))


def test_sama_podejrzana_przechodzi_z_flaga():
    wynik = scal("x" * 11, [_zakres(0, 11, TypEncji.PESEL, 0.5, podejrzana=True)])
    assert wynik[0].podejrzana is True


def test_podejrzana_nakryta_sumą_traci_etykietę_a_obszar_zostaje():
    # The winning label is certain, but the masked area still covers the whole union:
    # a suspect fragment must not be left exposed.
    kandydaci = [
        _zakres(0, 20, TypEncji.PESEL, 0.5, podejrzana=True),
        _zakres(4, 14, TypEncji.NIP, 1.0, suma=True),
    ]
    wynik = scal("x" * 30, kandydaci)
    assert len(wynik) == 1
    assert (wynik[0].start, wynik[0].koniec) == (0, 20)
    assert wynik[0].typ is TypEncji.NIP
    assert wynik[0].podejrzana is False
