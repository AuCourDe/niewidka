"""Desktop tests: okno.py - API in a thread, free port, weights next to the app,
map key in the system store (first run = explicit setup screen),
closing the window = stopping the server. pywebview mocked; real server on 127.0.0.1.
"""

from __future__ import annotations

import base64
import json
import re
import socket
import sys
import urllib.request
from pathlib import Path
from typing import Any

import keyring
import pytest

from niewidka import okno
from niewidka.konfig import Konfig
from niewidka.model import TypEncji

KLUCZ = base64.b64encode(bytes(range(32))).decode()
USLUGA = "niewidka-testy"


class AtrapaDetektora:
    """Detector injected instead of weights (tests do not load ONNX)."""

    nazwa = "atrapa"
    typy = frozenset({TypEncji.OSOBA})

    def znajdz(self, tekst: str) -> list:
        return []


class AtrapaOkna:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.wczytane_url: list[str] = []

    def load_url(self, url: str) -> None:
        self.wczytane_url.append(url)


def _token_z_strony(url: str) -> str:
    """Session token from the main page meta (the same flow as the browser)."""
    with urllib.request.urlopen(url, timeout=5) as odpowiedz:
        strona = odpowiedz.read().decode("utf-8")
    dopasowanie = re.search(r'<meta name="niewidka-token" content="([^"]*)"', strona)
    assert dopasowanie, "strona startowa bez tokenu sesji"
    return dopasowanie.group(1)


class AtrapaWebview:
    """create_window/start like pywebview; start() = the user closed the window."""

    def __init__(self):
        self.okna: list[AtrapaOkna] = []
        self.status_podczas_startu: int | None = None
        self.blad: Exception | None = None

    def create_window(self, *args: Any, **kwargs: Any) -> AtrapaOkna:
        atrapa = AtrapaOkna(**kwargs)
        self.okna.append(atrapa)
        return atrapa

    def start(self) -> None:
        url = self.okna[0].kwargs.get("url")
        if not url:
            return
        try:
            # the API guards the token also on GET /api/stan and /api/pakiety,
            # so the stub takes the token from meta like a real browser
            zadanie = urllib.request.Request(
                f"{url}api/stan", headers={"X-Niewidka-Token": _token_z_strony(url)}
            )
            with urllib.request.urlopen(zadanie, timeout=5) as odpowiedz:
                self.status_podczas_startu = odpowiedz.status
        except Exception as blad:  # noqa: BLE001 — the stub collects everything for assertions
            self.blad = blad


@pytest.fixture()
def srodowisko(monkeypatch, tmp_path):
    """Isolated desktop env: test keyring service, weights irrelevant (stub)."""
    monkeypatch.setenv("NIEWIDKA_KEYRING_USLUGA", USLUGA)
    monkeypatch.delenv("NIEWIDKA_PORT", raising=False)
    monkeypatch.delenv("NIEWIDKA_KLUCZ_PLIK", raising=False)
    monkeypatch.delenv("NIEWIDKA_MODELE_KATALOG", raising=False)
    # the user data directory also in tmp: otherwise the test sees real weights from the profile
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profil"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "profil"))
    monkeypatch.setenv("NIEWIDKA_REJESTR_MAP", str(tmp_path / "wydane-mapy.jsonl"))


def _port_z_url(url: str) -> int:
    return int(url.split(":")[2].split("/")[0])


def test_port_wolny_zwraca_ponownie_wiazalny_port():
    port = okno.port_wolny()
    assert 1024 <= port <= 65535
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as gniazdo:
        gniazdo.bind(("127.0.0.1", port))  # port released by port_wolny


def test_rozwiaz_port_env_ma_pierwszenstwo(monkeypatch):
    monkeypatch.setenv("NIEWIDKA_PORT", "8971")
    assert okno.rozwiaz_port() == 8971
    monkeypatch.delenv("NIEWIDKA_PORT")
    assert 1024 <= okno.rozwiaz_port() <= 65535


def test_przygotuj_srodowisko_dane_poza_katalogiem_programu(monkeypatch, tmp_path):
    # replacing the program folder on update must not delete the weights or the map registry
    program = tmp_path / "program"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(program / "Niewidka.exe"))
    env = {"LOCALAPPDATA": str(tmp_path / "profil"), "XDG_DATA_HOME": str(tmp_path / "profil")}
    okno.przygotuj_srodowisko(env)
    dane = tmp_path / "profil" / "Niewidka"
    assert env["NIEWIDKA_MODELE_KATALOG"] == str(dane / "modele")
    assert env["NIEWIDKA_REJESTR_MAP"] == str(dane / "wydane-mapy.jsonl")
    assert program not in Path(env["NIEWIDKA_REJESTR_MAP"]).parents


