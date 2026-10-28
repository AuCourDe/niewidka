"""Testy desktopu (K6): okno.py — API w wątku, wolny port, wagi obok aplikacji,
klucz mapy w magazynie systemowym (pierwsze uruchomienie = jawny ekran konfiguracji),
zamknięcie okna = zatrzymanie serwera. pywebview mockowany; serwer realny na 127.0.0.1.
"""

from __future__ import annotations

import base64
import json
import re
import socket
import sys
import urllib.request
from typing import Any

import keyring
import pytest

from niewidka import okno
from niewidka.model import TypEncji

KLUCZ = base64.b64encode(bytes(range(32))).decode()
USLUGA = "niewidka-testy"


class AtrapaDetektora:
    """Detektor wstrzyknięty zamiast wag (testy nie ładują ONNX)."""

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
    """Token sesji z meta strony głównej (ten przepływ co przeglądarka)."""
    with urllib.request.urlopen(url, timeout=5) as odpowiedz:
        strona = odpowiedz.read().decode("utf-8")
    dopasowanie = re.search(r'<meta name="niewidka-token" content="([^"]*)"', strona)
    assert dopasowanie, "strona startowa bez tokenu sesji"
    return dopasowanie.group(1)


class AtrapaWebview:
    """create_window/start jak w pywebview; start() = użytkownik zamknął okno."""

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
            # K7c pkt 5: API pilnuje tokenu także na GET /api/stan i /api/pakiety,
            # więc atrapa bierze token z meta jak prawdziwa przeglądarka
            zadanie = urllib.request.Request(
                f"{url}api/stan", headers={"X-Niewidka-Token": _token_z_strony(url)}
            )
            with urllib.request.urlopen(zadanie, timeout=5) as odpowiedz:
                self.status_podczas_startu = odpowiedz.status
        except Exception as blad:  # noqa: BLE001 — atrapa zbiera wszystko do asercji
            self.blad = blad


@pytest.fixture()
def srodowisko(monkeypatch, tmp_path):
    """Izolowane env desktopu: usługa keyringa testowa, wagi bez znaczenia (atrapa)."""
    monkeypatch.setenv("NIEWIDKA_KEYRING_USLUGA", USLUGA)
    monkeypatch.delenv("NIEWIDKA_PORT", raising=False)
    monkeypatch.delenv("NIEWIDKA_KLUCZ_PLIK", raising=False)
    monkeypatch.delenv("NIEWIDKA_MODELE_KATALOG", raising=False)


def _port_z_url(url: str) -> int:
    return int(url.split(":")[2].split("/")[0])


def test_port_wolny_zwraca_ponownie_wiazalny_port():
    port = okno.port_wolny()
    assert 1024 <= port <= 65535
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as gniazdo:
        gniazdo.bind(("127.0.0.1", port))  # port zwolniony przez port_wolny


def test_rozwiaz_port_env_ma_pierwszenstwo(monkeypatch):
    monkeypatch.setenv("NIEWIDKA_PORT", "8971")
    assert okno.rozwiaz_port() == 8971
    monkeypatch.delenv("NIEWIDKA_PORT")
    assert 1024 <= okno.rozwiaz_port() <= 65535


def test_przygotuj_srodowisko_wagi_obok_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Niewidka.exe"))
    env: dict[str, str] = {}
    okno.przygotuj_srodowisko(env)
    assert env["NIEWIDKA_MODELE_KATALOG"] == str(tmp_path / "modele")


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
    # okno dostało URL aplikacji (nie ekran konfiguracji), serwer odpowiadał w trakcie
    kwargs = atrapa.okna[0].kwargs
    assert kwargs["url"].startswith("http://127.0.0.1:")
    assert atrapa.status_podczas_startu == 200, atrapa.blad
    # zamknięcie okna zatrzymało serwer
    port = _port_z_url(kwargs["url"])
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stan", timeout=1)


def test_uruchom_bez_klucza_pokazuje_jawny_ekran_konfiguracji(srodowisko, keyring_pamieciowy):
    atrapa = AtrapaWebview()
    kod = okno.uruchom(detektor=AtrapaDetektora(), webview=atrapa)
    assert kod == 0
    kwargs = atrapa.okna[0].kwargs
    assert "url" not in kwargs  # nie wchodzi do aplikacji bez klucza
    tresc = kwargs["html"]
    assert "klucz" in tresc.lower()
    assert "pywebview" in tresc  # przycisk rozmawia przez most js_api
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
    """K7b: brak wag NIE zabija startu — aplikacja wstaje, a brak pakietu
    prowadzi do ekranu pierwszego uruchomienia w web (GET /api/pakiety = brak)."""
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
    # most musi dostać konfigurację z tej samej instancji, którą czyta aplikacja
    atrapa = AtrapaWebview()
    okno.uruchom(detektor=AtrapaDetektora(), webview=atrapa)
    most: okno.Most = atrapa.okna[0].kwargs["js_api"]
    assert most.konfig.keyring_usluga == USLUGA


