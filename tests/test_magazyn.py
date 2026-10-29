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
    # przegląd Argona pkt 9: jedna blokada (RLock, by API trzymało ją wokół całej
    # sekwencji magazyn+dziennik+rejestr); inny wątek pod nią nie wejdzie
    with magazyn.blokada:
        wynik = []

        def probuj():
            wynik.append(magazyn.blokada.acquire(timeout=0.2))

        watek = __import__("threading").Thread(target=probuj)
        watek.start()
        watek.join()
        assert wynik == [False]  # wykluczanie między wątkami działa


def test_zapis_uszkodzonej_mapy_nie_powstaje(magazyn):
    # magazyn zapisuje tylko szyfrogram z nagłówkiem NWID (fail-closed przy śmieciach)
    with pytest.raises(BladMapy):
        magazyn.zapisz(b"nie mapa", mapa(), {"OSOBA": 1})
    assert magazyn.lista() == []


# --- API: magazyn w /api/ukryj, /api/przywroc, /api/mapy ----------------------

import base64
import zipfile
from dataclasses import replace

import httpx

from niewidka.api import create_app
from niewidka.detektory import RegulyDetektor
from niewidka.konfig import Konfig

TEKST = "Jan Kowalski, PESEL 44051401359. Telefon +48 601 234 567, e-mail jan@example.com."


@pytest.fixture()
def klucz_plik(tmp_path):
    sciezka = tmp_path / "klucz.b64"
    sciezka.write_bytes(base64.b64encode(KLUCZ))
    sciezka.chmod(0o600)
    return str(sciezka)


@pytest.fixture()
def katalog_danych_uzytkownika(tmp_path, monkeypatch):
    """Izolacja katalogu danych (LOCALAPPDATA/XDG_DATA_HOME): test nie pisze do
    prawdziwego profilu użytkownika."""
    profil = tmp_path / "profil"
    monkeypatch.setenv("LOCALAPPDATA", str(profil))
    monkeypatch.setenv("XDG_DATA_HOME", str(profil))
    return profil


@pytest.fixture()
def konfig_api(klucz_plik, tmp_path):
    return Konfig(
        klucz_plik=klucz_plik,
        mapy_retencja_dni=30,
        mapy_katalog=tmp_path / "magazyn",
        rejestr_map=tmp_path / "wydane-mapy.jsonl",
    )


def _klient(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{app.state.konfig.port}"
    )


def _naglowki(app, **dodatkowe) -> dict:
    return {"X-Niewidka-Token": app.state.token, **dodatkowe}


async def _ukryj(klient, app, tekst: str = TEKST):
    odpowiedz = await klient.post(
        "/api/ukryj", data={"tekst": tekst, "poziom": "1"}, headers=_naglowki(app)
    )
    assert odpowiedz.status_code == 200, odpowiedz.text
    with zipfile.ZipFile(__import__("io").BytesIO(odpowiedz.content)) as paczka:
        czesci = {nazwa: paczka.read(nazwa) for nazwa in paczka.namelist()}
    return odpowiedz, czesci


def _wynik_txt(identyfikator: str, czesci: dict[str, bytes]) -> str:
    return czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.txt"].decode()


def _mapa_paczka(identyfikator: str, czesci: dict[str, bytes]) -> bytes:
    return czesci[f"{identyfikator[:12]}.nwidka"]


@pytest.mark.anyio
async def test_ukryj_zapisuje_mape_do_magazynu_z_naglowkiem(konfig_api):
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, _ = await _ukryj(klient, app)
    wygasa = odpowiedz.headers.get("x-niewidka-mapa-zapisana")
    assert wygasa, "nagłówek o zapisanej mapie ma być obecny przy retencji > 0"
    identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
    magazyn = app.state.magazyn
    assert (magazyn.katalog / f"{identyfikator}.nwidka").is_file()
    assert (magazyn.katalog / f"{identyfikator}.json").is_file()
    assert datetime.fromisoformat(wygasa) > datetime.now(UTC) - timedelta(seconds=5)
    # dziennik audytu bez danych osobowych z dokumentu
    dziennik = (magazyn.katalog / "dziennik.jsonl").read_text(encoding="utf-8")
    assert "Jan Kowalski" not in dziennik and "44051401359" not in dziennik
    assert "utworzono" in dziennik


@pytest.mark.anyio
async def test_ukryj_przy_retencji_zero_nie_zapisuje_i_nie_daje_naglowka(klucz_plik, tmp_path):
    konfig = Konfig(
        klucz_plik=klucz_plik,
        mapy_retencja_dni=0,
        mapy_katalog=tmp_path / "magazyn",
        rejestr_map=tmp_path / "wydane-mapy.jsonl",
    )
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, _ = await _ukryj(klient, app)
    assert "x-niewidka-mapa-zapisana" not in odpowiedz.headers
    assert app.state.magazyn.lista() == []


