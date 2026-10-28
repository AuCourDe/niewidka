"""Testy modelu danych (LLD §2)."""

from niewidka.model import Dokument, Encja, RunInfo, Segment, TypEncji, Zakres


def test_typ_encji_ma_wszystkie_typy():
    wartosci = {t.value for t in TypEncji}
    assert {
        "OSOBA",
        "PESEL",
        "NIP",
        "REGON",
        "ADRES",
        "TELEFON",
        "EMAIL",
        "IBAN",
        "DOKUMENT",
        "DATA",
        "IP",
        "KARTA",
        "SWIFT",
        "LOGIN",
        "INNE",
    } == wartosci


def test_zakres_domyślnie_bez_sumy_kontrolnej():
    zakres = Zakres(start=3, koniec=14, typ=TypEncji.PESEL, pewnosc=1.0, zrodlo="regula")
    assert zakres.suma_kontrolna is False


def test_encja_domyslnie_bez_oznaczenia():
    encja = Encja(zakres=Zakres(0, 5, TypEncji.OSOBA, 0.9, "regula"), tekst="Kowal")
    assert encja.oznaczenie is None
    assert encja.klucz_grupy is None


def test_segment_przechowuje_runy_i_starty():
    segment = Segment(
        tekst="Jan Kowalski",
        runs=[RunInfo("Jan ", object()), RunInfo("Kowalski", object())],
        starts=[0, 4],
    )
    assert segment.starts == [0, 4]
    assert segment.runs[1].tekst == "Kowalski"


def test_dokument_przechowuje_format():
    dokument = Dokument(format="docx", segmenty=[])
    assert dokument.format == "docx"
    assert dokument.segmenty == []
