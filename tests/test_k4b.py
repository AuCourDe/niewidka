"""K4b — naprawy 15 znalezisk audytu bezpieczeństwa (docs/konsultacje/06-przeglad-codex-astra-1.md).

Każdy test najpierw odtwarzał atak z audytu (RED), potem dostawał poprawkę (GREEN).
Kolejność sekcji = priorytet zlecenia K4b.
"""

from __future__ import annotations

import asyncio
import base64
import io
import threading
import zipfile
from pathlib import Path

import httpx
import pytest

from narzedzia.generator_dokumentow import zapisz_podstawowy
from niewidka.api import create_app
from niewidka.detektory import RegulyDetektor
from niewidka.konfig import Konfig
from niewidka.model import TypEncji

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
                "wynik": (f"ZANONIMIZOWANY_{id_a[:12]}.txt", czesci_a[f"ZANONIMIZOWANY_{id_a[:12]}.txt"]),
                "mapa": ("m.nwidka", czesci_b[f"{id_b[:12]}.nwidka"]),
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
    from niewidka.znaczniki import zakoduj_identyfikator

    assert zakoduj_identyfikator(mapa.identyfikator) in wynik.decode()
    # identyfikator w dopisku bez ani jednej cyfry (cyfry tripały reguły numerów)
    id_w_tekscie = wynik.decode().split("mapy: ")[1].split(".")[0]
    assert id_w_tekscie and not any(znak.isdigit() for znak in id_w_tekscie)
    assert wynik.decode().startswith(DOPISEK)


# --- pkt 7: identyfikator ≥128 bit + rejestr skrótów wydanych szyfrogramów ------


def test_pkt7_identyfikator_ma_128_bit():
    _, mapa, _ = ukryj(b"PESEL 44051401359.", "txt", 1, detektor=RegulyDetektor())
    assert len(mapa.identyfikator) >= 32, "24-bitowy id pozwalał na kolizje starych map"
    int(mapa.identyfikator, 16)  # hex


@pytest.mark.anyio
async def test_pkt7_cudzy_szyfrogram_nie_odszyfrowuje(klucz_plik):
    """K4b pkt 7: sesja rejestruje skróty WYDANYCH szyfrogramów. Szyfrogram
    przechwycony z INNEJ sesji (nawet gdy atakujący wygrał kolizję identyfikatora —
    symulujemy to wpisem do zbioru sesji) nie podlega odszyfrowaniu."""
    app_nadawca = create_app(Konfig(klucz_plik=klucz_plik), detektor=RegulyDetektor())
    app_odbiorca = create_app(Konfig(klucz_plik=klucz_plik), detektor=RegulyDetektor())
    async with _klient(app_nadawca) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj", data={"tekst": "PESEL 44051401359.", "poziom": "1"}, headers=_naglowki(app_nadawca)
        )
    czesci = _zip(odpowiedz.content)
    identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
    szyfrogram = czesci[f"{identyfikator[:12]}.nwidka"]
    # kolizja "wygrana": identyfikator cudzej mapy jest w zbiorze sesji odbiorcy
    app_odbiorca.state.identyfikatory.add(identyfikator)
    async with _klient(app_odbiorca) as klient:
        wynik = await klient.post(
            "/api/przywroc",
            files={
                "wynik": ("w.txt", czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.txt"]),
                "mapa": ("m.nwidka", szyfrogram),
            },
            headers=_naglowki(app_odbiorca),
        )
    assert wynik.status_code == 422
    assert "44051401359" not in wynik.text


@pytest.mark.anyio
async def test_pkt7_krotki_id_w_nazwach_plikow(konfig):
    """Pełny identyfikator w nagłówku/mapie; w NAZWACH plików tylko krótki skrót."""
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj", data={"tekst": "PESEL 44051401359.", "poziom": "1"}, headers=_naglowki(app)
        )
    identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
    nazwy = list(_zip(odpowiedz.content))
    assert len(identyfikator) >= 32
    assert f"ZANONIMIZOWANY_{identyfikator[:12]}.txt" in nazwy
    assert f"{identyfikator[:12]}.nwidka" in nazwy
    assert not [n for n in nazwy if identyfikator in n], "pełny id wycieka do nazw plików"


# --- pkt 8: nagłówki X-Niewidka-* bez fragmentów i nazw części ------------------


