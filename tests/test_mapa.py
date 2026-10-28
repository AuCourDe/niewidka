"""Testy mapy i szyfrowania (K4, LLD §8): format JSON, AES-256-GCM, przywracanie
po parze (oznaczenie, wariant) — niezależne od pozycji, odporne na przestawienie zdań."""

from __future__ import annotations

import json

import pytest

from niewidka.mapa import (
    BladMapy,
    Mapa,
    Rozbieznosc,
    Wpis,
    Wystapienie,
    naglowek,
    odszyfruj,
    przywroc_tekst,
    slownik,
    zaszyfruj,
)

KLUCZ = bytes(range(32))


def mapa_proba() -> Mapa:
    return Mapa(
        identyfikator="a3f9c2",
        utworzono="2026-10-28T12:00:00+02:00",
        poziom=1,
        wpisy=[
            Wpis(typ="OSOBA", oznaczenie="OSOBA_1", formy={"F1": "Jan Kowalski", "F2": "Jana Kowalskiego"}),
            Wpis(typ="PESEL", oznaczenie="PESEL_1", formy={"F1": "44051401359"}),
        ],
        wystapienia=[
            Wystapienie(0, "OSOBA_1", "F1", "Jan Kowalski"),
            Wystapienie(1, "PESEL_1", "F1", "44051401359"),
            Wystapienie(2, "OSOBA_1", "F2", "Jana Kowalskiego"),
        ],
    )


def test_slownik_format_lld_8():
    d = slownik(mapa_proba())
    assert d["wersja"] == 1
    assert d["identyfikator"] == "a3f9c2"
    assert d["poziom"] == 1
    assert d["wpisy"][0] == {
        "typ": "OSOBA",
        "oznaczenie": "OSOBA_1",
        "formy": {"F1": "Jan Kowalski", "F2": "Jana Kowalskiego"},
    }
    assert d["wystapienia"][0] == {
        "kolejny": 0,
        "oznaczenie": "OSOBA_1",
        "wariant": "F1",
        "oryginal": "Jan Kowalski",
    }
    assert Mapa.z_slownika(json.loads(json.dumps(d))) == mapa_proba()


def test_szyfrowanie_naglowek_nwid():
    zaszyfrowana = zaszyfruj(mapa_proba(), KLUCZ)
    assert zaszyfrowana[:4] == b"NWID"
    assert zaszyfrowana[4] == 1  # wersja formatu
    assert len(zaszyfrowana) > 4 + 1 + 12  # + nonce + id + ciphertext


def test_szyfrowanie_odszyfrowanie_roundtrip():
    assert odszyfruj(zaszyfruj(mapa_proba(), KLUCZ), KLUCZ) == mapa_proba()


def test_zly_klucz_blad_mapy():
    with pytest.raises(BladMapy):
        odszyfruj(zaszyfruj(mapa_proba(), KLUCZ), bytes(32))


def test_zmieniony_bajt_blad_mapy():
    dane = bytearray(zaszyfruj(mapa_proba(), KLUCZ))
    dane[-1] ^= 0x01
    with pytest.raises(BladMapy):
        odszyfruj(bytes(dane), KLUCZ)


def test_podmieniony_identyfikator_w_naglowku_blad_mapy():
    """AAD = identyfikator: mapa nie da się podstawić pod inny dokument."""
    dane = bytearray(zaszyfruj(mapa_proba(), KLUCZ))
    wersja, identyfikator = naglowek(bytes(dane))
    assert (wersja, identyfikator) == (1, "a3f9c2")
    start_id = 4 + 1 + 12 + 1
    dane[start_id] = ord("b")  # podmiana id w nagłówku
    with pytest.raises(BladMapy):
        odszyfruj(bytes(dane), KLUCZ)  # tag GCM nie zgodzi się z nowym AAD


def test_zla_wersja_i_zly_magic():
    dane = bytearray(zaszyfruj(mapa_proba(), KLUCZ))
    dane[4] = 9
    with pytest.raises(BladMapy, match="wersja"):
        odszyfruj(bytes(dane), KLUCZ)
    dane[0:4] = b"XXXX"
    with pytest.raises(BladMapy, match="NWID"):
        odszyfruj(bytes(dane), KLUCZ)


def test_przywroc_tekst_po_parze_oznaczenie_wariant():
    tekst = "[OSOBA_1_F1] złożył wniosek; PESEL [PESEL_1] został zweryfikowany."
    wynik, rozbieznosci = przywroc_tekst(tekst, mapa_proba())
    assert wynik == (
        "Jan Kowalski złożył wniosek; PESEL 44051401359 został zweryfikowany."
    )
    assert rozbieznosci == []


def test_przywroc_po_przestawieniu_zdan():
    tekst = "PESEL [PESEL_1] zweryfikowano. Wniosek złożył [OSOBA_1_F2] w boo."
    wynik, _ = przywroc_tekst(tekst, mapa_proba())
    assert "Jana Kowalskiego" in wynik
    assert "44051401359" in wynik


def test_znacznik_bez_wariantu_trafia_na_F1():
    wynik, rozbieznosci = przywroc_tekst("PESEL [PESEL_1].", mapa_proba())
    assert wynik == "PESEL 44051401359."
    # OSOBA_1 nie wystąpił — uczciwa rozbieżność, nie ciche pominięcie
    assert rozbieznosci == [Rozbieznosc("wpis_niewykorzystany", "OSOBA_1")]


def test_znacznik_bez_wpisu_rozbieznosc():
    wynik, rozbieznosci = przywroc_tekst("[OSOBA_9_F1] i [TELEFON_2].", mapa_proba())
    assert wynik == "[OSOBA_9_F1] i [TELEFON_2]."  # bez wpisu zostaje, bez zgadywania
    assert Rozbieznosc("znacznik_bez_wpisu", "[OSOBA_9_F1]") in rozbieznosci
    assert Rozbieznosc("znacznik_bez_wpisu", "[TELEFON_2]") in rozbieznosci


def test_wpis_niewykorzystany_rozbieznosc():
    wynik, rozbieznosci = przywroc_tekst("Tylko [OSOBA_1_F1].", mapa_proba())
    assert wynik == "Tylko Jan Kowalski."
    # PESEL_1 nie wystąpił wcale; OSOBA_1 częściowo (F1) — wpis niewykorzystany
    # to dopiero ten bez żadnej użytej formy; nieużyta forma jest normalna
    assert [r for r in rozbieznosci if r.typ == "wpis_niewykorzystany"] == [
        Rozbieznosc("wpis_niewykorzystany", "PESEL_1")
    ]


def test_pusta_mapa_i_tekst_bez_znacznikow():
    pusta = Mapa(identyfikator="x", utworzono="t", poziom=1)
    wynik, rozbieznosci = przywroc_tekst("czysty tekst", pusta)
    assert wynik == "czysty tekst"
    assert rozbieznosci == []
