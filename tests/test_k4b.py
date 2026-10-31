"""Resilience tests: result block, DOCX, ZIP, request limits, binding a map to a document."""

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


# --- shared DOCX tools ---


def _wzorzec_docx() -> bytes:
    return zapisz_podstawowy(Path("/tmp") / "niewidka-k4b-wzorzec.docx").read_bytes()


def _docx_przebuduj(dane: bytes, podmien: dict[str, bytes] | None = None, dodaj: dict[str, bytes] | None = None) -> bytes:
    """DOCX after rebuild: replace existing parts + add new ones."""
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
    """Part word/theme/*.xml — the allowlist keeps it, the adapter does not parse it."""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">{tresc or PESEL}</theme>'
    ).encode()


def _docx_z_peselem_w_czesci() -> bytes:
    """Valid DOCX with a PESEL in a part the adapter preserves (word/theme/).
    PESEL different from the one in the body, so the finding comes only from the hidden part."""
    return _docx_przebuduj(
        _wzorzec_docx(), dodaj={"word/theme/proba.xml": _theme_z_peselem("55010101234")}
    )


# --- block = no document in the response ---


@pytest.mark.anyio
async def test_pkt1_blokada_422_bez_dokumentu(konfig):
    """A "blocked" result does not come back as 200 with a document:
    422 with a list of types, no fragments and no document bytes whatsoever."""
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
    assert tresc["typy"] == {"PESEL": 1}
    # block carries places for a decision,
    # fragment only in the response's `miejsca` field for the UI, nowhere else
    assert [m["typ"] for m in tresc["miejsca"]] == ["PESEL"]
    assert tresc["podglad"] is None  # DOCX has no text preview
    assert PESEL not in odpowiedz.text
    assert not odpowiedz.content.startswith(b"PK")  # no document leaked


def test_pkt1_ui_blokada_wylacza_pobieranie_i_kopiowanie():
    """UI: a blocked result (422) shows STOP and offers no download or
    clipboard; the old path "200 + x-niewidka-status header" is gone."""
    apka = (Path(__file__).parents[1] / "niewidka" / "web" / "apka.js").read_text(encoding="utf-8")
    assert 'status === "zablokowany"' in apka  # handling of a blocked 422
    assert "STOP" in apka
    assert '"x-niewidka-status"' not in apka  # a 200 result is never blocked


# --- images removed, unverified binary parts = block ---

from niewidka.formaty import ElementNieobslugiwany
from niewidka.rdzen import ukryj


def test_pkt2_obrazy_usuwane_z_uwaga_w_raporcie():
    """Without OCR an image cannot be checked — REMOVED by default,
    neutral text in its place, report has a note, status stays clean."""
    wynik, _, raport = ukryj(
        _wzorzec_docx(), "docx", 1, detektor=RegulyDetektor(), max_rozpakowane_bajtow=200 * _MB
    )
    czesci = _zip(wynik)
    assert not [n for n in czesci if n.startswith("word/media/")], "obraz zostawiony w wyniku"
    assert "[OBRAZ USUNIĘTY]" in czesci["word/document.xml"].decode()
    assert any("OBRAZ" in uwaga for uwaga in raport.uwagi)
    assert raport.status == "ukonczony"  # removal = note, not a block


@pytest.mark.anyio
async def test_pkt2_niezweryfikowana_czesc_binarna_blokada(konfig):
    """Word/media/*.bin cannot be verified without OCR or a scan — block."""
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
    """Image policy is configurable — "zostaw" keeps the image,
    but the report warns; "blokuj" raises ElementNieobslugiwany."""
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


# --- scan also e.tail (itertext) ---


def test_pkt3_pesel_w_ogonie_xml_blokuje():
    """PESEL in the element tail (text AFTER the marker) bypassed the scan."""
    from niewidka.kontrola import kontroluj

    dane = _docx_przebuduj(
        _wzorzec_docx(),
        dodaj={"word/theme/proba.xml": b"<?xml version='1.0'?><root><node/>55010101234</root>"},
    )
    uwagi = kontroluj(dane, "umowa.docx", RegulyDetektor())
    assert any(
        u.typ == "PESEL" and u.czesc == "word/theme/proba.xml" for u in uwagi
    ), f"skan nie widzi ogonka elementu: {uwagi}"