def test_przygotuj_srodowisko_jawne_env_wygywa(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Niewidka.exe"))
    env = {"NIEWIDKA_MODELE_KATALOG": r"D:\wagi\niewidka"}
    okno.przygotuj_srodowisko(env)
    assert env["NIEWIDKA_MODELE_KATALOG"] == r"D:\wagi\niewidka"


def test_uruchom_startuje_serwer_i_zatrzymuje_po_zamknieciu_okna(srodowisko, keyring_pamieciowy):
    keyring.set_password(USLUGA, "mapa", KLUCZ)
    atrapa = AtrapaWebview()
    kod = okno.uruchom(detektor=AtrapaDetektora(), webview=atrapa)
    assert kod == 0
    # the window got the app URL (not the setup screen), the server was answering meanwhile
    kwargs = atrapa.okna[0].kwargs
    assert kwargs["url"].startswith("http://127.0.0.1:")
    assert atrapa.status_podczas_startu == 200, atrapa.blad
    # closing the window stopped the server
    port = _port_z_url(kwargs["url"])
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stan", timeout=1)


def test_uruchom_bez_klucza_pokazuje_jawny_ekran_konfiguracji(srodowisko, keyring_pamieciowy):
    atrapa = AtrapaWebview()
    kod = okno.uruchom(detektor=AtrapaDetektora(), webview=atrapa)
    assert kod == 0
    kwargs = atrapa.okna[0].kwargs
    assert "url" not in kwargs  # does not enter the app without a key
    tresc = kwargs["html"]
    assert "klucz" in tresc.lower()
    assert "pywebview" in tresc  # the button talks through the js_api bridge
    assert isinstance(kwargs["js_api"], okno.Most)


def test_most_utworz_klucz_zapisuje_i_przechodzi_do_aplikacji(srodowisko, keyring_pamieciowy):
    atrapa = AtrapaWebview()
    okno.uruchom(detektor=AtrapaDetektora(), webview=atrapa)
    okno_atrapa = atrapa.okna[0]
    most: okno.Most = okno_atrapa.kwargs["js_api"]
    assert most.utworz_klucz() == {"stan": "ok"}
    zapisane = keyring.get_password(USLUGA, "mapa")
    assert len(base64.b64decode(zapisane)) == 32
    assert most.otworz_aplikacje() == {"stan": "ok"}
    assert okno_atrapa.wczytane_url[0].startswith("http://127.0.0.1:")


def test_most_nie_nadpisuje_istniejacego_klucza(srodowisko, keyring_pamieciowy):
    keyring.set_password(USLUGA, "mapa", KLUCZ)
    atrapa = AtrapaWebview()
    okno.uruchom(detektor=AtrapaDetektora(), webview=atrapa)
    most: okno.Most = atrapa.okna[0].kwargs["js_api"]
    assert most.utworz_klucz() == {"stan": "jest"}
    assert keyring.get_password(USLUGA, "mapa") == KLUCZ


def test_most_blad_magazynu_jest_jawny(srodowisko, keyring_pamieciowy):
    def padajacy(usluga: str, konto: str, haslo: str) -> None:
        raise RuntimeError("symulowany pad magazynu")

    keyring_pamieciowy.set_password = padajacy  # type: ignore[method-assign]
    atrapa = AtrapaWebview()
    okno.uruchom(detektor=AtrapaDetektora(), webview=atrapa)
    most: okno.Most = atrapa.okna[0].kwargs["js_api"]
    wynik = most.utworz_klucz()
    assert wynik["stan"] == "blad"
    assert "magazyn" in wynik["komunikat"]


def test_uruchom_bez_wag_aplikacja_wstaje_z_ekranem_pakietow(srodowisko, keyring_pamieciowy):
    """Missing weights do NOT kill startup: the app comes up, and a missing
        package leads to the first-run screen in the web UI (GET /api/pakiety = missing)."""
    keyring.set_password(USLUGA, "mapa", KLUCZ)

    class AtrapaZPakietami(AtrapaWebview):
        def start(self):
            url = self.okna[0].kwargs.get("url")
            if not url:
                return
            zadanie = urllib.request.Request(
                f"{url}api/pakiety", headers={"X-Niewidka-Token": _token_z_strony(url)}
            )
            with urllib.request.urlopen(zadanie, timeout=5) as odpowiedz:
                self.dane_pakietow = json.loads(odpowiedz.read())

    atrapa = AtrapaZPakietami()
    kod = okno.uruchom(detektor=None, webview=atrapa)
    assert kod == 0
    dane = atrapa.dane_pakietow
    assert dane["poziomy_dostepne"] == []
    assert dane["pakiety"][0]["stan"] == "brak"


def test_ekran_konfiguracji_ma_klucz_i_konfig_konfiguracja(srodowisko):
    # the bridge must get the configuration from the same instance the app reads
    atrapa = AtrapaWebview()
    okno.uruchom(detektor=AtrapaDetektora(), webview=atrapa)
    most: okno.Most = atrapa.okna[0].kwargs["js_api"]
    assert most._konfig.keyring_usluga == USLUGA


def test_awaria_importu_webview_ma_komunikat_systemowy(srodowisko, keyring_pamieciowy, monkeypatch):
    """webview not importable: a windowed process must not die silently (no console)."""
    monkeypatch.setitem(sys.modules, "webview", None)  # importing webview raises ImportError
    zapisane: list[str] = []
    monkeypatch.setattr(okno, "_komunikat_systemowy", zapisane.append)
    kod = okno.uruchom(detektor=AtrapaDetektora())
    assert kod == 1
    assert zapisane and "Niewidka" in zapisane[0]


def test_awaria_okna_webview_ma_fallback_systemowy(srodowisko, keyring_pamieciowy, monkeypatch):
    """create_window failed (e.g. missing webview resources): the message goes to the system."""

    class AtrapaPadajaca(AtrapaWebview):
        def create_window(self, *args, **kwargs):
            raise RuntimeError("Directory 'webview' does not exist")

    zapisane: list[str] = []
    monkeypatch.setattr(okno, "_komunikat_systemowy", zapisane.append)
    kod = okno.uruchom(detektor=AtrapaDetektora(), webview=AtrapaPadajaca())
    assert kod == 1
    assert zapisane and "webview" in zapisane[0]


def test_strumienie_do_pliku_z_logiem(monkeypatch, tmp_path):
    """In a frozen app the streams go to NIEWIDKA_LOG_PLIK."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cel = tmp_path / "niewidka.log"
    okno._ukryj_strumienie_bez_konsoli({"NIEWIDKA_LOG_PLIK": str(cel)})
    print("probna linia", file=sys.stderr)
    sys.stderr.flush()
    assert "probna linia" in cel.read_text(encoding="utf-8")
    # Windows: a handle open for the process lifetime blocks deleting the file
    sys.stdout.close()


def test_strumienie_w_zamrozonym_zastepuja_nieme_atrapy(monkeypatch, tmp_path):
    """PyInstaller --windowed gives stdout/stderr as mute stubs (not None):
        the redirect must work then too, otherwise logs vanish silently."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", object(), raising=False)
    monkeypatch.setattr(sys, "stderr", object(), raising=False)
    cel = tmp_path / "niewidka.log"
    okno._ukryj_strumienie_bez_konsoli({"NIEWIDKA_LOG_PLIK": str(cel)})
    print("atrapy nadpisane", file=sys.stderr)
    sys.stderr.flush()
    assert "atrapy nadpisane" in cel.read_text(encoding="utf-8")
    sys.stdout.close()


