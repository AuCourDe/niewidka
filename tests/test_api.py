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
from niewidka import api
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
    assert "ZANONIMIZOWANY" not in teksty


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
async def test_stan_wymaga_tokenu_a_z_tokenu_ma_pola(konfig):
    """K7c pkt 5 (audyt): GET /api/stan pilnuje tokenu jak POST-y."""
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        assert (await klient.get("/api/stan")).status_code == 403
        odpowiedz = await klient.get("/api/stan", headers=_naglowki(app))
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
    """Suwak poziomów zmienia detekcję w API. Korekta K7c: wagi produktu to
    teraz bardsai Q4 bl32 z zaufanego pakiety.json (pkt 2/3) — Q4 na poziomie 1
    łapie cały „Piotrowi Wiśniewskiemu" (próbka osoba-011 z K2d mierzona była
    na INT8), więc różnicującą próbką jest inst-061 z korpusu: słownik imion
    poziomu 3 dodaje „Adama Mickiewicza", poziom 1 go pomija."""
    from niewidka.mapa import odszyfruj

    konfig = Konfig(klucz_plik=klucz_plik, modele_katalog=katalog_modeli)
    app = create_app(konfig)  # produkcja: bez wstrzyknięcia, detektory per poziom
    tekst = "Muzeum im. Adama Mickiewicza zaprasza."
    async with _klient(app) as klient:
        r1 = await klient.post(
            "/api/ukryj", data={"tekst": tekst, "poziom": "1"}, headers=_naglowki(app)
        )
        r3 = await klient.post(
            "/api/ukryj", data={"tekst": tekst, "poziom": "3"}, headers=_naglowki(app)
        )
    assert r1.status_code == 200 and r3.status_code == 200
    assert {p for p, _ in app.state.detektory} == {1, 3}  # leniwy cache per poziom
    assert "OSOBA" not in json.loads(r1.headers["x-niewidka-statystyki"])
    assert json.loads(r3.headers["x-niewidka-statystyki"])["OSOBA"] == 1
    identyfikator = r3.headers["x-niewidka-identyfikator"]
    mapa = odszyfruj(_zip(r3.content)[f"{identyfikator[:12]}.nwidka"], KLUCZ)
    assert [wyst.oryginal for wyst in mapa.wystapienia] == ["Adama Mickiewicza"]


# --- K7b: pakiety modeli przez API -------------------------------------------

import json as _json

from niewidka.pakiety import MenedzerPakietow, wczytaj_pakiety


def _pakiet_testowy(tmp_path):
    """Katalog pakietów z hashami TREŚCI TESTOWYCH + lustro HTTPX w pamięci."""
    import hashlib

    tresci = {}
    pliki = []
    for zrodlo in ("podstawowy-model.onnx", "podstawowy-tokenizer.json"):
        tresc = f"tresc-{zrodlo}".encode()
        tresci[zrodlo] = tresc
        pliki.append(
            {
                "nazwa": zrodlo.replace("podstawowy-", ""),
                "zrodlo": zrodlo,
                "rozmiar": len(tresc),
                "sha256": hashlib.sha256(tresc).hexdigest(),
            }
        )
    dane = {
        "pakiety": [
            {
                "id": "podstawowy",
                "nazwa": "Podstawowy",
                "opis": "testowy",
                "wymagany": True,
                "poziomy": [1, 2, 3],
                "katalog_rel": "",
                "pliki": pliki,
            }
        ]
    }
    plik = tmp_path / "pakiety.json"
    plik.write_text(_json.dumps(dane), encoding="utf-8")
    return plik, tresci


