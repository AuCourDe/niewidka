"""Centralny serwer inferencji w sieci lokalnej (docs/SERWER-INFERENCJI.md): tylko wykrywanie
(tekst -> zakresy), bez kluczy map, bez zapisu i logowania treści. Wymaga tokenu i TLS poza
loopbackiem (fail-closed). Start: `python -m niewidka.serwer_inferencji --konfig <plik.toml>`;
token: `... nowy-token <plik>`.
"""

from __future__ import annotations

import argparse
import hmac
import logging
import os
import sys
import threading
import time
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from niewidka import __version__
from niewidka.api import Kolejka, KolejkaPelna, LimitBajtow, PracaPrzekroczylaCzas
from niewidka.konfig import PROG_OSOBA_DOMYSLNY, Konfig, _jako_bool, _jako_int, _jako_sciezka
from niewidka.pakiety import katalog_modeli
from niewidka.rdzen import zbuduj_detektor
from niewidka.zdalny import BladTokenu, jest_loopbackiem, wczytaj_token, zapisz_nowy_token

logger = logging.getLogger("niewidka.serwer_inferencji")

_MB = 1024 * 1024
POZIOMY = (1, 2, 3)
URZADZENIA = ("auto", "cpu", "gpu")
CPU, CUDA, DML = "CPUExecutionProvider", "CUDAExecutionProvider", "DmlExecutionProvider"


class Zadanie(BaseModel):
    tekst: str
    poziom: int


class BladKonfiguracji(Exception):
    """Konfiguracja serwera nie pozwala na bezpieczny start; komunikat dla administratora."""


@dataclass(frozen=True)
class KonfigSerwera:
    host: str = "127.0.0.1"
    port: int = 8443
    cert_plik: Path | None = None
    klucz_plik: Path | None = None
    zezwol_bez_tls: bool = False
    token_plik: Path | None = None
    modele_katalog: Path | None = None
    poziomy: tuple[int, ...] = POZIOMY
    urzadzenie: str = "auto"
    watki: int = 0
    rownolegle: int = 1
    pakiet_rozszerzony: bool = False
    prog_osoba: float = PROG_OSOBA_DOMYSLNY
    max_tekst_mb: int = 1
    timeout_s: int = 120


def _poziomy(wartosc: object) -> tuple[int, ...]:
    surowe = wartosc.split(",") if isinstance(wartosc, str) else list(wartosc)  # type: ignore[call-overload]
    try:
        poziomy = tuple(int(str(p).strip()) for p in surowe if str(p).strip())
    except ValueError:
        raise BladKonfiguracji(
            f"[modele] poziomy: oczekiwano liczb 1-3, jest {wartosc!r}"
        ) from None
    if not poziomy or any(p not in POZIOMY for p in poziomy):
        raise BladKonfiguracji(f"[modele] poziomy: dozwolone 1, 2, 3; jest {wartosc!r}")
    return tuple(sorted(set(poziomy)))


