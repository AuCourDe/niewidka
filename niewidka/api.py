"""FastAPI API: hide/restore/status on 127.0.0.1. Session token, Host/Origin validation, limits
before buffering and after decompression, files only in RAM, no-store, only an error UUID in logs,
inference in a thread pool (Semaphore(1), timeout; full queue -> 503), fail-closed detector."""

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

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser

from niewidka import __version__
from niewidka.aktualizacje import (
    TRYBY_AKTUALIZACJI,
    BladAktualizacji,
    MenedzerAktualizacji,
    TrybNarzucony,
)
from niewidka.archiwum import BladArchiwum
from niewidka.formaty import (
    BladKodowania,
    ElementNieobslugiwany,
    NieznanyFormat,
    adapter_formatu,
    nazwa_wyniku,
    rozszerzenia_wspierane,
)
from niewidka.jakosc import opisy_ryzyka, r95_poziomy
from niewidka.klucze import BrakKlucza, pobierz_klucz
from niewidka.konfig import Konfig, host_w_adresie, host_z_naglowka, wczytaj_konfig
from niewidka.kontrola import Ostrzezenie
from niewidka.listy import ListyStale
from niewidka.magazyn import MagazynMap, kontekst_domyslny, wersje_pakietow
from niewidka.mapa import (
    WARIANT_DOMYSLNY,
    BladMapy,
    Mapa,
    odszyfruj,
    zaszyfruj,
    znajdz_znaczniki,
)
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
from niewidka.poprawki import (
    BladPoprawki,
    PamiecWykryc,
    pewne_znaczniki,
    popraw,
    sprawdz_liste,
    z_pewna_suma,
)
from niewidka.rdzen import (
    ArchiwumZaDuze,
    identyfikator_z_dopisku,
    przywroc,
    ukryj,
    zbuduj_detektor,
)
from niewidka.zdalny import SerwerModeliNiedostepny, ZdalnyDetektor, stan_serwera, zbuduj_klienta

logger = logging.getLogger("niewidka.api")

_MB = 1024 * 1024
_TOKEN_NAGLOWEK = "x-niewidka-token"
_KATALOG_WEB = Path(__file__).parent / "web"
_POZIOMY = (1, 2, 3)  # quality slider


class BrakWymaganegoPakietu(Exception):
    """The slider level needs a package that is missing."""

    def __init__(self, brakujace: list[str], nazwy: list[str] | None = None):
        self.brakujace = brakujace
        self.nazwy = nazwy or brakujace
        super().__init__(
            "brakuje pakietu modeli: "
            + ", ".join(self.nazwy)
            + "; pobierz go w Ustawieniach albo przy pierwszym uruchomieniu"
        )


class KolejkaPelna(Exception):
    """All slots are busy and the queue is full."""


class PracaPrzekroczylaCzas(Exception):
    """The work exceeded the time limit. Work that has started keeps the slot until it actually
        finishes (a thread cannot be stopped); work still waiting for the slot is dropped."""

    def __init__(self, rozpoczeta: bool = True):
        self.rozpoczeta = rozpoczeta
        super().__init__("praca przekroczyła limit czasu")


class BladKontroli(Exception):
    """The write check blocked the result (-> 422). Besides the types it carries the places for the
        user to decide (fragment + position in the preview), the preview text and the job id
        for `/api/popraw`. Fragments go only in the response
        to the UI on this computer, never to logs or the journal."""

    def __init__(
        self,
        typy: dict[str, int],
        miejsca: list[dict] | None = None,
        podglad: str | None = None,
        zadanie: str | None = None,
        pewne: list[str] | None = None,
    ):
        self.typy = typy
        self.miejsca = miejsca or []
        self.podglad = podglad
        self.zadanie = zadanie
        self.pewne = pewne or []
        super().__init__("kontrola zapisu zablokowała wynik")


class BrakZadaniaPoprawek(Exception):
    """The job's detections expired or never existed (-> 410)."""


class WybierzMape(Exception):
    """Restoring without a given map: the user must pick from the job list."""

    def __init__(self, komunikat: str, kandydaci: list[dict]):
        self.kandydaci = kandydaci
        super().__init__(komunikat)


def _wartosci(mapa: Mapa) -> dict[tuple[str, str], str]:
    """(marker, variant) -> original: the key the restore looks up."""
    return {(w.oznaczenie, wariant): oryginal for w in mapa.wpisy for wariant, oryginal in w.formy.items()}


def _rozne_dane(mapy: list[Mapa], pary: set[tuple[str, str]]) -> bool:
    """Whether a (marker, variant) of the text stands for different data in the given maps (the
    markers of "Ukryj wszędzie" are numbered anew in every correction)."""
    wartosci = [_wartosci(m) for m in mapy]
    return any(len({w[para] for w in wartosci if para in w}) > 1 for para in pary)


class BrakMapyWMagazynie(Exception):
    """The note or id points to a map that is not in the store
        (expired, deleted, foreign session) -> 422 with a clear message."""