def _menedzer_testowy(tmp_path):
    plik, tresci = _pakiet_testowy(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        nazwa = str(request.url).rsplit("/", 1)[-1]
        if nazwa not in tresci:
            return httpx.Response(404)
        return httpx.Response(200, content=tresci[nazwa])

    return MenedzerPakietow(
        wczytaj_pakiety(plik),
        tmp_path / "modele",
        "http://x/",
        klient=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.anyio
async def test_pakiety_get_stan_i_poziomy(konfig, tmp_path):
    app = create_app(
        konfig, detektor=RegulyDetektor(), menedzer_pakietow=_menedzer_testowy(tmp_path)
    )
    async with _klient(app) as klient:
        odpowiedz = await klient.get("/api/pakiety", headers=_naglowki(app))
    assert odpowiedz.status_code == 200
    dane = odpowiedz.json()
    assert [p["id"] for p in dane["pakiety"]] == ["podstawowy"]
    assert dane["pakiety"][0]["stan"] == "brak"
    assert dane["poziomy_dostepne"] == []


@pytest.mark.anyio
async def test_pakiety_post_wymaga_tokenu_i_hosta(konfig, tmp_path):
    app = create_app(
        konfig, detektor=RegulyDetektor(), menedzer_pakietow=_menedzer_testowy(tmp_path)
    )
    async with _klient(app) as klient:
        assert (await klient.post("/api/pakiety", json={"akcja": "pobierz", "pakiet": "podstawowy"})).status_code == 403
        assert (
            await klient.post(
                "/api/pakiety",
                json={"akcja": "pobierz", "pakiet": "podstawowy"},
                headers={"X-Niewidka-Token": app.state.token, "host": "zly.example"},
            )
        ).status_code == 403


@pytest.mark.anyio
async def test_pakiety_post_pobierz_usun(konfig, tmp_path):
    menedzer = _menedzer_testowy(tmp_path)
    app = create_app(konfig, detektor=RegulyDetektor(), menedzer_pakietow=menedzer)
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/pakiety",
            json={"akcja": "pobierz", "pakiet": "podstawowy"},
            headers=_naglowki(app),
        )
        assert odpowiedz.status_code == 202
        menedzer.czekaj()
        stan = (await klient.get("/api/pakiety", headers=_naglowki(app))).json()
        assert stan["pakiety"][0]["stan"] == "zainstalowany"
        assert stan["poziomy_dostepne"] == [1, 2, 3]
        odpowiedz = await klient.post(
            "/api/pakiety",
            json={"akcja": "usun", "pakiet": "podstawowy"},
            headers=_naglowki(app),
        )
        assert odpowiedz.status_code == 200
        stan = (await klient.get("/api/pakiety", headers=_naglowki(app))).json()
        assert stan["pakiety"][0]["stan"] == "brak"


@pytest.mark.anyio
async def test_pakiety_post_nieznane_wartosci_422(konfig, tmp_path):
    app = create_app(
        konfig, detektor=RegulyDetektor(), menedzer_pakietow=_menedzer_testowy(tmp_path)
    )
    async with _klient(app) as klient:
        assert (
            await klient.post(
                "/api/pakiety", json={"akcja": "pobierz", "pakiet": "nie-ma"}, headers=_naglowki(app)
            )
        ).status_code == 422
        assert (
            await klient.post(
                "/api/pakiety", json={"akcja": "wskocz"}, headers=_naglowki(app)
            )
        ).status_code == 422


@pytest.mark.anyio
async def test_pakiety_post_pobierz_w_toku_409(konfig, tmp_path):
    menedzer = _menedzer_testowy(tmp_path)
    menedzer._w_toku = True  # symulacja pobierania w toku
    app = create_app(konfig, detektor=RegulyDetektor(), menedzer_pakietow=menedzer)
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/pakiety",
            json={"akcja": "pobierz", "pakiet": "podstawowy"},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 409


@pytest.mark.anyio
async def test_pakiety_instaluj_offline_z_katalogu(konfig, tmp_path):
    plik, tresci = _pakiet_testowy(tmp_path)
    lustro = tmp_path / "lustro"
    lustro.mkdir()
    for zrodlo, tresc in tresci.items():
        (lustro / zrodlo).write_bytes(tresc)
    menedzer = MenedzerPakietow(
        wczytaj_pakiety(plik), tmp_path / "modele", "http://x/", klient=httpx.Client()
    )
    app = create_app(konfig, detektor=RegulyDetektor(), menedzer_pakietow=menedzer)
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/pakiety",
            json={"akcja": "instaluj", "pakiet": "podstawowy", "katalog": str(lustro)},
            headers=_naglowki(app),
        )
        assert odpowiedz.status_code == 202  # K7c pkt 8: instalacja w tle
        menedzer.czekaj()
        stan = (await klient.get("/api/pakiety", headers=_naglowki(app))).json()
        assert stan["pakiety"][0]["stan"] == "zainstalowany"
        # zły katalog: błąd operacji w tle w postep.blad, bez treści plików
        odpowiedz = await klient.post(
            "/api/pakiety",
            json={"akcja": "instaluj", "pakiet": "podstawowy", "katalog": str(tmp_path / "pustka")},
            headers=_naglowki(app),
        )
        assert odpowiedz.status_code == 202
        menedzer.czekaj()
        assert "brak pliku" in (menedzer.postep.blad or "")