def wczytaj_konfig_serwera(
    sciezka: Path | None = None, env: Mapping[str, str] | None = None
) -> KonfigSerwera:
    """TOML (sekcje [siec] [dostep] [modele] [limity]) nadpisywany zmiennymi NIEWIDKA_SERWER_*."""
    env = os.environ if env is None else env
    toml: dict = {}
    if sciezka is not None:
        try:
            with Path(sciezka).open("rb") as uchwyt:
                toml = tomllib.load(uchwyt)
        except OSError as blad:
            raise BladKonfiguracji(f"plik konfiguracji nieczytelny: {blad.strerror}") from None
        except tomllib.TOMLDecodeError as blad:
            raise BladKonfiguracji(f"plik konfiguracji ma błąd składni: {blad}") from None
    siec, dostep = toml.get("siec", {}), toml.get("dostep", {})
    modele, limity = toml.get("modele", {}), toml.get("limity", {})

    def sciezka_z(zmienna: str, wartosc: object) -> Path | None:
        return _jako_sciezka(env, zmienna) or (Path(str(wartosc)) if wartosc else None)

    urzadzenie = str(
        env.get("NIEWIDKA_SERWER_URZADZENIE", modele.get("urzadzenie", "auto"))
    ).lower()
    if urzadzenie not in URZADZENIA:
        raise BladKonfiguracji(
            f"[modele] urzadzenie: dozwolone {', '.join(URZADZENIA)}; jest {urzadzenie!r}"
        )
    try:
        konfig = KonfigSerwera(
            host=env.get("NIEWIDKA_SERWER_HOST", siec.get("host", "127.0.0.1")),
            port=_jako_int(env, "NIEWIDKA_SERWER_PORT", int(siec.get("port", 8443))),
            cert_plik=sciezka_z("NIEWIDKA_SERWER_CERT_PLIK", siec.get("cert_plik")),
            klucz_plik=sciezka_z("NIEWIDKA_SERWER_KLUCZ_PLIK", siec.get("klucz_plik")),
            zezwol_bez_tls=_jako_bool(
                env.get("NIEWIDKA_SERWER_ZEZWOL_BEZ_TLS", siec.get("zezwol_bez_tls", False))
            ),
            token_plik=sciezka_z("NIEWIDKA_SERWER_TOKEN_PLIK", dostep.get("token_plik")),
            modele_katalog=sciezka_z("NIEWIDKA_SERWER_MODELE_KATALOG", modele.get("katalog")),
            poziomy=_poziomy(env.get("NIEWIDKA_SERWER_POZIOMY", modele.get("poziomy", POZIOMY))),
            urzadzenie=urzadzenie,
            watki=_jako_int(env, "NIEWIDKA_SERWER_WATKI", int(modele.get("watki", 0))),
            rownolegle=_jako_int(
                env, "NIEWIDKA_SERWER_ROWNOLEGLE", int(modele.get("rownolegle", 1))
            ),
            pakiet_rozszerzony=_jako_bool(
                env.get("NIEWIDKA_SERWER_ROZSZERZONY", modele.get("pakiet_rozszerzony", False))
            ),
            prog_osoba=float(modele.get("prog_osoba", PROG_OSOBA_DOMYSLNY)),
            max_tekst_mb=_jako_int(
                env, "NIEWIDKA_SERWER_MAX_TEKST_MB", int(limity.get("max_tekst_mb", 1))
            ),
            timeout_s=_jako_int(
                env, "NIEWIDKA_SERWER_TIMEOUT_S", int(limity.get("timeout_s", 120))
            ),
        )
    except ValueError as blad:
        raise BladKonfiguracji(str(blad)) from None
    if konfig.rownolegle < 1 or konfig.watki < 0 or konfig.max_tekst_mb < 1 or konfig.timeout_s < 1:
        raise BladKonfiguracji("rownolegle, max_tekst_mb i timeout_s muszą być >= 1, watki >= 0")
    return konfig


def wybierz_provider(urzadzenie: str, dostepne: list[str], platforma: str | None = None) -> str:
    """`urzadzenie` -> provider ONNX. gpu: CUDA, na Windows także DirectML, inaczej błąd
    startu; auto: najlepszy dostępny z fallbackiem na CPU; cpu: zawsze CPU."""
    platforma = platforma or sys.platform
    if urzadzenie == "cpu":
        return CPU
    if urzadzenie not in ("auto", "gpu"):
        raise BladKonfiguracji(
            f"urzadzenie: dozwolone {', '.join(URZADZENIA)}; jest {urzadzenie!r}"
        )
    if CUDA in dostepne:
        return CUDA
    if DML in dostepne and platforma == "win32":
        return DML
    if urzadzenie == "auto":
        return CPU
    raise BladKonfiguracji(
        'urzadzenie = "gpu", ale onnxruntime nie ma dostępnego GPU '
        f"(dostępne providery: {', '.join(dostepne) or 'brak'}). Zainstaluj onnxruntime-gpu "
        "i sterowniki CUDA (Linux/Windows) albo onnxruntime-directml (Windows), "
        'albo ustaw urzadzenie = "auto" lub "cpu".'
    )


def _dostepne_providery() -> list[str]:
    import onnxruntime

    return list(onnxruntime.get_available_providers())


def uzyte_providery(detektor: object, glebokosc: int = 6) -> set[str]:
    """Providery, których sesje ONNX faktycznie używa (pierwszy z `get_providers()`)."""
    znalezione: set[str] = set()
    if glebokosc <= 0:
        return znalezione
    atrybuty = getattr(detektor, "__dict__", None)
    if not atrybuty:
        return znalezione
    for wartosc in atrybuty.values():
        elementy = wartosc if isinstance(wartosc, (list, tuple)) else [wartosc]
        for element in elementy:
            if callable(getattr(element, "get_providers", None)):
                providery = element.get_providers()
                if providery:
                    znalezione.add(providery[0])
            else:
                znalezione |= uzyte_providery(element, glebokosc - 1)
    return znalezione


