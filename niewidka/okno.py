"""Aplikacja okienkowa (K6): pywebview + API Niewidki w jednym procesie.

REUŻYJ: logika żyje wyłącznie w create_app (api.py) i rdzeniu; okno tylko skleja
serwer z oknem. Uvicorn w wątku na 127.0.0.1: domyślnie wolny port, stały port
wyłącznie z NIEWIDKA_PORT. Klucz mapy w magazynie systemowym (Windows: Menedżer
poświadczeń, przez keyring); pierwsze uruchomienie bez klucza = jawny ekran
konfiguracji (klucz powstaje wprost w magazynie, nigdy plik obok exe, nigdy
w kodzie ani logach). Zamknięcie okna zatrzymuje serwer. Budowa:
narzedzia/zbuduj_windows.ps1 (PyInstaller onedir, --windowed).
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
from niewidka.konfig import Konfig, wczytaj_konfig

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
    """Katalog programu: w pakiecie PyInstallera katalog exe, w rozwoju katalog repo."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def przygotuj_srodowisko(env: MutableMapping[str, str] | None = None) -> None:
    """Launcher: wagi domyślnie w <katalog aplikacji>/modele; jawne env wygrywa
    (setdefault), konfig TOML też może wskazać inne miejsce."""
    env = os.environ if env is None else env
    env.setdefault("NIEWIDKA_MODELE_KATALOG", str(katalog_aplikacji() / "modele"))


def port_wolny() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as gniazdo:
        gniazdo.bind(("127.0.0.1", 0))
        return int(gniazdo.getsockname()[1])


def rozwiaz_port(env: MutableMapping[str, str] | None = None) -> int:
    """Stały port wyłącznie na jawne żądanie (NIEWIDKA_PORT); domyślnie wolny.
    SIMPLIFICATION: między port_wolny() a bind uvicorna jest wyścig teoretyczny;
    przy zderzeniu serwer nie wstanie i okno pokaże ekran błędu."""
    env = os.environ if env is None else env
    podany = env.get("NIEWIDKA_PORT", "")
    return int(podany) if podany else port_wolny()


def _ukryj_strumienie_bez_konsoli(env: MutableMapping[str, str] | None = None) -> None:
    """Pakiet --windowed: stdout/stderr to None albo nieme atrapy PyInstallera,
    więc pierwsze logi uvicorna znikają po cichu. W zamrożonej aplikacji oba
    strumienie idą zawsze do devnull (logi Niewidki nie mają treści dokumentów,
    LLD §12); NIEWIDKA_LOG_PLIK kieruje je do pliku (diagnostyka u IT)."""
    if not getattr(sys, "frozen", False):
        return  # rozwój z konsolą: strumienie rzeczywiste, nic nie ruszamy
    env = os.environ if env is None else env
    cel = env.get("NIEWIDKA_LOG_PLIK") or os.devnull
    # buffering=1: tracebacky wątku serwera muszą do pliku od razu, nie w buforze
    uchwyt = open(cel, "w", encoding="utf-8", buffering=1)  # noqa: SIM115 — na czas życia procesu
    sys.stdout = uchwyt
    sys.stderr = uchwyt


def ustaw_katalog_roboczy() -> None:
    """cwd na katalog aplikacji: GUI startowany z lim/tuneli (WSL, harmonogram)
    dziedziczy cwd na ścieżce UNC, na której WebView2 wisi, a bind potrafi paść;
    przy okazji niewidka.toml obok exe staje się czytelny."""
    os.chdir(katalog_aplikacji())


class Serwer:
    """Uvicorn w wątku demona; czekanie na started, zatrzymanie po zamknięciu okna."""

    def __init__(self, aplikacja, host: str, port: int):
        self._server = uvicorn.Server(
            uvicorn.Config(aplikacja, host=host, port=port, log_level="warning")
        )
        self._watek: threading.Thread | None = None

    def start(self) -> None:
        def _run_z_logiem():
            try:
                self._server.run()
            except Exception:  # noqa: BLE001 — celowo wszystko: log zamiast cichej śmierci wątku
                # bez konsoli: ślad wątku serwera musi zostać w logu (NIEWIDKA_LOG_PLIK)
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
    """Jedyne, co strona może wywołać w procesie (pywebview js_api): utworzenie
    klucza w magazynie systemowym i przejście do aplikacji. Bez treści dokumentów."""

    def __init__(self, konfig: Konfig, url: str):
        self._konfig = konfig
        self._url = url
        self._okno = None  # po create_window; prywatne: pywebview nie przegląda atrybutów z „_”

    def utworz_klucz(self) -> dict:
        try:
            utworz_klucz_w_keyringu(self._konfig.keyring_usluga)
        except KluczJuzIstnieje:
            return {"stan": "jest"}
        except Exception as blad:  # noqa: BLE001 — pad magazynu pokazujemy w oknie
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
    """Ostatnia deska: natywne okno komunikatu, gdy webview sam nie działa."""
    czysty = re.sub(r"\n{2,}", "\n", re.sub(r"<[^>]+>", "\n", tresc)).strip()
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, czysty, "Niewidka", 0x10)  # MB_ICONERROR
    except Exception:  # noqa: BLE001 — brak windll (POSIX): stderr, by nie umrzeć po cichu
        print(czysty, file=sys.stderr)


def _pokaz(modul_webview, tresc: str) -> None:
    """Ekran awarii startu: okno z komunikatem; gdy webview sam nie działa,
    natywny komunikat systemowy (aplikacja bez konsoli nie może umrzeć po cichu)."""
    if modul_webview is not None:
        try:
            modul_webview.create_window("Niewidka", html=tresc, width=640, height=420)
            modul_webview.start()
            return
        except Exception as blad:  # noqa: BLE001 — webview padł: zostaje komunikat systemowy
            print(f"webview nie zadziałal: {type(blad).__name__}", file=sys.stderr)
    _komunikat_systemowy(tresc)


def uruchom(*, detektor=None, webview=None) -> int:
    """Punkt wejścia okienki: serwer w wątku + okno pywebview. Zwraca 0 po zamknięciu
    okna, 1 przy awarii startu (ekran błędu). `detektor` i `webview` wstrzykiwane
    w testach; produkcyjnie None (wagi z katalogu aplikacji, prawdziwy pywebview)."""
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
        # port PRZED create_app: kontrola Origin musi znać port, na którym stoi
        # okno (wolny port ≠ konfig.port → każdy POST z okna 403)
        konfig = replace(wczytaj_konfig(), port=rozwiaz_port())
        # ładowanie wag tu = kontrola manifestu SHA-256 przy starcie (detektory.py)
        aplikacja = create_app(konfig, detektor=detektor)
        print("start: wagi i aplikacja OK", file=sys.stderr)
    except Exception as blad:  # noqa: BLE001 — okno bez konsoli: awaria musi być widoczna
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

    url = f"http://{konfig.host}:{port}/"
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
    except Exception as blad:  # noqa: BLE001 — awaria okna: komunikat systemowy, nie cisza
        print(f"awaria okna: {type(blad).__name__}: {blad}", file=sys.stderr)
        serwer.zatrzymaj()
        _pokaz(modul_webview, strona_bledu(f"{type(blad).__name__}: {blad}"))
        return 1
    serwer.zatrzymaj()  # zamknięcie okna kończy serwer
    return 0


if __name__ == "__main__":
    raise SystemExit(uruchom())
