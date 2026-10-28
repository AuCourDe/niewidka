"""Testy reguł detekcji (LLD §3): wyrażenia regularne + sumy kontrolne."""

from niewidka.model import TypEncji
from niewidka.reguly import znajdz


def _zakresy(tekst: str):
    return [(z.start, z.koniec, z.typ) for z in znajdz(tekst)]


def _podejrzane(tekst: str):
    return [z for z in znajdz(tekst) if z.podejrzana]


# --- cykl A: PESEL ----------------------------------------------------------

def test_pesel_poprawny_znaleziony():
    tekst = "PESEL: 44051401359, wniosek."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.PESEL]
    assert [(z.start, z.koniec) for z in wynik] == [(7, 18)]
    assert wynik[0].pewnosc == 1.0
    assert wynik[0].suma_kontrolna is True
    assert wynik[0].zrodlo == "regula"


def test_pesel_bledna_suma_podejrzany_nie_odrzucony():
    # Przegląd Astry pkt 14: błędna suma = encja z flagą „podejrzana", nie
    # odrzucenie — literówka w prawdziwym numerze nie może zniknąć cicho.
    wynik = znajdz("PESEL: 44051401358, wniosek.")
    assert [(z.start, z.koniec) for z in wynik] == [(7, 18)]
    assert wynik[0].podejrzana is True
    assert wynik[0].suma_kontrolna is False
    assert wynik[0].pewnosc == 0.5
    assert wynik[0].typ is TypEncji.PESEL


def test_pesel_poprawny_nie_jest_podejrzany():
    wynik = znajdz("PESEL: 44051401359, wniosek.")
    assert wynik[0].podejrzana is False
    assert wynik[0].suma_kontrolna is True
    assert wynik[0].pewnosc == 1.0


def test_pesel_w_dluzszej_liczbie_nie_znaleziony():
    # PESEL-kształt zanurzony w dłuższym ciągu nie jest PESEL-em; ciąg 16 cyfr
    # z poprawną sumą Luhna (K7b) jest natomiast legalną kartą płatniczą
    wynik = _zakresy("Id transakcji 1234405140135977 end.")
    assert TypEncji.PESEL not in [z[2] for z in wynik]


# --- cykl B: NIP, REGON, IBAN, DOWÓD ---------------------------------------

def test_nip_poprawny_z_łącznikami():
    tekst = "NIP: 123-456-32-18, zakład."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.NIP]
    assert [(z.start, z.koniec) for z in wynik] == [(5, 18)]
    assert wynik[0].suma_kontrolna is True


def test_nip_ciagly_znaleziony():
    assert (5, 15, TypEncji.NIP) in _zakresy("NIP: 1234563218, zakład.")


def test_nip_bledna_suma_podejrzany():
    wynik = _podejrzane("NIP: 1234563219, zakład.")
    assert wynik[0].typ is TypEncji.NIP
    assert wynik[0].podejrzana is True


def test_regon_9_i_14_cyfrowy():
    assert (6, 15, TypEncji.REGON) in _zakresy("REGON 192598184 firmy.")
    assert (6, 20, TypEncji.REGON) in _zakresy("REGON 12345678512347 oddziału.")


def test_regon_bledna_suma_podejrzany():
    wynik = _podejrzane("REGON 192598183 firmy.")
    assert wynik[0].typ is TypEncji.REGON
    assert wynik[0].podejrzana is True


def test_iban_ze_spacjami():
    tekst = "Konto: PL61 1090 1014 0000 0712 1981 2874."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.IBAN]
    assert [(z.start, z.koniec) for z in wynik] == [(7, 41)]
    assert wynik[0].suma_kontrolna is True


def test_iban_bledna_suma_podejrzany():
    wynik = _podejrzane("Konto: PL61 1090 1014 0000 0712 1981 2875.")
    assert wynik[0].typ is TypEncji.IBAN
    assert wynik[0].podejrzana is True


def test_dowod_ze_spacja():
    tekst = "Dowód ABC 212345 stracił ważność."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.DOKUMENT]
    assert [(z.start, z.koniec) for z in wynik] == [(6, 16)]
    assert wynik[0].suma_kontrolna is True


def test_dowod_bledna_suma_podejrzany():
    wynik = _podejrzane("Dowód ABC212346 stracił ważność.")
    assert wynik[0].typ is TypEncji.DOKUMENT
    assert wynik[0].podejrzana is True


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


# --- K2b: FN z rozszerzonego korpusu (tel-085, tel-086, data-094) ---