@pytest.mark.anyio
async def test_pkt8_naglowki_bez_fragmentow(klucz_plik):
    """K4b pkt 8: nawet przy kontrola_blokada=False nagłówki niosą wyłącznie
    typy i liczniki — zero fragmentów danych i zero nazw części."""
    import json

    konfig = Konfig(klucz_plik=klucz_plik, kontrola_blokada=False)
    app = create_app(konfig, detektor=RegulyDetektor())
    dane = _docx_przebuduj(
        _wzorzec_docx(), dodaj={"word/theme/proba.xml": _theme_z_peselem("55010101234")}
    )
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"poziom": "1"},
            files={"plik": ("umowa.docx", dane)},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 200  # kontrola_blokada=False: wynik wychodzi
    calosc = odpowiedz.text + str(dict(odpowiedz.headers))
    assert "55010101234" not in calosc, "fragment danych wycieka nagłówkiem"
    assert "proba.xml" not in calosc, "nazwa części wycieka nagłówkiem"
    ostrzezenia = json.loads(odpowiedz.headers["x-niewidka-ostrzezenia"])
    assert ostrzezenia == {"PESEL": 1}  # typy + liczniki


# --- pkt 9: licznik bajtów PRZED parserem (chunked), limit w /przywroc ----------


@pytest.mark.anyio
async def test_pkt9_chunked_ponad_limit_413_bez_spoolowania(konfig, monkeypatch):
    """K4b pkt 9: upload bez Content-Length ponad limit → 413, zanim JAKIKOLWIEK
    bajt trafi do parsera formularza; rollover na dysk nigdy nie następuje."""
    import tempfile

    rollovery = []
    oryginalny_rollover = tempfile.SpooledTemporaryFile.rollover

    def sledzony_rollover(self):
        rollovery.append(1)
        return oryginalny_rollover(self)

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", sledzony_rollover)

    async def strumien():
        kawalek = b"x" * 65536
        for _ in range(18):  # 1,125 MB > limit 1 MB, bez Content-Length (chunked)
            yield kawalek

    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            headers=_naglowki(app, **{"content-type": "multipart/form-data; boundary=x"}),
            content=strumien(),
        )
    assert odpowiedz.status_code == 413
    assert not rollovery, "treść dotarła do parsera — rollover na dysk się wydarzył"


@pytest.mark.anyio
async def test_pkt9_przywroc_ma_limit_przed_buforowaniem(konfig):
    """K4b pkt 9: /api/przywroc ma ten sam licznik — chunked ponad limit = 413."""

    async def strumien():
        kawalek = b"m" * 65536
        for _ in range(18):
            yield kawalek

    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/przywroc",
            headers=_naglowki(app, **{"content-type": "multipart/form-data; boundary=x"}),
            content=strumien(),
        )
    assert odpowiedz.status_code == 413


# --- pkt 10: ZIP — odczyt porcjami z budżetem, weryfikacja długości, metody -----

import struct

from niewidka.archiwum import ArchiwumZaDuze, BladArchiwum, wczytaj_czesci


def test_pkt10_bomba_ucziwy_naglowek_budzet():
    """Uczciwy nagłówek, wielka treść: budżet dekompresji tnie w trakcie, nie po fakcie."""
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
        paczka.writestr("word/pompa.xml", "a" * (2 * _MB))
    with pytest.raises(ArchiwumZaDuze):
        wczytaj_czesci(bufor.getvalue(), limit_bajtow=_MB)


def _kłamliwy_zip(roznica: int) -> bytes:
    """ZIP z wpisem, którego nagłówki (lokalny i centralny) kłamią o rozmiarze
    rozpakowanym; rozmiar spakowany i CRC zostają zgodne z prefiksem strumienia."""
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
        paczka.writestr("word/pompa.xml", "a" * 1000)
    bajty = bytearray(bufor.getvalue())
    prawdziwy = 1000 + roznica
    struct.pack_into("<I", bajty, bajty.find(b"PK\x03\x04") + 18, 1000)  # spakowany (lokalny)
    struct.pack_into("<I", bajty, bajty.find(b"PK\x03\x04") + 22, prawdziwy)  # rozpakowany
    struct.pack_into("<I", bajty, bajty.find(b"PK\x01\x02") + 20, 1000)  # spakowany (centralny)
    struct.pack_into("<I", bajty, bajty.find(b"PK\x01\x02") + 24, prawdziwy)  # rozpakowany
    return bytes(bajty)


def test_pkt10_klamliwy_naglowek_wiekszy_niz_strumien():
    """Nagłówek deklaruje więcej, niż strumień naprawdę ma → odmowa, nie cisza."""
    with pytest.raises(BladArchiwum):
        wczytaj_czesci(_kłamliwy_zip(roznica=500))


def test_pkt10_klamliwy_naglowek_mniejszy_niz_strumien():
    """Nagłówek deklaruje MNIEJ, niż strumień ma (wektor audytu): po deklaracji
    strumień wciąż ma dane → odmowa zamiast cichego ucięcia treści."""
    with pytest.raises(BladArchiwum):
        wczytaj_czesci(_kłamliwy_zip(roznica=-500))