class LicznikZlecen:
    """limits the number of requests IN PROGRESS (POST /api/ukryj and /api/przywroc)
        before anything reads the body: the excess gets 503 immediately, so
        uploads cannot hold memory while waiting outside the inference queue."""

    def __init__(self, app, limit: int):
        self.app = app
        self.limit = limit
        self.w_toku = 0

    async def __call__(self, scope, receive, send):
        sciezka = scope.get("path", "")
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not sciezka.startswith(("/api/ukryj", "/api/przywroc", "/api/popraw"))
        ):
            await self.app(scope, receive, send)
            return
        # increment with no await between check and write: atomic in the event loop
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
    """counts the request body bytes BEFORE the form parser, also
        for chunked transfer without a Content-Length header. Once the limit is exceeded
        the app receives no byte (nothing lands in buffers, the disk spool
        never starts) and the client gets 413. All POSTs are covered,
        including /api/przywroc."""

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
    """One inference at a time (Semaphore in a thread pool), `kolejka` waiting.

        The semaphore holds the TASK of the work, not the waiting request: after a
        timeout the request gets 503 and the slot stays held until the work ACTUALLY
        ends (cancelling the wait does not stop the executor thread)."""

    maks: int
    timeout_s: int
    czekajacy: int = 0
    rownolegle: int = 1  # inference server: this many jobs at once; the user app stays at 1
    _semafor: asyncio.Semaphore | None = None

    def _slot(self) -> asyncio.Semaphore:
        if self._semafor is None:  # created in the event loop that uses it first
            self._semafor = asyncio.Semaphore(self.rownolegle)
        return self._semafor

    async def wykonaj(self, praca, timeout_s: int | None = None):
        limit = timeout_s or self.timeout_s
        if self._slot().locked():
            # slot busy: this request becomes the next waiting one; the place is freed
            if self.czekajacy >= self.maks:
                raise KolejkaPelna()
            self.czekajacy += 1
            return await self._oczekiwane(praca, limit, liczone=True)
        # slot free: this request creates its own task under the semaphore
        return await self._oczekiwane(praca, limit)

    async def _oczekiwane(self, praca, limit: int, liczone: bool = False):
        rozpoczeta = asyncio.Event()
        zadanie = asyncio.create_task(self._z_slotem(praca, liczone, rozpoczeta))
        zadanie.add_done_callback(_pochlonnij_wyjatek)
        zakonczone, _ = await asyncio.wait({zadanie}, timeout=limit)
        if zadanie not in zakonczone:
            if not rozpoczeta.is_set():
                # still waiting for the slot: nobody waits for this result, so it never starts;
                # its place in the queue is free before the reply goes out
                zadanie.cancel()
                await asyncio.wait({zadanie})
                raise PracaPrzekroczylaCzas(rozpoczeta=False)
            raise PracaPrzekroczylaCzas()  # task keeps working and holds the slot
        return zadanie.result()

    async def _z_slotem(self, praca, liczone: bool, rozpoczeta: asyncio.Event):
        zwolnione = False
        try:
            async with self._slot():
                if liczone:
                    self.czekajacy -= 1
                    zwolnione = True
                rozpoczeta.set()  # no await until the thread is submitted
                return await asyncio.to_thread(praca)
        finally:
            if liczone and not zwolnione:  # cancelled before it got a slot
                self.czekajacy -= 1

    def stan(self) -> dict[str, int]:
        return {"czekajacy": self.czekajacy, "maks": self.maks}


def _pochlonnij_wyjatek(zadanie: asyncio.Task) -> None:
    """A task abandoned after a timeout: it fetches the exception so the event loop stays quiet."""
    if not zadanie.cancelled():
        zadanie.exception()


async def _obiekt_json(request: Request) -> dict:
    try:
        tresc = await request.json()
    except Exception:  # noqa: BLE001 - the content is not echoed in the response
        raise HTTPException(status_code=422, detail="oczekiwano JSON") from None
    if not isinstance(tresc, dict):
        raise HTTPException(status_code=422, detail="oczekiwano obiektu JSON")
    return tresc


def _json_naglowek(wartosc: Any) -> str:
    # HTTP headers are latin-1: Polish characters (warning fragments) must be escaped
    # as \uXXXX, otherwise the response dies with UnicodeEncodeError.
    return json.dumps(wartosc, ensure_ascii=True)


def _licznik_typow(ostrzezenia: list[Ostrzezenie]) -> dict[str, int]:
    """Finding types with counts: headers and errors never carry fragments
        or part names."""
    licznik: dict[str, int] = {}
    for ostrzezenie in ostrzezenia:
        licznik[ostrzezenie.typ] = licznik.get(ostrzezenie.typ, 0) + 1
    return licznik


def _wczytaj_rejestr_map(plik: Path | None, szyfrogramy: dict[str, str], identyfikatory: set[str]) -> None:
    """Maps issued before a restart: without this, closing the window ended
        the ability to restore. Damaged rows are skipped (fail-closed: a map outside the
        registry would not pass anyway)."""
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
    except OSError as blad:  # no write = the map works only in this session; not a failure
        logger.warning("rejestr map niezapisany: %s", type(blad).__name__)


def _przepisz_rejestr(plik: Path | None, bez_identyfikatorow: set[str]) -> None:
    """Registry of issued maps rewritten atomically without the struck maps:
        downloaded copies of those maps stop working on restore."""
    if plik is None or not plik.is_file():
        return
    wiersze = []
    for wiersz in plik.read_text(encoding="utf-8").splitlines():
        try:
            if str(json.loads(wiersz)["id"]) in bez_identyfikatorow:
                continue
        except (ValueError, KeyError, TypeError):
            pass  # damaged row is kept: _wczytaj_rejestr_map skips it anyway
        wiersze.append(wiersz)
    opublikuj_bez_hasza(
        ("\n".join(wiersze) + "\n").encode("utf-8") if wiersze else b"", plik, plik.parent
    )

