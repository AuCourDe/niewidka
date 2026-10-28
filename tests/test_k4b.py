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
_MB = 1024 * 1024


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


# --- pkt 2: obrazy usuwane, niezweryfikowane części binarne = blokada ----------

from niewidka.formaty import ElementNieobslugiwany
from niewidka.rdzen import ukryj


def test_pkt2_obrazy_usuwane_z_uwaga_w_raporcie():
    """K4b pkt 2: bez OCR obraz nie daje się sprawdzić — domyślnie USUWANY,
    w jego miejscu neutralny tekst, raport ma uwagę, status zostaje czysty."""
    wynik, _, raport = ukryj(
        _wzorzec_docx(), "docx", 1, detektor=RegulyDetektor(), max_rozpakowane_bajtow=200 * _MB
    )
    czesci = _zip(wynik)
    assert not [n for n in czesci if n.startswith("word/media/")], "obraz zostawiony w wyniku"
    assert "[OBRAZ USUNIĘTY]" in czesci["word/document.xml"].decode()
    assert any("OBRAZ" in uwaga for uwaga in raport.uwagi)
    assert raport.status == "ukonczony"  # usunięcie = uwaga, nie blokada


@pytest.mark.anyio
async def test_pkt2_niezweryfikowana_czesc_binarna_blokada(konfig):
    """K4b pkt 2: word/media/*.bin nie da się zweryfikować bez OCR ani skanu — blokada."""
    app = create_app(konfig, detektor=RegulyDetektor())
    dane = _docx_przebuduj(_wzorzec_docx(), dodaj={"word/media/skrytka.bin": b"\x00\x01\x02dane"})
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"poziom": "1"},
            files={"plik": ("umowa.docx", dane)},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 422


def test_pkt2_polityka_obrazow_z_konfiguracji():
    """K4b pkt 2: polityka obrazów konfigurowalna — „zostaw" zachowuje obraz,
    ale raport ostrzega; „blokuj" podnosi ElementNieobslugiwany."""
    wynik, _, raport = ukryj(
        _wzorzec_docx(),
        "docx",
        1,
        detektor=RegulyDetektor(),
        max_rozpakowane_bajtow=200 * _MB,
        polityka_obrazow="zostaw",
    )
    assert [n for n in _zip(wynik) if n.startswith("word/media/")], "polityka zostaw straciła obraz"
    assert any("OBRAZ" in uwaga for uwaga in raport.uwagi)
    with pytest.raises(ElementNieobslugiwany):
        ukryj(
            _wzorzec_docx(),
            "docx",
            1,
            detektor=RegulyDetektor(),
            polityka_obrazow="blokuj",
        )


def test_pkt2_konfig_wcztuje_polityke_obrazow():
    from niewidka.konfig import wczytaj_konfig

    assert wczytaj_konfig(env={"NIEWIDKA_OBRAZY": "zostaw"}).obrazy == "zostaw"
    assert wczytaj_konfig(env={}).obrazy == "usun"
    with pytest.raises(ValueError, match="NIEWIDKA_OBRAZY"):
        wczytaj_konfig(env={"NIEWIDKA_OBRAZY": "czarodziejka"})


# --- pkt 3: skan także e.tail (itertext) ---------------------------------------


def test_pkt3_pesel_w_ogonie_xml_blokuje():
    """K4b pkt 3: PESEL w ogonku elementu (tekst ZA znacznikiem) omijał skan."""
    from niewidka.kontrola import kontroluj

    dane = _docx_przebuduj(
        _wzorzec_docx(),
        dodaj={"word/theme/proba.xml": b"<?xml version='1.0'?><root><node/>55010101234</root>"},
    )
    uwagi = kontroluj(dane, "umowa.docx", RegulyDetektor())
    assert any(
        u.typ == "PESEL" and u.czesc == "word/theme/proba.xml" for u in uwagi
    ), f"skan nie widzi ogonka elementu: {uwagi}"


# --- pkt 4: błąd parsowania zachowanej części XML = blokada (fail-closed) ------


def test_pkt4_nieprawidlowy_xml_zachowanej_czesci_blokuje():
    """K4b pkt 4: niedomknięty XML w zachowywanej części to fail-closed,
    nie ciche „continue" — treści, której nie da się przeskanować, nie wysyłamy."""
    from niewidka.kontrola import kontroluj

    dane = _docx_przebuduj(
        _wzorzec_docx(),
        dodaj={"word/theme/proba.xml": b"<?xml version='1.0'?><root>55010101234"},
    )
    uwagi = kontroluj(dane, "umowa.docx", RegulyDetektor())
    assert any(
        u.typ == "XML_NIEPRAWIDLOWY" and u.czesc == "word/theme/proba.xml" for u in uwagi
    ), f"błąd parsowania przeszedł cicho: {uwagi}"


