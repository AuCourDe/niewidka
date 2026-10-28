"""Testy webu lokalnego (K5, LLD §13): strona serwowana przez api.py, token w treści.

Strona z tokenem sesji w meta, zasoby (apka.js, styl.css, fonty) wyłącznie lokalne —
nic nie sięga po sieć, bo narzędzie ma działać na komputerze bez internetu.
"""

from __future__ import annotations

import re

import httpx
import pytest

from niewidka.api import create_app
from niewidka.detektory import RegulyDetektor
from niewidka.konfig import Konfig

KLUCZ = bytes(range(32))


@pytest.fixture()
def konfig(tmp_path):
    plik = tmp_path / "klucz.b64"
    import base64

    plik.write_bytes(base64.b64encode(KLUCZ))
    plik.chmod(0o600)
    return Konfig(klucz_plik=str(plik))


@pytest.fixture()
def app(konfig):
    return create_app(konfig, detektor=RegulyDetektor())


@pytest.fixture()
async def klient(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{app.state.konfig.port}"
    ) as klient:
        yield klient


@pytest.mark.anyio
async def test_strona_glowna_serwuje_html_z_tokenem(klient, app):
    odpowiedz = await klient.get("/")
    assert odpowiedz.status_code == 200
    assert "text/html" in odpowiedz.headers["content-type"]
    assert 'lang="pl"' in odpowiedz.text
    meta = re.search(r'<meta name="niewidka-token" content="([^"]*)"', odpowiedz.text)
    assert meta, "strona musi mieć meta niewidka-token"
    assert meta.group(1) == app.state.token


@pytest.mark.anyio
async def test_token_nie_leci_url_i_zasobami(klient, app):
    strona = (await klient.get("/")).text
    assert "token=" not in strona.lower().replace("niewidka-token", "")
    apka = (await klient.get("/apka.js")).text
    styl = (await klient.get("/styl.css")).text
    assert app.state.token not in apka
    assert app.state.token not in styl
    # zasoby referowane względnie — żądania idą na ten sam serwer, nigdy do internetu
    for sciezka in (strona, apka, styl):
        for wzorzec in (r'(src|href)\s*=\s*["\']https?://', r'url\(\s*["\']?https?://', r'@import\s+https?:'):
            assert not re.search(wzorzec, sciezka), f"zewnętrzny zasób w pliku web: {wzorzec}"


@pytest.mark.anyio
async def test_zasoby_statyczne_serwowane(klient):
    apka = await klient.get("/apka.js")
    styl = await klient.get("/styl.css")
    assert apka.status_code == 200
    assert "javascript" in apka.headers["content-type"] or apka.text.lstrip().startswith(("/*", "//", '"use strict"'))
    assert styl.status_code == 200
    assert "css" in styl.headers["content-type"]


@pytest.mark.anyio
async def test_strona_bez_tokenu_dostepna_i_bez_cache(klient):
    odpowiedz = await klient.get("/")
    assert odpowiedz.status_code == 200
    assert odpowiedz.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_fonty_lokalne_w_katalogu_web(klient):
    """Font wchodzi w repo (offline, bez CDN); żądanie o niego trafia w nasz serwer."""
    fonty = re.findall(r'@font-face\s*{[^}]*url\(["\']?([^)"\']+)', styl := (await klient.get("/styl.css")).text)
    assert fonty, "styl.css ma ładować font z katalogu web"
    for sciezka in fonty:
        assert sciezka.startswith("/") or not sciezka.startswith("http")
        odpowiedz = await klient.get(sciezka if sciezka.startswith("/") else f"/{sciezka}")
        assert odpowiedz.status_code == 200, f"brak fonta: {sciezka}"
    assert "font-family" in styl


@pytest.mark.anyio
async def test_strona_mieci_elementy_funkcjonalne(klient):
    strona = (await klient.get("/")).text
    for wyraz in (
        "Ukryj dane",
        "Przywróć dane",
        "Na tym urządzeniu",
        "Jakość wykrywania",
        "Szybko",
        "Najdokładniej",
        "aria-live",
        "mapa",
    ):
        assert wyraz in strona, f"brak na stronie: {wyraz}"


@pytest.mark.anyio
async def test_api_trasy_priorytet_przed_statycznymi(klient):
    odpowiedz = await klient.get("/api/stan")
    assert odpowiedz.status_code == 200
    assert odpowiedz.json()["wersja"]


@pytest.mark.anyio
async def test_bez_polpauz_i_pauz_w_tekstach(klient):
    """Zlecenie właściciela (12:55 / K5b): zero półpauz i pauz (– —) w tekstach
    widocznych dla użytkownika: strona, skrypt i dopisek w plikach wynikowych."""
    from niewidka.znaczniki import DOPISEK, dopisek

    for nazwa, tresc in (
        ("index.html", (await klient.get("/")).text),
        ("apka.js", (await klient.get("/apka.js")).text),
        ("dopisek", DOPISEK),
        ("dopisek z identyfikatorem", dopisek("abcdef")),
    ):
        for znak in ("–", "—"):
            assert znak not in tresc, f"zakazany znak {znak!r} w {nazwa}"


@pytest.mark.anyio
async def test_podglad_zwija_dopisek_a_ryzyko_przychodzi_z_serwera(klient):
    """K5c: dopisek z identyfikatorem mapy zwija się w podglądzie do
    „ZANONIMIZOWANY. …" (pełny zostaje w pliku wynikowym); etykiety ryzyka
    (w tym próg małej próby) podaje serwer w gotowym tekście."""
    apka = (await klient.get("/apka.js")).text
    assert "ZANONIMIZOWANY. …" in apka, "podgląd ma pokazywać skrócony dopisek"
    assert 'createElement("details")' in apka, "rozwinięcie dopisku ma być natywne"
    assert "podwyższone" not in apka, "etykieta ryzyka pochodzi z serwera (jakosc.py)"