def test_telefon_stacjonarny_3_3_3_pierwsza_cyfra_1_4():
    assert _znalezione("Tel.: +48 123 456 789.", TypEncji.TELEFON) == ["+48 123 456 789"]
    assert _znalezione("Tel.: 123-456-789.", TypEncji.TELEFON) == ["123-456-789"]


def test_telefon_stacjonarny_wymaga_separatorow():
    # 9 cyfr bez separatorów to pułapka na REGON — nie telefon (K2b, decyzja reguły).
    assert _znalezione("REGON 123456789 wpisano błędnie.", TypEncji.TELEFON) == []


def test_data_iso_rrrr_mm_dd():
    assert _znalezione("Data urodzenia: 1982-05-13.", TypEncji.DATA) == ["1982-05-13"]


def test_data_iso_nie_zagniezdrza_sie_w_innych_liczbach():
    assert _znalezione("Kod 12345-05-13-6789 pozycja.", TypEncji.DATA) == []


# --- K2e: ADRES obejmuje kod pocztowy z miejscowością (błąd z żywego UI) ---

def test_adres_ulica_z_kodem_i_miejscowoscia():
    # Kod pocztowy z miejscowością to quasi-identyfikator — zostawienie go
    # jawnego przy zamaskowanej ulicy to wyciek; ADRES to ciągła całość.
    assert _znalezione(
        "Zamieszkały ul. Długa 15/3, 00-238 Warszawa.", TypEncji.ADRES
    ) == ["ul. Długa 15/3, 00-238 Warszawa"]


def test_adres_kod_bez_przecinka():
    assert _znalezione("Poczta: al. Pracy 12 25-422 Kielce.", TypEncji.ADRES) == [
        "al. Pracy 12 25-422 Kielce"
    ]


def test_adres_sam_kod_z_miejscowoscia():
    assert _znalezione("Adres korespondencyjny: 00-238 Warszawa.", TypEncji.ADRES) == [
        "00-238 Warszawa"
    ]


def test_adres_miejscowosc_dwuczlonowa():
    assert _znalezione("Filia: ul. Cieszyńska 12, 43-300 Bielsko-Biała.", TypEncji.ADRES) == [
        "ul. Cieszyńska 12, 43-300 Bielsko-Biała"
    ]
    assert _znalezione("Magazyn: 65-001 Zielona Góra.", TypEncji.ADRES) == [
        "65-001 Zielona Góra"
    ]


def test_adres_osiedle():
    assert _znalezione("Mieszka na os. Centrum 4/11, 65-001 Zielona Góra.", TypEncji.ADRES) == [
        "os. Centrum 4/11, 65-001 Zielona Góra"
    ]


def test_zwykle_liczby_z_lacznikiem_nie_sa_adresem():
    assert _znalezione("Dostarczono 10-15 sztuk do klienta.", TypEncji.ADRES) == []
    assert _znalezione("Cykl składa się z 12-345 kroków.", TypEncji.ADRES) == []
    assert _znalezione("Tel.: 123-456-789.", TypEncji.ADRES) == []


def test_adres_kod_nie_pochlania_dalej_bez_miejscowosci():
    # Kod bez wielkiej litery za nim (tu: bez miejscowości) — bez ogona.
    assert _znalezione("Paczka z kodem 12-345 w dzienniku.", TypEncji.ADRES) == []


# --- cykl G (K7b): adres IP v4/v6 --------------------------------------------

def test_ip_v4_poprawny_znaleziony():
    # offsety = próbka nowe-ip-1 z tests/korpus/probki_nowe_typy.jsonl
    tekst = "Zapis logu: połączenie z adresu 192.168.14.201."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.IP]
    assert [(z.start, z.koniec) for z in wynik] == [(32, 46)]
    assert wynik[0].podejrzana is False
    assert wynik[0].pewnosc > 0.5


def test_ip_v4_oktet_za_duzy_podejrzany():
    # 256 to nie oktet: maskowane jako podejrzane (bezpieczna strona), nie pewne
    wynik = znajdz("Serwer 256.1.2.3 nie odpowiada.")
    ip = [z for z in wynik if z.typ is TypEncji.IP]
    assert [(z.start, z.koniec) for z in ip] == [(7, 16)]
    assert ip[0].podejrzana is True


def test_ip_v4_zanurzone_w_dluzszym_ciagu_nie_znalezione():
    assert [z for z in znajdz("Id 1192.168.14.201 x") if z.typ is TypEncji.IP] == []