def test_strumienie_w_rozwoju_nietkniete(monkeypatch):
    """Without freezing (development with a console) the real streams stay."""
    stary = sys.stderr
    monkeypatch.delattr(sys, "frozen", raising=False)
    okno._ukryj_strumienie_bez_konsoli({})
    assert sys.stderr is stary


def test_uruchom_ustawia_katalog_roboczy_na_aplikacje(srodowisko, keyring_pamieciowy, monkeypatch):
    """Starting from a UNC share inherits a cwd on UNC, on which WebView2 hangs: uruchom
        must first move the cwd to the app directory."""
    zrobione: list[str] = []
    monkeypatch.setattr(okno, "ustaw_katalog_roboczy", lambda: zrobione.append("x"))
    okno.uruchom(detektor=AtrapaDetektora(), webview=AtrapaWebview())
    assert zrobione == ["x"]


def test_ustaw_katalog_roboczy_celuje_w_katalog_aplikacji(monkeypatch):
    cel: list[str] = []
    monkeypatch.setattr(okno.os, "chdir", lambda sciezka: cel.append(str(sciezka)))
    okno.ustaw_katalog_roboczy()
    assert cel == [str(okno.katalog_aplikacji())]


def test_awaria_watku_serwera_zostaje_w_logu(monkeypatch, tmp_path):
    """An exception in the uvicorn thread must not vanish silently: the traceback goes to stderr."""
    class PadliwySerwer:
        started = False

        def run(self):
            raise RuntimeError("wątek padł")

    serwer = okno.Serwer.__new__(okno.Serwer)
    serwer._server = PadliwySerwer()
    serwer._watek = None
    uchwyt = open(tmp_path / "log.txt", "w", encoding="utf-8", buffering=1)  # noqa: SIM115 — closed in the test
    monkeypatch.setattr(sys, "stderr", uchwyt)
    serwer.start()
    serwer._watek.join(timeout=5)
    uchwyt.close()
    zawartosc = (tmp_path / "log.txt").read_text(encoding="utf-8")
    assert "wątek padł" in zawartosc
    assert "Traceback" in zawartosc


