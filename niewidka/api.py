"""API FastAPI (K4, LLD §12): ukryj/przywroc/stan na 127.0.0.1.

Bezpieczeństwo: token sesji (generowany przy starcie), walidacja Host/Origin,
limity PRZED buforowaniem (Content-Length) i po dekompresji, pliki tylko w RAM,
Cache-Control: no-store, logi wyłącznie z UUID błędu (Gemini pkt 15), inferencja
w puli wątków z Semaphore(1) i timeoutem (Gemini pkt 5), pełna kolejka → 503.
Błędy wg LLD §15: 413/415/422/500/503; detektor fail-closed.
"""

from __future__ import annotations

import asyncio
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
from niewidka.formaty import (
    ElementNieobslugiwany,
    NieznanyFormat,
    nazwa_wyniku,
    rozszerzenia_wspierane,
)
from niewidka.klucze import BrakKlucza, pobierz_klucz
from niewidka.konfig import Konfig, wczytaj_konfig
from niewidka.kontrola import Ostrzezenie
from niewidka.mapa import BladMapy, odszyfruj, zaszyfruj
from niewidka.rdzen import ArchiwumZaDuze, przywroc, ukryj, zbuduj_detektor

logger = logging.getLogger("niewidka.api")

_MB = 1024 * 1024
_TOKEN_NAGLOWEK = "x-niewidka-token"
_KATALOG_WEB = Path(__file__).parent / "web"


class KolejkaPelna(Exception):
    """Wszystkie sloty zajęte i kolejka pełna (LLD §15 → 503 + Retry-After)."""


@dataclass
class Kolejka:
    """Jedna inferencja naraz (Semaphore w puli wątków), `kolejka` oczekujących."""

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
                async with self._slot():
                    return await asyncio.wait_for(asyncio.to_thread(praca), limit)
            finally:
                self.czekajacy -= 1
        # slot wolny: acquire nie zawiesza się, więc między locked() a wejściem nie ma wyścigu
        async with self._slot():
            return await asyncio.wait_for(asyncio.to_thread(praca), limit)

    def stan(self) -> dict[str, int]:
        return {"czekajacy": self.czekajacy, "maks": self.maks}


def _json_naglowek(wartosc: Any) -> str:
    return json.dumps(wartosc, ensure_ascii=False)


def _ostrzezenia_lista(ostrzezenia: list[Ostrzezenie]) -> list[dict]:
    return [
        {"typ": o.typ, "fragment": o.fragment, "segment": o.segment, "czesc": o.czesc}
        for o in ostrzezenia
    ]


def create_app(konfig: Konfig | None = None, detektor: Any = None) -> FastAPI:
    """Aplikacja API; `detektor` wstrzyknięty (testy/desktop) albo z wag (NIEWIDKA_MODELE_KATALOG)."""
    konfig = konfig or wczytaj_konfig()
    if detektor is None:
        detektor = zbuduj_detektor(konfig.poziom, konfig)  # brak wag = awaria startu (fail-closed)

    # multipart bez zrzynania na dysk: spool ≥ limit, który i tak pilnujemy przed buforowaniem
    MultiPartParser.spool_max_size = konfig.max_rozmiar_mb * _MB

    app = FastAPI(title="Niewidka", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.konfig = konfig
    app.state.token = secrets.token_urlsafe(32)
    app.state.detektor = detektor
    app.state.kolejka = Kolejka(maks=konfig.kolejka, timeout_s=konfig.timeout_s)
    app.state.identyfikatory: set[str] = set()
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
        if poziom not in (1, 2, 3):
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
                detektor=detektor,
                kontrola_blokada=konfig.kontrola_blokada,
                max_rozpakowane_bajtow=konfig.max_rozpakowane_mb * _MB,
            )
            return wynik, mapa, raport, zaszyfruj(mapa, klucz)

        wynik, mapa, raport, mapa_paczka = await app.state.kolejka.wykonaj(praca)
        app.state.identyfikatory.add(mapa.identyfikator)

        paczka = io.BytesIO()
        with zipfile.ZipFile(paczka, "w", zipfile.ZIP_DEFLATED) as zip_archiwum:
            zip_archiwum.writestr(nazwa_wyniku(nazwa, mapa.identyfikator), wynik)
            zip_archiwum.writestr(f"{mapa.identyfikator}.nwidka", mapa_paczka)
        naglowki = {
            "x-niewidka-identyfikator": mapa.identyfikator,
            "x-niewidka-statystyki": _json_naglowek(raport.statystyki),
            "x-niewidka-ostrzezenia": _json_naglowek(_ostrzezenia_lista(raport.ostrzezenia)),
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
            "limity": {
                "rozmiar_mb": konfig.max_rozmiar_mb,
                "rozpakowane_mb": konfig.max_rozpakowane_mb,
                "tekst_mb": konfig.max_tekst_mb,
                "kolejka": konfig.kolejka,
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