@pytest.mark.anyio
async def test_ukryj_bez_wymaganego_pakietu_409_jasny_blad(konfig, tmp_path):
    """Poziom bez wymaganego pakietu = jasny błąd (polecenie K7b pkt 3), nie 500."""
    app = create_app(konfig, detektor=None, menedzer_pakietow=_menedzer_testowy(tmp_path))
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"tekst": "Jan Kowalski, PESEL 44051401359.", "poziom": "2"},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 409
    assert odpowiedz.json()["brak_pakietu"] == ["podstawowy"]
    assert "Podstawowy" in odpowiedz.json()["blad"]


@pytest.mark.anyio
async def test_stan_z_pakietami_poziomy_dostepne(konfig, tmp_path):
    menedzer = _menedzer_testowy(tmp_path)
    app = create_app(konfig, detektor=RegulyDetektor(), menedzer_pakietow=menedzer)
    async with _klient(app) as klient:
        dane = (await klient.get("/api/stan", headers=_naglowki(app))).json()
        assert dane["poziomy_dostepne"] == []  # pakiet testowy nie zainstalowany
        menedzer.pobierz("podstawowy")
        menedzer.czekaj()
        dane = (await klient.get("/api/stan", headers=_naglowki(app))).json()
        assert dane["poziomy_dostepne"] == [1, 2, 3]


@pytest.mark.anyio
async def test_stan_bez_detektora_wstaje_i_mowi_o_braku(konfig, tmp_path):
    """K7b: łagodny start bez wag — /api/stan odpowiada, modele = [] (żywy bieg exe:
    None.nazwa wywalał endpoint na 500)."""
    app = create_app(konfig, detektor=None, menedzer_pakietow=_menedzer_testowy(tmp_path))
    async with _klient(app) as klient:
        odpowiedz = await klient.get("/api/stan", headers=_naglowki(app))
    assert odpowiedz.status_code == 200
    assert odpowiedz.json()["modele"] == []
    assert odpowiedz.json()["poziomy_dostepne"] == []


@pytest.mark.model
@pytest.mark.anyio
async def test_pakiet_rozszerzony_uczestniczy_w_anonimizacji_przez_api(
    katalog_modeli, klucz_plik, tmp_path
):
    """K7c pkt 1: zainstalowany pakiet Rozszerzony MUSI wykrywać LOGIN na poziomie 3,
    a zmiana stanu pakietów MUSI unieważnić cache detektorów (to samo app).
    Ścieżka przez API i menedżera pakietów, bez ręcznych flag (audyt #1: rdzeń
    nie przekazywał pakiet_rozszerzony=True i login zostawał w tekście)."""
    import shutil

    menedzer_katalog = tmp_path / "wagi"
    lustro = tmp_path / "lustro"
    lustro.mkdir()
    for pakiet in wczytaj_pakiety():
        for plik in pakiet.pliki:
            shutil.copyfile(katalog_modeli / plik.nazwa, lustro / plik.zrodlo)
    konfig = Konfig(klucz_plik=klucz_plik, modele_katalog=menedzer_katalog)
    menedzer = MenedzerPakietow(wczytaj_pakiety(), menedzer_katalog, "http://x/")
    app = create_app(konfig, menedzer_pakietow=menedzer)  # produkcja: detektory leniwe
    tekst = "Kontakt na czacie: stefan_wodorost."
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/pakiety",
            json={"akcja": "instaluj", "pakiet": "podstawowy", "katalog": str(lustro)},
            headers=_naglowki(app),
        )
        assert odpowiedz.status_code == 202  # K7c pkt 8: instalacja w tle
        menedzer.czekaj()
        bez = await klient.post(
            "/api/ukryj", data={"tekst": tekst, "poziom": "3"}, headers=_naglowki(app)
        )
        assert bez.status_code == 200
        assert json.loads(bez.headers["x-niewidka-statystyki"]).get("LOGIN", 0) == 0
        odpowiedz = await klient.post(
            "/api/pakiety",
            json={"akcja": "instaluj", "pakiet": "rozszerzony", "katalog": str(lustro)},
            headers=_naglowki(app),
        )
        assert odpowiedz.status_code == 202
        menedzer.czekaj()
        z = await klient.post(
            "/api/ukryj", data={"tekst": tekst, "poziom": "3"}, headers=_naglowki(app)
        )
    assert z.status_code == 200
    statystyki = json.loads(z.headers["x-niewidka-statystyki"])
    assert statystyki.get("LOGIN") == 1, f"login nieukryty mimo pakietu: {statystyki}"
    czesci = _zip(z.content)
    identyfikator = z.headers["x-niewidka-identyfikator"]
    wynik_txt = czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.txt"].decode()
    assert "stefan_wodorost" not in wynik_txt


