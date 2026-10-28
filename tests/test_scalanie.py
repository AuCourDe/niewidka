"""Testy scalania kandydatów (LLD §5 + przegląd Astry pkt 1)."""

import random

from niewidka.model import TypEncji, Zakres
from niewidka.scalanie import scal


def _zakres(start, koniec, typ=TypEncji.INNE, pewnosc=0.9, suma=False, zrodlo="regula"):
    return Zakres(start, koniec, typ, pewnosc, zrodlo, suma)


def test_rozlaczne_przechodza_bez_zmian():
    kandydaci = [_zakres(0, 5), _zakres(10, 20)]
    wynik = scal("abcdefghijk", kandydaci)
    assert [(z.start, z.koniec) for z in wynik] == [(0, 5), (10, 20)]


def test_dotykajace_sie_nie_lacza():
    kandydaci = [_zakres(0, 10), _zakres(10, 20)]
    assert len(scal("x", kandydaci)) == 2


def test_nakladajace_sie_maskowane_unia_bez_dziury():
    # Przegląd Astry pkt 1: wybór jednego zwycięzcy z [0,12) i [8,20)
    # zostawiłby jawne 12-20 — maskowana jest cała unia.
    kandydaci = [
        _zakres(0, 12, TypEncji.PESEL, 1.0, suma=True),
        _zakres(8, 20, TypEncji.INNE, 0.9),
    ]
    wynik = scal("x" * 30, kandydaci)
    assert len(wynik) == 1
    assert (wynik[0].start, wynik[0].koniec) == (0, 20)
    assert wynik[0].typ is TypEncji.PESEL  # suma kontrolna wygrywa etykietę


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
    # LLD §5: nazwisko w środku adresu — wygrywa bardziej specyficzny typ;
    # maskowana i tak jest cała unia, wybieramy tylko etykietę.
    kandydaci = [
        _zakres(0, 20, TypEncji.ADRES),
        _zakres(4, 14, TypEncji.OSOBA),
    ]
    wynik = scal("x" * 30, kandydaci)
    assert (wynik[0].start, wynik[0].koniec) == (0, 20)
    assert wynik[0].typ is TypEncji.OSOBA


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
    # Własność (przegląd Astry pkt 1): dla dowolnego zestawu kandydatów maskowane
    # znaki = suma znaków wejściowych — żadna grupa nakładań nie zostawia dziury,
    # wynik rozłączny i posortowany. Przypadek graniczny [0,12)+[8,20) → [0,20)
    # jest zamknięty testem test_nakladajace_sie_maskowane_unia_bez_dziury.
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
        assert wyjście == wejście  # ani dziury, ani nadmiaru
        assert pozycje == sorted(pozycje)
        assert all(k1 <= s2 for (_, k1), (s2, _) in zip(pozycje, pozycje[1:]))