@pytest.mark.anyio
async def test_get_mapy_lista_z_retencja_i_wymogiem_tokenu(konfig_api):
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        assert (await klient.get("/api/mapy")).status_code == 403  # bez tokenu
        _, _ = await _ukryj(klient, app)
        _, _ = await _ukryj(klient, app)
        lista = await klient.get("/api/mapy", headers=_naglowki(app))
    assert lista.status_code == 200
    dane = lista.json()
    assert dane["retencja_dni"] == 30
    assert len(dane["mapy"]) == 2
    assert all(
        set(w) == {"id", "utworzono", "wygasa", "poziom", "statystyki"} for w in dane["mapy"]
    )
    assert dane["mapy"][0]["utworzono"] >= dane["mapy"][1]["utworzono"]  # od najnowszej


@pytest.mark.anyio
async def test_przywroc_przez_wklejony_tekst_z_dopiskiem(konfig_api):
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        przywroc = await klient.post(
            "/api/przywroc",
            data={"tekst": _wynik_txt(identyfikator, czesci)},
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 200, przywroc.text
    assert "text/plain" in przywroc.headers["content-type"]
    assert przywroc.text == TEKST
    assert przywroc.headers["x-niewidka-identyfikator"] == identyfikator


@pytest.mark.anyio
async def test_przywroc_przez_tekst_bez_dopisku_z_polem_identyfikator(konfig_api):
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        bez_dopisku = _wynik_txt(identyfikator, czesci).split("\n", 1)[1]
        przywroc = await klient.post(
            "/api/przywroc",
            data={"tekst": bez_dopisku, "identyfikator": identyfikator},
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 200
    assert przywroc.text == TEKST


@pytest.mark.anyio
async def test_przywroc_dopisek_wygrywa_z_polem_identyfikator(konfig_api):
    # przegląd Argona pkt 10: stary wybór z listy + nowy tekst z dopiskiem = dopisek wygrywa
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        pierwsza, _czesci_1 = await _ukryj(klient, app)
        id_pierwszej = pierwsza.headers["x-niewidka-identyfikator"]
        druga, czesci_2 = await _ukryj(klient, app)
        id_drugiej = druga.headers["x-niewidka-identyfikator"]
        # wybór z listy wskazuje starą mapę, ale wklejony tekst ma dopisek nowej
        przywroc = await klient.post(
            "/api/przywroc",
            data={
                "tekst": _wynik_txt(id_drugiej, czesci_2),
                "identyfikator": id_pierwszej,
            },
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 200
    assert przywroc.headers["x-niewidka-identyfikator"] == id_drugiej


@pytest.mark.anyio
async def test_przywroc_bez_wskazania_mapy_wybierz_mape(konfig_api):
    # nic nie wskazuje mapy: brak dopisku, brak pola, magazyn pusty (retencja 0 = jak u wielu organizacji)
    konfig = replace(konfig_api, mapy_retencja_dni=0)
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        bez_dopisku = _wynik_txt(identyfikator, czesci).split("\n", 1)[1]
        przywroc = await klient.post(
            "/api/przywroc", data={"tekst": bez_dopisku}, headers=_naglowki(app)
        )
    assert przywroc.status_code == 422
    dane = przywroc.json()
    assert dane["kod"] == "wybierz_mape"
    assert dane["kandydaci"] == []  # nic nie wskazuje mapy


@pytest.mark.anyio
async def test_przywroc_bez_dopisku_jeden_kandydat_z_kompletem_znacznikow(konfig_api):
    # przegląd Argona pkt 2: dokładnie jeden kandydat ze WSZYSTKIMI znacznikami = wybrany
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        bez_dopisku = _wynik_txt(identyfikator, czesci).split("\n", 1)[1]
        przywroc = await klient.post(
            "/api/przywroc", data={"tekst": bez_dopisku}, headers=_naglowki(app)
        )
    assert przywroc.status_code == 200
    assert przywroc.text == TEKST
    assert przywroc.headers["x-niewidka-identyfikator"] == identyfikator
    assert przywroc.headers.get("x-niewidka-mapa-wybrana-automatycznie") == "1"


@pytest.mark.anyio
async def test_przywroc_bez_dopisku_wiele_kandydatow_wybierz_mape(konfig_api):
    # dwa ukrycia TEJ SAMEJ treści: obie mapy mają komplet znaczników → brak domyślnego wyboru
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        bez_dopisku = _wynik_txt(identyfikator, czesci).split("\n", 1)[1]
        await _ukryj(klient, app)  # druga mapa z tymi samymi typami
        przywroc = await klient.post(
            "/api/przywroc", data={"tekst": bez_dopisku}, headers=_naglowki(app)
        )
    assert przywroc.status_code == 422
    dane = przywroc.json()
    assert dane["kod"] == "wybierz_mape"
    assert len(dane["kandydaci"]) == 2


@pytest.mark.anyio
async def test_przywroc_tekst_bez_znacznikow_komunikat(konfig_api):
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        przywroc = await klient.post(
            "/api/przywroc", data={"tekst": "Zwykły tekst bez znaczników."}, headers=_naglowki(app)
        )
    assert przywroc.status_code == 422
    assert przywroc.json()["kod"] == "wybierz_mape"


@pytest.mark.anyio
async def test_przywroc_plikiem_mapy_jak_dawniej(konfig_api):
    # wklejony tekst + plik mapy (.nwidka): dawna ścieżka bez magazynu
    konfig = replace(konfig_api, mapy_retencja_dni=0)  # magazyn wyłączony, plik mapy obowiązuje
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        przywroc = await klient.post(
            "/api/przywroc",
            data={"tekst": _wynik_txt(identyfikator, czesci)},
            files={"mapa": (f"{identyfikator[:12]}.nwidka", _mapa_paczka(identyfikator, czesci))},
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 200
    assert przywroc.text == TEKST


@pytest.mark.anyio
async def test_przywroc_plik_mapy_z_dopiskiem_innej_mapy_odmowa(konfig_api):
    # dopisek w tekście ≠ identyfikator dostarczonej mapy = odmowa (K4b pkt 6, nadal)
    konfig = replace(konfig_api, mapy_retencja_dni=0)
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        pierwsza, czesci_1 = await _ukryj(klient, app)
        id_pierwszej = pierwsza.headers["x-niewidka-identyfikator"]
        druga, czesci_2 = await _ukryj(klient, app)
        id_drugiej = druga.headers["x-niewidka-identyfikator"]
        # tekst drugiego zadania + mapa pierwszego zadania
        przywroc = await klient.post(
            "/api/przywroc",
            data={"tekst": _wynik_txt(id_drugiej, czesci_2)},
            files={"mapa": (f"{id_pierwszej[:12]}.nwidka", _mapa_paczka(id_pierwszej, czesci_1))},
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 422
    assert "innego zadania" in przywroc.json()["blad"]


@pytest.mark.anyio
async def test_przywroc_po_usunieciu_mapy_z_magazynu_wybierz_mape(konfig_api):
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        usuniecie = await klient.delete(f"/api/mapy/{identyfikator}", headers=_naglowki(app))
        assert usuniecie.status_code == 200
        # dopisek wskazuje mapę, której już nie ma w magazynie
        przywroc = await klient.post(
            "/api/przywroc",
            data={"tekst": _wynik_txt(identyfikator, czesci)},
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 422
    assert "Nie ma już zapisanej mapy" in przywroc.json()["blad"]


@pytest.mark.anyio
async def test_delete_mapy_wymaga_tokenu_i_usuwa(konfig_api):
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, _ = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        assert (
            await klient.delete(f"/api/mapy/{identyfikator}")
        ).status_code == 403  # bez tokenu
        assert (await klient.delete("/api/mapy")).status_code == 403
        usuniete = await klient.delete(f"/api/mapy/{identyfikator}", headers=_naglowki(app))
        assert usuniete.status_code == 200
        lista = (await klient.get("/api/mapy", headers=_naglowki(app))).json()
    assert lista["mapy"] == []


@pytest.mark.anyio
async def test_delete_mapy_zly_identyfikator_422(konfig_api):
    # id nie z [a-f0-9]{32} nigdy nie dotyka ścieżki dysku; traversal wyłapuje
    # walidacja regexem w magazynie (test jednostkowy wyżej), routing nie przekazuje "/",
    # więc tu sprawdzamy warstwę API: 422 zamiast 500
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        for zly in ("krotki", "ZZZZ", "g" * 32):
            atak = await klient.delete(f"/api/mapy/{zly}", headers=_naglowki(app))
            assert atak.status_code == 422, zly


@pytest.mark.anyio
async def test_usuniecie_domyslnie_nie_skresla_pobranej_kopii(konfig_api):
    # przegląd Argona pkt 3: retencja i ręczne Usuń dotyczą magazynu; pobrana kopia działa
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        assert (await klient.delete(f"/api/mapy/{identyfikator}", headers=_naglowki(app))).status_code == 200
        przywroc = await klient.post(
            "/api/przywroc",
            data={"tekst": _wynik_txt(identyfikator, czesci)},
            files={"mapa": (f"{identyfikator[:12]}.nwidka", _mapa_paczka(identyfikator, czesci))},
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 200
    assert przywroc.text == TEKST


@pytest.mark.anyio
async def test_usuniecie_z_uniewaznij_pobrane_skresla_z_rejestru(klucz_plik, tmp_path):
    konfig = replace(
        Konfig(
            klucz_plik=klucz_plik,
            mapy_katalog=tmp_path / "magazyn",
            rejestr_map=tmp_path / "wydane-mapy.jsonl",
        ),
        mapy_uniewaznij_pobrane=True,
    )
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        paczka = _mapa_paczka(identyfikator, czesci)
        assert (await klient.delete(f"/api/mapy/{identyfikator}", headers=_naglowki(app))).status_code == 200
        przywroc = await klient.post(
            "/api/przywroc",
            data={"tekst": _wynik_txt(identyfikator, czesci)},
            files={"mapa": (f"{identyfikator[:12]}.nwidka", paczka)},
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 422
    assert "nie została wydana" in przywroc.json()["blad"]
    # plik rejestru przepisany atomowo, bez usuniętej mapy
    rejestr = konfig.rejestr_map.read_text(encoding="utf-8")
    assert identyfikator not in rejestr


@pytest.mark.anyio
async def test_sprzatanie_wygaslych_przy_starcie_i_przed_operacja(klucz_plik, tmp_path):
    katalog = tmp_path / "magazyn"
    konfig = Konfig(
        klucz_plik=klucz_plik, mapy_katalog=katalog, rejestr_map=tmp_path / "wydane-mapy.jsonl"
    )
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, _ = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        lista = (await klient.get("/api/mapy", headers=_naglowki(app))).json()
        assert len(lista["mapy"]) == 1
    # retencja dobiegła końca; program wyłączony nie sprząta, więc robi to nowy start
    for plik in katalog.glob(f"{identyfikator}.json"):
        metadane = json.loads(plik.read_text(encoding="utf-8"))
        metadane["wygasa"] = "2020-01-01T00:00:00+00:00"  # termin minął
        plik.write_text(json.dumps(metadane), encoding="utf-8")
    app2 = create_app(replace(konfig), detektor=RegulyDetektor())
    assert app2.state.magazyn.lista() == []
    zdarzenia = [
        json.loads(w)["zdarzenie"]
        for w in (katalog / "dziennik.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert zdarzenia == ["utworzono", "wygasla"]


@pytest.mark.anyio
async def test_przywrocenie_wpisuje_przywrocono_do_dziennika(konfig_api):
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        await klient.post(
            "/api/przywroc",
            data={"tekst": _wynik_txt(identyfikator, czesci)},
            headers=_naglowki(app),
        )
    dziennik = app.state.magazyn.katalog.joinpath("dziennik.jsonl").read_text(encoding="utf-8")
    assert "przywrocono" in dziennik
    assert "Jan Kowalski" not in dziennik and "44051401359" not in dziennik


@pytest.mark.anyio
async def test_przywroc_zly_identyfikator_w_polu_422_a_nie_500(konfig_api):
    # id spoza [a-f0-9]{32} w polu formularza: 422, nie 500 (walidacja magazynu)
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        bez_dopisku = _wynik_txt(identyfikator, czesci).split("\n", 1)[1]
        przywroc = await klient.post(
            "/api/przywroc",
            data={"tekst": bez_dopisku, "identyfikator": "krotki"},
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 422
    assert "identyfikator" in przywroc.json()["blad"]


@pytest.mark.anyio
async def test_przywroc_wiele_kandydatow_lista_dotyczy_kandydatow(konfig_api):
    # 422 z wieloma kandydatami pokazuje metadane TYLKO pasujących map, nie całego magazynu
    app = create_app(konfig_api, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz, czesci = await _ukryj(klient, app)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        bez_dopisku = _wynik_txt(identyfikator, czesci).split("\n", 1)[1]
        await _ukryj(klient, app)  # druga pasująca
        _, _czesci_3 = await _ukryj(klient, app, "Inny tekst bez wspolnych znacznikow. PESEL 44051401359.")
        przywroc = await klient.post(
            "/api/przywroc", data={"tekst": bez_dopisku}, headers=_naglowki(app)
        )
    assert przywroc.status_code == 422
    kandydaci = przywroc.json()["kandydaci"]
    assert len(kandydaci) == 2  # trzecia mapa (inny zestaw znaczników) nie jest kandydatem