def test_pkt10_tylko_stored_i_deflate():
    """Inne metody kompresji (bzip2/lzma) = odmowa odczytu."""
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_BZIP2) as paczka:
        paczka.writestr("word/pompa.xml", "a" * 1000)
    with pytest.raises(BladArchiwum):
        wczytaj_czesci(bufor.getvalue())


@pytest.mark.anyio
async def test_pkt10_bomba_przez_api_413(konfig):
    """Integracja: DOCX z bombą ponad budżet = 413 fail-closed (zanim adapter wczyta)."""
    from dataclasses import replace as podmien_konfig

    konfig_bomba = podmien_konfig(konfig, max_rozpakowane_mb=1)
    app = create_app(konfig_bomba, detektor=RegulyDetektor())
    zrodlo = zipfile.ZipFile(io.BytesIO(_wzorzec_docx()))
    czesci = {n: zrodlo.read(n) for n in zrodlo.namelist()}
    zrodlo.close()
    czesci["word/pompa.xml"] = "a" * (2 * _MB)
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
        for nazwa, zawartosc in czesci.items():
            paczka.writestr(nazwa, zawartosc)
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"poziom": "1"},
            files={"plik": ("umowa.docx", bufor.getvalue())},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 413


# --- pkt 11: slot zwalniany dopiero po faktycznym końcu pracy -------------------


@pytest.mark.anyio
async def test_pkt11_timeout_zostawia_slot_zajety_do_konca_pracy(klucz_plik):
    """K4b pkt 11: timeout zwraca 503, ale wątek pracuje dalej i slot zostaje
    zajęty do faktycznego końca — następne żądanie NIE wchodzi równolegle."""
    konfig = Konfig(klucz_plik=klucz_plik, kolejka=0, timeout_s=1)
    start = threading.Event()
    zakonczone = threading.Event()

    class Wolny:
        nazwa = "wolny"
        typy = frozenset({TypEncji.INNE})

        def znajdz(self, tekst):
            start.set()
            zakonczone.wait(10)  # praca trwa dłużej niż timeout
            return []

    app = create_app(konfig, detektor=Wolny())
    async with _klient(app) as klient:
        pierwsze = asyncio.create_task(
            klient.post("/api/ukryj", data={"tekst": "spokojny tekst."}, headers=_naglowki(app))
        )
        await asyncio.to_thread(start.wait)  # praca zajęła slot
        timeout_odpowiedz = await pierwsze
        assert timeout_odpowiedz.status_code == 503  # timeout → 503 (nie cisza, nie 500)
        assert not zakonczone.is_set(), "wątek powinien wciąż pracować po timeoucie"
        drugie = await klient.post(
            "/api/ukryj", data={"tekst": "spokojny tekst."}, headers=_naglowki(app)
        )
        assert drugie.status_code == 503, "slot zwolniony mimo że praca trwa"
        zakonczone.set()  # praca może się skończyć
        for _ in range(200):  # czekamy, aż semafor FAKTYCZNIE puści
            if not app.state.kolejka._slot().locked():
                break
            await asyncio.sleep(0.05)
        trzecie = await klient.post(
            "/api/ukryj", data={"tekst": "spokojny tekst."}, headers=_naglowki(app)
        )
        assert trzecie.status_code == 200, "po realnym końcu pracy slot wolny"


# --- pkt 12: limit równoczesnych żądań przed parsowaniem body --------------------


@pytest.mark.anyio
async def test_pkt12_nadmiarowe_zlecenie_503_zanim_czyta_tresc(klucz_plik):
    """K4b pkt 12: żądanie ponad limit równoczesnych dostaje 503 ZANIM jakikolwiek
    bajt jego treści dotrze do aplikacji (stare: parser wisiał na treści bez końca)."""
    from dataclasses import replace as podmien_konfig

    konfig = podmien_konfig(Konfig(klucz_plik=klucz_plik), zlecenia=1, timeout_s=15)
    brama = threading.Event()

    class Wolny:
        nazwa = "wolny"
        typy = frozenset({TypEncji.INNE})

        def znajdz(self, tekst):
            brama.wait(10)
            return []

    app = create_app(konfig, detektor=Wolny())
    stan_tresci = {"odczytana": False}

    async def cialo_drugiego():
        yield b"--x\r\n"  # pierwszy kawałek — ale dopiero, gdy aplikacja go czyta
        stan_tresci["odczytana"] = True
        await asyncio.Event().wait()  # reszta treści nigdy nie przyjdzie

    async with _klient(app) as klient:
        pierwsze = asyncio.create_task(
            klient.post("/api/ukryj", data={"tekst": "spokojny tekst."}, headers=_naglowki(app))
        )
        await asyncio.sleep(0.3)  # pierwsze weszło do handlera (czeka na bramę)
        drugie = asyncio.create_task(
            klient.post(
                "/api/ukryj",
                headers=_naglowki(app, **{"content-type": "multipart/form-data; boundary=x"}),
                content=cialo_drugiego(),
            )
        )
        odpowiedz_drugiego = await asyncio.wait_for(drugie, 5)
        assert odpowiedz_drugiego.status_code == 503
        assert not stan_tresci["odczytana"], "treść nadmiarowego żądania została przeczytana"
        brama.set()  # pierwsze może się skończyć
        assert (await pierwsze).status_code == 200


