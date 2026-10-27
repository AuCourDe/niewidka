"""Testy reguł detekcji (LLD §3): wyrażenia regularne + sumy kontrolne."""

from niewidka.model import TypEncji
from niewidka.reguly import znajdz


def _zakresy(tekst: str):
    return [(z.start, z.koniec, z.typ) for z in znajdz(tekst)]


# --- cykl A: PESEL ----------------------------------------------------------

def test_pesel_poprawny_znaleziony():
    tekst = "PESEL: 44051401359, wniosek."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.PESEL]
    assert [(z.start, z.koniec) for z in wynik] == [(7, 18)]
    assert wynik[0].pewnosc == 1.0
    assert wynik[0].suma_kontrolna is True
    assert wynik[0].zrodlo == "regula"


def test_pesel_bledna_suma_nie_znaleziony():
    assert _zakresy("PESEL: 44051401358, wniosek.") == []


def test_pesel_w_dluzszej_liczbie_nie_znaleziony():
    assert _zakresy("Id transakcji 1234405140135977 end.") == []


# --- cykl B: NIP, REGON, IBAN, DOWÓD ---------------------------------------

def test_nip_poprawny_z_łącznikami():
    tekst = "NIP: 123-456-32-18, zakład."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.NIP]
    assert [(z.start, z.koniec) for z in wynik] == [(5, 18)]
    assert wynik[0].suma_kontrolna is True


def test_nip_ciagly_znaleziony():
    assert (5, 15, TypEncji.NIP) in _zakresy("NIP: 1234563218, zakład.")


def test_nip_bledna_suma_nie_znaleziony():
    assert _zakresy("NIP: 1234563219, zakład.") == []


def test_regon_9_i_14_cyfrowy():
    assert (6, 15, TypEncji.REGON) in _zakresy("REGON 192598184 firmy.")
    assert (6, 20, TypEncji.REGON) in _zakresy("REGON 12345678512347 oddziału.")


def test_regon_bledna_suma_nie_znaleziony():
    assert _zakresy("REGON 192598183 firmy.") == []


def test_iban_ze_spacjami():
    tekst = "Konto: PL61 1090 1014 0000 0712 1981 2874."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.IBAN]
    assert [(z.start, z.koniec) for z in wynik] == [(7, 41)]
    assert wynik[0].suma_kontrolna is True


def test_iban_bledna_suma_nie_znaleziony():
    assert _zakresy("Konto: PL61 1090 1014 0000 0712 1981 2875.") == []


def test_dowod_ze_spacja():
    tekst = "Dowód ABC 212345 stracił ważność."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.DOKUMENT]
    assert [(z.start, z.koniec) for z in wynik] == [(6, 16)]
    assert wynik[0].suma_kontrolna is True


def test_dowod_bledna_suma_nie_znaleziony():
    assert _zakresy("Dowód ABC212346 stracił ważność.") == []