def sprawdz_siec(konfig: KonfigSerwera) -> list[str]:
    """Fail-closed: poza loopbackiem wymagany TLS (albo jawne zezwol_bez_tls).
    Zwraca ostrzeżenia do logu."""
    ostrzezenia: list[str] = []
    if bool(konfig.cert_plik) != bool(konfig.klucz_plik):
        raise BladKonfiguracji("[siec] cert_plik i klucz_plik podaje się razem albo wcale")
    for plik in (konfig.cert_plik, konfig.klucz_plik):
        if plik is not None and not plik.is_file():
            raise BladKonfiguracji(f"[siec] plik TLS nie istnieje: {plik}")
    if konfig.cert_plik is None and not jest_loopbackiem(konfig.host):
        if not konfig.zezwol_bez_tls:
            raise BladKonfiguracji(
                f"[siec] host {konfig.host!r} jest poza loopbackiem, a nie podano cert_plik i klucz_plik. "
                "Podaj certyfikat TLS albo (tylko sieć wydzielona/test) ustaw zezwol_bez_tls = true."
            )
        ostrzezenia.append(
            "UWAGA: serwer działa BEZ TLS w sieci lokalnej (zezwol_bez_tls = true); "
            "token i teksty przechodzą jawnie. Tylko sieć wydzielona/test."
        )
    return ostrzezenia


