"""API FastAPI (K4, LLD §12): ukryj/przywroc/stan na 127.0.0.1.

Bezpieczeństwo: token sesji (generowany przy starcie), walidacja Host/Origin,
limity PRZED buforowaniem (Content-Length) i po dekompresji, pliki tylko w RAM,
Cache-Control: no-store, logi wyłącznie z UUID błędu (Gemini pkt 15), inferencja
w puli wątków z Semaphore(1) i timeoutem (Gemini pkt 5), pełna kolejka → 503.
Wynik zablokowany przez kontrolę → 422 z listą typów, bez dokumentu (K4b pkt 1).
Błędy wg LLD §15: 413/415/422/500/503; detektor fail-closed.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import secrets
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.formparsers import MultiPartParser

from niewidka import __version__
from niewidka.aktualizacje import (
    BladAktualizacji,
    MenedzerAktualizacji,
    TrybNarzucony,
)
from niewidka.archiwum import BladArchiwum
from niewidka.formaty import (
    ElementNieobslugiwany,
    NieznanyFormat,
    adapter_formatu,
    nazwa_wyniku,
    rozszerzenia_wspierane,
)
from niewidka.jakosc import opisy_ryzyka, r95_poziomy
from niewidka.klucze import BrakKlucza, pobierz_klucz
from niewidka.konfig import Konfig, wczytaj_konfig
from niewidka.kontrola import Ostrzezenie
from niewidka.magazyn import MagazynMap, kontekst_domyslny, wersje_pakietow
from niewidka.mapa import WZORZEC_ZNACZNIKA, BladMapy, Mapa, odszyfruj, zaszyfruj
from niewidka.pakiety import (
    BladPakietu,
    MenedzerPakietow,
    katalog_danych,
    katalog_modeli,
    opublikuj_bez_hasza,
    wczytaj_pakiety,
    wczytaj_wersje_katalogu,
    zrodlo,
)
from niewidka.rdzen import (
    ArchiwumZaDuze,
    identyfikator_z_dopisku,
    przywroc,
    ukryj,
    zbuduj_detektor,
)

logger = logging.getLogger("niewidka.api")

_MB = 1024 * 1024
_TOKEN_NAGLOWEK = "x-niewidka-token"
_KATALOG_WEB = Path(__file__).parent / "web"
_POZIOMY = (1, 2, 3)  # suwak jakości (K2d: 2 = wariant A, 3 = wariant B)


class BrakWymaganegoPakietu(Exception):
    """Poziom suwaka wymaga pakietu, którego nie ma (K7b → 409 z listą pakietów)."""

    def __init__(self, brakujace: list[str], nazwy: list[str] | None = None):
        self.brakujace = brakujace
        self.nazwy = nazwy or brakujace
        super().__init__(
            "brakuje pakietu modeli: "
            + ", ".join(self.nazwy)
            + "; pobierz go w Ustawieniach albo przy pierwszym uruchomieniu"
        )


class KolejkaPelna(Exception):
    """Wszystkie sloty zajęte i kolejka pełna (LLD §15 → 503 + Retry-After)."""


class PracaPrzekroczylaCzas(Exception):
    """Praca przekroczyła limit czasu; slot zostaje zajęty do jej faktycznego
    końca (K4b pkt 11 → 503, nie 500)."""


class BladKontroli(Exception):
    """Kontrola zapisu zablokowała wynik (K4b pkt 1 → 422 BEZ dokumentu)."""

    def __init__(self, typy: dict[str, int]):
        self.typy = typy
        super().__init__("kontrola zapisu zablokowała wynik")


class WybierzMape(Exception):
    """Przywracanie bez wskazania mapy: użytkownik ma wybrać z listy zadań
    (docs/MAPY-I-AKTUALIZACJE.md §3 → 422 z kodem `wybierz_mape` i kandydatami)."""

    def __init__(self, komunikat: str, kandydaci: list[dict]):
        self.kandydaci = kandydaci
        super().__init__(komunikat)


class BrakMapyWMagazynie(Exception):
    """Dopisek albo identyfikator wskazuje mapę, której nie ma w magazynie
    (wygasła, usunięta, obca sesja) → 422 z jasnym komunikatem."""


class LicznikZlecen:
    """K4b pkt 12: ogranicza liczbę żądań W TOKU (POST /api/ukryj i /api/przywroc)
    zanim cokolwiek przeczyta treść — nadmiar dostaje 503 natychmiast, więc
    uploady nie potrafią zająć pamięci, stojąc poza kolejką inferencji."""

    def __init__(self, app, limit: int):
        self.app = app
        self.limit = limit
        self.w_toku = 0

    async def __call__(self, scope, receive, send):
        sciezka = scope.get("path", "")
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not sciezka.startswith(("/api/ukryj", "/api/przywroc"))
        ):
            await self.app(scope, receive, send)
            return
        # inkrement bez await między sprawdzeniem a zapisem — atomowe w pętli zdarzeń
        if self.w_toku >= self.limit:
            await JSONResponse(
                {"blad": "za dużo równoczesnych żądań; spróbuj ponownie za chwilę"},
                status_code=503,
                headers={"retry-after": "2"},
            )(scope, receive, send)
            return
        self.w_toku += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.w_toku -= 1


class LimitBajtow:
    """K4b pkt 9: liczy bajty treści żądania PRZED parserem formularza — także
    przy transferze chunked, bez nagłówka Content-Length. Po przekroczeniu limitu
    aplikacja nie dostaje ani bajtu (nic nie wpada do buforów, spool na dysk nie
    zdąży się uruchomić), klient dostaje 413. Limit objęte są wszystkie POST-y,
    więc też /api/przywroc."""

    def __init__(self, app, limit_bajtow: int):
        self.app = app
        self.limit = limit_bajtow

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        zebrane: list[dict] = []
        stan = {"razem": 0, "przekroczone": False}

        async def odczytaj():
            message = await receive()
            if message["type"] == "http.request":
                stan["razem"] += len(message.get("body", b""))
                if stan["razem"] > self.limit:
                    stan["przekroczone"] = True
                else:
                    zebrane.append(message)
            return message

        while True:
            message = await odczytaj()
            if stan["przekroczone"]:
                break
            if message["type"] != "http.request" or not message.get("more_body"):
                break
        if stan["przekroczone"]:
            mb = self.limit // (1024 * 1024)
            await JSONResponse({"blad": f"wejście ponad limit {mb} MB"}, status_code=413)(
                scope, receive, send
            )
            return
        pozycja = {"i": 0}

        async def odtworz():
            if pozycja["i"] < len(zebrane):
                pozycja["i"] += 1
                return zebrane[pozycja["i"] - 1]
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, odtworz, send)


@dataclass
class Kolejka:
    """Jedna inferencja naraz (Semaphore w puli wątków), `kolejka` oczekujących.

    K4b pkt 11: semafor trzyma ZADANIE pracy, nie czekające żądanie — po
    timeoucie żądanie dostaje 503, a slot zostaje zajęty do FAKTYCZNEGO końca
    pracy (anulowanie oczekiwania nie zatrzymuje wątku executora)."""

    maks: int
    timeout_s: int
    czekajacy: int = 0
    _semafor: asyncio.Semaphore | None = None

    def _slot(self) -> asyncio.Semaphore:
        if self._semafor is None:  # tworzone w pętli zdarzeń, która pierwsza użyje
            self._semafor = asyncio.Semaphore(1)
        return self._semafor

    async def wykonaj(self, praca, timeout_s: int | None = None):
        limit = timeout_s or self.timeout_s
        if self._slot().locked():
            # slot zajęty: to żądanie jest kolejnym oczekującym
            if self.czekajacy >= self.maks:
                raise KolejkaPelna()
            self.czekajacy += 1
            try:
                return await self._oczekiwane(praca, limit)
            finally:
                self.czekajacy -= 1
        # slot wolny: to żądanie zakłada własne zadanie pod semaforem
        return await self._oczekiwane(praca, limit)

    async def _oczekiwane(self, praca, limit: int):
        zadanie = asyncio.create_task(self._z_slotem(praca))
        zadanie.add_done_callback(_pochlonnij_wyjatek)
        zakonczone, _ = await asyncio.wait({zadanie}, timeout=limit)
        if zadanie not in zakonczone:
            raise PracaPrzekroczylaCzas()  # zadanie pracuje dalej, trzyma slot
        return zadanie.result()

    async def _z_slotem(self, praca):
        async with self._slot():
            return await asyncio.to_thread(praca)

    def stan(self) -> dict[str, int]:
        return {"czekajacy": self.czekajacy, "maks": self.maks}


def _pochlonnij_wyjatek(zadanie: asyncio.Task) -> None:
    """Zadanie porzucone po timeoucie: pobiera wyjątek, żeby pętla zdarzeń milczała."""
    if not zadanie.cancelled():
        zadanie.exception()


def _json_naglowek(wartosc: Any) -> str:
    # Nagłówki HTTP są latin-1: polskie znaki (fragmenty ostrzeżeń) muszą uciekać
    # jako \uXXXX, inaczej odpowiedź ginie na UnicodeEncodeError (test suwaka K2d).
    return json.dumps(wartosc, ensure_ascii=True)


def _licznik_typow(ostrzezenia: list[Ostrzezenie]) -> dict[str, int]:
    """Typy znalezisk z licznikami — nagłówki i błędy nigdy nie niosą fragmentów
    ani nazw części (K4b pkt 8; wcześniejsze PII wyciekało nagłówkiem HTTP)."""
    licznik: dict[str, int] = {}
    for ostrzezenie in ostrzezenia:
        licznik[ostrzezenie.typ] = licznik.get(ostrzezenie.typ, 0) + 1
    return licznik


def _wczytaj_rejestr_map(plik: Path | None, szyfrogramy: dict[str, str], identyfikatory: set[str]) -> None:
    """Mapy wydane przed restartem (2026-10-29): bez tego zamknięcie okna kończyło
    możliwość przywrócenia. Uszkodzone wiersze pomijane (fail-closed: mapa spoza
    rejestru i tak nie przejdzie)."""
    if plik is None or not plik.is_file():
        return
    for wiersz in plik.read_text(encoding="utf-8").splitlines():
        try:
            wpis = json.loads(wiersz)
            szyfrogramy[str(wpis["sha256"])] = str(wpis["id"])
            identyfikatory.add(str(wpis["id"]))
        except (ValueError, KeyError, TypeError):
            continue


def _dopisz_do_rejestru(plik: Path | None, skrot: str, identyfikator: str) -> None:
    if plik is None:
        return
    try:
        plik.parent.mkdir(parents=True, exist_ok=True)
        with plik.open("a", encoding="utf-8") as rejestr:
            rejestr.write(json.dumps({"sha256": skrot, "id": identyfikator}) + "\n")
    except OSError as blad:  # brak zapisu = mapa działa tylko w tej sesji, nie awaria
        logger.warning("rejestr map niezapisany: %s", type(blad).__name__)


def _przepisz_rejestr(plik: Path | None, bez_identyfikatorow: set[str]) -> None:
    """Rejestr wydanych map przepisany atomowo bez skreślonych map (przegląd
    Argona pkt 3): pobrane kopie tych map przestają działać przy przywracaniu."""
    if plik is None or not plik.is_file():
        return
    wiersze = []
    for wiersz in plik.read_text(encoding="utf-8").splitlines():
        try:
            if str(json.loads(wiersz)["id"]) in bez_identyfikatorow:
                continue
        except (ValueError, KeyError, TypeError):
            pass  # uszkodzony wiersz zostaje: _wczytaj_rejestr_map i tak go pomija
        wiersze.append(wiersz)
    opublikuj_bez_hasza(
        ("\n".join(wiersze) + "\n").encode("utf-8") if wiersze else b"", plik, plik.parent
    )

def create_app(
    konfig: Konfig | None = None,
    detektor: Any = None,
    menedzer_pakietow: MenedzerPakietow | None = None,
) -> FastAPI:
    """Aplikacja API; `detektor` wstrzyknięty (testy/desktop) albo z wag
    (NIEWIDKA_MODELE_KATALOG). K7b: brak wag NIE zabija startu — aplikacja wstaje,
    a ukrywanie odpowiada 409 z listą brakujących pakietów (ekran pierwszego
    uruchomienia prowadzi do pobrania); `menedzer_pakietow` wstrzykiwany w testach."""
    konfig = konfig or wczytaj_konfig()
    if konfig.modele_katalog is None:
        # jedna ścieżka dla menedżera pakietów i detektora (przegląd Codex 2026-10-29):
        # inaczej pakiet pobierał się do katalogu domyślnego, a ukrywanie szukało wag gdzie indziej
        konfig = replace(
            konfig,
            modele_katalog=menedzer_pakietow.katalog if menedzer_pakietow else katalog_modeli(),
        )
    if konfig.mapy_katalog is None:
        # magazyn map w katalogu danych użytkownika (przegląd Argona, docs/MAPY-I-AKTUALIZACJE.md §2)
        konfig = replace(konfig, mapy_katalog=katalog_danych() / "mapy")
    wstrzykniety = detektor
    if wstrzykniety is None:
        try:
            wstrzykniety = zbuduj_detektor(konfig.poziom, konfig)
        except Exception:  # noqa: BLE001 — brak pakietu/wag: łagodny start (patrz wyżej)
            wstrzykniety = None

    # multipart bez zrzynania na dysk: spool ≥ limit, który i tak pilnujemy przed buforowaniem
    MultiPartParser.spool_max_size = konfig.max_rozmiar_mb * _MB

    app = FastAPI(title="Niewidka", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    # kolejność wg głębokości: LicznikZlecen (najbardziej zewnętrzny, dodany ostatni)
    # → LimitBajtow → middleware http; nadmiarowe żądanie dostaje 503 bez czytania treści
    app.add_middleware(LimitBajtow, limit_bajtow=konfig.max_rozmiar_mb * _MB)
    app.add_middleware(LicznikZlecen, limit=konfig.zlecenia)
    app.state.konfig = konfig
    app.state.token = secrets.token_urlsafe(32)
    app.state.detektor = wstrzykniety
    # klucz (poziom, pakiet Rozszerzony zainstalowany): wstrzyknięty detektor obsługuje
    # wszystkie; produkcyjnie cache leniwy. Startowy zbudowano bez pakietu Rozszerzonego.
    app.state.detektory: dict[tuple[int, bool], Any] = (
        {} if detektor is not None else {(konfig.poziom, False): wstrzykniety}
    )
    app.state.kolejka = Kolejka(maks=konfig.kolejka, timeout_s=konfig.timeout_s)
    app.state.identyfikatory: set[str] = set()
    # K4b pkt 7: skróty SHA-256 szyfrogramów wydanych w TEJ sesji — przy przywracaniu
    # mapa musi być jednym z nich (stare/przechwycone szyfrogramy nie podlegają odszyfrowaniu)
    app.state.szyfrogramy: dict[str, str] = {}
    _wczytaj_rejestr_map(konfig.rejestr_map, app.state.szyfrogramy, app.state.identyfikatory)
    # magazyn map z retencją (docs/MAPY-I-AKTUALIZACJE.md §2); sprzątanie wygasłych
    # przy starcie, zanim cokolwiek przywrócimy (SIMPLIFICATION: bez zegara w tle)
    def _kontekst_dziennika() -> dict:
        """Audyt z kontekstem środowiska (§9 pkt 10): użytkownik, wersja programu,
        wersje pakietów modeli z manifestów (jeśli manifesty je podają)."""
        pola = kontekst_domyslny()
        pola["pakiety"] = wersje_pakietow(konfig.modele_katalog)
        return pola

    app.state.magazyn = MagazynMap(
        konfig.mapy_katalog, retencja_dni=konfig.mapy_retencja_dni, kontekst=_kontekst_dziennika
    )

    def _skresl_z_rejestru(identyfikatory: set[str] | list[str]) -> None:
        """Przegląd Argona pkt 3: retencja i ręczne „Usuń" dotyczą magazynu programu,
        a pobrana kopia działa dalej. Dopiero opcja `mapy_uniewaznij_pobrane`
        skreśla mapę z rejestru wydanych map (pamięć i plik), więc kopie przestają
        działać. Jedna blokada magazynu obejmuję zmianę obu miejsc (pkt 9)."""
        if not konfig.mapy_uniewaznij_pobrane or not identyfikatory:
            return
        identyfikatory = set(identyfikatory)
        app.state.identyfikatory -= identyfikatory
        for skrot, wydane in list(app.state.szyfrogramy.items()):
            if wydane in identyfikatory:
                del app.state.szyfrogramy[skrot]
        _przepisz_rejestr(konfig.rejestr_map, identyfikatory)

    def _posprzataj() -> None:
        """Sprzątanie wygasłych przy każdym wywołaniu ukryj/przywroc/lista (§2)."""
        with app.state.magazyn.blokada:
            _skresl_z_rejestru(app.state.magazyn.posprzataj())

    _posprzataj()  # program wyłączony nie sprząta; sprząta przy starcie, zanim cokolwiek przywrócimy
    if menedzer_pakietow is None:
        menedzer_pakietow = MenedzerPakietow(
            wczytaj_pakiety(), konfig.modele_katalog or katalog_modeli(), zrodlo()
        )
    # K7c pkt 1: zmiana pakietów (pobranie/usunięcie/instalacja) unieważnia cache
    # detektorów — inaczej zainstalowany pakiet Rozszerzony nie wchodzi do detekcji
    menedzer_pakietow.ustaw_zwrot_zmiany(app.state.detektory.clear)
    app.state.pakiety = menedzer_pakietow

    app.state.aktualizacje = MenedzerAktualizacji(
        katalog_modeli_sciezka=konfig.modele_katalog or katalog_modeli(),
        katalog_danych_sciezka=katalog_danych(),
        zrodlo_url=zrodlo(),
        menedzer_pakietow=menedzer_pakietow,
        konfig_tryb=konfig.aktualizacje_tryb,
    )
    app.state.aktualizacje.sprawdz_przy_starcie()

    def _detektor_dla(poziom: int):
        """Detektor wybranego poziomu suwaka (K2d). Wstrzyknięty obsługuje wszystkie
        poziomy (testy/desktop); produkcyjne budowane leniwie i cache'owane — budowa
        i tak jest serializowana przez Semaphore(1) kolejki. K7b: brak wymaganego
        pakietu = jasny `BrakWymaganegoPakietu` (409), nie 500. K7c (audyt #1):
        poziom 3 dostaje zweryfikowany stan pakietu Rozszerzonego z menedżera."""
        if detektor is not None:  # wstrzyknięty obsługuje wszystkie poziomy
            return detektor
        # stan pakietu w kluczu: detektor ze stanu sprzed weryfikacji po starcie
        # (bez zwrotu zmiany) nie zostaje w cache dla poziomu 3 (odbiór K7c)
        rozszerzony = poziom == 3 and app.state.pakiety.stan_pakietu("rozszerzony") == "zainstalowany"
        zbudowany = app.state.detektory.get((poziom, rozszerzony))
        if zbudowany is None:
            try:
                zbudowany = zbuduj_detektor(poziom, konfig, pakiet_rozszerzony=rozszerzony)
            except Exception as blad:
                brakujace = app.state.pakiety.brakujacy_wymagany()
                if brakujace:
                    nazwy = [
                        w["nazwa"]
                        for w in app.state.pakiety.lista()
                        if w["id"] in brakujace
                    ]
                    raise BrakWymaganegoPakietu(brakujace, nazwy) from blad
                raise
            app.state.detektory[(poziom, rozszerzony)] = zbudowany
        return zbudowany
    originy = {
        f"http://{konfig.host}:{konfig.port}",
        f"https://{konfig.host}:{konfig.port}",
        f"http://localhost:{konfig.port}",
        f"https://localhost:{konfig.port}",
    }
    hosty = (konfig.host, "localhost")

    @app.middleware("http")
    async def straznik_i_limity(request: Request, call_next):
        """Token sesji + Host/Origin dla POST-ów i DELETE-ów /api/ oraz GET-ów
        pakietów/stanu/map (K7c pkt 5: status pakietów bywa nośnikiem sekreta
        z lustra); limity przed buforowaniem treści."""
        strazliwe_gety = ("/api/pakiety", "/api/stan", "/api/mapy", "/api/aktualizacje")
        # Host sprawdzany przy KAŻDYM żądaniu: strona główna wydaje token w meta
        # (Codex 2026-10-29: GET / z obcym Host oddawał token — DNS rebinding)
        if (request.headers.get("host") or "").split(":")[0] not in hosty:
            return JSONResponse({"blad": "niedozwolony Host"}, status_code=403)
        if (
            request.method in ("POST", "DELETE") and request.url.path.startswith("/api/")
        ) or (request.method == "GET" and request.url.path in strazliwe_gety):
            host = (request.headers.get("host") or "").split(":")[0]
            origin = request.headers.get("origin")
            token = request.headers.get(_TOKEN_NAGLOWEK)
            if host not in hosty:
                return JSONResponse({"blad": "niedozwolony Host"}, status_code=403)
            if origin is not None and origin not in originy:
                return JSONResponse({"blad": "niedozwolony Origin"}, status_code=403)
            if token != app.state.token:
                return JSONResponse({"blad": "brak albo zły token sesji"}, status_code=403)
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > konfig.max_rozmiar_mb * _MB:
            return JSONResponse(
                {"blad": f"wejście ponad limit {konfig.max_rozmiar_mb} MB"}, status_code=413
            )
        return await call_next(request)

    @app.middleware("http")
    async def logi_bez_tresci(request: Request, call_next):
        """Nieobsłużony wyjątek → wyłącznie UUID błędu w logu (Gemini pkt 15)."""
        try:
            odpowiedz = await call_next(request)
        except Exception:  # noqa: BLE001 — łapiemy WSZYSTKO, logujemy tylko UUID (bez treści)
            identyfikator_bledu = uuid4().hex
            logger.error("blad obslugi zadania: %s", identyfikator_bledu)
            return JSONResponse({"blad": identyfikator_bledu}, status_code=500)
        odpowiedz.headers.setdefault("cache-control", "no-store")
        return odpowiedz

    @app.exception_handler(NieznanyFormat)
    async def _nieznany_format(request: Request, blad: NieznanyFormat):
        # K4b pkt 15: nazwa pliku bywa osobowa — odpowiedź niesie tylko listę formatów
        return JSONResponse(
            {"blad": f"nieznany format pliku; obsługiwane: {', '.join(sorted(blad.wspierane))}"},
            status_code=415,
        )

    @app.exception_handler(ElementNieobslugiwany)
    async def _element_nieobslugiwany(request: Request, blad: ElementNieobslugiwany):
        # K4b pkt 15: nazwy części nie wracają (PII potrafi siedzieć w nazwie)
        return JSONResponse(
            {"blad": "dokument zawiera nieobsługiwane elementy", "liczba": len(blad.elementy)},
            status_code=422,
        )

    @app.exception_handler(RequestValidationError)
    async def _walidacja_zadania(request: Request, blad: RequestValidationError):
        # K4b pkt 15: bez pola input i bez odbicia wartości wejściowych
        return JSONResponse({"blad": "nieprawidłowe dane żądania"}, status_code=422)

    @app.exception_handler(zipfile.BadZipFile)
    async def _zly_docx(request: Request, blad: zipfile.BadZipFile):
        # testy GUI 2026-10-29 (S-WSP-37): uszkodzony .docx dawał 500
        return JSONResponse(
            {"blad": "plik nie jest poprawnym dokumentem DOCX (uszkodzony albo to inny format)"},
            status_code=422,
        )

    @app.exception_handler(BladMapy)
    async def _blad_mapy(request: Request, blad: BladMapy):
        return JSONResponse({"blad": str(blad)}, status_code=422)

    @app.exception_handler(WybierzMape)
    async def _wybierz_mape(request: Request, blad: WybierzMape):
        # docs/MAPY-I-AKTUALIZACJE.md §3: interfejs prowadzi do listy zadań
        return JSONResponse(
            {"kod": "wybierz_mape", "blad": str(blad), "kandydaci": blad.kandydaci},
            status_code=422,
        )

    @app.exception_handler(BrakMapyWMagazynie)
    async def _brak_mapy_w_magazynie(request: Request, blad: BrakMapyWMagazynie):
        return JSONResponse({"kod": "brak_mapy", "blad": str(blad)}, status_code=422)

    @app.exception_handler(ArchiwumZaDuze)
    async def _archiwum_za_duze(request: Request, blad: ArchiwumZaDuze):
        return JSONResponse({"blad": str(blad)}, status_code=413)

    @app.exception_handler(BladArchiwum)
    async def _blad_archiwum(request: Request, blad: BladArchiwum):
        # K4b pkt 10: kłamliwe nagłówki/obca kompresja = odmowa (fail-closed, 422)
        return JSONResponse({"blad": "archiwum nieprawidłowe lub niebezpieczne"}, status_code=422)

    @app.exception_handler(BrakKlucza)
    async def _brak_klucza(request: Request, blad: BrakKlucza):
        return JSONResponse({"blad": str(blad)}, status_code=500)

    # BladDetektora celowo BEZ handlera: przelatuje do middleware logi_bez_tresci
    # → 500 z UUID, fail-closed, bez treści wyjątku w odpowiedzi.

    @app.exception_handler(KolejkaPelna)
    async def _kolejka_pelna(request: Request, blad: KolejkaPelna):
        return JSONResponse(
            {"blad": "kolejka pełna, spróbuj ponownie za chwilę"},
            status_code=503,
            headers={"retry-after": str(konfig.timeout_s)},
        )

    @app.exception_handler(PracaPrzekroczylaCzas)
    async def _praca_przekroczyla_czas(request: Request, blad: PracaPrzekroczylaCzas):
        # K4b pkt 11: 503 z retry-after — praca nadal trwa i trzyma slot
        return JSONResponse(
            {
                "blad": "praca nad dokumentem przekroczyła limit czasu; "
                "poczekaj, aż serwer ją dokończy"
            },
            status_code=503,
            headers={"retry-after": str(konfig.timeout_s)},
        )

    @app.exception_handler(BrakWymaganegoPakietu)
    async def _brak_wymaganego_pakietu(request: Request, blad: BrakWymaganegoPakietu):
        # K7b: poziom bez wymaganego pakietu = jasny błąd z listą pakietów do pobrania
        return JSONResponse(
            {"blad": str(blad), "brak_pakietu": blad.brakujace}, status_code=409
        )

    @app.exception_handler(BladPakietu)
    async def _blad_pakietu(request: Request, blad: BladPakietu):
        # instalacja offline z rozbieżnym SHA-256: fail-closed, pliki nie trafiają
        # do katalogu wag; komunikat bez treści plików
        return JSONResponse({"blad": str(blad)}, status_code=422)

    @app.exception_handler(TrybNarzucony)
    async def _tryb_narzucony(request: Request, blad: TrybNarzucony):
        return JSONResponse({"blad": str(blad)}, status_code=409)

    @app.exception_handler(BladAktualizacji)
    async def _blad_aktualizacji(request: Request, blad: BladAktualizacji):
        return JSONResponse({"blad": str(blad)}, status_code=422)

    @app.get("/api/pakiety")
    async def endpoint_pakiety() -> dict:
        """Stan pakietów + postęp bieżącej operacji (K7b); bez tokena: dane
        nieosobowe, ale za POST-em stoi sesyjny token jak wszędzie."""
        pakiety_stan = app.state.pakiety
        odpowiedz = {
            "pakiety": pakiety_stan.lista(),
            "poziomy_dostepne": pakiety_stan.poziomy_dostepne(),
            "postep": {
                "pakiet": pakiety_stan.postep.pakiet,
                "pobrane": pakiety_stan.postep.pobrane,
                "razem": pakiety_stan.postep.razem,
                "blad": pakiety_stan.postep.blad,
            },
        }
        return odpowiedz

    @app.post("/api/pakiety")
    async def endpoint_pakiety_akcja(request: Request) -> JSONResponse:
        """pobierz (w tle, 202) | usun (200) | instaluj z katalogu IT (w tle, 202,
        K7c pkt 8) | anuluj bieżącą operację (200). Błędy operacji w tle lądują
        w postep.blad (GET /api/pakiety)."""
        try:
            zlecenie = await request.json()
        except Exception:  # noqa: BLE001 — ciało bez JSON = 422 bez odbicia treści
            raise HTTPException(status_code=422, detail="oczekiwano JSON") from None
        akcja = zlecenie.get("akcja")
        identyfikator = zlecenie.get("pakiet")
        pakiety_stan = app.state.pakiety
        znane = {w["id"] for w in pakiety_stan.lista()}
        if akcja not in ("pobierz", "usun", "instaluj", "anuluj"):
            raise HTTPException(status_code=422, detail="nieznana akcja albo pakiet")
        if akcja == "anuluj":
            pakiety_stan.anuluj()
            return JSONResponse({"stan": "przerywanie"})
        if identyfikator not in znane:
            raise HTTPException(status_code=422, detail="nieznana akcja albo pakiet")
        if akcja == "pobierz":
            if not pakiety_stan.pobierz(identyfikator):
                raise HTTPException(status_code=409, detail="pobieranie już trwa")
            return JSONResponse({"stan": "pobieranie"}, status_code=202)
        if akcja == "usun":
            pakiety_stan.usun(identyfikator)
            return JSONResponse({"stan": "usunieto"})
        katalog = zlecenie.get("katalog")
        if not katalog:
            raise HTTPException(status_code=422, detail="instaluj wymaga katalogu")
        if not pakiety_stan.instaluj(identyfikator, Path(katalog)):
            raise HTTPException(status_code=409, detail="inna operacja na pakietach trwa")
        return JSONResponse({"stan": "instalowanie"}, status_code=202)

    @app.get("/api/aktualizacje")
    async def endpoint_aktualizacje() -> dict:
        akt = app.state.aktualizacje
        return {
            "tryb": akt.tryb,
            "narzucony": akt.narzucony,
            "stan": akt.stan,
            "blad": akt.blad,
            "wersja_katalogu": wczytaj_wersje_katalogu(akt.katalog_aktywny_plik),
            "ostatnie_sprawdzenie": akt.ostatnie_sprawdzenie,
            "pakiety": akt.lista_pakietow(),
            "postep": akt.postep,
        }

    @app.post("/api/aktualizacje")
    async def endpoint_aktualizacje_akcja(request: Request) -> JSONResponse:
        try:
            zlecenie = await request.json()
        except Exception:  # noqa: BLE001 — ciało bez JSON = 422 bez odbicia treści
            raise HTTPException(status_code=422, detail="oczekiwano JSON") from None
        akcja = zlecenie.get("akcja")
        akt = app.state.aktualizacje
        if akcja not in ("sprawdz", "instaluj", "cofnij", "tryb"):
            raise HTTPException(status_code=422, detail="nieznana akcja aktualizacji")

        if akcja == "tryb":
            nowy_tryb = zlecenie.get("tryb")
            if not nowy_tryb:
                raise HTTPException(status_code=422, detail="brak pola tryb")
            akt.ustaw_tryb(nowy_tryb)
            return JSONResponse({"stan": "zmieniono_tryb", "tryb": nowy_tryb})

        if akcja == "sprawdz":
            akt.sprawdz_aktualizacje()
            return JSONResponse({"stan": akt.stan, "blad": akt.blad})

        if akcja == "instaluj":
            pakiet_id = zlecenie.get("pakiet")
            if not pakiet_id:
                raise HTTPException(status_code=422, detail="instaluj wymaga podania pakietu")
            if not akt.instaluj_aktualizacje(pakiet_id, w_tle=True):
                raise HTTPException(status_code=409, detail="operacja aktualizacji już trwa")
            return JSONResponse({"stan": "instalowanie", "pakiet": pakiet_id}, status_code=202)

        if akcja == "cofnij":
            pakiet_id = zlecenie.get("pakiet")
            if not pakiet_id:
                raise HTTPException(status_code=422, detail="cofnij wymaga podania pakietu")
            akt.cofnij_aktualizacje(pakiet_id)
            return JSONResponse({"stan": "cofnieto", "pakiet": pakiet_id})

        raise HTTPException(status_code=422, detail="nieznana akcja")

    @app.exception_handler(BladKontroli)
    async def _blad_kontroli(request: Request, blad: BladKontroli):
        # K4b pkt 1: zablokowany dokument NIE wraca — żadnych bajtów dokumentu,
        # żadnych fragmentów; tylko typy znalezisk z licznikami.
        return JSONResponse(
            {
                "blad": "kontrola znalazła w wyniku dane przypominające oryginalne, dokument zablokowany",
                "status": "zablokowany",
                "typy": blad.typy,
            },
            status_code=422,
        )

    def _format_z_nazwy(nazwa: str) -> str:
        rozszerzenie = Path(nazwa).suffix.lstrip(".").lower()
        if not rozszerzenie:
            raise NieznanyFormat(nazwa, sorted(rozszerzenia_wspierane()))
        return rozszerzenie

    @app.post("/api/ukryj")
    async def endpoint_ukryj(
        request: Request,
        poziom: int = Form(1),
        plik: UploadFile | None = File(None),  # noqa: B008 — wzorzec FastAPI
        tekst: str | None = Form(None),
    ) -> Response:
        if poziom not in _POZIOMY:
            raise HTTPException(status_code=422, detail="poziom poza 1-3")
        if (plik is None) == (tekst is None):
            raise HTTPException(status_code=422, detail="podaj dokładnie jedno: plik albo tekst")
        if tekst is not None and len(tekst.encode()) > konfig.max_tekst_mb * _MB:
            raise HTTPException(status_code=413, detail=f"tekst ponad limit {konfig.max_tekst_mb} MB")
        nazwa = plik.filename if plik is not None else "tekst.txt"
        format = _format_z_nazwy(nazwa)
        dane = await plik.read() if plik is not None else tekst.encode()
        if len(dane) > konfig.max_rozmiar_mb * _MB:
            raise HTTPException(status_code=413, detail=f"wejście ponad limit {konfig.max_rozmiar_mb} MB")

        def praca():
            klucz = pobierz_klucz(konfig)  # klucz żywy wyłącznie w wątku operacji
            wynik, mapa, raport = ukryj(
                dane,
                format,
                poziom,
                detektor=_detektor_dla(poziom),
                kontrola_blokada=konfig.kontrola_blokada,
                max_rozpakowane_bajtow=konfig.max_rozpakowane_mb * _MB,
                polityka_obrazow=konfig.obrazy,
            )
            return wynik, mapa, raport, zaszyfruj(mapa, klucz)

        wynik, mapa, raport, mapa_paczka = await app.state.kolejka.wykonaj(praca)
        if raport.status == "zablokowany":
            raise BladKontroli(_licznik_typow(raport.ostrzezenia))  # przed pakowaniem: nic nie wychodzi
        _posprzataj()  # sprzątanie wygasłych przy każdym wywołaniu (§2)
        mapa_zapisana = None  # datetime wygaśnięcia albo "blad" (§9 pkt 5)
        with app.state.magazyn.blokada:  # jedna blokada: magazyn + dziennik + rejestr (pkt 9)
            app.state.identyfikatory.add(mapa.identyfikator)
            skrot = hashlib.sha256(mapa_paczka).hexdigest()
            app.state.szyfrogramy[skrot] = mapa.identyfikator
            _dopisz_do_rejestru(konfig.rejestr_map, skrot, mapa.identyfikator)
            try:
                # zapis PRZED odpowiedzią (§9 pkt 5): błąd nie zabija ukrywania,
                # wynik wraca z nagłówkiem „blad", a UI każe pobrać mapę
                mapa_zapisana = app.state.magazyn.zapisz(mapa_paczka, mapa, raport.statystyki)
            except (OSError, BladMapy) as blad:
                logger.warning("magazyn map niezapisany: %s", type(blad).__name__)
                app.state.identyfikatory.discard(mapa.identyfikator)
                mapa_zapisana = "blad"

        # K4b pkt 7: pełny identyfikator żyje w mapie i nagłówku; w nazwach plików
        # tylko krótki skrót (nazwa pliku nie musi być niepodrabialna)
        skrot = mapa.identyfikator[:12]
        paczka = io.BytesIO()
        with zipfile.ZipFile(paczka, "w", zipfile.ZIP_DEFLATED) as zip_archiwum:
            zip_archiwum.writestr(nazwa_wyniku(nazwa, skrot), wynik)
            zip_archiwum.writestr(f"{skrot}.nwidka", mapa_paczka)
        naglowki = {
            "x-niewidka-identyfikator": mapa.identyfikator,
            "x-niewidka-statystyki": _json_naglowek(raport.statystyki),
            "x-niewidka-ostrzezenia": _json_naglowek(_licznik_typow(raport.ostrzezenia)),
            "x-niewidka-uwagi": _json_naglowek(raport.uwagi),
            # K5c: gotowe teksty ryzyka (próg małej próby liczy serwer), nie gołe R95
            "x-niewidka-r95": _json_naglowek(opisy_ryzyka(poziom, list(raport.statystyki))),
            "x-niewidka-status": raport.status,
            # docs/MAPY-I-AKTUALIZACJE.md §3: obecny tylko, gdy mapa trafiła do magazynu
            "content-disposition": 'attachment; filename="wynik.zip"',
        }
        if mapa_zapisana is not None:
            naglowki["x-niewidka-mapa-zapisana"] = (
                mapa_zapisana if isinstance(mapa_zapisana, str) else mapa_zapisana.isoformat()
            )
        return Response(paczka.getvalue(), media_type="application/zip", headers=naglowki)

    def _metadane_listy() -> list[dict]:
        return [
            {
                "id": wpis["identyfikator"],
                "utworzono": wpis["utworzono"],
                "wygasa": wpis["wygasa"],
                "poziom": wpis["poziom"],
                "statystyki": wpis["statystyki"],
            }
            for wpis in app.state.magazyn.lista()
        ]

    def _mapa_z_magazynu(dane: bytes, format: str, wskazanie: str | None, klucz: bytes) -> tuple[Mapa, bool]:
        """Wybór mapy bez pliku .nwidka (docs/MAPY-I-AKTUALIZACJE.md §3, §8):
        dopisek w treści wygrywa z polem `identyfikator` (przegląd Argona pkt 10);
        bez dopisku kandydatem jest tylko mapa z kompletem znaczników z tekstu
        (pkt 2: dokładnie jeden = wybrany, więcej albo zero = wybierz_mape)."""
        limit = konfig.max_rozpakowane_mb * _MB
        id_z_dopisku = identyfikator_z_dopisku(dane, format, max_rozpakowane_bajtow=limit)
        wskazane = id_z_dopisku or wskazanie
        if wskazane is not None:
            try:
                paczka = app.state.magazyn.wczytaj(wskazane)
            except ValueError as blad:  # id spoza wzorca (w tym traversal): 422, nie 500
                raise WybierzMape(f"Zły identyfikator mapy: {blad}", []) from None
            if paczka is None:
                raise BrakMapyWMagazynie(
                    "Nie ma już zapisanej mapy tego zadania (usunięta albo po okresie "
                    "przechowywania). Jeśli masz plik mapy (.nwidka), przywróć nim."
                )
            return odszyfruj(paczka, klucz), False
        adapter = adapter_formatu(format)
        dok = adapter.wczytaj(dane, max_rozpakowane=limit)
        tresc = "\n".join(s.tekst for s in dok.segmenty)
        znaczniki = {f"{m.group(1)}_{m.group(2)}" for m in WZORZEC_ZNACZNIKA.finditer(tresc)}
        if not znaczniki:
            raise WybierzMape("W tekście nie ma znaczników Niewidki, więc nie wiem, którą mapę użyć.", [])
        kandydaci = []
        for wpis in app.state.magazyn.lista():  # od najnowszej; dopisek i tak wygrywa wyżej
            paczka = app.state.magazyn.wczytaj(wpis["identyfikator"])
            if paczka is None:
                continue
            try:
                mapa_ob = odszyfruj(paczka, klucz)
            except BladMapy:
                continue  # nieczytelna mapa nie jest kandydatem
            if {w.oznaczenie for w in mapa_ob.wpisy} >= znaczniki:
                kandydaci.append(wpis)
        if len(kandydaci) == 1:
            return odszyfruj(app.state.magazyn.wczytaj(kandydaci[0]["identyfikator"]), klucz), True
        if len(kandydaci) > 1:
            raise WybierzMape(
                "Kilka zapisanych zadań pasuje do tych znaczników. Wybierz zadanie z listy.",
                kandydaci,  # metadane TYLKO pasujących, nie całego magazynu
            )
        raise WybierzMape(
            "Żadna zapisana mapa nie zawiera już tych znaczników. Wybierz mapę z pliku "
            "(.nwidka), jeśli ją masz.",
            [],
        )

    @app.post("/api/przywroc")
    async def endpoint_przywroc(
        request: Request,
        wynik: UploadFile | None = File(None),  # noqa: B008 — wzorzec FastAPI
        tekst: str | None = Form(None),
        mapa: UploadFile | None = File(None),  # noqa: B008
        identyfikator: str | None = Form(None),
    ) -> Response:
        """Przywracanie: plik wyniku ALBO wklejony tekst; mapa z pliku, dopisku
        w treści albo z magazynu po identyfikatorze (§3)."""
        if (wynik is None) == (tekst is None):
            raise HTTPException(status_code=422, detail="podaj dokładnie jedno: plik wyniku albo tekst")
        if tekst is not None and len(tekst.encode()) > konfig.max_tekst_mb * _MB:
            raise HTTPException(status_code=413, detail=f"tekst ponad limit {konfig.max_tekst_mb} MB")
        if wynik is not None:
            format = _format_z_nazwy(wynik.filename or "")
            dane_wyniku = await wynik.read()
            if len(dane_wyniku) > konfig.max_rozmiar_mb * _MB:
                raise HTTPException(
                    status_code=413, detail=f"wejście ponad limit {konfig.max_rozmiar_mb} MB"
                )
        else:
            format = "txt"
            dane_wyniku = tekst.encode()
        dane_mapy = await mapa.read() if mapa is not None else None
        _posprzataj()  # sprzątanie wygasłych, zanim cokolwiek przywrócimy (§2)

        def praca():
            klucz = pobierz_klucz(konfig)
            wybrana_automatycznie = False
            if dane_mapy is not None:
                # K4b pkt 7: najpierw rejestr wydanych szyfrogramów, dopiero potem
                # odszyfrowanie — stara mapa z trafionym identyfikatorem nie przechodzi
                if hashlib.sha256(dane_mapy).hexdigest() not in app.state.szyfrogramy:
                    raise BladMapy("mapa nie została wydana przez ten program")
                mapa_ob = odszyfruj(dane_mapy, klucz)
                del klucz
                if mapa_ob.identyfikator not in app.state.identyfikatory:
                    raise BladMapy("niezgodny identyfikator mapy — mapa z innego zadania albo sesji")
            else:
                mapa_ob, wybrana_automatycznie = _mapa_z_magazynu(dane_wyniku, format, identyfikator, klucz)
                del klucz
            przywrocony, rozbieznosci = przywroc(
                dane_wyniku, format, mapa_ob, max_rozpakowane_bajtow=konfig.max_rozpakowane_mb * _MB
            )
            try:
                app.state.magazyn.odnotuj("przywrocono", mapa_ob.identyfikator, mapa_ob.poziom)
            except ValueError:  # obcy identyfikator: audyt bez śmieci w dzienniku
                pass
            return przywrocony, rozbieznosci, mapa_ob.identyfikator, wybrana_automatycznie

        plik_przywrocony, rozbieznosci, identyfikator_mapy, wybrana_automatycznie = (
            await app.state.kolejka.wykonaj(praca)
        )
        naglowki = {
            "x-niewidka-rozbieznosci": _json_naglowek(
                [{"typ": r.typ, "opis": r.opis} for r in rozbieznosci]
            ),
            "x-niewidka-identyfikator": identyfikator_mapy,
        }
        if wybrana_automatycznie:
            # przegląd Argona pkt 2: jeden kandydat wybrany za użytkownika, jawnie
            naglowki["x-niewidka-mapa-wybrana-automatycznie"] = "1"
        if wynik is not None:
            naglowki["content-disposition"] = (
                f'attachment; filename="PRZYWROCONY_{identyfikator_mapy}.{format}"'
            )
            return Response(
                plik_przywrocony, media_type="application/octet-stream", headers=naglowki
            )
        return PlainTextResponse(
            plik_przywrocony.decode("utf-8"), media_type="text/plain; charset=utf-8", headers=naglowki
        )

    @app.get("/api/mapy")
    async def endpoint_mapy() -> dict:
        """Zapisane mapy od najnowszej (lista wyboru „Zadanie" i Ustawienia); id to
        pełny identyfikator - nie jest daną osobową (docs/MAPY-I-AKTUALIZACJE.md §3)."""
        with app.state.magazyn.blokada:  # odczyt spójny z równoległym usuwaniem/sprzątaniem
            _posprzataj()
            return {
                "retencja_dni": konfig.mapy_retencja_dni,
                "mapy": _metadane_listy(),
            }

    @app.delete("/api/mapy/{identyfikator}")
    async def endpoint_usun_mape(identyfikator: str) -> JSONResponse:
        try:
            with app.state.magazyn.blokada:
                _skresl_z_rejestru(app.state.magazyn.posprzataj())
                usunieto = app.state.magazyn.usun(identyfikator)
                if usunieto:
                    _skresl_z_rejestru([identyfikator])
        except ValueError as blad:  # zły identyfikator: 422, nie 500 (path traversal)
            raise HTTPException(status_code=422, detail=str(blad)) from None
        if not usunieto:
            raise HTTPException(status_code=404, detail="nie ma takiej mapy w magazynie")
        return JSONResponse({"stan": "usunieto"})

    @app.delete("/api/mapy")
    async def endpoint_usun_wszystkie_mapy() -> JSONResponse:
        with app.state.magazyn.blokada:
            usuniete = app.state.magazyn.posprzataj()
            for wpis in app.state.magazyn.lista():
                if app.state.magazyn.usun(wpis["identyfikator"]):
                    usuniete.append(wpis["identyfikator"])
            _skresl_z_rejestru(usuniete)
        return JSONResponse({"usunieto": len(usuniete)})

    @app.get("/api/stan")
    async def endpoint_stan() -> dict:
        czesci = getattr(app.state.detektor, "czesci", None) if app.state.detektor else None
        modele = [c.nazwa for c in czesci] if czesci else (
            [app.state.detektor.nazwa] if app.state.detektor else []
        )
        return {
            "wersja": __version__,
            "modele": modele,
            "poziom": konfig.poziom,
            "poziomy": list(_POZIOMY),  # dostępne poziomy suwaka
            "poziomy_dostepne": app.state.pakiety.poziomy_dostepne(),  # K7b: z pakietami
            "r95": r95_poziomy(),  # R95 per poziom — interfejs pokazuje dla wybranego
            "limity": {
                "rozmiar_mb": konfig.max_rozmiar_mb,
                "rozpakowane_mb": konfig.max_rozpakowane_mb,
                "tekst_mb": konfig.max_tekst_mb,
                "kolejka": konfig.kolejka,
                "zlecenia": konfig.zlecenia,
                "timeout_s": konfig.timeout_s,
            },
            "kolejka": app.state.kolejka.stan(),
        }

    @app.get("/", include_in_schema=False)
    async def strona_glowna() -> HTMLResponse:
        """Web lokalny (K5): index.html z tokenem sesji w meta — nigdy w URL ani w zasobach.

        Trasa zarejestrowana przed montażem StaticFiles, więc wygrywa z plikiem index.html.
        no-store już dokleja middleware — token nie trafia do cache przeglądarki.
        """
        tresc = (_KATALOG_WEB / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(tresc.replace("__NIEWIDKA_TOKEN__", app.state.token))

    app.mount("/", StaticFiles(directory=_KATALOG_WEB), name="web")

    return app


def main(argv: list[str] | None = None) -> int:
    """Serwer: python -m niewidka.api (uvicorn, host/port z konfiguracji)."""
    import uvicorn

    konfig = wczytaj_konfig()
    uvicorn.run(create_app(konfig), host=konfig.host, port=konfig.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