# --- parse error of a preserved XML part = block (fail-closed) ---


def test_pkt4_nieprawidlowy_xml_zachowanej_czesci_blokuje():
    """Unclosed XML in a preserved part is fail-closed,
    not a silent "continue" — content that cannot be scanned is not sent."""
    from niewidka.kontrola import kontroluj

    dane = _docx_przebuduj(
        _wzorzec_docx(),
        dodaj={"word/theme/proba.xml": b"<?xml version='1.0'?><root>55010101234"},
    )
    uwagi = kontroluj(dane, "umowa.docx", RegulyDetektor())
    assert any(
        u.typ == "XML_NIEPRAWIDLOWY" and u.czesc == "word/theme/proba.xml" for u in uwagi
    ), f"błąd parsowania przeszedł cicho: {uwagi}"


# --- scan of ZIP part names + neutralization of media names ---


def _docx_z_media_o_pieselowej_nazwie() -> bytes:
    """Template with an image renamed to word/media/44051401359.png (rels consistent)."""
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
    """The check also scans part NAMES — PESEL in a name = finding."""
    from niewidka.kontrola import kontroluj

    dane = _docx_przebuduj(
        _wzorzec_docx(), dodaj={"word/theme/44051401359.xml": b"<?xml version='1.0'?><root/>"}
    )
    uwagi = kontroluj(dane, "umowa.docx", RegulyDetektor())
    assert any(
        u.typ == "NAZWA_CZESCI" and u.czesc == "word/theme/44051401359.xml" for u in uwagi
    ), f"nazwa części bez skanu: {uwagi}"


def test_pkt5_media_przemianowane_a_relacje_zaktualizowane():
    """A media name with PII disappears from the result; the image stays under a neutral
    name, the relation points to the new target, the document opens with the adapter."""
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
    adapter_dla("w.docx").wczytaj(wynik)  # result stays a valid DOCX


# --- restore binds the map to a SPECIFIC document ---


@pytest.mark.anyio
async def test_pkt6_mapa_z_innego_dokumentu_tej_sesji_422(konfig):
    """Map B slipped into result A (both from the same session, so the old
    identifier check passes) = 422, never restoring someone else's data."""
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
    assert "55010101234" not in wynik.text  # someone else's data did not come back


def test_pkt6_dopisek_zawiera_identyfikator():
    """Map identifier written in the result content (note) — binding is based on it."""
    from niewidka.rdzen import ukryj
    from niewidka.znaczniki import DOPISEK

    wynik, mapa, _ = ukryj(b"PESEL 44051401359.", "txt", 1, detektor=RegulyDetektor())
    from niewidka.znaczniki import zakoduj_identyfikator

    assert zakoduj_identyfikator(mapa.identyfikator) in wynik.decode()
    # identifier in the note without a single digit (digits would trip the number rules)
    id_w_tekscie = wynik.decode().split("mapy: ")[1].split(".")[0]
    assert id_w_tekscie and not any(znak.isdigit() for znak in id_w_tekscie)
    assert wynik.decode().startswith(DOPISEK)


# --- identifier ≥128 bit + registry of hashes of issued ciphertexts ---


def test_pkt7_identyfikator_ma_128_bit():
    _, mapa, _ = ukryj(b"PESEL 44051401359.", "txt", 1, detektor=RegulyDetektor())
    assert len(mapa.identyfikator) >= 32, "24-bitowy id pozwalał na kolizje starych map"
    int(mapa.identyfikator, 16)  # hex


