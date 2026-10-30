"""Centralny serwer inferencji i klient, bez prawdziwych wag.

Serwer dostaje atrapę detektora; test pełnej drogi (aplikacja użytkownika -> HTTP ->
serwer) uruchamia serwer na loopbacku w wątku (uvicorn), bez kontenerów.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import socket
import stat
import threading
import time
import zipfile
from pathlib import Path

import httpx
import pytest
import uvicorn

from niewidka import serwer_inferencji as si
from niewidka.api import create_app as create_app_uzytkownika
from niewidka.konfig import Konfig, wczytaj_konfig
from niewidka.serwer_inferencji import (
    BladKonfiguracji,
    KonfigSerwera,
    create_app,
    wczytaj_konfig_serwera,
    wybierz_provider,
)
from niewidka.zdalny import (
    BladTokenu,
    SerwerModeliNiedostepny,
    ZdalnyDetektor,
    sprawdz_adres,
    stan_serwera,
    wczytaj_token,
    zbuduj_klienta,
)
from tests.test_poprawki import DetektorZLicznikiem

TEKST = "Jan Nowak mieszka tu. PESEL 44051401359, biuro@firma-example.pl."
TAJNY = "TajnaFrazaKtoraNieMaTraficDoLogow"


@pytest.fixture()
def token_plik(tmp_path):
    plik = tmp_path / "token"
    si.zapisz_nowy_token(plik)
    return plik


@pytest.fixture()
def konfig_serwera(token_plik):
    return KonfigSerwera(token_plik=token_plik, max_tekst_mb=1)


def _naglowek(token_plik) -> dict:
    return {"Authorization": f"Bearer {wczytaj_token(token_plik)}"}


def _klient(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8443")


# --- token ------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="uprawnienia 0600 sprawdzane tylko na POSIX (jak klucze.py)")
def test_nowy_token_ma_uprawnienia_0600_i_nie_nadpisuje(tmp_path):
    plik = tmp_path / "t"
    assert si.main(["nowy-token", str(plik)]) == 0
    assert stat.S_IMODE(plik.stat().st_mode) == 0o600
    pierwotny = plik.read_bytes()
    assert si.main(["nowy-token", str(plik)]) == 1
    assert plik.read_bytes() == pierwotny


def test_start_bez_pliku_tokenu_odmawia(tmp_path):
    with pytest.raises(BladKonfiguracji, match="nie startuje"):
        create_app(KonfigSerwera(token_plik=tmp_path / "brak"), detektor=DetektorZLicznikiem())
    with pytest.raises(BladKonfiguracji, match="token_plik"):
        create_app(KonfigSerwera(), detektor=DetektorZLicznikiem())


@pytest.mark.skipif(os.name != "posix", reason="uprawnienia 0600 sprawdzane tylko na POSIX (jak klucze.py)")
def test_token_z_zbyt_otwartymi_uprawnieniami_odrzucony(token_plik):
    token_plik.chmod(0o644)
    with pytest.raises(BladKonfiguracji, match="uprawnienia"):
        create_app(KonfigSerwera(token_plik=token_plik), detektor=DetektorZLicznikiem())


# --- sieć i TLS -------------------------------------------------------------------


def test_host_lan_bez_tls_odmawia_a_z_zezwoleniem_startuje(token_plik, caplog):
    lan = KonfigSerwera(host="192.168.1.10", token_plik=token_plik)
    with pytest.raises(BladKonfiguracji, match="zezwol_bez_tls"):
        create_app(lan, detektor=DetektorZLicznikiem())
    with caplog.at_level(logging.WARNING, logger="niewidka.serwer_inferencji"):
        create_app(
            KonfigSerwera(host="192.168.1.10", token_plik=token_plik, zezwol_bez_tls=True),
            detektor=DetektorZLicznikiem(),
        )
    assert "BEZ TLS" in caplog.text


def test_loopback_bez_tls_startuje_a_cert_bez_klucza_odmawia(token_plik, tmp_path):
    create_app(KonfigSerwera(host="127.0.0.1", token_plik=token_plik), detektor=DetektorZLicznikiem())
    cert = tmp_path / "c.pem"
    cert.write_text("x")
    with pytest.raises(BladKonfiguracji, match="razem"):
        create_app(
            KonfigSerwera(host="10.0.0.5", token_plik=token_plik, cert_plik=cert),
            detektor=DetektorZLicznikiem(),
        )


# --- endpointy --------------------------------------------------------------------


@pytest.mark.anyio
async def test_bez_tokenu_i_ze_zlym_tokenem_401(konfig_serwera, token_plik):
    app = create_app(konfig_serwera, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        tresc = {"tekst": TEKST, "poziom": 1}
        assert (await klient.post("/v1/wykryj", json=tresc)).status_code == 401
        zly = {"Authorization": "Bearer " + base64.b64encode(bytes(32)).decode()}
        assert (await klient.post("/v1/wykryj", json=tresc, headers=zly)).status_code == 401
        assert (await klient.post("/v1/wykryj", json=tresc, headers={"Authorization": "Basic x"})).status_code == 401
        assert (await klient.get("/v1/stan")).status_code == 401


@pytest.mark.anyio
async def test_poprawny_token_zwraca_zakresy_i_stan(konfig_serwera, token_plik):
    app = create_app(konfig_serwera, detektor=DetektorZLicznikiem())
    naglowki = _naglowek(token_plik)
    async with _klient(app) as klient:
        odpowiedz = await klient.post("/v1/wykryj", json={"tekst": TEKST, "poziom": 2}, headers=naglowki)
        assert odpowiedz.status_code == 200, odpowiedz.text
        zakresy = odpowiedz.json()["zakresy"]
        typy = {z["typ"] for z in zakresy}
        assert {"OSOBA", "PESEL", "EMAIL"} <= typy
        pierwszy = next(z for z in zakresy if z["typ"] == "OSOBA")
        assert TEKST[pierwszy["start"] : pierwszy["koniec"]] == "Jan Nowak"
        assert set(pierwszy) == {
            "start", "koniec", "typ", "pewnosc", "zrodlo", "suma_kontrolna", "podejrzana",
        }
        stan = (await klient.get("/v1/stan", headers=naglowki)).json()
    assert stan["poziomy"] == [1, 2, 3] and stan["urzadzenie"] == ["atrapa"]


@pytest.mark.anyio
async def test_limity_i_zly_poziom(token_plik):
    app = create_app(KonfigSerwera(token_plik=token_plik, max_tekst_mb=1), detektor=DetektorZLicznikiem())
    naglowki = _naglowek(token_plik)
    async with _klient(app) as klient:
        za_duzy = {"tekst": "a" * (1024 * 1024 + 1), "poziom": 1}
        assert (await klient.post("/v1/wykryj", json=za_duzy, headers=naglowki)).status_code == 413
        ogromny = b'{"tekst": "' + b"a" * (8 * 1024 * 1024) + b'", "poziom": 1}'
        assert (await klient.post("/v1/wykryj", content=ogromny, headers=naglowki)).status_code == 413
        assert (await klient.post("/v1/wykryj", json={"tekst": "x", "poziom": 4}, headers=naglowki)).status_code == 422
        zle = await klient.post("/v1/wykryj", json={"tekst": TAJNY, "poziom": "abc"}, headers=naglowki)
        assert zle.status_code == 422 and TAJNY not in zle.text  # walidacja nie odbija tekstu
    wezszy = create_app(
        KonfigSerwera(token_plik=token_plik, poziomy=(1,)), detektor=DetektorZLicznikiem()
    )
    async with _klient(wezszy) as klient:
        assert (await klient.post("/v1/wykryj", json={"tekst": "x", "poziom": 3}, headers=naglowki)).status_code == 422


@pytest.mark.anyio
async def test_tekst_nie_trafia_do_logow(konfig_serwera, token_plik, caplog):
    class Pada:
        nazwa = "pada"

        def znajdz(self, tekst):
            raise RuntimeError(f"boom na {tekst}")

    naglowki = _naglowek(token_plik)
    with caplog.at_level(logging.DEBUG):
        async with _klient(create_app(konfig_serwera, detektor=DetektorZLicznikiem())) as klient:
            ok = await klient.post("/v1/wykryj", json={"tekst": f"Jan Nowak {TAJNY}", "poziom": 1}, headers=naglowki)
            assert ok.status_code == 200
        async with _klient(create_app(konfig_serwera, detektor=Pada())) as klient:
            zle = await klient.post("/v1/wykryj", json={"tekst": TAJNY, "poziom": 1}, headers=naglowki)
            assert zle.status_code == 500 and TAJNY not in zle.text
    assert TAJNY not in caplog.text
    assert "wykryj: poziom=1" in caplog.text  # log niesie długość i czas, nie treść
    assert wczytaj_token(token_plik) not in caplog.text


# --- urządzenie ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("urzadzenie", "dostepne", "platforma", "oczekiwany"),
    [
        ("cpu", [si.CUDA, si.CPU], "linux", si.CPU),
        ("auto", [si.CUDA, si.CPU], "linux", si.CUDA),
        ("auto", [si.CPU], "linux", si.CPU),
        ("auto", [si.DML, si.CPU], "win32", si.DML),
        ("auto", [si.DML, si.CPU], "linux", si.CPU),
        ("gpu", [si.CUDA, si.CPU], "linux", si.CUDA),
        ("gpu", [si.DML, si.CPU], "win32", si.DML),
    ],
)
def test_urzadzenie_na_provider(urzadzenie, dostepne, platforma, oczekiwany):
    assert wybierz_provider(urzadzenie, dostepne, platforma) == oczekiwany


def test_gpu_bez_gpu_to_czytelny_blad_startu(token_plik):
    with pytest.raises(BladKonfiguracji, match="onnxruntime-gpu"):
        wybierz_provider("gpu", [si.CPU], "linux")
    with pytest.raises(BladKonfiguracji, match="onnxruntime-gpu"):
        create_app(
            KonfigSerwera(token_plik=token_plik, urzadzenie="gpu"),
            dostepne_providery=lambda: [si.CPU],
        )


def test_provider_i_watki_trafiaja_do_budowy_detektora(token_plik, monkeypatch):
    zebrane = {}

    def falszywa_budowa(poziom, konfig, pakiet_rozszerzony=False):
        zebrane.update(poziom=poziom, provider=konfig.provider, watki=konfig.watki)
        return DetektorZLicznikiem()

    monkeypatch.setattr(si, "zbuduj_detektor", falszywa_budowa)
    app = create_app(
        KonfigSerwera(token_plik=token_plik, urzadzenie="auto", watki=3, poziomy=(2,)),
        dostepne_providery=lambda: [si.CUDA, si.CPU],
        rozgrzej=True,
    )
    assert zebrane == {"poziom": 2, "provider": si.CUDA, "watki": 3}
    assert app.state.provider == si.CUDA


def test_uzyte_providery_czyta_sesje_z_drzewa_detektorow():
    class Sesja:
        def get_providers(self):
            return [si.CPU]

    class Onnx:
        def __init__(self):
            self._sesja = Sesja()

    class Kompozyt:
        def __init__(self):
            self.czesci = [object(), Onnx()]

    assert si.uzyte_providery(Kompozyt()) == {si.CPU}


# --- konfiguracja z pliku ---------------------------------------------------------------


def test_konfig_z_pliku_i_env(tmp_path):
    plik = tmp_path / "s.toml"
    plik.write_text(
        '[siec]\nhost = "0.0.0.0"\nport = 9000\nzezwol_bez_tls = true\n'
        '[dostep]\ntoken_plik = "/etc/niewidka/token"\n'
        '[modele]\npoziomy = [1, 3]\nurzadzenie = "gpu"\nwatki = 4\nrownolegle = 2\n'
        "[limity]\nmax_tekst_mb = 3\n",
        encoding="utf-8",
    )
    k = wczytaj_konfig_serwera(plik, env={"NIEWIDKA_SERWER_PORT": "9100"})
    assert (k.host, k.port, k.zezwol_bez_tls) == ("0.0.0.0", 9100, True)
    assert (k.poziomy, k.urzadzenie, k.watki, k.rownolegle, k.max_tekst_mb) == ((1, 3), "gpu", 4, 2, 3)
    assert k.token_plik == Path("/etc/niewidka/token")  # Path: na Windows separator to \\
    with pytest.raises(BladKonfiguracji, match="urzadzenie"):
        wczytaj_konfig_serwera(plik, env={"NIEWIDKA_SERWER_URZADZENIE": "tpu"})
    with pytest.raises(BladKonfiguracji, match="poziomy"):
        wczytaj_konfig_serwera(plik, env={"NIEWIDKA_SERWER_POZIOMY": "1,7"})


def test_przykladowe_pliki_konfiguracyjne_sie_parsuja():
    from pathlib import Path

    katalog = Path(__file__).parent.parent / "konfiguracja"
    serwer = wczytaj_konfig_serwera(katalog / "serwer-inferencji.przyklad.toml", env={})
    assert serwer.urzadzenie == "auto" and serwer.poziomy == (1, 2, 3)
    klient = wczytaj_konfig(katalog / "klient-web.przyklad.toml", env={})
    assert klient.inferencja_adres is None  # przykład ma adres w komentarzu: modele lokalne


# --- klient -------------------------------------------------------------------------------


def test_adres_http_tylko_dla_loopbacku_albo_za_zgoda():
    assert sprawdz_adres("http://127.0.0.1:8443/", False) == "http://127.0.0.1:8443"
    assert sprawdz_adres("https://serwer.urzad.local:8443", False)
    with pytest.raises(ValueError, match="TLS"):
        sprawdz_adres("http://serwer.urzad.local:8443", False)
    assert sprawdz_adres("http://serwer.urzad.local:8443", True)
    with pytest.raises(ValueError):
        sprawdz_adres("ftp://x", True)


def test_zdalny_detektor_na_mock_transport(token_plik):
    zapytania = []

    def obsluz(zapytanie: httpx.Request) -> httpx.Response:
        zapytania.append(zapytanie)
        return httpx.Response(
            200,
            json={"zakresy": [
                {"start": 0, "koniec": 3, "typ": "DATA", "pewnosc": 1.0, "zrodlo": "regula"},
                {"start": 4, "koniec": 9, "typ": "OSOBA", "pewnosc": 0.9, "zrodlo": "onnx:bardsai"},
            ]},
        )

    konfig = Konfig(
        inferencja_adres="https://serwer.test:8443", inferencja_token_plik=token_plik
    )
    klient = zbuduj_klienta(konfig, transport=httpx.MockTransport(obsluz))
    zakresy = ZdalnyDetektor(2, klient).znajdz("abc Jan N")
    assert [z.typ.value for z in zakresy] == ["DATA", "OSOBA"]
    assert zapytania[0].headers["authorization"] == f"Bearer {wczytaj_token(token_plik)}"
    assert [z.typ.value for z in ZdalnyDetektor(2, klient, wykrywaj_date=False).znajdz("abc Jan N")] == ["OSOBA"]


@pytest.mark.parametrize(
    "odpowiedz",
    [
        httpx.Response(401),
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="to nie json"),
        httpx.Response(200, json={"zakresy": [{"start": 0, "koniec": 99, "typ": "OSOBA", "pewnosc": 1, "zrodlo": "x"}]}),
        httpx.Response(200, json={"zakresy": [{"start": 0}]}),
    ],
)
def test_zdalny_detektor_fail_closed_na_bledach_serwera(token_plik, odpowiedz):
    konfig = Konfig(inferencja_adres="https://serwer.test", inferencja_token_plik=token_plik)
    klient = zbuduj_klienta(konfig, transport=httpx.MockTransport(lambda _: odpowiedz))
    with pytest.raises(SerwerModeliNiedostepny, match="Serwer modeli nie odpowiada"):
        ZdalnyDetektor(1, klient).znajdz("abc")


def test_brak_pliku_tokenu_klienta_zglaszany_od_razu(tmp_path):
    with pytest.raises(BladTokenu):
        zbuduj_klienta(Konfig(inferencja_adres="https://x.test", inferencja_token_plik=tmp_path / "nie"))


def test_konfig_klienta_z_toml_i_env(tmp_path):
    plik = tmp_path / "k.toml"
    plik.write_text(
        '[inferencja]\nadres = "https://s.local:8443"\ntoken_plik = "/t"\nca_plik = "/ca.pem"\ntimeout_s = 15\n',
        encoding="utf-8",
    )
    k = wczytaj_konfig(plik, env={"NIEWIDKA_INFERENCJA_TIMEOUT_S": "7"})
    assert k.inferencja_adres == "https://s.local:8443" and k.inferencja_timeout_s == 7
    assert k.inferencja_token_plik == Path("/t") and k.inferencja_ca_plik == Path("/ca.pem")
    assert wczytaj_konfig(plik, env={"NIEWIDKA_INFERENCJA_ADRES": ""}).inferencja_adres is None


# --- cała droga: aplikacja użytkownika -> HTTP -> serwer ---------------------------------------


@pytest.fixture()
def serwer_na_zywo(konfig_serwera):
    """Serwer na wolnym porcie loopbacku w wątku; zwraca (adres, atrapa)."""
    with socket.socket() as gniazdo:
        gniazdo.bind(("127.0.0.1", 0))
        port = gniazdo.getsockname()[1]
    atrapa = DetektorZLicznikiem()
    app = create_app(KonfigSerwera(token_plik=konfig_serwera.token_plik, port=port), detektor=atrapa)
    serwer = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    watek = threading.Thread(target=serwer.run, daemon=True)
    watek.start()
    for _ in range(100):
        if serwer.started:
            break
        time.sleep(0.05)
    assert serwer.started
    yield f"http://127.0.0.1:{port}", atrapa
    serwer.should_exit = True
    watek.join(timeout=5)


def _konfig_uzytkownika(tmp_path, adres, token_plik) -> Konfig:
    klucz = tmp_path / "klucz.b64"
    klucz.write_bytes(base64.b64encode(bytes(range(32))))
    klucz.chmod(0o600)
    return Konfig(
        klucz_plik=str(klucz),
        mapy_katalog=tmp_path / "mapy",
        modele_katalog=tmp_path / "puste-wagi",  # brak lokalnych pakietow
        inferencja_adres=adres,
        inferencja_token_plik=token_plik,
        inferencja_timeout_s=5,
    )


@pytest.mark.anyio
async def test_aplikacja_z_adresem_ukrywa_bez_lokalnych_pakietow(serwer_na_zywo, token_plik, tmp_path):
    adres, atrapa = serwer_na_zywo
    konfig = _konfig_uzytkownika(tmp_path, adres, token_plik)
    app = create_app_uzytkownika(konfig)
    naglowki = {"X-Niewidka-Token": app.state.token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8390"
    ) as klient:
        stan = (await klient.get("/api/stan", headers=naglowki)).json()
        assert stan["poziomy_dostepne"] == [1, 2, 3]  # z serwera, nie z lokalnych pakietów
        assert stan["inferencja"]["dostepny"] is True
        assert stan["inferencja"]["urzadzenie"] == ["atrapa"]
        odpowiedz = await klient.post(
            "/api/ukryj", data={"tekst": "Jan Nowak i Maria Lis.", "poziom": "2"}, headers=naglowki
        )
    assert odpowiedz.status_code == 200, odpowiedz.text
    assert atrapa.wywolania > 0
    with zipfile.ZipFile(io.BytesIO(odpowiedz.content)) as paczka:
        wynik = next(paczka.read(n) for n in paczka.namelist() if not n.endswith(".nwidka")).decode()
    assert "Jan Nowak" not in wynik and "[OSOBA_1" in wynik


@pytest.mark.anyio
async def test_serwer_nieosiagalny_to_503_bez_wyniku(token_plik, tmp_path):
    with socket.socket() as gniazdo:
        gniazdo.bind(("127.0.0.1", 0))
        port = gniazdo.getsockname()[1]  # nikt nie nasłuchuje
    konfig = _konfig_uzytkownika(tmp_path, f"http://127.0.0.1:{port}", token_plik)
    app = create_app_uzytkownika(konfig)
    naglowki = {"X-Niewidka-Token": app.state.token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8390"
    ) as klient:
        odpowiedz = await klient.post("/api/ukryj", data={"tekst": "Jan Nowak.", "poziom": "1"}, headers=naglowki)
        stan = (await klient.get("/api/stan", headers=naglowki)).json()
    assert odpowiedz.status_code == 503
    assert "Serwer modeli nie odpowiada" in odpowiedz.json()["blad"]
    assert "Jan Nowak" not in odpowiedz.text
    assert stan["poziomy_dostepne"] == [] and stan["inferencja"]["dostepny"] is False


def test_stan_serwera_z_zlym_tokenem(serwer_na_zywo, tmp_path):
    adres, _ = serwer_na_zywo
    obcy = tmp_path / "obcy"
    si.zapisz_nowy_token(obcy)
    klient = zbuduj_klienta(Konfig(inferencja_adres=adres, inferencja_token_plik=obcy))
    with pytest.raises(SerwerModeliNiedostepny, match="token"):
        stan_serwera(klient)


def test_watki_trafiaja_do_sesji_onnx(monkeypatch):
    import types

    import onnxruntime

    from niewidka.detektory import OnnxDetektor

    zebrane: list[int | None] = []

    class Sesja:
        def get_inputs(self):
            return [types.SimpleNamespace(name=n) for n in ("input_ids", "attention_mask")]

    def falszywa_sesja(bajty, providers, sess_options=None):
        zebrane.append(sess_options.intra_op_num_threads if sess_options else None)
        return Sesja()

    monkeypatch.setattr(onnxruntime, "InferenceSession", falszywa_sesja)
    for watki in (3, 0):
        OnnxDetektor("x", b"m", b"{}", {}, {}, tokenizer_obj=object(), laduj_manifest=False, watki=watki)
    assert zebrane == [3, None]  # 0 = domyślne ustawienia onnxruntime
