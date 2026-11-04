"""Tests of detection rules: regular expressions + checksums."""

from niewidka.model import TypEncji
from niewidka.reguly import znajdz


def _zakresy(tekst: str):
    return [(z.start, z.koniec, z.typ) for z in znajdz(tekst)]


def _podejrzane(tekst: str):
    return [z for z in znajdz(tekst) if z.podejrzana]


# --- cycle A: PESEL ----------------------------------------------------------

def test_pesel_poprawny_znaleziony():
    tekst = "PESEL: 44051401359, wniosek."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.PESEL]
    assert [(z.start, z.koniec) for z in wynik] == [(7, 18)]
    assert wynik[0].pewnosc == 1.0
    assert wynik[0].suma_kontrolna is True
    assert wynik[0].zrodlo == "regula"


def test_pesel_bledna_suma_podejrzany_nie_odrzucony():
    # a wrong checksum = an entity with a 'suspect' flag, not a
    # rejection: a typo in a real number must not vanish silently.
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
    # a PESEL-shaped string inside a longer one is not a PESEL; a 16-digit string
    # with a valid Luhn sum, however, is a legitimate payment card
    wynik = _zakresy("Id transakcji 1234405140135977 end.")
    assert TypEncji.PESEL not in [z[2] for z in wynik]


# --- cycle B: NIP, REGON, IBAN, DOWOD ---------------------------------------

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


def _konta(tekst: str):
    return [(tekst[z.start : z.koniec], z.suma_kontrolna) for z in znajdz(tekst) if z.typ is TypEncji.IBAN]


def test_nrb_bez_pl_w_zapisach_spotykanych_w_pismach():
    # NRB = IBAN without the country code; the checksum is the IBAN one with "PL" in front
    for numer in (
        "61 1090 1014 0000 0712 1981 2874",
        "61109010140000071219812874",
        "61-1090-1014-0000-0712-1981-2874",
        "6110 9010 1400 0007 1219 8128 74",
        "61 1090 1014 0000 0712 1981 2874",
    ):
        assert _konta(f"Konto: {numer}.") == [(numer, True)], numer


def test_iban_ze_spacja_po_pl():
    assert _konta("Konto: PL 61 1090 1014 0000 0712 1981 2874.") == [
        ("PL 61 1090 1014 0000 0712 1981 2874", True)
    ]


def test_nrb_bledna_suma_podejrzany():
    wynik = _podejrzane("Konto: 61 1090 1014 0000 0712 1981 2875.")
    assert [z.typ for z in wynik] == [TypEncji.IBAN]


def test_nrb_nie_lapie_fragmentu_dluzszego_ciagu():
    assert _konta("Kod 611090101400000712198128741 i 161109010140000071219812874.") == []


def test_nrb_caly_numer_w_jednej_encji():
    from niewidka.detektory import RegulyDetektor

    tekst = "Przelew na 61 1090 1014 0000 0712 1981 2874 wykonany."
    wynik = RegulyDetektor().znajdz(tekst)
    assert [(tekst[z.start : z.koniec], z.typ) for z in wynik] == [
        ("61 1090 1014 0000 0712 1981 2874", TypEncji.IBAN)
    ]


def test_paszport_wykryty_bez_sumy_kontrolnej():
    # two letters + seven digits; no checksum we could verify, so it stays correctable
    for numer in ("ZE 1234567", "ZE1234567"):
        tekst = f"Paszport nr {numer} wydany w Gdańsku."
        wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.DOKUMENT]
        assert [(tekst[z.start : z.koniec], z.suma_kontrolna, z.podejrzana) for z in wynik] == [
            (numer, False, False)
        ], numer


def test_kod_waluty_przed_kwota_nigdy_nie_jest_pewnym_dowodem():
    # "PLN 100000" happens to pass the ID card sum (by hand: 25*7+21*3+23*1+1*9 = 270): an amount
    for tekst in ("Kwota PLN 100000 do zapłaty.", "Prowizja EUR 100000."):
        wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.DOKUMENT]
        assert [z.suma_kontrolna for z in wynik] == [False], tekst


def test_dowod_ze_spacja():
    tekst = "Dowód ABC 412345 stracił ważność."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.DOKUMENT]
    assert [(z.start, z.koniec) for z in wynik] == [(6, 16)]
    assert wynik[0].suma_kontrolna is True


def test_dowod_z_dokumentacji_mswia_ma_poprawna_sume():
    wynik = [z for z in znajdz("Dowód ABA300000.") if z.typ is TypEncji.DOKUMENT]
    assert wynik and wynik[0].suma_kontrolna is True


def test_dowod_bledna_suma_podejrzany():
    wynik = _podejrzane("Dowód ABC212346 stracił ważność.")
    assert wynik[0].typ is TypEncji.DOKUMENT
    assert wynik[0].podejrzana is True


# --- cycle C: EMAIL, TELEFON, ADRES, DATA ------------------------------------

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


# --- false negatives from the extended corpus (tel-085, tel-086, data-094) ---

