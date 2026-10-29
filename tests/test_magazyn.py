"""Testy magazynu map z retencją (docs/MAPY-I-AKTUALIZACJE.md §1-3, §8: wiersze 2, 3, 9, 10).

Zegar wstrzyknięty: testy retencji bez czekania. Dziennik JSONL bez danych
osobowych. Usunięcie/wygaśnięcie skreśla mapę z rejestru wydanych map wyłącznie
gdy `uniewaznij_pobrane` (przegląd Argona pkt 3). Jedna blokada na rejestr,
dziennik i magazyn (przegląd Argona pkt 9).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from niewidka.magazyn import MagazynMap
from niewidka.mapa import BladMapy, Mapa, Wpis, Wystapienie, odszyfruj, zaszyfruj

KLUCZ = bytes(range(32))
ID_A = "ab" * 16
ID_B = "cd" * 16


class ZegarAtrapa:
    """Czas przesuwany ręcznie: retencja testowana bez czekania."""

    def __init__(self, start: datetime):
        self.teraz = start

    def __call__(self) -> datetime:
        return self.teraz

    def przesun(self, **kw):
        self.teraz += timedelta(**kw)


@pytest.fixture()
def zegar():
    return ZegarAtrapa(datetime(2026, 10, 29, 7, 41, tzinfo=UTC))


@pytest.fixture()
def magazyn(tmp_path, zegar):
    return MagazynMap(tmp_path / "mapy", retencja_dni=30, zegar=zegar)


def mapa(identyfikator: str = ID_A) -> Mapa:
    return Mapa(
        identyfikator=identyfikator,
        utworzono="2026-10-29T07:41:00+00:00",
        poziom=2,
        wpisy=[Wpis("OSOBA", "OSOBA_1", {"F1": "Jan Kowalski"})],
        wystapienia=[Wystapienie(0, "OSOBA_1", "F1", "Jan Kowalski")],
    )


def test_zapisz_tworzy_szyfrogram_metadane_i_dziennik(magazyn):
    wygasa = magazyn.zapisz(zaszyfruj(mapa(), KLUCZ), mapa(), {"OSOBA": 1})
    assert wygasa == datetime(2026, 11, 28, 7, 41, tzinfo=UTC)  # 30 dni po zegarze
    katalog = magazyn.katalog
    assert (katalog / f"{ID_A}.nwidka").is_file()
    metadane = json.loads((katalog / f"{ID_A}.json").read_text(encoding="utf-8"))
    assert metadane["identyfikator"] == ID_A
    assert metadane["wygasa"] == wygasa.isoformat()
    assert metadane["poziom"] == 2
    assert metadane["statystyki"] == {"OSOBA": 1}
    dziennik = (katalog / "dziennik.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(dziennik) == 1
    wpis = json.loads(dziennik[0])
    assert wpis["zdarzenie"] == "utworzono"
    assert wpis["skrot_id"] == ID_A[:12]  # skrót, nie pełny identyfikator treści


def test_zapisz_nie_zostawia_danych_osobowych_w_magazynie(magazyn):
    magazyn.zapisz(zaszyfruj(mapa(), KLUCZ), mapa(), {"OSOBA": 1})
    jawne = ""
    for plik in magazyn.katalog.iterdir():
        if plik.suffix != ".nwidka":  # .nwidka to szyfrogram, ale i tak go nie czytamy jawne
            jawne += plik.read_text(encoding="utf-8", errors="replace")
    for dana in ("Jan Kowalski", "OSOBA_1", ID_A):  # dane, oznaczenia, pełny id poza metadanymi
        if dana == ID_A:
            assert dana in (magazyn.katalog / f"{ID_A}.json").read_text(encoding="utf-8")
        else:
            assert dana not in jawne, f"dana osobowa w pliku jawnym: {dana}"


def test_wczytaj_zwraca_szyfrogram_do_odszyfrowania(magazyn):
    paczka = zaszyfruj(mapa(), KLUCZ)
    magazyn.zapisz(paczka, mapa(), {"OSOBA": 1})
    assert magazyn.wczytaj(ID_A) == paczka
    assert odszyfruj(magazyn.wczytaj(ID_A), KLUCZ).identyfikator == ID_A
    assert magazyn.wczytaj(ID_B) is None
    assert magazyn.wczytaj("fe" * 16) is None


def test_lista_od_najnowszej_z_metadanymi(magazyn, zegar):
    magazyn.zapisz(zaszyfruj(mapa(ID_A), KLUCZ), mapa(ID_A), {"OSOBA": 1})
    zegar.przesun(minutes=3)
    magazyn.zapisz(zaszyfruj(mapa(ID_B), KLUCZ), mapa(ID_B), {"PESEL": 2})
    lista = magazyn.lista()
    assert [w["identyfikator"] for w in lista] == [ID_B, ID_A]
    assert lista[0]["statystyki"] == {"PESEL": 2}
    assert lista[1]["poziom"] == 2
    assert all(set(w) == {"identyfikator", "utworzono", "wygasa", "poziom", "statystyki"} for w in lista)


def test_usun_pojedyncza(magazyn):
    magazyn.zapisz(zaszyfruj(mapa(ID_A), KLUCZ), mapa(), {"OSOBA": 1})
    assert magazyn.usun(ID_A) is True
    assert magazyn.wczytaj(ID_A) is None
    assert magazyn.lista() == []
    zdarzenia = [
        json.loads(w)["zdarzenie"]
        for w in (magazyn.katalog / "dziennik.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert zdarzenia == ["utworzono", "usunieto"]
    assert magazyn.usun(ID_A) is False  # drugi raz: nic do usunięcia


def test_usun_wszystkie(magazyn):
    magazyn.zapisz(zaszyfruj(mapa(ID_A), KLUCZ), mapa(ID_A), {"OSOBA": 1})
    magazyn.zapisz(zaszyfruj(mapa(ID_B), KLUCZ), mapa(ID_B), {"OSOBA": 2})
    assert magazyn.usun_wszystkie() == 2
    assert magazyn.lista() == []
    assert magazyn.usun_wszystkie() == 0


def test_posprzataj_usuwa_wylacznie_wygasle(magazyn, zegar):
    magazyn.zapisz(zaszyfruj(mapa(ID_A), KLUCZ), mapa(ID_A), {"OSOBA": 1})
    zegar.przesun(days=20)
    magazyn.zapisz(zaszyfruj(mapa(ID_B), KLUCZ), mapa(ID_B), {"PESEL": 1})
    zegar.przesun(days=11)  # mapa A: 31 dni, mapa B: 11 dni
    assert magazyn.posprzataj() == [ID_A]
    assert magazyn.wczytaj(ID_A) is None
    assert magazyn.wczytaj(ID_B) is not None
    zdarzenia = [
        json.loads(w)["zdarzenie"]
        for w in (magazyn.katalog / "dziennik.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert zdarzenia == ["utworzono", "utworzono", "wygasla"]


def test_retencja_zero_niczego_nie_zapisuje(tmp_path, zegar):
    magazyn = MagazynMap(tmp_path / "mapy", retencja_dni=0, zegar=zegar)
    assert magazyn.zapisz(zaszyfruj(mapa(), KLUCZ), mapa(), {"OSOBA": 1}) is None
    assert not magazyn.katalog.exists() or list(magazyn.katalog.iterdir()) == []
    assert magazyn.lista() == []


def test_path_traversal_odrzucony(magazyn):
    for zly in ("../dziennik", "..\\dziennik", f"{ID_A}/../../dziennik", "krotki", "ZZZZ", ""):
        with pytest.raises(ValueError):
            magazyn.wczytaj(zly)
        with pytest.raises(ValueError):
            magazyn.usun(zly)
    # nic nie powstało poza katalogiem magazynu
    if magazyn.katalog.exists():
        assert [p.name for p in magazyn.katalog.iterdir()] == ["dziennik.jsonl"]


def test_uprawnienia_plikow_0600_na_posix(magazyn):
    if os.name == "nt":
        pytest.skip("POSIX-owe uprawnienia")
    magazyn.zapisz(zaszyfruj(mapa(), KLUCZ), mapa(), {"OSOBA": 1})
    for nazwa in (f"{ID_A}.nwidka", f"{ID_A}.json"):
        assert (magazyn.katalog / nazwa).stat().st_mode & 0o777 == 0o600


def test_jedna_blokada_na_magazyn_dziennik_i_rejestr(magazyn):
    # przegląd Argona pkt 9: API trzyma tę samą blokadę wokół rejestru wydanych map
    assert isinstance(magazyn.blokada, type(__import__("threading").Lock()))
    with magazyn.blokada:
        assert magazyn.blokada.locked()


def test_zapis_uszkodzonej_mapy_nie_powstaje(magazyn):
    # magazyn zapisuje tylko szyfrogram z nagłówkiem NWID (fail-closed przy śmieciach)
    with pytest.raises(BladMapy):
        magazyn.zapisz(b"nie mapa", mapa(), {"OSOBA": 1})
    assert magazyn.lista() == []
