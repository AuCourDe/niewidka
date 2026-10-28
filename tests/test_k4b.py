"""K4b — naprawy 15 znalezisk audytu bezpieczeństwa (docs/konsultacje/06-przeglad-codex-astra-1.md).

Każdy test najpierw odtwarzał atak z audytu (RED), potem dostawał poprawkę (GREEN).
Kolejność sekcji = priorytet zlecenia K4b.
"""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from narzedzia.generator_dokumentow import zapisz_podstawowy
from niewidka.api import create_app
from niewidka.detektory import RegulyDetektor
from niewidka.konfig import Konfig

KLUCZ = bytes(range(32))
PESEL = "44051401359"


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


def _zip(dane: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(dane)) as paczka:
        return {nazwa: paczka.read(nazwa) for nazwa in paczka.namelist()}


# --- wspólne narzędzia DOCX ---------------------------------------------------


def _wzorzec_docx() -> bytes:
    return zapisz_podstawowy(Path("/tmp") / "niewidka-k4b-wzorzec.docx").read_bytes()


def _docx_przebuduj(dane: bytes, podmien: dict[str, bytes] | None = None, dodaj: dict[str, bytes] | None = None) -> bytes:
    """DOCX po przebudowie: podmiana istniejących części + dołożenie nowych."""
    zrodlo = zipfile.ZipFile(io.BytesIO(dane))
    czesci = {n: zrodlo.read(n) for n in zrodlo.namelist()}
    zrodlo.close()
    czesci.update(podmien or {})
    czesci.update(dodaj or {})
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
        for nazwa, zawartosc in czesci.items():
            paczka.writestr(nazwa, zawartosc)
    return bufor.getvalue()


def _theme_z_peselem(tresc: str | None = None) -> bytes:
    """Część word/theme/*.xml — allowlista ją zachowuje, adapter jej nie parsuje."""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">{tresc or PESEL}</theme>'
    ).encode()


def _docx_z_peselem_w_czesci() -> bytes:
    """Poprawny DOCX z PESEL-em w części, którą adapter zachowuje (word/theme/).
    PESEL inny niż w treści, żeby znalezisko pochodziło wyłącznie z ukrytej części."""
    return _docx_przebuduj(
        _wzorzec_docx(), dodaj={"word/theme/proba.xml": _theme_z_peselem("55010101234")}
    )


# --- pkt 1: blokada = brak dokumentu w odpowiedzi ------------------------------


@pytest.mark.anyio
async def test_pkt1_blokada_422_bez_dokumentu(konfig):
    """„Zablokowany" wynik nie wraca jako 200 z dokumentem (audyt pkt 1):
    422 z listą typów, bez fragmentów i bez jakichkolwiek bajtów dokumentu."""
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"poziom": "1"},
            files={"plik": ("umowa.docx", _docx_z_peselem_w_czesci())},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 422
    tresc = odpowiedz.json()
    assert tresc["status"] == "zablokowany"
    assert tresc["typy"] == {"PESEL": 1}  # typy + liczniki, zero fragmentów
    assert PESEL not in odpowiedz.text  # żadnych danych w odpowiedzi
    assert not odpowiedz.content.startswith(b"PK")  # żaden dokument nie wyleciał


def test_pkt1_ui_blokada_wylacza_pobieranie_i_kopiowanie():
    """UI: zablokowany wynik (422) pokazuje STOP i nie udostępnia pobrania ani
    schowka; stara ścieżka „200 + nagłówek x-niewidka-status" znika."""
    apka = (Path(__file__).parents[1] / "niewidka" / "web" / "apka.js").read_text(encoding="utf-8")
    assert 'status === "zablokowany"' in apka  # obsługa 422 zablokowanego
    assert "STOP" in apka
    assert '"x-niewidka-status"' not in apka  # wynik 200 nigdy nie jest zablokowany