def test_telefon_stacjonarny_3_3_3_pierwsza_cyfra_1_4():
    assert _znalezione("Tel.: +48 123 456 789.", TypEncji.TELEFON) == ["+48 123 456 789"]
    assert _znalezione("Tel.: 123-456-789.", TypEncji.TELEFON) == ["123-456-789"]


def test_telefon_stacjonarny_wymaga_separatorow():
    # 9 digits without separators are a REGON trap, not a phone.
    assert _znalezione("REGON 123456789 wpisano błędnie.", TypEncji.TELEFON) == []


def test_data_iso_rrrr_mm_dd():
    assert _znalezione("Data urodzenia: 1982-05-13.", TypEncji.DATA) == ["1982-05-13"]


def test_data_iso_nie_zagniezdrza_sie_w_innych_liczbach():
    assert _znalezione("Kod 12345-05-13-6789 pozycja.", TypEncji.DATA) == []


# --- ADRES includes a postal code with a town (bug from the live UI) ---

def test_adres_ulica_z_kodem_i_miejscowoscia():
    # A postal code with a town is a quasi-identifier: leaving it
    # visible next to a masked street is a leak; ADRES is one continuous whole.
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
    # A code without a capital letter after it (here: no town) has no tail.
    assert _znalezione("Paczka z kodem 12-345 w dzienniku.", TypEncji.ADRES) == []


# --- cycle G: IPv4/IPv6 address --------------------------------------------

def test_ip_v4_poprawny_znaleziony():
    # offsets = sample nowe-ip-1 from tests/korpus/probki_nowe_typy.jsonl
    tekst = "Zapis logu: połączenie z adresu 192.168.14.201."
    wynik = [z for z in znajdz(tekst) if z.typ is TypEncji.IP]
    assert [(z.start, z.koniec) for z in wynik] == [(32, 46)]
    assert wynik[0].podejrzana is False
    assert wynik[0].pewnosc > 0.5


def test_ip_v4_oktet_za_duzy_podejrzany():
    # 256 is not an octet: masked as suspect (the safe side), not as certain
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
    # five dotted groups are not an IPv4
    assert [z for z in znajdz("Ciąg 1.2.3.4.5 w opisie.") if z.typ is TypEncji.IP] == []


# --- cycle H: payment card with a Luhn sum ------------------------------

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
    # 2234 = corpus sample (fictitious, wrong Luhn sum): masked with a flag
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
    # REGON-14 (valid checksum) fits the card window by shape:
    # after merging the label is REGON (checksum > Luhn window without checksum)
    from niewidka.detektory import RegulyDetektor

    wynik = RegulyDetektor().znajdz("REGON 49000001000003 w rejestrze.")
    assert [z.typ for z in wynik] == [TypEncji.REGON]


def test_iban_wygrywa_z_karta():
    # An IBAN with spaces every 4 characters contains a 16-digit window: after merging the whole
    # entity is labelled IBAN with a valid checksum, never KARTA
    from niewidka.detektory import RegulyDetektor

    iban = "PL61 1090 1014 0000 0712 1981 2874"
    wynik = RegulyDetektor().znajdz(f"Przelew na {iban} wykonany.")
    typy = [z.typ for z in wynik]
    assert TypEncji.IBAN in typy
    assert TypEncji.KARTA not in typy


def test_adres_miejscowosc_nie_przechodzi_do_nastepnej_linii():
    # 'Warszawa\n\nDotyczy:' vanished into [ADRES_2]
    tekst = "ul. Różana 8/24\n02-562 Warszawa\n\nDotyczy: wezwania"
    assert _znalezione(tekst, TypEncji.ADRES) == ["ul. Różana 8/24\n02-562 Warszawa"]
    assert _znalezione("00-108 Warszawa\nTel. 22 555", TypEncji.ADRES) == ["00-108 Warszawa"]


def test_adres_miejscowosc_ze_spacja_nierozdzielajaca():
    # NBSP in 'Nowy Dwór Mazowiecki' left 'Dwór Mazowiecki'
    tekst = "ul. Długa 5, 05-100 Nowy\u00a0Dwór\u00a0Mazowiecki"
    assert _znalezione(tekst, TypEncji.ADRES) == [tekst]


# --- logic fixes 2026-11 -----------------------------------------------------

def test_adres_z_wielkiej_litery_caly():
    for tekst, adres in [
        ("Ul. Lipowa 5, 80-001 Gdańsk", "Ul. Lipowa 5, 80-001 Gdańsk"),
        ("Al. Jerozolimskie 100, 00-001 Warszawa", "Al. Jerozolimskie 100, 00-001 Warszawa"),
        ("Pl. Zamkowy 1", "Pl. Zamkowy 1"),
        ("UL. LIPOWA 5", "UL. LIPOWA 5"),
    ]:
        wynik = [tekst[z.start : z.koniec] for z in znajdz(tekst) if z.typ is TypEncji.ADRES]
        assert wynik == [adres], (tekst, wynik)