# --- pkt 5: skan nazw części ZIP + neutralizacja nazw media ---------------------


def _docx_z_media_o_pieselowej_nazwie() -> bytes:
    """Wzorzec z obrazem przemianowanym na word/media/44051401359.png (rels zgodnie)."""
    zrodlo = zipfile.ZipFile(io.BytesIO(_wzorzec_docx()))
    czesci = {n: zrodlo.read(n) for n in zrodlo.namelist()}
    zrodlo.close()
    stara = next(n for n in czesci if n.startswith("word/media/"))
    nowa = f"word/media/{PESEL}.png"
    czesci[nowa] = czesci.pop(stara)
    for nazwa in [n for n in czesci if n.endswith(".rels")]:
        if stara.rpartition("/")[2] in czesci[nazwa].decode():
            czesci[nazwa] = czesci[nazwa].replace(
                stara.rpartition("/")[2].encode(), nowa.rpartition("/")[2].encode()
            )
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
        for nazwa, zawartosc in czesci.items():
            paczka.writestr(nazwa, zawartosc)
    return bufor.getvalue()


def test_pkt5_pii_w_nazwie_czesci_blokuje():
    """K4b pkt 5: kontrola skanuje też NAZWY części — PESEL w nazwie = znalezisko."""
    from niewidka.kontrola import kontroluj

    dane = _docx_przebuduj(
        _wzorzec_docx(), dodaj={"word/theme/44051401359.xml": b"<?xml version='1.0'?><root/>"}
    )
    uwagi = kontroluj(dane, "umowa.docx", RegulyDetektor())
    assert any(
        u.typ == "NAZWA_CZESCI" and u.czesc == "word/theme/44051401359.xml" for u in uwagi
    ), f"nazwa części bez skanu: {uwagi}"


def test_pkt5_media_przemianowane_a_relacje_zaktualizowane():
    """K4b pkt 5: nazwa media z PII znika z wyniku; obraz zostaje pod neutralną
    nazwą, relacja wskazuje nowy cel, dokument otwiera się adapterem."""
    from niewidka.formaty import adapter_dla

    wynik, _, _ = ukryj(
        _docx_z_media_o_pieselowej_nazwie(),
        "docx",
        1,
        detektor=RegulyDetektor(),
        max_rozpakowane_bajtow=200 * _MB,
        polityka_obrazow="zostaw",
    )
    czesci = _zip(wynik)
    nazwy = list(czesci)
    assert not [n for n in nazwy if PESEL in n], f"PII w nazwie części wyniku: {nazwy}"
    media = [n for n in nazwy if n.startswith("word/media/")]
    assert media, "obraz zniknął mimo polityki zostaw"
    rels = czesci["word/_rels/document.xml.rels"].decode()
    assert media[0].rpartition("/")[2] in rels, "relacja nie wskazuje przemianowanego obrazu"
    adapter_dla("w.docx").wczytaj(wynik)  # wynik pozostaje poprawnym DOCX


# --- pkt 6: przywracanie wiąże mapę z KONKRETNYM dokumentem ---------------------


@pytest.mark.anyio
async def test_pkt6_mapa_z_innego_dokumentu_tej_sesji_422(konfig):
    """K4b pkt 6: mapa B podsunięta do wyniku A (obie z tej samej sesji, więc stara
    kontrola identyfikatorów przechodzi) = 422, nigdy przywrócenie cudzych danych."""
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        a = await klient.post(
            "/api/ukryj", data={"tekst": "PESEL 44051401359.", "poziom": "1"}, headers=_naglowki(app)
        )
        b = await klient.post(
            "/api/ukryj", data={"tekst": "PESEL 55010101234.", "poziom": "1"}, headers=_naglowki(app)
        )
        czesci_a, czesci_b = _zip(a.content), _zip(b.content)
        id_a = a.headers["x-niewidka-identyfikator"]
        id_b = b.headers["x-niewidka-identyfikator"]
        wynik = await klient.post(
            "/api/przywroc",
            files={
                "wynik": (f"ZANONIMIZOWANY_{id_a}.txt", czesci_a[f"ZANONIMIZOWANY_{id_a}.txt"]),
                "mapa": ("m.nwidka", czesci_b[f"{id_b}.nwidka"]),
            },
            headers=_naglowki(app),
        )
    assert wynik.status_code == 422
    assert "55010101234" not in wynik.text  # cudze dane nie wróciły


def test_pkt6_dopisek_zawiera_identyfikator():
    """Identyfikator mapy zapisany w treści wyniku (dopisek) — o nim wiązanie."""
    from niewidka.rdzen import ukryj
    from niewidka.znaczniki import DOPISEK

    wynik, mapa, _ = ukryj(b"PESEL 44051401359.", "txt", 1, detektor=RegulyDetektor())
    assert mapa.identyfikator in wynik.decode()
    assert wynik.decode().startswith(DOPISEK)

