"""Windowed application: pywebview + the Niewidka API in one process, uvicorn on 127.0.0.1
(fixed port only from NIEWIDKA_PORT). The map key lives in the system store; without a key the first
screen is setup. Build: narzedzia/zbuduj_windows.ps1.
"""

from __future__ import annotations

import html
import multiprocessing
import os
import re
import socket
import sys
import threading
import time
import traceback
from collections.abc import MutableMapping
from dataclasses import replace
from pathlib import Path

import uvicorn

from niewidka.api import create_app
from niewidka.klucze import BrakKlucza, KluczJuzIstnieje, pobierz_klucz, utworz_klucz_w_keyringu
from niewidka.konfig import Konfig, host_w_adresie, wczytaj_konfig
from niewidka.pakiety import katalog_danych, katalog_modeli

CZAS_NA_START_S = 30
SZEROKOSC_OKNA = 1100
WYSOKOSC_OKNA = 860

STRONA_KONFIGURACJI = """<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>Niewidka: klucz mapy</title>
<style>
  :root { color-scheme: light; }
  body { margin: 0; font-family: system-ui, sans-serif; background: #FBFBF9; color: #23282D;
         display: grid; place-items: center; min-height: 100vh; }
  main { max-width: 34rem; background: #fff; border: 1px solid #E3E1DA; border-radius: 10px;
         padding: 2rem 2.25rem; }
  h1 { font-size: 1.35rem; margin: 0 0 .75rem; }
  p { line-height: 1.55; margin: .5rem 0; }
  button { margin-top: 1rem; padding: .6rem 1.2rem; font-size: 1rem; background: #2D4A6B;
           color: #fff; border: 0; border-radius: 8px; cursor: pointer; }
  button:disabled { opacity: .6; cursor: wait; }
  #komunikat.ok { color: #1F6B3A; }
  #komunikat.blad { color: #8A1F2B; }
</style>
</head>
<body>
<main>
  <h1>Ustaw klucz mapy</h1>
  <p>Niewidka szyfruje pliki przywracania (.nwidka) kluczem mapy. Klucz powstaje raz,
  lokalnie, i trafi do magazynu haseł tego komputera (w Windows: Menedżer poświadczeń).
  Nigdy nie opuszcza urządzenia i nie zapisuje się jako plik.</p>
  <p>Bez klucza ukrywanie i przywracanie danych nie zadziała.</p>
  <button id="utworz" type="button">Utwórz klucz</button>
  <p id="komunikat" aria-live="polite"></p>
</main>
<script>
const przycisk = document.getElementById('utworz');
const komunikat = document.getElementById('komunikat');
function pokaz(tresc, klasa) { komunikat.textContent = tresc; komunikat.className = klasa || ''; }
przycisk.addEventListener('click', async () => {
  przycisk.disabled = true;
  przycisk.textContent = 'Tworzę klucz...';
  try {
    const wynik = await window.pywebview.api.utworz_klucz();
    if (wynik.stan === 'ok' || wynik.stan === 'jest') {
      pokaz('Klucz gotowy. Otwieram aplikację...', 'ok');
      await window.pywebview.api.otworz_aplikacje();
    } else {
      pokaz(wynik.komunikat || 'Nie udało się utworzyć klucza.', 'blad');
      przycisk.disabled = false;
      przycisk.textContent = 'Spróbuj ponownie';
    }
  } catch (blad) {
    pokaz('Brak połączenia z aplikacją. Uruchom Niewidkę ponownie.', 'blad');
    przycisk.disabled = false;
  }
});
</script>
</body>
</html>
"""

_SZABLON_BLEDU = """<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>Niewidka: nie można wystartować</title>
<style>
  :root { color-scheme: light; }
  body { margin: 0; font-family: system-ui, sans-serif; background: #FBFBF9; color: #23282D;
         display: grid; place-items: center; min-height: 100vh; }
  main { max-width: 34rem; background: #fff; border: 1px solid #E3E1DA; border-radius: 10px;
         padding: 2rem 2.25rem; }
  h1 { font-size: 1.35rem; margin: 0 0 .75rem; }
  p { line-height: 1.55; margin: .5rem 0; }
  code { background: #F1EFE9; padding: .1rem .35rem; border-radius: 4px; }
</style>
</head>
<body>
<main>
  <h1>Nie można wystartować</h1>
  <p>__KOMUNIKAT__</p>
  <p>Sprawdź, czy katalog wag <code>modele</code> leży obok programu (albo ustaw zmienną
  <code>NIEWIDKA_MODELE_KATALOG</code>), i uruchom Niewidkę ponownie.</p>
</main>
</body>
</html>
"""


def strona_bledu(komunikat: str) -> str:
    return _SZABLON_BLEDU.replace("__KOMUNIKAT__", html.escape(komunikat))


