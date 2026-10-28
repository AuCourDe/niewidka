"""Testy API FastAPI (K4, LLD §12): ukryj/przywroc/stan, token sesji, limity, kolejka.

Testy bez wag: detektor (reguły albo atrapa) wstrzyknięty przez zależność.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import threading
import time
import zipfile

import httpx
import pytest

from narzedzia.generator_dokumentow import zapisz_podstawowy
from niewidka.api import create_app
from niewidka.detektory import RegulyDetektor
from niewidka.konfig import Konfig
from niewidka.model import TypEncji

KLUCZ = bytes(range(32))
TEKST = "Jan Kowalski, PESEL 44051401359. Telefon +48 601 234 567, e-mail jan@example.com."


@pytest.fixture()
def klucz_plik(tmp_path):
    sciezka = tmp_path / "klucz.b64"
    sciezka.write_bytes(base64.b64encode(KLUCZ))
    sciezka.chmod(0o600)
    return str(sciezka)


@pytest.fixture()
def konfig(klucz_plik):
    return Konfig(klucz_plik=klucz_plik, max_rozmiar_mb=1, max_rozpakowane_mb=200)


def _klient(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{app.state.konfig.port}"
    )


def _naglowki(app, **dodatkowe) -> dict:
    return {"X-Niewidka-Token": app.state.token, **dodatkowe}


async def _ukryj_tekst(klient, app, tekst: str = TEKST):
    return await klient.post(
        "/api/ukryj", data={"tekst": tekst, "poziom": "1"}, headers=_naglowki(app)
    )


def _zip(dane: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(dane)) as paczka:
        return {nazwa: paczka.read(nazwa) for nazwa in paczka.namelist()}


@pytest.mark.anyio
async def test_ukryj_txt_zip_z_mapa_i_naglowkami(konfig):
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await _ukryj_tekst(klient, app)
    assert odpowiedz.status_code == 200
    assert odpowiedz.headers["content-type"] == "application/zip"
    assert odpowiedz.headers["cache-control"] == "no-store"
    identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
    czesci = _zip(odpowiedz.content)
    assert f"ZANONIMIZOWANY_{identyfikator[:12]}.txt" in czesci
    assert f"{identyfikator[:12]}.nwidka" in czesci
    wynik_txt = czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.txt"]
    assert b"[PESEL_1]" in wynik_txt and b"44051401359" not in wynik_txt
    statystyki = json.loads(odpowiedz.headers["x-niewidka-statystyki"])
    assert statystyki["PESEL"] == 1
    assert "x-niewidka-status" in odpowiedz.headers
    assert "x-niewidka-ostrzezenia" in odpowiedz.headers


@pytest.mark.anyio
async def test_ukryj_przywroc_txt_roundtrip(konfig):
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await _ukryj_tekst(klient, app)
        czesci = _zip(odpowiedz.content)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        przywroc = await klient.post(
            "/api/przywroc",
            files={
                "wynik": (f"ZANONIMIZOWANY_{identyfikator[:12]}.txt", czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.txt"]),
                "mapa": (f"{identyfikator[:12]}.nwidka", czesci[f"{identyfikator[:12]}.nwidka"]),
            },
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 200
    assert przywroc.content == TEKST.encode()
    rozbieznosci = json.loads(przywroc.headers["x-niewidka-rozbieznosci"])
    assert rozbieznosci == []


@pytest.mark.anyio
async def test_ukryj_przywroc_txt_po_przestawieniu_zdan(konfig):
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await _ukryj_tekst(klient, app, "Jan Kowalski wniósł. PESEL 44051401359 sprawdzono.")
        czesci = _zip(odpowiedz.content)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        wynik = czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.txt"].decode()
        dopisek, tresc = wynik.split("\n", 1)
        zdania = tresc.strip().split(". ")
        przestawione = f"{dopisek}\n{zdania[1]} {zdania[0]}.\n".encode()
        przywroc = await klient.post(
            "/api/przywroc",
            files={
                "wynik": (f"ZANONIMIZOWANY_{identyfikator[:12]}.txt", przestawione),
                "mapa": (f"{identyfikator[:12]}.nwidka", czesci[f"{identyfikator[:12]}.nwidka"]),
            },
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 200
    assert "44051401359" in przywroc.content.decode()
    assert "[PESEL_1]" not in przywroc.content.decode()


@pytest.mark.anyio
async def test_ukryj_przywroc_docx_roundtrip(konfig, tmp_path):
    app = create_app(konfig, detektor=RegulyDetektor())
    dane = zapisz_podstawowy(tmp_path / "umowa.docx").read_bytes()
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"poziom": "1"},
            files={"plik": ("umowa.docx", dane)},
            headers=_naglowki(app),
        )
        assert odpowiedz.status_code == 200
        czesci = _zip(odpowiedz.content)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        przywroc = await klient.post(
            "/api/przywroc",
            files={
                "wynik": (f"ZANONIMIZOWANY_{identyfikator[:12]}.docx", czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.docx"]),
                "mapa": (f"{identyfikator[:12]}.nwidka", czesci[f"{identyfikator[:12]}.nwidka"]),
            },
            headers=_naglowki(app),
        )
    assert przywroc.status_code == 200
    from niewidka.formaty import adapter_formatu

    teksty = "\n".join(s.tekst for s in adapter_formatu("docx").wczytaj(przywroc.content).segmenty)
    assert "44051401359" in teksty
    assert "[PESEL_1]" not in teksty
    assert "ZANONIMIZOWANO" not in teksty


@pytest.mark.anyio
async def test_mapa_bez_klucza_nie_odszyfrowuje_500(monkeypatch):
    from niewidka.klucze import BrakKlucza

    monkeypatch.setattr(
        "niewidka.api.pobierz_klucz",
        lambda konfig: (_ for _ in ()).throw(BrakKlucza("brak klucza mapy")),
    )
    konfig = Konfig(klucz_plik=None)
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/przywroc",
            files={"wynik": ("w.txt", b"x"), "mapa": ("m.nwidka", b"NWID\x01" + bytes(20))},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 500
    assert "klucz" in odpowiedz.json()["blad"]


@pytest.mark.anyio
async def test_zly_klucz_422(klucz_plik, tmp_path):
    app_nadawca = create_app(Konfig(klucz_plik=klucz_plik), detektor=RegulyDetektor())
    inny_klucz = tmp_path / "inny.b64"
    inny_klucz.write_bytes(base64.b64encode(bytes(range(32, 64))))
    inny_klucz.chmod(0o600)
    app_odbiorca = create_app(Konfig(klucz_plik=str(inny_klucz)), detektor=RegulyDetektor())
    async with _klient(app_nadawca) as klient:
        odpowiedz = await _ukryj_tekst(klient, app_nadawca)
    czesci = _zip(odpowiedz.content)
    identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
    async with _klient(app_odbiorca) as klient:
        wynik = await klient.post(
            "/api/przywroc",
            files={
                "wynik": ("w.txt", czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.txt"]),
                "mapa": ("m.nwidka", czesci[f"{identyfikator[:12]}.nwidka"]),
            },
            headers=_naglowki(app_odbiorca),
        )
    assert wynik.status_code == 422  # zły klucz = zły tag GCM


@pytest.mark.anyio
async def test_zmieniony_bajt_mapy_422(konfig):
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await _ukryj_tekst(klient, app)
        czesci = _zip(odpowiedz.content)
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        mapa = bytearray(czesci[f"{identyfikator[:12]}.nwidka"])
        mapa[-1] ^= 0x01
        wynik = await klient.post(
            "/api/przywroc",
            files={
                "wynik": ("w.txt", czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.txt"]),
                "mapa": ("m.nwidka", bytes(mapa)),
            },
            headers=_naglowki(app),
        )
    assert wynik.status_code == 422


@pytest.mark.anyio
async def test_niezgodny_identyfikator_422(klucz_plik):
    """Mapa z innej sesji (ten sam klucz) = cudze personaliów — odrzucenie (Astra pkt 3)."""
    app_nadawca = create_app(Konfig(klucz_plik=klucz_plik), detektor=RegulyDetektor())
    app_odbiorca = create_app(Konfig(klucz_plik=klucz_plik), detektor=RegulyDetektor())  # świeża sesja
    async with _klient(app_nadawca) as klient:
        pierwsza = await _ukryj_tekst(klient, app_nadawca)
        czesci_1 = _zip(pierwsza.content)
        id_1 = pierwsza.headers["x-niewidka-identyfikator"]
        druga = await _ukryj_tekst(klient, app_nadawca, "PESEL 55010101234 i telefon 700 800 900.")
        id_2 = druga.headers["x-niewidka-identyfikator"]
        assert id_1 != id_2
    async with _klient(app_odbiorca) as klient:
        wynik = await klient.post(
            "/api/przywroc",
            files={
                "wynik": ("w.txt", czesci_1[f"ZANONIMIZOWANY_{id_1[:12]}.txt"]),
                "mapa": ("m.nwidka", _zip(druga.content)[f"{id_2[:12]}.nwidka"]),
            },
            headers=_naglowki(app_odbiorca),
        )
    assert wynik.status_code == 422
    assert wynik.json()["blad"]  # mapa z innej sesji odrzucona (komunikat bez treści mapy)


@pytest.mark.anyio
async def test_pelna_kolejka_503(klucz_plik):
    konfig = Konfig(klucz_plik=klucz_plik, kolejka=0, timeout_s=15)
    brama = threading.Event()

    class WolnyDetektor:
        nazwa = "wolny"
        typy = frozenset({TypEncji.INNE})

        def znajdz(self, tekst):
            brama.set()
            time.sleep(0.5)
            return []

    app = create_app(konfig, detektor=WolnyDetektor())
    async with _klient(app) as klient:
        pierwsze = asyncio.create_task(
            klient.post("/api/ukryj", data={"tekst": TEKST}, headers=_naglowki(app))
        )
        await asyncio.to_thread(brama.wait)  # pierwsze zajęło jedyny slot
        drugie = await klient.post("/api/ukryj", data={"tekst": TEKST}, headers=_naglowki(app))
        assert drugie.status_code == 503
        assert "retry-after" in drugie.headers
        assert (await pierwsze).status_code == 200


@pytest.mark.anyio
async def test_za_duzy_plik_413_przed_buforowaniem(konfig):
    app = create_app(konfig, detektor=RegulyDetektor())  # limit 1 MB z konfig
    async with _klient(app) as klient:
        odpowiedz = await klient.post("/api/ukryj", data={"tekst": "x" * (2 * 1024 * 1024)}, headers=_naglowki(app))
    assert odpowiedz.status_code == 413


@pytest.mark.anyio
async def test_zip_bomb_413_po_dekompresji(klucz_plik, tmp_path):
    konfig = Konfig(klucz_plik=klucz_plik, max_rozpakowane_mb=1)
    app = create_app(konfig, detektor=RegulyDetektor())
    # poprawny docx + doklejony mocno kompresowalny wpis (rozpakowany > limit 1 MB)
    wzorzec = zapisz_podstawowy(tmp_path / "w.docx").read_bytes()
    dane = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(wzorzec)) as zrodlo, zipfile.ZipFile(dane, "w", zipfile.ZIP_DEFLATED) as cel:
        for nazwa in zrodlo.namelist():
            cel.writestr(nazwa, zrodlo.read(nazwa))
        cel.writestr("word/pompa.xml", "a" * (2 * 1024 * 1024))
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj", data={"poziom": "1"}, files={"plik": ("duzy.docx", dane.getvalue())}, headers=_naglowki(app)
        )
    assert odpowiedz.status_code == 413


@pytest.mark.anyio
async def test_zly_format_415(konfig):
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"poziom": "1"},
            files={"plik": ("prezentacja.pptx", b"PK\x03\x04")},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 415
    assert "txt" in odpowiedz.json()["blad"] and "docx" in odpowiedz.json()["blad"]


@pytest.mark.anyio
async def test_brak_tokenu_403(konfig):
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        bez_tokenu = await klient.post("/api/ukryj", data={"tekst": TEKST})
        zly_token = await klient.post(
            "/api/ukryj", data={"tekst": TEKST}, headers={"X-Niewidka-Token": "zly"}
        )
    assert bez_tokenu.status_code == 403
    assert zly_token.status_code == 403


@pytest.mark.anyio
async def test_zly_origin_403(konfig):
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"tekst": TEKST},
            headers=_naglowki(app, Origin="http://zlosliwy.example"),
        )
    assert odpowiedz.status_code == 403


@pytest.mark.anyio
async def test_stan_bez_tokenu(konfig):
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await klient.get("/api/stan")
    assert odpowiedz.status_code == 200
    stan = odpowiedz.json()
    assert stan["wersja"]
    assert "reguly" in stan["modele"]
    assert stan["poziom"] == konfig.poziom
    assert stan["poziomy"] == [1, 2, 3]  # dostępne poziomy suwaka (K2d wpięte do produktu)
    assert isinstance(stan["r95"], dict)  # R95 per poziom dla interfejsu
    assert stan["limity"]["rozmiar_mb"] == konfig.max_rozmiar_mb
    assert stan["kolejka"]["maks"] == konfig.kolejka
    assert app.state.token not in odpowiedz.text  # token nie wycieka przez stan


@pytest.mark.anyio
async def test_blad_detektora_fail_closed_500_bez_tresci_w_logach(konfig, caplog):
    class Padajacy:
        nazwa = "padajacy"
        typy = frozenset({TypEncji.INNE})

        def znajdz(self, tekst):
            raise RuntimeError("symulowana awaria modelu")

    app = create_app(konfig, detektor=Padajacy())
    with caplog.at_level(logging.ERROR, logger="niewidka.api"):
        async with _klient(app) as klient:
            odpowiedz = await _ukryj_tekst(klient, app)
    assert odpowiedz.status_code == 500
    identyfikator_bledu = odpowiedz.json()["blad"]
    assert len(identyfikator_bledu) == 32  # UUID błędu, nie traceback
    assert "symulowana awaria" not in odpowiedz.text
    # logi bez treści dokumentu i bez klucza (Gemini pkt 15)
    assert "Jan Kowalski" not in caplog.text
    assert "44051401359" not in caplog.text
    assert base64.b64encode(KLUCZ).decode() not in caplog.text
    assert identyfikator_bledu in caplog.text


@pytest.mark.model
@pytest.mark.anyio
async def test_ukryj_poziom_suwa_dzialanie_detektora(katalog_modeli, klucz_plik):
    """Suwak poziomów zmienia detekcję w API (WYNIK-K2d, osoba-011): poziom 1 zostawia
    „Piotrowi", poziom 2 maskuje pełne „Piotrowi Wiśniewskiemu"; R95 raportowane per poziom.
    """
    from niewidka.mapa import odszyfruj

    konfig = Konfig(klucz_plik=klucz_plik, modele_katalog=katalog_modeli)
    app = create_app(konfig)  # produkcja: bez wstrzyknięcia, detektory per poziom
    tekst = "Przekazano akt do Piotrowi Wiśniewskiemu."
    async with _klient(app) as klient:
        r1 = await klient.post(
            "/api/ukryj", data={"tekst": tekst, "poziom": "1"}, headers=_naglowki(app)
        )
        r2 = await klient.post(
            "/api/ukryj", data={"tekst": tekst, "poziom": "2"}, headers=_naglowki(app)
        )
    assert r1.status_code == r2.status_code == 200
    assert set(app.state.detektory) == {1, 2}  # leniwy cache per poziom

    def oryginaly(odpowiedz):
        identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
        mapa = odszyfruj(_zip(odpowiedz.content)[f"{identyfikator[:12]}.nwidka"], KLUCZ)
        return [wyst.oryginal for wyst in mapa.wystapienia]

    assert oryginaly(r2) == ["Piotrowi Wiśniewskiemu"]
    # kontrola słusznie BLOKUJE poziom 1 (zostawił „Wiśniewskiemu") — K4b pkt 1:
    # 422 z typami, bez dokumentu i bez mapy; poziom 2 czysty
    assert r1.status_code == 422
    assert r1.json()["typy"] == {"OSOBA": 1}
    assert not r1.content.startswith(b"PK")
    assert r2.headers["x-niewidka-status"] == "ukonczony"
    r95_poziom2 = json.loads(r2.headers["x-niewidka-r95"])
    assert isinstance(r95_poziom2.get("OSOBA"), float)
