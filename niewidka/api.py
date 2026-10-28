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
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.formparsers import MultiPartParser

from niewidka import __version__
from niewidka.archiwum import BladArchiwum
from niewidka.formaty import (
    ElementNieobslugiwany,
    NieznanyFormat,
    nazwa_wyniku,
    rozszerzenia_wspierane,
)
from niewidka.jakosc import r95_poziomy
from niewidka.klucze import BrakKlucza, pobierz_klucz
from niewidka.konfig import Konfig, wczytaj_konfig
from niewidka.kontrola import Ostrzezenie
from niewidka.mapa import BladMapy, odszyfruj, zaszyfruj
from niewidka.rdzen import ArchiwumZaDuze, przywroc, ukryj, zbuduj_detektor

logger = logging.getLogger("niewidka.api")

_MB = 1024 * 1024
_TOKEN_NAGLOWEK = "x-niewidka-token"
_KATALOG_WEB = Path(__file__).parent / "web"
_POZIOMY = (1, 2, 3)  # suwak jakości (K2d: 2 = wariant A, 3 = wariant B)


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


def create_app(konfig: Konfig | None = None, detektor: Any = None) -> FastAPI:
    """Aplikacja API; `detektor` wstrzyknięty (testy/desktop) albo z wag (NIEWIDKA_MODELE_KATALOG)."""
    konfig = konfig or wczytaj_konfig()
    wstrzykniety = detektor
    if wstrzykniety is None:
        # brak wag = awaria startu (fail-closed); pozostałe poziomy buduje leniwie _detektor_dla
        wstrzykniety = zbuduj_detektor(konfig.poziom, konfig)

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
    # per poziom: wstrzyknięty detektor obsługuje wszystkie; produkcyjnie cache leniwy
    app.state.detektory: dict[int, Any] = (
        {} if detektor is not None else {konfig.poziom: wstrzykniety}
    )
    app.state.kolejka = Kolejka(maks=konfig.kolejka, timeout_s=konfig.timeout_s)
    app.state.identyfikatory: set[str] = set()
    # K4b pkt 7: skróty SHA-256 szyfrogramów wydanych w TEJ sesji — przy przywracaniu
    # mapa musi być jednym z nich (stare/przechwycone szyfrogramy nie podlegają odszyfrowaniu)
    app.state.szyfrogramy: dict[str, str] = {}

    def _detektor_dla(poziom: int):
        """Detektor wybranego poziomu suwaka (K2d). Wstrzyknięty obsługuje wszystkie
        poziomy (testy/desktop); produkcyjne budowane leniwie i cache'owane — budowa
        i tak jest serializowana przez Semaphore(1) kolejki."""
        if detektor is not None:  # wstrzyknięty obsługuje wszystkie poziomy
            return detektor
        zbudowany = app.state.detektory.get(poziom)
        if zbudowany is None:
            zbudowany = zbuduj_detektor(poziom, konfig)
            app.state.detektory[poziom] = zbudowany
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
        """Token sesji + Host/Origin dla POST-ów; limity przed buforowaniem treści."""
        if request.method == "POST" and request.url.path.startswith("/api/"):
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
        return JSONResponse({"blad": str(blad)}, status_code=415)

    @app.exception_handler(ElementNieobslugiwany)
    async def _element_nieobslugiwany(request: Request, blad: ElementNieobslugiwany):
        return JSONResponse({"blad": str(blad), "elementy": blad.elementy}, status_code=422)

    @app.exception_handler(BladMapy)
    async def _blad_mapy(request: Request, blad: BladMapy):
        return JSONResponse({"blad": str(blad)}, status_code=422)

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
        app.state.identyfikatory.add(mapa.identyfikator)
        app.state.szyfrogramy[hashlib.sha256(mapa_paczka).hexdigest()] = mapa.identyfikator

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
            "x-niewidka-r95": _json_naglowek(raport.r95),
            "x-niewidka-status": raport.status,
            "content-disposition": 'attachment; filename="wynik.zip"',
        }
        return Response(paczka.getvalue(), media_type="application/zip", headers=naglowki)

    @app.post("/api/przywroc")
    async def endpoint_przywroc(
        request: Request,
        wynik: UploadFile = File(...),  # noqa: B008 — wzorzec FastAPI
        mapa: UploadFile = File(...),  # noqa: B008
    ) -> Response:
        format = _format_z_nazwy(wynik.filename or "")
        dane_wyniku = await wynik.read()
        dane_mapy = await mapa.read()

        def praca():
            klucz = pobierz_klucz(konfig)
            # K4b pkt 7: najpierw rejestr wydanych szyfrogramów, dopiero potem
            # odszyfrowanie — stara mapa z trafionym identyfikatorem nie przechodzi
            if hashlib.sha256(dane_mapy).hexdigest() not in app.state.szyfrogramy:
                raise BladMapy("mapa nie została wydana przez tę sesję")
            mapa_ob = odszyfruj(dane_mapy, klucz)
            del klucz
            if mapa_ob.identyfikator not in app.state.identyfikatory:
                raise BladMapy("niezgodny identyfikator mapy — mapa z innego zadania albo sesji")
            przywrocony, rozbieznosci = przywroc(
                dane_wyniku, format, mapa_ob, max_rozpakowane_bajtow=konfig.max_rozpakowane_mb * _MB
            )
            return przywrocony, rozbieznosci, mapa_ob.identyfikator

        plik_przywrocony, rozbieznosci, identyfikator = await app.state.kolejka.wykonaj(praca)
        naglowki = {
            "x-niewidka-rozbieznosci": _json_naglowek(
                [{"typ": r.typ, "opis": r.opis} for r in rozbieznosci]
            ),
            "x-niewidka-identyfikator": identyfikator,
            "content-disposition": f'attachment; filename="PRZYWROCONY_{identyfikator}.{format}"',
        }
        return Response(plik_przywrocony, media_type="application/octet-stream", headers=naglowki)

    @app.get("/api/stan")
    async def endpoint_stan() -> dict:
        czesci = getattr(app.state.detektor, "czesci", None)
        modele = [c.nazwa for c in czesci] if czesci else [app.state.detektor.nazwa]
        return {
            "wersja": __version__,
            "modele": modele,
            "poziom": konfig.poziom,
            "poziomy": list(_POZIOMY),  # dostępne poziomy suwaka
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