# --- pkt 13: regex e-maila liniowy ------------------------------------------------


def test_pkt13_regex_email_liniowy():
    """K4b pkt 13: długi ciąg bez @ nie może uruchamiać kwadratowego cofania —
    100 tys. znaków poniżej 50 ms (audyt: 0,24 s już przy 16 tys., GIL zajęty)."""
    import time

    from niewidka.reguly import znajdz

    tekst = "a" * 100_000 + " koniec"
    start_pomiar = time.perf_counter()
    wynik = znajdz(tekst)
    czas = time.perf_counter() - start_pomiar
    # Próg 0.1 s: WSL ~0.03-0.05 s; Windows (bieg budowy K7b) 0.055 s na brzegu
    # starego progu. Celem testu jest obrona przed regresją kwadratową (było
    # 7,15 s), nie tuning liniowego kosztu.
    assert czas < 0.1, f"regex e-maila kwadratowy: {czas:.3f} s na 100 tys. znaków"
    assert wynik == []


def test_pkt13_email_nadal_wykrywany():
    from niewidka.reguly import znajdz

    tekst = "Napisz na jan.kowalski@example.com.pl proszę."
    trafienia = [t for t in znajdz(tekst) if t.typ.value == "EMAIL"]
    assert len(trafienia) == 1
    assert tekst[trafienia[0].start : trafienia[0].koniec] == "jan.kowalski@example.com.pl"


# --- pkt 14: nasłuch wyłącznie na loopbacku ---------------------------------------


def test_pkt14_konfig_odrzuca_host_poza_loopbackiem():
    """K4b pkt 14: host poza loopbackiem = jawny błąd startu; nasłuch LAN
    udostępniałby odszyfrowanie bez uwierzytelnienia użytkownika."""
    from niewidka.konfig import wczytaj_konfig

    for host in ("0.0.0.0", "192.168.1.10", "10.0.0.5"):
        with pytest.raises(ValueError, match="loopback"):
            wczytaj_konfig(env={"NIEWIDKA_HOST": host})


def test_pkt14_loopback_dozwolony():
    from niewidka.konfig import wczytaj_konfig

    assert wczytaj_konfig(env={"NIEWIDKA_HOST": "127.0.0.1"}).host == "127.0.0.1"
    assert wczytaj_konfig(env={"NIEWIDKA_HOST": "localhost"}).host == "localhost"
    assert wczytaj_konfig(env={"NIEWIDKA_HOST": "::1"}).host == "::1"


# --- pkt 15: odpowiedzi błędów bez odbicia danych wejściowych ---------------------


@pytest.mark.anyio
async def test_pkt15_415_bez_nazwy_pliku(konfig):
    """K4b pkt 15: osobowa nazwa pliku (bez rozszerzenia) nie wraca w 415."""
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"poziom": "1"},
            files={"plik": (f"umowa-{PESEL}", b"tresc")},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 415
    assert PESEL not in odpowiedz.text


@pytest.mark.anyio
async def test_pkt15_nieobslugiwane_elementy_bez_nazw_czesci(konfig):
    """K4b pkt 15: 422 dla nieobsługiwanych części nie wypisuje ich nazw
    (PESEL potrafi siedzieć w nazwie części archiwum)."""
    app = create_app(konfig, detektor=RegulyDetektor())
    dane = _docx_przebuduj(_wzorzec_docx(), dodaj={"word/obcy/44051401359.xml": b"<root/>"})
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"poziom": "1"},
            files={"plik": ("umowa.docx", dane)},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 422
    assert PESEL not in odpowiedz.text
    assert "44051401359.xml" not in odpowiedz.text


@pytest.mark.anyio
async def test_pkt15_walidacja_bez_pola_input(konfig):
    """K4b pkt 15: RequestValidationError nie odbija wartości wejściowych
    (audyt: poziom=44051401359-test wracał w polu input)."""
    app = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj",
            data={"poziom": f"{PESEL}-test", "tekst": "x"},
            headers=_naglowki(app),
        )
    assert odpowiedz.status_code == 422
    assert PESEL not in odpowiedz.text
    assert "input" not in odpowiedz.json()