def create_app(
    konfig: KonfigSerwera,
    detektor: Any = None,
    *,
    dostepne_providery: Callable[[], list[str]] = _dostepne_providery,
    rozgrzej: bool = False,
) -> FastAPI:
    """Aplikacja serwera. `detektor` wstrzyknięty (testy) obsługuje wszystkie poziomy
    i pomija ładowanie modeli. Brak tokenu, zły TLS, brak GPU = wyjątek przy starcie."""
    ostrzezenia = sprawdz_siec(konfig)
    try:
        token = wczytaj_token(konfig.token_plik, "[dostep] token_plik").encode("ascii")
    except BladTokenu as blad:
        raise BladKonfiguracji(f"{blad}; serwer bez tokenu nie startuje") from None
    if detektor is None:
        provider = wybierz_provider(konfig.urzadzenie, dostepne_providery())
        katalog = konfig.modele_katalog or katalog_modeli()
        konfig_modeli = Konfig(
            modele_katalog=katalog,
            provider=provider,
            watki=konfig.watki,
            prog_osoba=konfig.prog_osoba,
        )
    else:
        provider = "atrapa"
        konfig_modeli = None
    for ostrzezenie in ostrzezenia:
        logger.warning(ostrzezenie)

    app = FastAPI(
        title="Niewidka - serwer inferencji",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # LimitBajtow zlicza surowe bajty (JSON może cytować znaki jako \uXXXX); dokładny
    # limit tekstu sprawdza endpoint. Dodany przed straznikiem, więc straznik jest zewnętrzny.
    app.add_middleware(LimitBajtow, limit_bajtow=6 * konfig.max_tekst_mb * _MB + 4096)
    app.state.konfig = konfig
    app.state.provider = provider
    app.state.kolejka = Kolejka(
        maks=max(8, 4 * konfig.rownolegle), timeout_s=konfig.timeout_s, rownolegle=konfig.rownolegle
    )
    app.state.detektory: dict[int, Any] = {}
    blokada_budowy = threading.Lock()

    def detektor_dla(poziom: int) -> Any:
        if detektor is not None:
            return detektor
        with blokada_budowy:
            if poziom not in app.state.detektory:
                app.state.detektory[poziom] = zbuduj_detektor(
                    poziom, konfig_modeli, pakiet_rozszerzony=konfig.pakiet_rozszerzony
                )
            return app.state.detektory[poziom]

    app.state.detektor_dla = detektor_dla
    if rozgrzej and detektor is None:
        for (
            poziom
        ) in konfig.poziomy:  # błąd wag/GPU wychodzi przy starcie, nie przy pierwszym tekście
            detektor_dla(poziom)

    @app.middleware("http")
    async def straznik(request: Request, call_next):
        """Bearer token (compare_digest) przed czytaniem treści; błąd nieobsłużony -> sam UUID."""
        naglowek = request.headers.get("authorization", "")
        schemat, _, podany = naglowek.partition(" ")
        if schemat.lower() != "bearer" or not hmac.compare_digest(
            podany.strip().encode("utf-8"), token
        ):
            return JSONResponse(
                {"blad": "brak albo zły token"},
                status_code=401,
                headers={"www-authenticate": "Bearer"},
            )
        try:
            odpowiedz = await call_next(request)
        except Exception:  # noqa: BLE001 - nigdy treść wyjątku (może cytować tekst), tylko UUID
            identyfikator = uuid4().hex
            logger.error("blad obslugi zadania: %s", identyfikator)
            return JSONResponse({"blad": identyfikator}, status_code=500)
        odpowiedz.headers.setdefault("cache-control", "no-store")
        return odpowiedz

    @app.exception_handler(RequestValidationError)
    async def _zle_zadanie(request: Request, blad: RequestValidationError):
        # domyślny handler odbijałby w odpowiedzi cały tekst (`input`)
        pola = sorted({str(e["loc"][-1]) for e in blad.errors() if e.get("loc")})
        return JSONResponse({"blad": "niepoprawne żądanie", "pola": pola}, status_code=422)

    @app.exception_handler(KolejkaPelna)
    async def _kolejka_pelna(request: Request, blad: KolejkaPelna):
        return JSONResponse(
            {"blad": "kolejka pełna, spróbuj ponownie za chwilę"},
            status_code=503,
            headers={"retry-after": "2"},
        )

    @app.exception_handler(PracaPrzekroczylaCzas)
    async def _przekroczono_czas(request: Request, blad: PracaPrzekroczylaCzas):
        return JSONResponse(
            {"blad": "przekroczono czas wykrywania"},
            status_code=503,
            headers={"retry-after": str(konfig.timeout_s)},
        )

    @app.post("/v1/wykryj")
    async def wykryj(zadanie: Zadanie) -> dict:
        if zadanie.poziom not in konfig.poziomy:
            raise HTTPException(
                status_code=422, detail=f"poziom niedostępny; dostępne: {list(konfig.poziomy)}"
            )
        if len(zadanie.tekst.encode("utf-8")) > konfig.max_tekst_mb * _MB:
            raise HTTPException(
                status_code=413, detail=f"tekst ponad limit {konfig.max_tekst_mb} MB"
            )
        tekst, poziom = zadanie.tekst, zadanie.poziom

        def praca() -> list[dict]:
            return [{**asdict(z), "typ": str(z.typ)} for z in detektor_dla(poziom).znajdz(tekst)]

        start = time.perf_counter()
        zakresy = await app.state.kolejka.wykonaj(praca)
        # w logu wyłącznie liczby: długość, poziom, czas, liczba zakresów
        logger.info(
            "wykryj: poziom=%d znaki=%d zakresy=%d czas_ms=%d",
            poziom,
            len(tekst),
            len(zakresy),
            (time.perf_counter() - start) * 1000,
        )
        return {"zakresy": zakresy}

    @app.get("/v1/stan")
    async def stan() -> dict:
        uzyte: set[str] = set()
        for wbudowany in list(app.state.detektory.values()):
            uzyte |= uzyte_providery(wbudowany)
        return {
            "wersja": __version__,
            "poziomy": list(konfig.poziomy),
            # faktycznie użyty provider (z sesji ONNX); przed pierwszym budowaniem: wybrany
            "urzadzenie": sorted(uzyte) if uzyte else [provider],
        }

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m niewidka.serwer_inferencji",
        description="Centralny serwer inferencji Niewidki",
    )
    parser.add_argument(
        "--konfig", type=Path, help="plik TOML (patrz konfiguracja/serwer-inferencji.przyklad.toml)"
    )
    polecenia = parser.add_subparsers(dest="polecenie")
    nowy = polecenia.add_parser("nowy-token", help="wygeneruj token do pliku (uprawnienia 0600)")
    nowy.add_argument("sciezka", type=Path)
    argumenty = parser.parse_args(argv)

    if argumenty.polecenie == "nowy-token":
        if argumenty.sciezka.exists():
            print(f"plik istnieje, nie nadpisuję: {argumenty.sciezka}", file=sys.stderr)
            return 1
        zapisz_nowy_token(argumenty.sciezka)
        print(
            f"token zapisany: {argumenty.sciezka} (rozdaj użytkownikom plik, nie wklejaj go do czatów ani maili)"
        )
        return 0

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        konfig = wczytaj_konfig_serwera(argumenty.konfig)
        app = create_app(konfig, rozgrzej=True)
    except BladKonfiguracji as blad:
        print(f"BŁĄD KONFIGURACJI: {blad}", file=sys.stderr)
        return 2
    tls = (
        {"ssl_certfile": str(konfig.cert_plik), "ssl_keyfile": str(konfig.klucz_plik)}
        if konfig.cert_plik
        else {}
    )
    logger.info(
        "start: %s:%d, urządzenie %s, poziomy %s",
        konfig.host,
        konfig.port,
        app.state.provider,
        list(konfig.poziomy),
    )
    uvicorn.run(app, host=konfig.host, port=konfig.port, log_level="info", **tls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