@pytest.mark.anyio
async def test_pkt7_cudzy_szyfrogram_nie_odszyfrowuje(klucz_plik):
    """The session registers hashes of ISSUED ciphertexts. A ciphertext
    captured from ANOTHER session (even if the attacker won the identifier collision —
    we simulate that with an entry in the session set) is not decryptable."""
    app_nadawca = create_app(Konfig(klucz_plik=klucz_plik), detektor=RegulyDetektor())
    app_odbiorca = create_app(Konfig(klucz_plik=klucz_plik), detektor=RegulyDetektor())
    async with _klient(app_nadawca) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj", data={"tekst": "PESEL 44051401359.", "poziom": "1"}, headers=_naglowki(app_nadawca)
        )
    czesci = _zip(odpowiedz.content)
    identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
    szyfrogram = czesci[f"{identyfikator[:12]}.nwidka"]
    # collision "won": the foreign map identifier is in the receiver session set
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
    """Full identifier in the header/map; in file NAMES only a short hash."""
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


# --- X-Niewidka-* headers without fragments and part names ---


@pytest.mark.anyio
async def test_pkt8_naglowki_bez_fragmentow(klucz_plik):
    """Even with kontrola_blokada=False the headers carry only
    types and counters — zero data fragments and zero part names."""
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
    assert odpowiedz.status_code == 200  # kontrola_blokada=False: the result goes out
    calosc = odpowiedz.text + str(dict(odpowiedz.headers))
    assert "55010101234" not in calosc, "fragment danych wycieka nagłówkiem"
    assert "proba.xml" not in calosc, "nazwa części wycieka nagłówkiem"
    ostrzezenia = json.loads(odpowiedz.headers["x-niewidka-ostrzezenia"])
    assert ostrzezenia == {"PESEL": 1}  # types + counters


# --- byte counter BEFORE the parser (chunked), limit in /przywroc ---


@pytest.mark.anyio
async def test_pkt9_chunked_ponad_limit_413_bez_spoolowania(konfig, monkeypatch):
    """Upload without Content-Length over the limit → 413, before ANY
    byte reaches the form parser; rollover to disk never happens."""
    import tempfile

    rollovery = []
    oryginalny_rollover = tempfile.SpooledTemporaryFile.rollover

    def sledzony_rollover(self):
        rollovery.append(1)
        return oryginalny_rollover(self)

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", sledzony_rollover)

    async def strumien():
        kawalek = b"x" * 65536
        for _ in range(18):  # 1.125 MB > 1 MB limit, no Content-Length (chunked)
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
    """/api/przywroc has the same counter — chunked over the limit = 413."""

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


# --- ZIP: chunked read with a budget, length verification, methods ---

import struct

from niewidka.archiwum import ArchiwumZaDuze, BladArchiwum, wczytaj_czesci


def test_pkt10_bomba_ucziwy_naglowek_budzet():
    """Honest header, huge content: the decompression budget cuts mid-stream, not after the fact."""
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
        paczka.writestr("word/pompa.xml", "a" * (2 * _MB))
    with pytest.raises(ArchiwumZaDuze):
        wczytaj_czesci(bufor.getvalue(), limit_bajtow=_MB)


def _kłamliwy_zip(roznica: int) -> bytes:
    """ZIP with an entry whose headers (local and central) lie about the uncompressed
    size; compressed size and CRC stay consistent with the stream prefix."""
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
        paczka.writestr("word/pompa.xml", "a" * 1000)
    bajty = bytearray(bufor.getvalue())
    prawdziwy = 1000 + roznica
    struct.pack_into("<I", bajty, bajty.find(b"PK\x03\x04") + 18, 1000)  # compressed (local)
    struct.pack_into("<I", bajty, bajty.find(b"PK\x03\x04") + 22, prawdziwy)  # uncompressed
    struct.pack_into("<I", bajty, bajty.find(b"PK\x01\x02") + 20, 1000)  # compressed (central)
    struct.pack_into("<I", bajty, bajty.find(b"PK\x01\x02") + 24, prawdziwy)  # uncompressed
    return bytes(bajty)


def test_pkt10_klamliwy_naglowek_wiekszy_niz_strumien():
    """Header declares more than the stream really has → refusal, not silence."""
    with pytest.raises(BladArchiwum):
        wczytaj_czesci(_kłamliwy_zip(roznica=500))


