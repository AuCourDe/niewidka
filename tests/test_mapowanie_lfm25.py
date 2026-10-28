"""Mapowanie klas LFM2.5 -> typy Niewidki (K2e, detektory.mapuj_typ_lfm25)."""

from niewidka.detektory import mapuj_typ_lfm25
from niewidka.model import TypEncji


def test_mapowanie_typow_jednoznacznych():
    assert mapuj_typ_lfm25("identity.person_name") is TypEncji.OSOBA
    assert mapuj_typ_lfm25("identity.passport") is TypEncji.DOKUMENT
    assert mapuj_typ_lfm25("identity.drivers_license") is TypEncji.DOKUMENT
    assert mapuj_typ_lfm25("contact.address") is TypEncji.ADRES
    assert mapuj_typ_lfm25("contact.postal_code") is TypEncji.ADRES
    assert mapuj_typ_lfm25("contact.phone") is TypEncji.TELEFON
    assert mapuj_typ_lfm25("contact.email") is TypEncji.EMAIL
    assert mapuj_typ_lfm25("financial.iban") is TypEncji.IBAN
    assert mapuj_typ_lfm25("financial.bank_account") is TypEncji.IBAN
    assert mapuj_typ_lfm25("identity.date_of_birth") is TypEncji.DATA


def test_national_id_kształtem_zapisu():
    assert mapuj_typ_lfm25("identity.national_id", "44051401359") is TypEncji.PESEL
    assert mapuj_typ_lfm25("identity.national_id", "123-456-32-18") is TypEncji.NIP
    assert mapuj_typ_lfm25("identity.national_id", "445566778") is TypEncji.REGON
    assert mapuj_typ_lfm25("identity.national_id", "12345678901234") is TypEncji.REGON
    assert mapuj_typ_lfm25("identity.national_id", "ABC 212345") is TypEncji.DOKUMENT


def test_nieznana_klasa_wypada_surowa_nazwa():
    assert mapuj_typ_lfm25("healthcare.condition") == "healthcare.condition"
    assert mapuj_typ_lfm25("org.company_name") == "org.company_name"