def test_awaria_importu_webview_ma_komunikat_systemowy(srodowisko, keyring_pamieciowy, monkeypatch):
    """webview nie do importu: proces okienkowy nie może umrzeć po cichu (bez konsoli)."""
    monkeypatch.setitem(sys.modules, "webview", None)  # import webview rzuci ImportError
    zapisane: list[str] = []
    monkeypatch.setattr(okno, "_komunikat_systemowy", zapisane.append)
    kod = okno.uruchom(detektor=AtrapaDetektora())
    assert kod == 1
    assert zapisane and "Niewidka" in zapisane[0]


def test_awaria_okna_webview_ma_fallback_systemowy(srodowisko, keyring_pamieciowy, monkeypatch):
    """create_window padło (np. brak zasobów webview): komunikat idzie do systemu."""

    class AtrapaPadajaca(AtrapaWebview):
        def create_window(self, *args, **kwargs):
            raise RuntimeError("Directory 'webview' does not exist")

    zapisane: list[str] = []
    monkeypatch.setattr(okno, "_komunikat_systemowy", zapisane.append)
    kod = okno.uruchom(detektor=AtrapaDetektora(), webview=AtrapaPadajaca())
    assert kod == 1
    assert zapisane and "webview" in zapisane[0]


def test_strumienie_do_pliku_z_logiem(monkeypatch, tmp_path):
    """W zamrożonej aplikacji strumienie idą do NIEWIDKA_LOG_PLIK."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cel = tmp_path / "niewidka.log"
    okno._ukryj_strumienie_bez_konsoli({"NIEWIDKA_LOG_PLIK": str(cel)})
    print("probna linia", file=sys.stderr)
    sys.stderr.flush()
    assert "probna linia" in cel.read_text(encoding="utf-8")
    # Windows: uchwyt otwarty na czas życia procesu blokuje usuwanie pliku
    sys.stdout.close()


def test_strumienie_w_zamrozonym_zastepuja_nieme_atrapy(monkeypatch, tmp_path):
    """PyInstaller --windowed daje stdout/stderr jako nieme atrapy (nie None):
    przekierowanie musi zadziałać też wtedy, inaczej logi znikają po cichu."""
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
    """Bez zamrożenia (rozwój z konsolą) strumienie rzeczywiste zostają."""
    stary = sys.stderr
    monkeypatch.delattr(sys, "frozen", raising=False)
    okno._ukryj_strumienie_bez_konsoli({})
    assert sys.stderr is stary


def test_uruchom_ustawia_katalog_roboczy_na_aplikacje(srodowisko, keyring_pamieciowy, monkeypatch):
    """Start z lim/tuneli dziedziczy cwd na UNC, na którym WebView2 wisi: uruchom
    musi najpierw przenieść cwd na katalog aplikacji."""
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
    """Wyjątek w wątku uvicorna nie może zniknąć po cichu: traceback idzie do stderr."""
    class PadliwySerwer:
        started = False

        def run(self):
            raise RuntimeError("wątek padł")

    serwer = okno.Serwer.__new__(okno.Serwer)
    serwer._server = PadliwySerwer()
    serwer._watek = None
    uchwyt = open(tmp_path / "log.txt", "w", encoding="utf-8", buffering=1)  # noqa: SIM115 — zamykany w teście
    monkeypatch.setattr(sys, "stderr", uchwyt)
    serwer.start()
    serwer._watek.join(timeout=5)
    uchwyt.close()
    zawartosc = (tmp_path / "log.txt").read_text(encoding="utf-8")
    assert "wątek padł" in zawartosc
    assert "Traceback" in zawartosc


def test_teksty_gui_bez_polpauz_i_pauz():
    """Zlecenie 12:55: zero półpauz i pauz w tekstach GUI."""
    for tresc in (okno.STRONA_KONFIGURACJI, okno.strona_bledu("przykładowy komunikat")):
        assert "–" not in tresc
        assert "—" not in tresc