def test_pkt10_klamliwy_naglowek_mniejszy_niz_strumien():
    """Header declares LESS than the stream has: after the declaration
    the stream still has data → refusal instead of silently truncating the content."""
    with pytest.raises(BladArchiwum):
        wczytaj_czesci(_kłamliwy_zip(roznica=-500))


def test_pkt10_tylko_stored_i_deflate():
    """Other compression methods (bzip2/lzma) = refusal to read."""
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_BZIP2) as paczka:
        paczka.writestr("word/pompa.xml", "a" * 1000)
    with pytest.raises(BladArchiwum):
        wczytaj_czesci(bufor.getvalue())


@pytest.mark.anyio
async def test_pkt10_bomba_przez_api_413(konfig):
    """Integration: DOCX with a bomb over the budget = 413 fail-closed (before the adapter loads)."""
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


# --- slot released only after the work really ends ---


@pytest.mark.anyio
async def test_pkt11_timeout_zostawia_slot_zajety_do_konca_pracy(klucz_plik):
    """Timeout returns 503, but the thread keeps working and the slot stays
    occupied until the real end — the next request does NOT enter in parallel."""
    konfig = Konfig(klucz_plik=klucz_plik, kolejka=0, timeout_s=1)
    start = threading.Event()
    zakonczone = threading.Event()

    class Wolny:
        nazwa = "wolny"
        typy = frozenset({TypEncji.INNE})

        def znajdz(self, tekst):
            start.set()
            zakonczone.wait(10)  # work takes longer than the timeout
            return []

    app = create_app(konfig, detektor=Wolny())
    async with _klient(app) as klient:
        pierwsze = asyncio.create_task(
            klient.post("/api/ukryj", data={"tekst": "spokojny tekst."}, headers=_naglowki(app))
        )
        await asyncio.to_thread(start.wait)  # work took the slot
        timeout_odpowiedz = await pierwsze
        assert timeout_odpowiedz.status_code == 503  # timeout → 503 (not silence, not 500)
        assert not zakonczone.is_set(), "wątek powinien wciąż pracować po timeoucie"
        drugie = await klient.post(
            "/api/ukryj", data={"tekst": "spokojny tekst."}, headers=_naglowki(app)
        )
        assert drugie.status_code == 503, "slot zwolniony mimo że praca trwa"
        zakonczone.set()  # work may finish
        for _ in range(200):  # wait until the semaphore ACTUALLY releases
            if not app.state.kolejka._slot().locked():
                break
            await asyncio.sleep(0.05)
        trzecie = await klient.post(
            "/api/ukryj", data={"tekst": "spokojny tekst."}, headers=_naglowki(app)
        )
        assert trzecie.status_code == 200, "po realnym końcu pracy slot wolny"


# --- limit of concurrent requests before parsing the body ---


@pytest.mark.anyio
async def test_pkt12_nadmiarowe_zlecenie_503_zanim_czyta_tresc(klucz_plik):
    """A request over the concurrency limit gets 503 BEFORE any
    byte of its body reaches the app (old: the parser hung on a body without end)."""
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
        yield b"--x\r\n"  # first chunk — but only once the app reads it
        stan_tresci["odczytana"] = True
        await asyncio.Event().wait()  # the rest of the content never arrives

    async with _klient(app) as klient:
        pierwsze = asyncio.create_task(
            klient.post("/api/ukryj", data={"tekst": "spokojny tekst."}, headers=_naglowki(app))
        )
        await asyncio.sleep(0.3)  # the first one entered the handler (waits for the gate)
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
        brama.set()  # the first one may finish
        assert (await pierwsze).status_code == 200


# --- linear e-mail regex ---


