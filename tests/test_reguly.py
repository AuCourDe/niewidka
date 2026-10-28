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


# --- cykl C: EMAIL, TELEFON, ADRES, DATA ------------------------------------

def _znalezione(tekst: str, typ: TypEncji) -> list[str]:
    return [tekst[z.start : z.koniec] for z in znajdz(tekst) if z.typ is typ]


def test_email_znaleziony():
    tekst = "Kontakt: jan.kowalski@example.com."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.EMAIL]
    assert [(z.start, z.koniec) for z in wynik] == [(9, 33)]
    assert wynik[0].suma_kontrolna is False


def test_email_kropka_koncowa_poza_zakresem():
    assert _znalezione("Pisz na biuro@firma-testowa.pl.", TypEncji.EMAIL) == ["biuro@firma-testowa.pl"]


def test_telefon_plus48():
    assert _znalezione("Tel. +48 601 234 567 — biuro.", TypEncji.TELEFON) == ["+48 601 234 567"]


def test_telefon_0048_stacjonarny():
    assert _znalezione("Kontakt: 0048 22 123 45 67.", TypEncji.TELEFON) == ["0048 22 123 45 67"]


def test_telefon_komorkowy_grupami():
    assert _znalezione("Zadzwoń pod 512 345 678 dziś.", TypEncji.TELEFON) == ["512 345 678"]


def test_telefon_z_łącznikami():
    assert _znalezione("tel. 601-234-567 w dni robocze.", TypEncji.TELEFON) == ["601-234-567"]


def test_telefon_w_nawiasach():
    assert _znalezione("Sekretariat: (22) 828 30 40.", TypEncji.TELEFON) == ["(22) 828 30 40"]


def test_dziewiec_cyfr_regonu_nie_jest_telefonem():
    assert _znalezione("REGON 490000011 wpisano błędnie.", TypEncji.TELEFON) == []


def test_adresy_wszystkie_formy():
    assert _znalezione("Zamieszkały przy ul. Lipowa 13/5 w Warszawie.", TypEncji.ADRES) == ["ul. Lipowa 13/5"]
    assert _znalezione("Adres: al. Róż 15 m. 3.", TypEncji.ADRES) == ["al. Róż 15 m. 3"]
    assert _znalezione("Siedziba: pl. Wolności 7/12.", TypEncji.ADRES) == ["pl. Wolności 7/12"]
    assert _znalezione(
        "Pismo doręczono na ulica Piotra Wysockiego 15 rano.", TypEncji.ADRES
    ) == ["ulica Piotra Wysockiego 15"]


def test_data_liczbowa_i_słowna():
    assert _znalezione("Data urodzenia: 13.05.1982.", TypEncji.DATA) == ["13.05.1982"]
    assert _znalezione("Termin: 31-12-2025.", TypEncji.DATA) == ["31-12-2025"]
    assert _znalezione("Umowę zawarto 2 lutego 1990 w obecności świadków.", TypEncji.DATA) == ["2 lutego 1990"]


def test_sygnatura_nie_jest_datą():
    assert _znalezione("Sygn. 1234.05.1982 sprawa.", TypEncji.DATA) == []