def test_teksty_gui_bez_polpauz_i_pauz():
    """Zero en/em dashes in GUI texts."""
    for tresc in (okno.STRONA_KONFIGURACJI, okno.strona_bledu("przykładowy komunikat")):
        assert "–" not in tresc
        assert "—" not in tresc


def test_most_wystawia_tylko_dwie_metody(tmp_path):
    """Live EXE run: pywebview recursively inspects public attributes of
        js_api from a non-UI thread; a public `okno` led to WebView2 (.NET) objects
        and deadlocked the whole process (the server and package downloads stalled)."""
    most = okno.Most(Konfig(klucz_plik=tmp_path / "k"), "http://127.0.0.1:1/")
    most._okno = object()
    publiczne = {n for n in dir(most) if not n.startswith("_")}
    assert publiczne == {"utworz_klucz", "otworz_aplikacje"}


class AtrapaWebviewZOrigin(AtrapaWebview):
    """Like WebView2: a POST from the window carries the page's Origin header (free port)."""

    def start(self) -> None:
        url = self.okna[0].kwargs["url"]
        zadanie = urllib.request.Request(
            f"{url}api/ukryj",
            data=b"tekst=Jan+Kowalski&poziom=1",
            headers={"X-Niewidka-Token": _token_z_strony(url), "Origin": url.rstrip("/")},
        )
        try:
            with urllib.request.urlopen(zadanie, timeout=5) as odpowiedz:
                self.status_podczas_startu = odpowiedz.status
        except urllib.error.HTTPError as blad:
            self.status_podczas_startu = blad.code


def test_okno_na_wolnym_porcie_przyjmuje_origin_wlasnej_strony(srodowisko, keyring_pamieciowy):
    # the window's server ran on a free port, while create_app knew only
    # konfig.port (8390) -> every POST from the window got 403 'niedozwolony Origin'
    keyring.set_password(USLUGA, "mapa", KLUCZ)
    atrapa = AtrapaWebviewZOrigin()
    assert okno.uruchom(detektor=AtrapaDetektora(), webview=atrapa) == 0
    assert atrapa.status_podczas_startu == 200


def test_okno_pozwala_pobierac_pliki(srodowisko, keyring_pamieciowy):
    # pywebview has ALLOW_DOWNLOADS=False by default
    # and WebView2 cancelled downloading the result, map and restored document
    keyring.set_password(USLUGA, "mapa", KLUCZ)
    atrapa = AtrapaWebview()
    atrapa.settings = {"ALLOW_DOWNLOADS": False}
    okno.uruchom(detektor=AtrapaDetektora(), webview=atrapa)
    assert atrapa.settings["ALLOW_DOWNLOADS"] is True


def test_przygotuj_srodowisko_magazyn_map_w_katalogu_danych(monkeypatch, tmp_path):
    # the map store sits next to the weights and registry: a program update does not delete it
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Niewidka.exe"))
    env = {"LOCALAPPDATA": str(tmp_path / "profil"), "XDG_DATA_HOME": str(tmp_path / "profil")}
    okno.przygotuj_srodowisko(env)
    dane = tmp_path / "profil" / "Niewidka"
    assert env["NIEWIDKA_MAPY_KATALOG"] == str(dane / "mapy")


def test_przygotuj_srodowisko_magazyn_jawne_env_wygywa(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Niewidka.exe"))
    env = {"NIEWIDKA_MAPY_KATALOG": r"D:\mapy-magazyn"}
    okno.przygotuj_srodowisko(env)
    assert env["NIEWIDKA_MAPY_KATALOG"] == r"D:\mapy-magazyn"