def create_app(
    konfig: Konfig | None = None,
    detektor: Any = None,
    menedzer_pakietow: MenedzerPakietow | None = None,
    klient_inferencji: httpx.Client | None = None,
) -> FastAPI:
    """API app; `detektor` injected (tests/desktop) or built from weights
        (NIEWIDKA_MODELE_KATALOG). Missing weights do NOT kill startup: the app comes up
        and hiding answers 409 with the list of missing packages (the first-run screen
        leads to the download); `menedzer_pakietow` is injected in tests.
        `[inferencja] adres` = detection on the central server (`klient_inferencji`
        injected in tests); client configuration errors abort startup."""
    konfig = konfig or wczytaj_konfig()
    if konfig.modele_katalog is None:
        # one path for the package manager and the detector:
        # otherwise a package was downloaded to the default directory while hiding looked for weights elsewhere
        konfig = replace(
            konfig,
            modele_katalog=menedzer_pakietow.katalog if menedzer_pakietow else katalog_modeli(),
        )
    if konfig.mapy_katalog is None:
        # map store in the user data directory
        konfig = replace(konfig, mapy_katalog=katalog_danych() / "mapy")
    if konfig.listy_plik is None:
        konfig = replace(konfig, listy_plik=katalog_danych() / "listy.json")
    if konfig.rejestr_map is None:
        # a downloaded .nwidka must restore after the program is started again
        konfig = replace(konfig, rejestr_map=katalog_danych() / "wydane-mapy.jsonl")
    wstrzykniety = detektor
    if konfig.inferencja_adres and klient_inferencji is None:
        klient_inferencji = zbuduj_klienta(konfig)
    zdalny = bool(konfig.inferencja_adres)
    if wstrzykniety is None and not zdalny:
        try:
            wstrzykniety = zbuduj_detektor(konfig.poziom, konfig)
        except Exception:  # noqa: BLE001 - no package/weights: soft start (see above)
            wstrzykniety = None

    # multipart without spilling to disk: spool >= the limit that is enforced before buffering anyway
    MultiPartParser.spool_max_size = konfig.max_rozmiar_mb * _MB

    app = FastAPI(title="Niewidka", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    # ordered by depth: LicznikZlecen (outermost, added last)
    # -> LimitBajtow -> http middleware; an excess request gets 503 without reading the body
    app.add_middleware(LimitBajtow, limit_bajtow=konfig.max_rozmiar_mb * _MB)
    app.add_middleware(LicznikZlecen, limit=konfig.zlecenia)
    app.state.konfig = konfig
    app.state.token = secrets.token_urlsafe(32)
    app.state.detektor = wstrzykniety
    # key (level, Extended package installed): an injected detector serves
    # all levels; in production a lazy cache. The startup one was built without the Extended package.
    app.state.detektory: dict[tuple[int, bool], Any] = (
        {} if detektor is not None or zdalny else {(konfig.poziom, False): wstrzykniety}
    )
    app.state.klient_inferencji = klient_inferencji if zdalny else None
    app.state.kolejka = Kolejka(maks=konfig.kolejka, timeout_s=konfig.timeout_s)
    app.state.identyfikatory: set[str] = set()
    # SHA-256 hashes of ciphertexts issued in THIS session: on restore
    # the map must be one of them (old/intercepted ciphertexts are not decrypted)
    app.state.szyfrogramy: dict[str, str] = {}
    _wczytaj_rejestr_map(konfig.rejestr_map, app.state.szyfrogramy, app.state.identyfikatory)
    # map store with retention; expired maps are cleaned
    # at startup, before anything is restored (SIMPLIFICATION: no background clock)
    def _kontekst_dziennika() -> dict:
        """Audit with environment context: user, program version,
                model package versions from the manifests (if the manifests give them)."""
        pola = kontekst_domyslny()
        pola["pakiety"] = wersje_pakietow(konfig.modele_katalog)
        return pola

    # detections of recent jobs for preview corrections: RAM only, short-lived
    app.state.poprawki = PamiecWykryc(konfig.poprawki_maks_zadan, konfig.poprawki_ttl_s)
    app.state.listy = ListyStale(
        konfig.listy_plik, konfig.listy_zawsze, konfig.listy_nigdy, konfig.listy_tylko_administrator
    )

    def _popraw_z_listami(detekcje, ukryj_uzytkownika=(), nie_dane=(), zostaw=(), na_inne=(), odkryj=()):
        """`popraw` with constant lists: "Zawsze ukrywaj" goes before the user list (fixed
                marker numbers), "Nigdy nie ukrywaj" works like "To nie dane"; the user's explicit
                "Ukryj wszędzie" wins over "Nigdy". It also returns `wlasne` converted to positions of the
                user list and the markers created from the "Zawsze" list (marker -> list position).
                `odkryj`: "Zawsze" entries switched off only in this document."""
        listy = app.state.listy.razem()
        zawsze = [f for f in listy.zawsze if f not in odkryj]
        nie_dane_razem = list(nie_dane) + [z for z in listy.znaczniki_nigdy(detekcje) if z not in nie_dane]
        wynik, mapa, raport, wlasne = popraw(
            detekcje,
            zawsze + list(ukryj_uzytkownika),
            nie_dane_razem,
            list(zostaw) + [f for f in listy.nigdy if f not in zostaw],
            na_inne,
            kontrola_blokada=konfig.kontrola_blokada,
            wykrywaj_date=konfig.wykrywaj_date,
        )
        n = len(zawsze)
        z_listy = {z: listy.zawsze.index(zawsze[i]) for z, i in sorted(wlasne.items()) if i < n}
        wlasne = {z: i - n for z, i in wlasne.items() if i >= n}
        return wynik, mapa, raport, wlasne, z_listy
    app.state.magazyn = MagazynMap(
        konfig.mapy_katalog, retencja_dni=konfig.mapy_retencja_dni, kontekst=_kontekst_dziennika
    )

    def _skresl_z_rejestru(identyfikatory: set[str] | list[str]) -> None:
        """Retention and the manual "Usuń" apply to the program store,
                and a downloaded copy keeps working. Only the `mapy_uniewaznij_pobrane` option
                strikes the map from the registry of issued maps (memory and file), so copies stop
                working. One store lock covers changing both places."""
        if not konfig.mapy_uniewaznij_pobrane or not identyfikatory:
            return
        identyfikatory = set(identyfikatory)
        app.state.identyfikatory -= identyfikatory
        for skrot, wydane in list(app.state.szyfrogramy.items()):
            if wydane in identyfikatory:
                del app.state.szyfrogramy[skrot]
        _przepisz_rejestr(konfig.rejestr_map, identyfikatory)

    def _posprzataj() -> None:
        """Clean up expired entries on every ukryj/przywroc/lista call."""
        with app.state.magazyn.blokada:
            _skresl_z_rejestru(app.state.magazyn.posprzataj())

    _posprzataj()  # a disabled program does not clean up; it cleans at startup, before anything is restored
    if menedzer_pakietow is None:
        menedzer_pakietow = MenedzerPakietow(
            wczytaj_pakiety(), konfig.modele_katalog or katalog_modeli(), zrodlo()
        )
    # a package change (download/removal/install) invalidates the detector
    # cache, otherwise an installed Extended package would not enter detection
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
        """Detector for the chosen slider level. An injected one serves all
                levels (tests/desktop); production ones are built lazily and cached; building
                is serialized by the queue's Semaphore(1) anyway. A missing required
                package = a clear `BrakWymaganegoPakietu` (409), not 500.
                Level 3 gets the verified Extended package state from the manager."""
        if detektor is not None:  # an injected detector serves all levels
            return detektor
        if zdalny:  # inference server: no local weights or packages, so no 409
            return app.state.detektory.setdefault(
                (poziom, False),
                ZdalnyDetektor(poziom, app.state.klient_inferencji, konfig.wykrywaj_date),
            )
        # package state in the key: a detector built from the pre-verification state
        # (with no change returned) must not stay cached for level 3
        rozszerzony = poziom == 3 and app.state.pakiety.stan_pakietu("rozszerzony") == "zainstalowany"
        zbudowany = app.state.detektory.get((poziom, rozszerzony))
        if zbudowany is None:
            try:
                zbudowany = zbuduj_detektor(
                    poziom,
                    konfig,
                    pakiet_rozszerzony=rozszerzony,
                    katalog_pakietow=app.state.aktualizacje.zaufane_pakiety(),
                )
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
        f"http://{host_w_adresie(konfig.host)}:{konfig.port}",
        f"https://{host_w_adresie(konfig.host)}:{konfig.port}",
        f"http://localhost:{konfig.port}",
        f"https://localhost:{konfig.port}",
    }
    hosty = (konfig.host, "localhost")

    @app.middleware("http")
    async def straznik_i_limity(request: Request, call_next):
        """Session token + Host/Origin for POST and DELETE on /api/ and GET on
                packages/status/maps (package status can carry a secret
                from the mirror); limits before buffering the body."""
        strazliwe_gety = ("/api/pakiety", "/api/stan", "/api/mapy", "/api/aktualizacje", "/api/listy")
        # Host is checked on EVERY request: the main page issues the token in meta
        # (a foreign Host + DNS rebinding would hand the token over)
        if host_z_naglowka(request.headers.get("host") or "") not in hosty:
            return JSONResponse({"blad": "niedozwolony Host"}, status_code=403)
        if (
            request.method in ("POST", "PUT", "DELETE") and request.url.path.startswith("/api/")
        ) or (request.method == "GET" and request.url.path in strazliwe_gety):
            host = host_z_naglowka(request.headers.get("host") or "")
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
        """Unhandled exception -> only an error UUID in the log."""
        try:
            odpowiedz = await call_next(request)
        except Exception:  # noqa: BLE001 - catch EVERYTHING, log only the UUID (no content)
            identyfikator_bledu = uuid4().hex
            logger.error("blad obslugi zadania: %s", identyfikator_bledu)
            return JSONResponse({"blad": identyfikator_bledu}, status_code=500)
        odpowiedz.headers.setdefault("cache-control", "no-store")
        return odpowiedz

    @app.exception_handler(NieznanyFormat)
    async def _nieznany_format(request: Request, blad: NieznanyFormat):
        # the file name may identify a person: the response carries only the list of formats
        return JSONResponse(
            {"blad": f"nieznany format pliku; obsługiwane: {', '.join(sorted(blad.wspierane))}"},
            status_code=415,
        )

    @app.exception_handler(BladKodowania)
    async def _blad_kodowania(request: Request, blad: BladKodowania):
        return JSONResponse({"blad": str(blad)}, status_code=422)

    @app.exception_handler(ElementNieobslugiwany)
    async def _element_nieobslugiwany(request: Request, blad: ElementNieobslugiwany):
        # part names are not returned (PII can sit in a name)
        return JSONResponse(
            {"blad": "dokument zawiera nieobsługiwane elementy", "liczba": len(blad.elementy)},
            status_code=422,
        )

    @app.exception_handler(RequestValidationError)
    async def _walidacja_zadania(request: Request, blad: RequestValidationError):
        # no input field and no echo of input values
        return JSONResponse({"blad": "nieprawidłowe dane żądania"}, status_code=422)

    @app.exception_handler(zipfile.BadZipFile)
    async def _zly_docx(request: Request, blad: zipfile.BadZipFile):
        # a corrupted .docx used to give 500
        return JSONResponse(
            {"blad": "plik nie jest poprawnym dokumentem DOCX (uszkodzony albo to inny format)"},
            status_code=422,
        )

    @app.exception_handler(BladMapy)
    async def _blad_mapy(request: Request, blad: BladMapy):
        return JSONResponse({"blad": str(blad)}, status_code=422)

    @app.exception_handler(WybierzMape)
    async def _wybierz_mape(request: Request, blad: WybierzMape):
        # the UI leads to the task list
        return JSONResponse(
            {"kod": "wybierz_mape", "blad": str(blad), "kandydaci": blad.kandydaci},
            status_code=422,
        )

    @app.exception_handler(BladPoprawki)
    async def _blad_poprawki(request: Request, blad: BladPoprawki):
        return JSONResponse({"blad": str(blad)}, status_code=422)

    @app.exception_handler(BrakZadaniaPoprawek)
    async def _brak_zadania_poprawek(request: Request, blad: BrakZadaniaPoprawek):
        return JSONResponse(
            {"kod": "brak_zadania", "blad": "Minął czas na poprawki tego zadania. Ukryj dokument ponownie."},
            status_code=410,
        )

    @app.exception_handler(BrakMapyWMagazynie)
    async def _brak_mapy_w_magazynie(request: Request, blad: BrakMapyWMagazynie):
        return JSONResponse({"kod": "brak_mapy", "blad": str(blad)}, status_code=422)

    @app.exception_handler(ArchiwumZaDuze)
    async def _archiwum_za_duze(request: Request, blad: ArchiwumZaDuze):
        return JSONResponse({"blad": str(blad)}, status_code=413)

    @app.exception_handler(BladArchiwum)
    async def _blad_archiwum(request: Request, blad: BladArchiwum):
        # lying headers/foreign compression = refusal (fail-closed, 422)
        return JSONResponse({"blad": "archiwum nieprawidłowe lub niebezpieczne"}, status_code=422)

    @app.exception_handler(BrakKlucza)
    async def _brak_klucza(request: Request, blad: BrakKlucza):
        return JSONResponse({"blad": str(blad)}, status_code=500)

    # BladDetektora deliberately has NO handler: it falls through to the logi_bez_tresci middleware
    # -> 500 with a UUID, fail-closed, no exception text in the response.

    @app.exception_handler(KolejkaPelna)
    async def _kolejka_pelna(request: Request, blad: KolejkaPelna):
        return JSONResponse(
            {"blad": "kolejka pełna, spróbuj ponownie za chwilę"},
            status_code=503,
            headers={"retry-after": str(konfig.timeout_s)},
        )

    @app.exception_handler(PracaPrzekroczylaCzas)
    async def _praca_przekroczyla_czas(request: Request, blad: PracaPrzekroczylaCzas):
        # 503 with retry-after; started work still holds the slot, so the next try may wait
        if blad.rozpoczeta:
            komunikat = (
                f"Praca nad tym dokumentem trwa dłużej niż limit ({konfig.timeout_s} s), więc nie "
                "czekam na wynik. Podziel dokument na mniejsze części albo wybierz niższy poziom "
                "jakości. Program kończy jeszcze tę pracę w tle, więc następna próba może chwilę "
                "poczekać."
            )
        else:
            komunikat = (
                "Program zajmował się innym dokumentem i nie zdążył zacząć tego. "
                "Spróbuj ponownie za chwilę."
            )
        return JSONResponse(
            {"kod": "limit_czasu", "blad": komunikat},
            status_code=503,
            headers={"retry-after": str(konfig.timeout_s)},
        )

    @app.exception_handler(SerwerModeliNiedostepny)
    async def _serwer_modeli_niedostepny(request: Request, blad: SerwerModeliNiedostepny):
        # fail-closed: no server means no result; the message carries no document content
        return JSONResponse(
            {"blad": str(blad), "kod": "serwer_modeli"},
            status_code=503,
            headers={"retry-after": "5"},
        )

    @app.exception_handler(BrakWymaganegoPakietu)
    async def _brak_wymaganego_pakietu(request: Request, blad: BrakWymaganegoPakietu):
        # a level without the required package = a clear error listing the packages to download
        return JSONResponse(
            {"blad": str(blad), "brak_pakietu": blad.brakujace}, status_code=409
        )

    @app.exception_handler(BladPakietu)
    async def _blad_pakietu(request: Request, blad: BladPakietu):
        # offline install with a mismatched SHA-256: fail-closed, the files do not enter
        # the weights directory; the message carries no file content
        return JSONResponse({"blad": str(blad)}, status_code=422)

    @app.exception_handler(TrybNarzucony)
    async def _tryb_narzucony(request: Request, blad: TrybNarzucony):
        return JSONResponse({"blad": str(blad)}, status_code=409)

    @app.exception_handler(BladAktualizacji)
    async def _blad_aktualizacji(request: Request, blad: BladAktualizacji):
        return JSONResponse({"blad": str(blad)}, status_code=422)

    async def _stan_serwera_inferencji() -> dict | None:
        """Inference server state (None = local models). An unreachable server does not
                break /api/stan: the UI gets `dostepny: false` and no levels."""
        if not zdalny:
            return None
        try:
            stan = await asyncio.to_thread(stan_serwera, app.state.klient_inferencji)
        except SerwerModeliNiedostepny as blad:
            return {"adres": konfig.inferencja_adres, "dostepny": False, "blad": str(blad)}
        poziomy = [p for p in stan.get("poziomy", []) if p in _POZIOMY]
        return {
            "adres": konfig.inferencja_adres,
            "dostepny": True,
            "poziomy": poziomy,
            "urzadzenie": stan.get("urzadzenie"),
            "wersja": stan.get("wersja"),
        }

    async def _poziomy_dostepne(serwer: dict | None) -> list[int]:
        if serwer is None:
            return app.state.pakiety.poziomy_dostepne()
        return serwer.get("poziomy", [])

    @app.get("/api/pakiety")
    async def endpoint_pakiety() -> dict:
        """Package state + progress of the current operation; no token needed: the data
                is not personal, but behind POST stands the session token as everywhere."""
        pakiety_stan = app.state.pakiety
        odpowiedz = {
            "pakiety": pakiety_stan.lista(),
            "poziomy_dostepne": await _poziomy_dostepne(await _stan_serwera_inferencji()),
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
        """download (background, 202) | remove (200) | install from the IT catalog (background, 202)
                | cancel the current operation (200). Background operation errors land
                in postep.blad (GET /api/pakiety)."""
        zlecenie = await _obiekt_json(request)
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
            "klucz_wydawcy": akt.ma_klucze,
            "wersja_katalogu": wczytaj_wersje_katalogu(akt.katalog_aktywny_plik),
            "ostatnie_sprawdzenie": akt.ostatnie_sprawdzenie,
            "pakiety": akt.lista_pakietow(),
            "postep": akt.postep,
        }

    @app.post("/api/aktualizacje")
    async def endpoint_aktualizacje_akcja(request: Request) -> JSONResponse:
        """check | install (background, 202; with folder: offline) | rollback | mode
                (409 when the mode is imposed by the administrator's configuration)."""
        zlecenie = await _obiekt_json(request)
        akcja = zlecenie.get("akcja")
        akt = app.state.aktualizacje
        if akcja not in ("sprawdz", "instaluj", "cofnij", "tryb"):
            raise HTTPException(status_code=422, detail="nieznana akcja aktualizacji")

        if akcja == "tryb":
            nowy_tryb = zlecenie.get("tryb")
            if not nowy_tryb:
                raise HTTPException(status_code=422, detail="brak pola tryb")
            if nowy_tryb not in TRYBY_AKTUALIZACJI:
                raise HTTPException(status_code=422, detail="nieznany tryb aktualizacji")
            akt.ustaw_tryb(nowy_tryb)
            return JSONResponse({"stan": "zmieniono_tryb", "tryb": nowy_tryb})

        if akcja == "sprawdz":
            # downloading the catalog is a network request: do not block the event loop
            await run_in_threadpool(akt.sprawdz_aktualizacje)
            return JSONResponse({"stan": akt.stan, "blad": akt.blad})

        if akcja == "instaluj":
            pakiet_id = zlecenie.get("pakiet")
            folder = zlecenie.get("folder")
            if not pakiet_id and not folder:
                raise HTTPException(
                    status_code=422, detail="instaluj wymaga pakietu albo folderu z aktualizacją"
                )
            if not akt.instaluj_aktualizacje(pakiet_id, w_tle=True, folder=folder and Path(folder)):
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
        # a blocked document does NOT come back: no document bytes,
        # no fragments; only finding types with counts.
        odpowiedz = {
            "blad": "kontrola znalazła w wyniku dane przypominające oryginalne, dokument zablokowany",
            "status": "zablokowany",
            "typy": blad.typy,
        }
        if blad.zadanie:
            odpowiedz.update(
                zadanie=blad.zadanie, miejsca=blad.miejsca, podglad=blad.podglad, pewne=blad.pewne
            )
        return JSONResponse(odpowiedz, status_code=422)

    def _format_z_nazwy(nazwa: str) -> str:
        rozszerzenie = Path(nazwa).suffix.lstrip(".").lower()
        if not rozszerzenie:
            raise NieznanyFormat(nazwa, sorted(rozszerzenia_wspierane()))
        return rozszerzenie

    @app.post("/api/ukryj")
    async def endpoint_ukryj(
        request: Request,
        poziom: int = Form(1),
        plik: UploadFile | None = File(None),  # noqa: B008 - FastAPI pattern
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
            klucz = pobierz_klucz(konfig)  # the key lives only in the operation thread
            wynik, mapa, raport = ukryj(
                dane,
                format,
                poziom,
                detektor=_detektor_dla(poziom),
                kontrola_blokada=konfig.kontrola_blokada,
                max_rozpakowane_bajtow=konfig.max_rozpakowane_mb * _MB,
                polityka_obrazow=konfig.obrazy,
            )
            zadanie = mapa.identyfikator
            detekcje = raport.detekcje
            listy = app.state.listy.razem()
            z_listy = None
            if detekcje is not None and (listy.zawsze or listy.znaczniki_nigdy(detekcje) or listy.nigdy):
                # constant lists are applied like a correction right after hiding (the model is not called again)
                wynik, mapa, raport, _, z_listy = _popraw_z_listami(detekcje)
            return wynik, mapa, raport, zaszyfruj(mapa, klucz), zadanie, detekcje, z_listy

        wynik, mapa, raport, mapa_paczka, zadanie, detekcje, z_listy = await app.state.kolejka.wykonaj(praca)
        # task = id of the base map; corrections are always computed from these detections
        app.state.poprawki.zapamietaj(zadanie, detekcje)
        return _wydaj_wynik(
            wynik, mapa, raport, mapa_paczka, nazwa, format, zadanie, z_listy=z_listy,
            pewne=pewne_znaczniki(detekcje) if detekcje is not None else set(),
        )

    def _miejsca_do_decyzji(raport, wynik: bytes, format: str) -> tuple[list[dict], str | None]:
        """List of doubtful places (fragment + position in the preview) and the preview text.
                The preview is for TXT only; other formats get the list without positions (-1)."""
        podglad = wynik.decode("utf-8", errors="replace") if format == "txt" else None
        zebrane: dict[tuple[str, str], dict] = {}
        for o in raport.ostrzezenia:
            fragment = o.fragment.strip()
            if not fragment:
                continue
            pozycja = -1
            if podglad is not None:
                # TXT is a single segment, so the offset from the check is an offset in the preview
                pozycja = (
                    o.start + len(o.fragment) - len(o.fragment.lstrip())
                    if o.segment >= 0 and o.start >= 0
                    else podglad.find(fragment)
                )
            miejsce = zebrane.setdefault(
                (o.typ, fragment),
                # "pewne": a matching checksum, so the UI offers no "To nie dane"
                {
                    "typ": o.typ, "fragment": fragment, "pozycja": pozycja, "wystapien": 0,
                    "pewne": z_pewna_suma(fragment),
                },
            )
            miejsce["wystapien"] += 1
        return list(zebrane.values()), podglad

    def _wydaj_wynik(
        wynik, mapa, raport, mapa_paczka, nazwa, format, zadanie, wlasne=None, z_listy=None,
        na_inne=None, pewne=frozenset(),
    ) -> Response:
        """Shared by /api/ukryj and /api/popraw: a block (422 with places to decide) or
                the map write before the response and the ZIP package with headers."""
        if raport.status == "zablokowany":
            miejsca, podglad = _miejsca_do_decyzji(raport, wynik, format)
            raise BladKontroli(
                _licznik_typow(raport.ostrzezenia), miejsca, podglad, zadanie, sorted(pewne)
            )
        _posprzataj()  # clean up expired entries on every call
        mapa_zapisana = None  # expiry datetime or "blad"
        with app.state.magazyn.blokada:  # one lock: store + journal + registry
            app.state.identyfikatory.add(mapa.identyfikator)
            skrot = hashlib.sha256(mapa_paczka).hexdigest()
            app.state.szyfrogramy[skrot] = mapa.identyfikator
            _dopisz_do_rejestru(konfig.rejestr_map, skrot, mapa.identyfikator)
            try:
                # write BEFORE responding: an error does not kill hiding,
                # the result returns with a "blad" header and the UI asks to download the map
                mapa_zapisana = app.state.magazyn.zapisz(
                    mapa_paczka, mapa, raport.statystyki, zadanie=zadanie
                )
            except (OSError, BladMapy) as blad:
                logger.warning("magazyn map niezapisany: %s", type(blad).__name__)
                mapa_zapisana = "blad"

        # the full id lives in the map and header; file names
        # get only a short hash (a file name need not be unforgeable)
        skrot = mapa.identyfikator[:12]
        paczka = io.BytesIO()
        with zipfile.ZipFile(paczka, "w", zipfile.ZIP_DEFLATED) as zip_archiwum:
            zip_archiwum.writestr(nazwa_wyniku(nazwa, skrot), wynik)
            zip_archiwum.writestr(f"{skrot}.nwidka", mapa_paczka)
        naglowki = {
            "x-niewidka-identyfikator": mapa.identyfikator,
            "x-niewidka-zadanie": zadanie,
            "x-niewidka-statystyki": _json_naglowek(raport.statystyki),
            "x-niewidka-ostrzezenia": _json_naglowek(_licznik_typow(raport.ostrzezenia)),
            "x-niewidka-uwagi": _json_naglowek(raport.uwagi),
            # ready-made risk texts (the small-sample threshold is computed by the server), not a bare R95
            "x-niewidka-r95": _json_naglowek(opisy_ryzyka(raport.poziom, list(raport.statystyki))),
            "x-niewidka-status": raport.status,
            # markers of numbers with a matching checksum: no "To nie dane" in the UI
            "x-niewidka-pewne": _json_naglowek(sorted(pewne)),
            # present only when the map went to the store
            "content-disposition": 'attachment; filename="wynik.zip"',
        }
        if wlasne is not None:
            # marker -> number of the "ukryj" entry it came from (the UI undoes these instead of "To nie dane")
            naglowki["x-niewidka-wlasne"] = _json_naglowek(wlasne)
        if z_listy:
            # markers from the "Zawsze ukrywaj" list -> index in `zawsze_razem` from GET /api/listy
            # (the entry text does not go in the header)
            naglowki["x-niewidka-z-listy"] = _json_naglowek(z_listy)
        if na_inne:
            # new marker INNE_n -> base marker that changed kind (corrections are computed from base markers)
            naglowki["x-niewidka-na-inne"] = _json_naglowek(na_inne)
        if mapa_zapisana is not None:
            naglowki["x-niewidka-mapa-zapisana"] = (
                mapa_zapisana if isinstance(mapa_zapisana, str) else mapa_zapisana.isoformat()
            )
        return Response(paczka.getvalue(), media_type="application/zip", headers=naglowki)

    def _nowe_na_bazowe(detekcje, mapa, na_inne, wlasne) -> dict[str, str]:
        """A INNE_n marker created by a kind change -> the base marker (matched by the
                original fragments from the map). Later corrections must point to base markers."""
        bazowe = {e.oznaczenie for encje in detekcje.encje for e in encje}
        teksty = {
            z: {e.tekst for encje in detekcje.encje for e in encje if e.oznaczenie == z}
            for z in na_inne
        }
        wynik: dict[str, str] = {}
        for wystapienie in mapa.wystapienia:
            nowy = wystapienie.oznaczenie
            if nowy in bazowe or nowy in wlasne or nowy in wynik:
                continue
            for z, fragmenty in teksty.items():
                if wystapienie.oryginal in fragmenty and z not in wynik.values():
                    wynik[nowy] = z
                    break
        return wynik

    @app.post("/api/popraw")
    async def endpoint_popraw(request: Request) -> Response:
        """Preview corrections without re-running the model.
                JSON: `zadanie` (x-niewidka-zadanie), `ukryj`, `nie_dane` (markers), `zostaw`
                (doubtful places from the block accepted as non-data). Always the full lists:
                undoing a correction means recomputing without it."""
        tresc = await _obiekt_json(request)
        if not isinstance(tresc.get("zadanie"), str):
            raise HTTPException(status_code=422, detail="brak identyfikatora zadania")
        lista_ukryj = sprawdz_liste("ukryj", tresc.get("ukryj"))
        lista_nie_dane = sprawdz_liste("nie_dane", tresc.get("nie_dane"))
        lista_zostaw = sprawdz_liste("zostaw", tresc.get("zostaw"))
        lista_na_inne = sprawdz_liste("na_inne", tresc.get("na_inne"))
        lista_odkryj = sprawdz_liste("odkryj", tresc.get("odkryj"))
        zadanie = tresc["zadanie"]
        detekcje = app.state.poprawki.pobierz(zadanie)
        if detekcje is None:
            raise BrakZadaniaPoprawek()

        def praca():
            klucz = pobierz_klucz(konfig)
            wynik, mapa, raport, wlasne, z_listy = _popraw_z_listami(
                detekcje, lista_ukryj, lista_nie_dane, lista_zostaw, lista_na_inne, lista_odkryj
            )
            return wynik, mapa, raport, zaszyfruj(mapa, klucz), wlasne, z_listy

        wynik, mapa, raport, mapa_paczka, wlasne, z_listy = await app.state.kolejka.wykonaj(praca)
        odpowiedz = _wydaj_wynik(
            wynik, mapa, raport, mapa_paczka, f"tekst.{detekcje.format}", detekcje.format, zadanie, wlasne,
            z_listy, _nowe_na_bazowe(detekcje, mapa, lista_na_inne, {**wlasne, **z_listy}),
            pewne=pewne_znaczniki(detekcje),
        )
        try:  # only entry counts, no content (audit journal)
            app.state.magazyn.odnotuj(
                "poprawiono",
                mapa.identyfikator,
                mapa.poziom,
                {
                    "ukryj": len(lista_ukryj),
                    "nie_dane": len(lista_nie_dane),
                    "zostaw": len(lista_zostaw),
                    "na_inne": len(lista_na_inne),
                    "odkryj": len(lista_odkryj),
                },
            )
        except ValueError:
            pass
        return odpowiedz

    def _opis_mapy(wpis: dict) -> dict:
        return {
            "id": wpis["identyfikator"],
            "utworzono": wpis["utworzono"],
            "wygasa": wpis["wygasa"],
            "poziom": wpis["poziom"],
            "statystyki": wpis["statystyki"],
        }

    def _metadane_listy() -> list[dict]:
        return [_opis_mapy(wpis) for wpis in app.state.magazyn.lista()]

    def _zapisana_mapa(identyfikator: str, klucz: bytes) -> Mapa:
        try:
            paczka = app.state.magazyn.wczytaj(identyfikator)
        except ValueError as blad:  # id outside the pattern (including traversal): 422, not 500
            raise WybierzMape(f"Zły identyfikator mapy: {blad}", []) from None
        if paczka is None:
            raise BrakMapyWMagazynie(
                "Nie ma już zapisanej mapy tego zadania (usunięta albo po okresie "
                "przechowywania). Jeśli masz plik mapy (.nwidka), przywróć nim."
            )
        return odszyfruj(paczka, klucz)

    def _mapa_z_magazynu(dane: bytes, format: str, wskazanie: str | None, klucz: bytes) -> Mapa:
        """Map choice without a .nwidka file. The note in the text names the exact map and wins
                over the `identyfikator` field. Without the note the user names the job, and its
                version holding the most markers of the text is used (the text may have been
                copied before a later correction). Without both nothing is restored: markers are
                numbered from 1 in every document, so a reply may come from a document whose map
                is not stored. The jobs sharing markers with the text are only suggested
                (`wybierz_mape`, the best match first)."""
        limit = konfig.max_rozpakowane_mb * _MB
        id_z_dopisku = identyfikator_z_dopisku(dane, format, max_rozpakowane_bajtow=limit)
        if id_z_dopisku is not None:
            return _zapisana_mapa(id_z_dopisku, klucz)
        adapter = adapter_formatu(format)
        dok = adapter.wczytaj(dane, max_rozpakowane=limit)
        tresc = "\n".join(s.tekst for s in dok.segmenty)
        pary = {
            (oznaczenie, wariant or WARIANT_DOMYSLNY)
            for _, _, oznaczenie, wariant in znajdz_znaczniki(tresc)
        }

        def wspolne(mapa_ob: Mapa) -> int:  # (marker, variant) pairs of the text the map restores
            return len(pary & _wartosci(mapa_ob).keys())

        if wskazanie is not None:
            wybrana = _zapisana_mapa(wskazanie, klucz)
            inne = []
            for wersja in app.state.magazyn.wersje(wskazanie):
                if wersja == wskazanie:
                    continue
                try:
                    inne.append(_zapisana_mapa(wersja, klucz))
                except (BladMapy, BrakMapyWMagazynie):
                    continue  # another version unreadable or gone: the chosen one still restores
            wersje = [wybrana, *inne]  # the chosen one first, then the newest
            najwiecej = max(map(wspolne, wersje))
            najlepsze = [m for m in wersje if wspolne(m) == najwiecej]
            if _rozne_dane(najlepsze, pary):
                raise WybierzMape(
                    "W kolejnych wersjach tego zadania te same znaczniki oznaczają różne dane, a "
                    "odpowiedź nie ma dopisku z identyfikatorem mapy. Przywróć ją plikiem mapy "
                    "(.nwidka) z wersji wysłanej do czatu albo wklej odpowiedź razem z linią "
                    "„ZANONIMIZOWANY…”.",
                    [],
                )
            return najlepsze[0]
        if not pary:
            raise WybierzMape("W tekście nie ma znaczników Niewidki, więc nie ma czego przywrócić.", [])
        kandydaci = []
        for wpis in app.state.magazyn.lista():  # newest first
            try:
                ile = max(
                    wspolne(_zapisana_mapa(wersja, klucz))
                    for wersja in app.state.magazyn.wersje(wpis["identyfikator"])
                )
            except (BladMapy, BrakMapyWMagazynie, ValueError):
                continue  # an unreadable or vanished map is not a candidate
            if ile:
                kandydaci.append((ile, wpis))
        if kandydaci:
            # only the best matches (a marker the chat made up does not rule a map out),
            # newest first; metadata only, never map content
            najwiecej = max(ile for ile, _ in kandydaci)
            raise WybierzMape(
                "Odpowiedź nie ma dopisku z identyfikatorem mapy, więc nie wiem na pewno, z którego "
                "zadania pochodzi. Wybierz je z listy i kliknij „Przywróć dane”.",
                [_opis_mapy(wpis) for ile, wpis in kandydaci if ile == najwiecej],
            )
        raise WybierzMape(
            "Żadna zapisana mapa nie pasuje do znaczników z tej odpowiedzi. Jeśli masz plik mapy "
            "(.nwidka), zaznacz „Mam plik mapy (.nwidka)” i wskaż go.",
            [],
        )

    @app.post("/api/przywroc")
    async def endpoint_przywroc(
        request: Request,
        wynik: UploadFile | None = File(None),  # noqa: B008 - FastAPI pattern
        tekst: str | None = Form(None),
        mapa: UploadFile | None = File(None),  # noqa: B008
        identyfikator: str | None = Form(None),
    ) -> Response:
        """Restore: a result file OR pasted text; the map from a file, a note
                in the text or from the store by id."""
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
        _posprzataj()  # clean up expired entries before anything is restored

        def praca():
            klucz = pobierz_klucz(konfig)
            if dane_mapy is not None:
                # first the registry of issued ciphertexts, only then
                # decryption: an old map with a guessed id does not pass
                if hashlib.sha256(dane_mapy).hexdigest() not in app.state.szyfrogramy:
                    raise BladMapy("mapa nie została wydana przez ten program")
                mapa_ob = odszyfruj(dane_mapy, klucz)
                del klucz
                if mapa_ob.identyfikator not in app.state.identyfikatory:
                    raise BladMapy("niezgodny identyfikator mapy — mapa z innego zadania albo sesji")
            else:
                mapa_ob = _mapa_z_magazynu(dane_wyniku, format, identyfikator, klucz)
                del klucz
            przywrocony, rozbieznosci = przywroc(
                dane_wyniku, format, mapa_ob, max_rozpakowane_bajtow=konfig.max_rozpakowane_mb * _MB
            )
            try:
                app.state.magazyn.odnotuj("przywrocono", mapa_ob.identyfikator, mapa_ob.poziom)
            except ValueError:  # foreign id: audit without junk in the journal
                pass
            # the job as the list shows it (its newest version), also when an older one was used
            wersje = app.state.magazyn.wersje(mapa_ob.identyfikator)
            return przywrocony, rozbieznosci, mapa_ob.identyfikator, (wersje or [None])[0]

        plik_przywrocony, rozbieznosci, identyfikator_mapy, mapa_z_listy = (
            await app.state.kolejka.wykonaj(praca)
        )
        naglowki = {
            "x-niewidka-rozbieznosci": _json_naglowek(
                [{"typ": r.typ, "opis": r.opis} for r in rozbieznosci]
            ),
            "x-niewidka-identyfikator": identyfikator_mapy,
        }
        if mapa_z_listy is not None:
            naglowki["x-niewidka-mapa-z-listy"] = mapa_z_listy
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
        """Saved maps, newest first (the "Zadanie" pick list and Settings); the id is
                the full identifier - not personal data."""
        with app.state.magazyn.blokada:  # read consistent with concurrent deletion/cleanup
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
                # the list shows a corrected job once: "Usuń" removes all its versions
                usunieto = [
                    wersja
                    for wersja in app.state.magazyn.wersje(identyfikator)
                    if app.state.magazyn.usun(wersja)
                ]
                _skresl_z_rejestru(usunieto)
        except ValueError as blad:  # bad id: 422, not 500 (path traversal)
            raise HTTPException(status_code=422, detail=str(blad)) from None
        if not usunieto:
            raise HTTPException(status_code=404, detail="nie ma takiej mapy w magazynie")
        return JSONResponse({"stan": "usunieto"})

    @app.delete("/api/mapy")
    async def endpoint_usun_wszystkie_mapy() -> JSONResponse:
        with app.state.magazyn.blokada:
            usuniete = app.state.magazyn.posprzataj()
            for wpis in app.state.magazyn.lista(wszystkie=True):
                if app.state.magazyn.usun(wpis["identyfikator"]):
                    usuniete.append(wpis["identyfikator"])
            _skresl_z_rejestru(usuniete)
        return JSONResponse({"usunieto": len(usuniete)})

    def _listy_odpowiedz() -> dict:
        listy = app.state.listy
        uzytkownik = listy.uzytkownika()
        return {
            "zawsze": uzytkownik.zawsze,
            "nigdy": uzytkownik.nigdy,
            "administrator": {"zawsze": listy.admin.zawsze, "nigdy": listy.admin.nigdy},
            "tylko_administrator": listy.tylko_administrator,
            "zawsze_razem": listy.razem().zawsze,  # indexes from the x-niewidka-z-listy header
        }

    @app.get("/api/listy")
    async def endpoint_listy() -> dict:
        """Constant lists: the user's (editable) and the administrator's (read-only)."""
        return _listy_odpowiedz()

    @app.put("/api/listy")
    async def endpoint_zapisz_listy(request: Request) -> dict:
        tresc = await _obiekt_json(request)
        try:
            listy = app.state.listy.zapisz(tresc.get("zawsze"), tresc.get("nigdy"))
        except PermissionError:
            raise HTTPException(status_code=403, detail="listy ustawia administrator") from None
        logger.info("listy stałe zapisane: zawsze %d, nigdy %d", len(listy.zawsze), len(listy.nigdy))
        return _listy_odpowiedz()

    @app.get("/api/stan")
    async def endpoint_stan() -> dict:
        serwer = await _stan_serwera_inferencji()
        czesci = getattr(app.state.detektor, "czesci", None) if app.state.detektor else None
        modele = [c.nazwa for c in czesci] if czesci else (
            [app.state.detektor.nazwa] if app.state.detektor else []
        )
        return {
            "wersja": __version__,
            "modele": modele,
            "poziom": konfig.poziom,
            "poziomy": list(_POZIOMY),  # available slider levels
            # with packages; with an inference server the server reports the levels
            "poziomy_dostepne": await _poziomy_dostepne(serwer),
            "inferencja": serwer,  # None = local models
            "r95": r95_poziomy(),  # R95 per level: the UI shows it for the selected one
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
        """Local web: index.html with the session token in meta - never in a URL or resources.

                The route is registered before mounting StaticFiles, so it wins over the index.html file.
                The middleware already adds no-store - the token does not reach the browser cache.
                """
        tresc = (_KATALOG_WEB / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(tresc.replace("__NIEWIDKA_TOKEN__", app.state.token))

    app.mount("/", StaticFiles(directory=_KATALOG_WEB), name="web")

    return app


def main(argv: list[str] | None = None) -> int:
    """Server: python -m niewidka.api (uvicorn, host/port from configuration)."""
    import uvicorn

    konfig = wczytaj_konfig()
    uvicorn.run(create_app(konfig), host=konfig.host, port=konfig.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