def test_slowo_ulica_wewnatrz_wyrazu_to_nie_adres():
    assert [z for z in znajdz("Mikulica 5 23") if z.typ is TypEncji.ADRES] == []


def test_nip_w_starym_zapisie():
    dobre = [z for z in znajdz("NIP 123-45-63-218") if z.typ is TypEncji.NIP]
    assert len(dobre) == 1 and dobre[0].suma_kontrolna
    zle = [z for z in znajdz("NIP 123-45-63-219") if z.typ is TypEncji.NIP]
    assert len(zle) == 1 and zle[0].podejrzana


def test_dowod_z_samych_zer_nie_jest_pewny():
    (dowod,) = [z for z in znajdz("dowód AAA 000000") if z.typ is TypEncji.DOKUMENT]
    assert dowod.podejrzana and not dowod.suma_kontrolna


def test_adres_ulica_bez_prefiksu_przed_kodem():
    # the postal code anchors the street written without "ul."
    assert _znalezione("Proszę pisać na Lipowa 5, 80-001 Gdańsk.", TypEncji.ADRES) == [
        "Lipowa 5, 80-001 Gdańsk"
    ]
    assert _znalezione("Adres: Armii Krajowej 12/4 80-001 Gdańsk.", TypEncji.ADRES) == [
        "Armii Krajowej 12/4 80-001 Gdańsk"
    ]


def test_adres_bez_prefiksu_nie_lapie_telefonu():
    znalezione = _znalezione("Tel 600 100 200, 00-001 Warszawa.", TypEncji.ADRES)
    assert znalezione == ["00-001 Warszawa"]


def test_adres_bez_prefiksu_znane_nadmaskowanie():
    # accepted: any "Word N," right before a postal code reads as a street
    assert _znalezione("Faktura 5, 00-001 Warszawa.", TypEncji.ADRES) == ["Faktura 5, 00-001 Warszawa"]


def test_telefon_w_nawiasie():
    assert _znalezione("Kontakt: Joanna Zając (500 333 444, jz@example.pl).", TypEncji.TELEFON) == [
        "500 333 444"
    ]
    assert _znalezione("Sekretariat: (22) 555 01 42.", TypEncji.TELEFON) == ["(22) 555 01 42"]


def test_adres_z_odmienionym_slowem_ulica():
    assert _znalezione("Kościół na osiedlu Słoneczne 12 w Krakowie.", TypEncji.ADRES) == [
        "osiedlu Słoneczne 12"
    ]
    assert _znalezione("Mieszka przy ulicy Długiej 7/2, 00-238 Warszawa.", TypEncji.ADRES) == [
        "ulicy Długiej 7/2, 00-238 Warszawa"
    ]
    assert _znalezione("Biuro przy alei Pracy 3.", TypEncji.ADRES) == ["alei Pracy 3"]


def test_plac_bez_numeru_to_nie_adres():
    assert _znalezione("Market przy placu Solidarności jest czynny.", TypEncji.ADRES) == []


def test_adres_bez_prefiksu_z_numerem_mieszkania():
    assert _znalezione("zamieszkały: Świętojańska 45 m. 12, 81-391 Gdynia, PESEL", TypEncji.ADRES) == [
        "Świętojańska 45 m. 12, 81-391 Gdynia"
    ]


def test_numer_rejestracyjny_pojazdu():
    assert _znalezione("Toyota Corolla, tab. rej. GD12345, oraz Opel nr rej. KR 99182.", TypEncji.DOKUMENT) == [
        "GD12345",
        "KR 99182",
    ]
    assert _znalezione("numer rejestracyjny WI 7824A", TypEncji.DOKUMENT) == ["WI 7824A"]


def test_rejestracja_bez_kontekstu_to_nie_dokument():
    assert _znalezione("Model GD12345 jest dostępny.", TypEncji.DOKUMENT) == []


def test_adres_bez_prefiksu_w_dwoch_liniach_naglowka():
    tekst = "Poszkodowany:\nKrzysztof Wilczek\nMickiewicza 8\n30-042 Kraków\ntel. 791 223 344"
    assert _znalezione(tekst, TypEncji.ADRES) == ["Mickiewicza 8\n30-042 Kraków"]


def test_numer_vin():
    assert _znalezione("Toyota Corolla, VIN: JTDKB20U0J3123456, rocznik 2018.", TypEncji.DOKUMENT) == [
        "JTDKB20U0J3123456"
    ]


def test_numer_polisy():
    tekst = "pan Roman Lis (polisa OC w PZU S.A. nr POL-99882211/2026), oraz polisy nr 900123456789"
    assert _znalezione(tekst, TypEncji.DOKUMENT) == ["POL-99882211/2026", "900123456789"]


def test_slowo_polisa_bez_numeru_nic_nie_lapie():
    assert _znalezione("Polisa obejmuje szkody do 10 tys. zł, nr umowy w załączniku.", TypEncji.DOKUMENT) == []