def katalog_aplikacji() -> Path:
    """Program directory: the exe directory in a PyInstaller bundle, the repo directory in development."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def przygotuj_srodowisko(env: MutableMapping[str, str] | None = None) -> None:
    """Launcher: weights and the map registry in the user data directory, not next to the exe
    (an update swaps the program folder); an explicit env wins (setdefault)."""
    env = os.environ if env is None else env
    env.setdefault("NIEWIDKA_MODELE_KATALOG", str(katalog_modeli(env)))
    # the map must be restorable after closing and reopening the window (2026-10-29)
    env.setdefault("NIEWIDKA_REJESTR_MAP", str(katalog_danych(env) / "wydane-mapy.jsonl"))
    # map store with retention in the data directory
    env.setdefault("NIEWIDKA_MAPY_KATALOG", str(katalog_danych(env) / "mapy"))


def port_wolny() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as gniazdo:
        gniazdo.bind(("127.0.0.1", 0))
        return int(gniazdo.getsockname()[1])


def rozwiaz_port(env: MutableMapping[str, str] | None = None) -> int:
    """Fixed port only on explicit request (NIEWIDKA_PORT); otherwise a free one.
    SIMPLIFICATION: there is a theoretical race between port_wolny() and the uvicorn bind;
    on a collision the server will not start and the window shows an error screen."""
    env = os.environ if env is None else env
    podany = env.get("NIEWIDKA_PORT", "")
    return int(podany) if podany else port_wolny()


def _ukryj_strumienie_bez_konsoli(env: MutableMapping[str, str] | None = None) -> None:
    """A --windowed bundle: stdout/stderr are None or mute PyInstaller stubs,
    so uvicorn's first logs vanish silently. In a frozen app both
    streams always go to devnull (Niewidka logs carry no document content);
    NIEWIDKA_LOG_PLIK redirects them to a file (diagnostics for IT)."""
    if not getattr(sys, "frozen", False):
        return  # development with a console: real streams, leave them alone
    env = os.environ if env is None else env
    cel = env.get("NIEWIDKA_LOG_PLIK") or os.devnull
    # buffering=1: tracebacks from the server thread must reach the file at once, not sit in a buffer
    uchwyt = open(cel, "w", encoding="utf-8", buffering=1)  # noqa: SIM115 - for the life of the process
    sys.stdout = uchwyt
    sys.stderr = uchwyt


def ustaw_katalog_roboczy() -> None:
    """cwd to the application directory: a GUI started from lim/tunnels (WSL, scheduler)
    inherits a UNC-path cwd on which WebView2 hangs, and the bind can fail;
    this also makes niewidka.toml next to the exe readable."""
    os.chdir(katalog_aplikacji())


class Serwer:
    """Uvicorn in a daemon thread; wait for started, stop when the window closes."""

    def __init__(self, aplikacja, host: str, port: int):
        self._server = uvicorn.Server(
            uvicorn.Config(aplikacja, host=host, port=port, log_level="warning")
        )
        self._watek: threading.Thread | None = None

    def start(self) -> None:
        def _run_z_logiem():
            try:
                self._server.run()
            except Exception:  # noqa: BLE001 - deliberately everything: log instead of a silent thread death
                # without a console: the server thread's trace must stay in the log (NIEWIDKA_LOG_PLIK)
                traceback.print_exc()

        self._watek = threading.Thread(target=_run_z_logiem, name="niewidka-serwer", daemon=True)
        self._watek.start()

    def czekaj_na_gotowosc(self, limit_s: int = CZAS_NA_START_S) -> bool:
        koniec = time.monotonic() + limit_s
        while time.monotonic() < koniec and not self._server.started:
            time.sleep(0.05)
        return bool(self._server.started)

    def zatrzymaj(self) -> None:
        self._server.should_exit = True
        if self._watek is not None:
            self._watek.join(timeout=10)


class Most:
    """The only thing the page may call in the process (pywebview js_api): creating
    a key in the system store and moving on to the app. No document content."""

    def __init__(self, konfig: Konfig, url: str):
        self._konfig = konfig
        self._url = url
        self._okno = None  # after create_window; private: pywebview does not walk attributes starting with "_"

    def utworz_klucz(self) -> dict:
        try:
            utworz_klucz_w_keyringu(self._konfig.keyring_usluga)
        except KluczJuzIstnieje:
            return {"stan": "jest"}
        except Exception as blad:  # noqa: BLE001 - a store failure is shown in the window
            return {
                "stan": "blad",
                "komunikat": f"Nie udało się zapisać klucza w magazynie systemowym: {blad}",
            }
        return {"stan": "ok"}

    def otworz_aplikacje(self) -> dict:
        if self._okno is not None:
            self._okno.load_url(self._url)
        return {"stan": "ok"}


def _komunikat_systemowy(tresc: str) -> None:
    """Last resort: a native message box when webview itself does not work."""
    czysty = re.sub(r"\n{2,}", "\n", re.sub(r"<[^>]+>", "\n", tresc)).strip()
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, czysty, "Niewidka", 0x10)  # MB_ICONERROR
    except Exception:  # noqa: BLE001 - no windll (POSIX): stderr, so we do not die silently
        print(czysty, file=sys.stderr)


def _pokaz(modul_webview, tresc: str) -> None:
    """Startup failure screen: a window with a message; when webview itself fails,
    a native system message (a console-less app must not die silently)."""
    if modul_webview is not None:
        try:
            modul_webview.create_window("Niewidka", html=tresc, width=640, height=420)
            modul_webview.start()
            return
        except Exception as blad:  # noqa: BLE001 - webview failed: the system message remains
            print(f"webview nie zadziałal: {type(blad).__name__}", file=sys.stderr)
    _komunikat_systemowy(tresc)


def uruchom(*, detektor=None, webview=None) -> int:
    """Windowed entry point: server in a thread + pywebview window. Returns 0 after the
    window closes, 1 on a startup failure (error screen). `detektor` and `webview` are injected
    in tests; None in production (weights from the app directory, real pywebview)."""
    multiprocessing.freeze_support()
    _ukryj_strumienie_bez_konsoli()
    przygotuj_srodowisko()
    ustaw_katalog_roboczy()
    print(f"start: cwd={os.getcwd()} wagi={os.environ.get('NIEWIDKA_MODELE_KATALOG')}", file=sys.stderr)
    modul_webview = webview
    try:
        if modul_webview is None:
            import webview

            modul_webview = webview
        # without this WebView2 cancels downloading the result, map and restored document
        # (pywebview: ALLOW_DOWNLOADS defaults to False)
        if isinstance(getattr(modul_webview, "settings", None), dict):
            modul_webview.settings["ALLOW_DOWNLOADS"] = True
        # port BEFORE create_app: the Origin check must know the port the window
        # is served on (free port != konfig.port -> every POST from the window gets 403)
        konfig = replace(wczytaj_konfig(), port=rozwiaz_port())
        # loading weights here = SHA-256 manifest check at startup (detektory.py)
        aplikacja = create_app(konfig, detektor=detektor)
        print("start: wagi i aplikacja OK", file=sys.stderr)
    except Exception as blad:  # noqa: BLE001 - windowed app without a console: a failure must be visible
        print(f"awaria startu: {type(blad).__name__}: {blad}", file=sys.stderr)
        _pokaz(modul_webview, strona_bledu(f"{type(blad).__name__}: {blad}"))
        return 1

    port = konfig.port
    serwer = Serwer(aplikacja, konfig.host, port)
    serwer.start()
    print(f"start: wątek serwera odpalony, port={port}", file=sys.stderr)
    if not serwer.czekaj_na_gotowosc():
        print("start: serwer NIE wstał", file=sys.stderr)
        serwer.zatrzymaj()
        serwer.zatrzymaj()
        _pokaz(
            modul_webview,
            strona_bledu(
                "Lokalny serwer Niewidki nie wystartował. Jeśli port jest zajęty, ustaw "
                "NIEWIDKA_PORT na wolny numer i uruchom program ponownie."
            ),
        )
        return 1

    url = f"http://{host_w_adresie(konfig.host)}:{port}/"
    most = Most(konfig, url)
    try:
        pobierz_klucz(konfig)
        strona, tytul = url, "Niewidka"
    except BrakKlucza:
        strona, tytul = None, "Niewidka: konfiguracja klucza"
    print(f"start: tworzę okno ({tytul})", file=sys.stderr)
    try:
        if strona is None:
            most._okno = modul_webview.create_window(
                tytul,
                html=STRONA_KONFIGURACJI,
                js_api=most,
                width=SZEROKOSC_OKNA,
                height=WYSOKOSC_OKNA,
            )
        else:
            most._okno = modul_webview.create_window(
                tytul,
                url=strona,
                js_api=most,
                width=SZEROKOSC_OKNA,
                height=WYSOKOSC_OKNA,
            )
        modul_webview.start()
    except Exception as blad:  # noqa: BLE001 - window failure: system message, not silence
        print(f"awaria okna: {type(blad).__name__}: {blad}", file=sys.stderr)
        serwer.zatrzymaj()
        _pokaz(modul_webview, strona_bledu(f"{type(blad).__name__}: {blad}"))
        return 1
    serwer.zatrzymaj()  # closing the window ends the server
    return 0


if __name__ == "__main__":
    raise SystemExit(uruchom())