@pytest.mark.anyio
async def test_get_pakiety_i_stan_wymagaja_tokenu_hosta_origin(konfig, tmp_path):
    """K7c pkt 5 (audyt): GET /api/pakiety ujawniał postep.blad (z hasłem lustra
    w URL) bez tokenu; teraz te GET-y pilnują tokenu i Host/Origin jak POST."""
    app = create_app(
        konfig, detektor=RegulyDetektor(), menedzer_pakietow=_menedzer_testowy(tmp_path)
    )
    async with _klient(app) as klient:
        assert (await klient.get("/api/pakiety")).status_code == 403
        assert (await klient.get("/api/stan")).status_code == 403
        assert (
            await klient.get("/api/pakiety", headers={"host": "obcy.example"})
        ).status_code == 403
        assert (
            await klient.get(
                "/api/stan", headers=_naglowki(app, Origin="http://zlosliwy.example")
            )
        ).status_code == 403
        assert (await klient.get("/api/pakiety", headers=_naglowki(app))).status_code == 200
        assert (await klient.get("/api/stan", headers=_naglowki(app))).status_code == 200


@pytest.mark.anyio
async def test_detektor_poziomu3_nie_zostaje_ze_starego_stanu_pakietu(
    konfig, tmp_path, monkeypatch
):
    """Odbiór K7c: cache detektorów był kluczowany samym poziomem. Detektor poziomu 3
    zbudowany zanim pierwsza weryfikacja SHA po starcie skończy się (stan „brak”)
    albo przy NIEWIDKA_POZIOM=3 zostawał bez LFM2.5, choć pakiet był zainstalowany,
    bo start nie zgłasza zmiany. Stan pakietu MUSI być częścią klucza cache."""
    from niewidka import api

    wywolania: list[bool] = []

    def falszywy(poziom, konfig, pakiet_rozszerzony=False):
        wywolania.append(pakiet_rozszerzony)
        return RegulyDetektor()

    monkeypatch.setattr(api, "zbuduj_detektor", falszywy)
    menedzer = _menedzer_testowy(tmp_path)
    stan = {"rozszerzony": "brak"}
    monkeypatch.setattr(menedzer, "stan_pakietu", lambda ident: stan.get(ident))
    app = create_app(
        Konfig(klucz_plik=konfig.klucz_plik, modele_katalog=tmp_path, poziom=3),
        menedzer_pakietow=menedzer,
    )
    async with _klient(app) as klient:
        dane = {"tekst": "Kontakt: stefan_wodorost.", "poziom": "3"}
        assert (await klient.post("/api/ukryj", data=dane, headers=_naglowki(app))).status_code == 200
        stan["rozszerzony"] = "zainstalowany"  # weryfikacja po starcie skończona, bez zwrotu zmiany
        assert (await klient.post("/api/ukryj", data=dane, headers=_naglowki(app))).status_code == 200
    assert wywolania[-1] is True, f"poziom 3 nadal bez pakietu Rozszerzonego: {wywolania}"


def test_bez_katalogu_modeli_detektor_i_menedzer_uzywaja_tej_samej_sciezki(monkeypatch, tmp_path):
    # przegląd Codex 2026-10-29 (P1): menedżer pobierał do katalogu domyślnego,
    # a detektor miał modele_katalog=None → po instalacji każde ukrycie 500
    monkeypatch.setattr(api, "katalog_modeli", lambda: tmp_path / "modele")
    app = api.create_app(Konfig(), detektor=None)
    assert app.state.konfig.modele_katalog == tmp_path / "modele"
    assert app.state.pakiety.katalog == tmp_path / "modele"


@pytest.mark.anyio
async def test_strona_glowna_nie_wydaje_tokenu_obcemu_hostowi(konfig):
    # przegląd Codex 2026-10-29: GET / z Host: evil.example zwracał token (DNS rebinding)
    app = create_app(konfig, detektor=RegulyDetektor())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://evil.example") as k:
        odpowiedz = await k.get("/")
    assert odpowiedz.status_code == 403
    assert app.state.token not in odpowiedz.text
