"""Testy generatora numerów do korpusu (narzędzia pomiarowe, nie kod rdzenia)."""

import stdnum.iban
import stdnum.pl.nip
import stdnum.pl.pesel
import stdnum.pl.regon

from narzedzia.numery import bledny, dowod, iban, nip, pesel, regon, regon14, waliduj_dowod

# Wyliczony ręcznie: litery ABC = 70+33+12 = 115; cyfry 2,1,2,3,4,5 z wagami
# 9,7,3,1,7,3 = 18+7+6+3+28+15 = 77; suma 192; 192 mod 10 = 2 = 4. znak.
PRZYKLAD_DOWODU = "ABC212345"

TYPO_Z_WALIDATOREM = [
    (pesel, stdnum.pl.pesel.is_valid),
    (nip, stdnum.pl.nip.is_valid),
    (regon, stdnum.pl.regon.is_valid),
    (regon14, stdnum.pl.regon.is_valid),
    (iban, stdnum.iban.is_valid),
]


def test_pesel_poprawny_przechodzi_stdnum():
    for i in range(12):
        assert stdnum.pl.pesel.is_valid(pesel(i))


def test_nip_poprawny_przechodzi_stdnum():
    for i in range(12):
        assert stdnum.pl.nip.is_valid(nip(i))


def test_regon_poprawny_przechodzi_stdnum():
    for i in range(12):
        assert stdnum.pl.regon.is_valid(regon(i))
        assert stdnum.pl.regon.is_valid(regon14(i))


def test_iban_poprawny_przechodzi_stdnum():
    for i in range(12):
        assert stdnum.iban.is_valid(iban(i))


def test_dowod_poprawny_przechodzi_walidator():
    for i in range(12):
        assert waliduj_dowod(dowod(i))
    assert waliduj_dowod(PRZYKLAD_DOWODU)
    assert waliduj_dowod("ABC 212345")  # spacje znormalizowane
    assert not waliduj_dowod("ABC212346")


def test_bledny_rozni_sie_jedna_cyfra_i_nie_przechodzi():
    for i in range(12):
        for generator, sprawdz in TYPO_Z_WALIDATOREM:
            poprawny = generator(i)
            zepsuty = bledny(poprawny, sprawdz)
            assert not sprawdz(zepsuty), (generator.__name__, poprawny, zepsuty)
            assert sum(a != b for a, b in zip(poprawny, zepsuty)) == 1


def test_bledny_dowodu_nie_przechodzi():
    for i in range(12):
        zepsuty = bledny(dowod(i), waliduj_dowod)
        assert not waliduj_dowod(zepsuty)
        assert sum(a != b for a, b in zip(dowod(i), zepsuty)) == 1


def test_determinizm():
    assert pesel(3) == pesel(3)
    assert dowod(5) == dowod(5)
    assert bledny(iban(2), stdnum.iban.is_valid) == bledny(iban(2), stdnum.iban.is_valid)