def test_pkt13_regex_email_liniowy():
    """A long string without @ must not trigger quadratic backtracking —
    100k characters under 50 ms."""
    import time

    from niewidka.reguly import znajdz

    tekst = "a" * 100_000 + " koniec"
    start_pomiar = time.perf_counter()
    wynik = znajdz(tekst)
    czas = time.perf_counter() - start_pomiar
    # Threshold 0.1 s: WSL ~0.03-0.05 s; Windows 0.055 s, on the edge
    # of the old threshold. The test aims to defend against a quadratic regression (it was
    # 7.15 s), not to tune the linear cost.
    assert czas < 0.1, f"regex e-maila kwadratowy: {czas:.3f} s na 100 tys. znaków"
    assert wynik == []


def test_pkt13_email_nadal_wykrywany():
    from niewidka.reguly import znajdz

    tekst = "Napisz na jan.kowalski@example.com.pl proszę."
    trafienia = [t for t in znajdz(tekst) if t.typ.value == "EMAIL"]
    assert len(trafienia) == 1
    assert tekst[trafienia[0].start : trafienia[0].koniec] == "jan.kowalski@example.com.pl"


# --- listening on loopback only ---


def test_pkt14_konfig_odrzuca_host_poza_loopbackiem():
    """Host outside loopback = explicit startup error; LAN listening
    would expose decryption without user authentication."""
    from niewidka.konfig import wczytaj_konfig

    for host in ("0.0.0.0", "192.168.1.10", "10.0.0.5"):
        with pytest.raises(ValueError, match="loopback"):
            wczytaj_konfig(env={"NIEWIDKA_HOST": host})


def test_pkt14_loopback_dozwolony():
    from niewidka.konfig import wczytaj_konfig

    assert wczytaj_konfig(env={"NIEWIDKA_HOST": "127.0.0.1"}).host == "127.0.0.1"
    assert wczytaj_konfig(env={"NIEWIDKA_HOST": "localhost"}).host == "localhost"
    assert wczytaj_konfig(env={"NIEWIDKA_HOST": "::1"}).host == "::1"


# --- error responses without echoing input data ---


@pytest.mark.anyio
async def test_pkt15_415_bez_nazwy_pliku(konfig):
    """A personal file name (without extension) does not come back in 415."""
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
    """422 for unsupported parts does not list their names
    (a PESEL can sit in an archive part name)."""
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
    """RequestValidationError does not echo input values."""
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



@pytest.mark.anyio
async def test_pkt7_mapa_przywraca_sie_po_restarcie_z_rejestrem(klucz_plik, tmp_path):
    """Window closed = session end, and a map issued
    earlier must be restorable after a restart. The hash registry in a file
    (no personal data); a map outside the registry is still rejected."""
    rejestr = tmp_path / "wydane-mapy.jsonl"
    konfig = Konfig(klucz_plik=klucz_plik, rejestr_map=rejestr)
    app1 = create_app(konfig, detektor=RegulyDetektor())
    async with _klient(app1) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj", data={"tekst": "PESEL 44051401359.", "poziom": "1"}, headers=_naglowki(app1)
        )
    czesci = _zip(odpowiedz.content)
    identyfikator = odpowiedz.headers["x-niewidka-identyfikator"]
    assert "44051401359" not in rejestr.read_text(encoding="utf-8")
    app2 = create_app(konfig, detektor=RegulyDetektor())  # „restart"
    async with _klient(app2) as klient:
        wynik = await klient.post(
            "/api/przywroc",
            files={
                "wynik": ("w.txt", czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.txt"]),
                "mapa": ("m.nwidka", czesci[f"{identyfikator[:12]}.nwidka"]),
            },
            headers=_naglowki(app2),
        )
    assert wynik.status_code == 200, wynik.text
    assert b"44051401359" in wynik.content
    app3 = create_app(Konfig(klucz_plik=klucz_plik, rejestr_map=tmp_path / "inny.jsonl"), detektor=RegulyDetektor())
    async with _klient(app3) as klient:
        obcy = await klient.post(
            "/api/przywroc",
            files={
                "wynik": ("w.txt", czesci[f"ZANONIMIZOWANY_{identyfikator[:12]}.txt"]),
                "mapa": ("m.nwidka", czesci[f"{identyfikator[:12]}.nwidka"]),
            },
            headers=_naglowki(app3),
        )
    assert obcy.status_code == 422