def test_ip_v6_skrócony_i_pelny():
    wynik = znajdz("Bramka: 2001:db8::1 skonfigurowana.")
    assert [(z.start, z.koniec, z.typ) for z in wynik] == [(8, 19, TypEncji.IP)]
    pelny = znajdz("Adres 2001:0db8:0000:0000:0000:0000:0000:0001 jest pełny.")
    assert any(z.typ is TypEncji.IP for z in pelny)
    loopback = znajdz("Host to ::1 w konfiguracji.")
    assert [(z.start, z.koniec, z.typ) for z in loopback] == [(8, 11, TypEncji.IP)]


def test_czas_i_wersja_nie_sa_ip():
    assert [z for z in znajdz("Wpis z godziny 12:45:30 potwierdzam.") if z.typ is TypEncji.IP] == []
    assert [z for z in znajdz("Biblioteka w wersji 1.2.3.") if z.typ is TypEncji.IP] == []
    # pięć członów z kropkami to nie IP v4
    assert [z for z in znajdz("Ciąg 1.2.3.4.5 w opisie.") if z.typ is TypEncji.IP] == []


# --- cykl H (K7b): karta płatnicza z sumą Luhna ------------------------------

def test_karta_poprawna_luhn_z_spacjami():
    tekst = "Karta płatnicza ma numer 4556 7788 9901 2232."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.KARTA]
    assert [(z.start, z.koniec) for z in wynik] == [(25, 44)]
    assert wynik[0].pewnosc == 1.0
    assert wynik[0].suma_kontrolna is True
    assert wynik[0].podejrzana is False


def test_karta_ciagla_poprawna():
    wynik = [z for z in znajdz("Płatność: 5417042188563314 zapisana.") if z.typ is TypEncji.KARTA]
    assert [(z.start, z.koniec) for z in wynik] == [(10, 26)]


def test_karta_bledna_suma_podejrzana():
    # 2234 = próbka z korpusu (fikcyjna, suma Luhna błędna): maskowana z flagą
    wynik = [z for z in znajdz("Karta 4556 7788 9901 2234 wygasła.") if z.typ is TypEncji.KARTA]
    assert wynik[0].podejrzana is True
    assert wynik[0].suma_kontrolna is False
    assert wynik[0].pewnosc == 0.5


def test_karta_13_cyfr_poprawna():
    wynik = [z for z in znajdz("Zapis 4556778899010 w systemie.") if z.typ is TypEncji.KARTA]
    assert [(z.start, z.koniec) for z in wynik] == [(6, 19)]


def test_pesel_nip_regon_nie_sa_karta():
    assert [z for z in znajdz("PESEL 44051401359.") if z.typ is TypEncji.KARTA] == []
    assert [z for z in znajdz("NIP 1234563218.") if z.typ is TypEncji.KARTA] == []
    assert [z for z in znajdz("REGON 491234567.") if z.typ is TypEncji.KARTA] == []


def test_regon14_wygrywa_z_karta():
    # REGON-14 (poprawna suma kontrolna) kształtem mieści się w oknie karty:
    # po scalaniu etykietą jest REGON (suma kontrolna > okno Luhna bez sumy)
    from niewidka.detektory import RegulyDetektor

    wynik = RegulyDetektor().znajdz("REGON 49000001000003 w rejestrze.")
    assert [z.typ for z in wynik] == [TypEncji.REGON]


def test_iban_wygrywa_z_karta():
    # IBAN ze spacjami co 4 znaki zawiera 16-cyfrowe okno: po scalaniu całą
    # encję etykietuje IBAN z poprawną sumą kontrolną, nigdy KARTA
    from niewidka.detektory import RegulyDetektor

    iban = "PL61 1090 1014 0000 0712 1981 2874"
    wynik = RegulyDetektor().znajdz(f"Przelew na {iban} wykonany.")
    typy = [z.typ for z in wynik]
    assert TypEncji.IBAN in typy
    assert TypEncji.KARTA not in typy


def test_adres_miejscowosc_nie_przechodzi_do_nastepnej_linii():
    # pismo właściciela 2026-10-28: „Warszawa\n\nDotyczy:" znikało w [ADRES_2]
    tekst = "ul. Różana 8/24\n02-562 Warszawa\n\nDotyczy: wezwania"
    assert _znalezione(tekst, TypEncji.ADRES) == ["ul. Różana 8/24\n02-562 Warszawa"]
    assert _znalezione("00-108 Warszawa\nTel. 22 555", TypEncji.ADRES) == ["00-108 Warszawa"]
