"""Model packages: weights downloaded AFTER installation (catalog `niewidka/dane/pakiety.json`),
streamed with resume and verified against SHA-256 before use. IT mirror source:
NIEWIDKA_MODELE_ZRODLO or `instaluj_z_katalogu`. Only model files, the tokenizer
and JSON are fetched; nothing downloaded is ever executed.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import stat
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

KATALOG_PAKIETOW = Path(__file__).resolve().parent / "dane" / "pakiety.json"
ZRODLO_DOMYSLNE = "https://github.com/AuCourDe/niewidka/releases/latest/download"
CZESCIOWY = ".częściowy"


class BladPakietu(Exception):
    """Download or package verification failure (fail-closed): a file does not reach
    the weights directory until its SHA-256 is correct."""


@dataclass(frozen=True)
class PlikPakietu:
    nazwa: str  # path relative to the weights directory (e.g. "lfm25/q4-bl32/model.onnx")
    zrodlo: str  # file name at the source (release asset / IT mirror)
    rozmiar: int
    sha256: str


@dataclass(frozen=True)
class Pakiet:
    id: str
    nazwa: str
    opis: str
    wymagany: bool
    poziomy: list[int]
    katalog_rel: str  # subdirectory holding manifest.json ("" = weights root)
    pliki: list[PlikPakietu]
    wymaga: str | None = None  # package required for this package to work
    wersja: int = 1
    min_wersja: int = 1
    # model origin and licence: shown to the user before download, informational only
    model_hf: str | None = None
    licencja: str | None = None
    licencja_url: str | None = None
    licencja_uwagi: str | None = None

    @property
    def rozmiar(self) -> int:
        return sum(p.rozmiar for p in self.pliki)


def wczytaj_wersje_katalogu(plik: Path = KATALOG_PAKIETOW) -> int:
    try:
        dane = json.loads(plik.read_text(encoding="utf-8"))
        return int(dane.get("wersja_katalogu", 1))
    except (OSError, ValueError):
        return 1


def wczytaj_pakiety(plik: Path = KATALOG_PAKIETOW) -> list[Pakiet]:
    dane = json.loads(plik.read_text(encoding="utf-8"))
    return [
        Pakiet(
            id=wpis["id"],
            nazwa=wpis["nazwa"],
            opis=wpis["opis"],
            wymagany=wpis.get("wymagany", False),
            poziomy=wpis.get("poziomy", []),
            katalog_rel=wpis.get("katalog_rel", ""),
            wymaga=wpis.get("wymaga"),
            wersja=int(wpis.get("wersja", 1)),
            min_wersja=int(wpis.get("min_wersja", 1)),
            model_hf=wpis.get("model_hf"),
            licencja=wpis.get("licencja"),
            licencja_url=wpis.get("licencja_url"),
            licencja_uwagi=wpis.get("licencja_uwagi"),
            pliki=[
                PlikPakietu(
                    nazwa=p["nazwa"], zrodlo=p["zrodlo"], rozmiar=p["rozmiar"], sha256=p["sha256"]
                )
                for p in wpis["pliki"]
            ],
        )
        for wpis in dane["pakiety"]
    ]


def katalog_danych(env: Mapping[str, str] | None = None) -> Path:
    """Program data in the user profile, not the program directory: an update
    (folder swap) does not wipe it, and Program Files may be read-only."""
    env = os.environ if env is None else env
    if sys.platform == "win32":
        baza = Path(env.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        baza = Path(env.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return baza / "Niewidka"


def katalog_modeli(env: Mapping[str, str] | None = None) -> Path:
    """Weights directory: env wins; defaults to the user data directory."""
    env = os.environ if env is None else env
    if env.get("NIEWIDKA_MODELE_KATALOG"):
        return Path(env["NIEWIDKA_MODELE_KATALOG"])
    return katalog_danych(env) / "modele"


def wczytaj_bajty_pakietu(
    identyfikator: str,
    katalog: Path,
    katalog_pakietow: Path | list[Pakiet] = KATALOG_PAKIETOW,
) -> dict[str, bytes]:
    """TRUSTED package catalog (built into the application)
    decides which package files are required and their SHA-256; the local
    manifest.json does not set expected hashes. Each file is read INTO MEMORY
    exactly once: the hash is computed from the same bytes handed to the loader
    (closes the check-then-use window). All required files are mandatory.
    """
    zaufane = wczytaj_pakiety(katalog_pakietow) if isinstance(katalog_pakietow, Path) else katalog_pakietow
    pakiet = next((p for p in zaufane if p.id == identyfikator), None)
    if pakiet is None:
        raise BladPakietu(f"nieznany pakiet {identyfikator} w zaufanym katalogu pakietów")
    wynik: dict[str, bytes] = {}
    for plik in pakiet.pliki:
        sciezka = katalog / plik.nazwa
        if sciezka.is_symlink() or not sciezka.is_file():
            raise BladPakietu(f"pakiet {identyfikator}: brak pliku {plik.nazwa}")
        bajty = sciezka.read_bytes()
        if len(bajty) != plik.rozmiar or hashlib.sha256(bajty).hexdigest() != plik.sha256:
            raise BladPakietu(f"pakiet {identyfikator}: rozbieżny SHA-256 dla {plik.nazwa}")
        wynik[plik.nazwa] = bajty
    return wynik


def zrodlo(env: dict[str, str] | None = None) -> str:
    """Download base URL: NIEWIDKA_MODELE_ZRODLO or the release assets."""
    env = os.environ if env is None else env
    return env.get("NIEWIDKA_MODELE_ZRODLO") or ZRODLO_DOMYSLNE


def limit_czasu_domyslny(env: dict[str, str] | None = None) -> int:
    """Total time limit for ONE download/install operation (the httpx read timeout covers a chunk, not the whole transfer).
    Configurable via NIEWIDKA_PAKIETY_LIMIT_CZASU_S; default 1800 s."""
    env = os.environ if env is None else env
    surowa = env.get("NIEWIDKA_PAKIETY_LIMIT_CZASU_S", "1800")
    try:
        return int(surowa)
    except ValueError:
        raise ValueError(
            f"NIEWIDKA_PAKIETY_LIMIT_CZASU_S: oczekiwano liczby, jest {surowa!r}"
        ) from None


def _sha256(plik: Path) -> str:
    skrot = hashlib.sha256()
    with plik.open("rb") as uchwyt:
        for kawalek in iter(lambda: uchwyt.read(1 << 20), b""):
            skrot.update(kawalek)
    return skrot.hexdigest()


def stan(pakiet: Pakiet, katalog: Path) -> str:
    """missing = at least one file absent; corrupted = files present, hash mismatch;
    installed = all files match the SHA-256 from the package catalog."""
    braki = 0
    uszkodzone = 0
    for plik in pakiet.pliki:
        cel = katalog / plik.nazwa
        if not cel.is_file():
            braki += 1
        elif _sha256(cel) != plik.sha256:
            uszkodzone += 1
    if uszkodzone:
        return "uszkodzony"
    return "brak" if braki else "zainstalowany"


def odczytaj_zainstalowana_wersje(pakiet: Pakiet, katalog: Path) -> int | None:
    """Installed package version from manifest.json; no file = None,
    no version field in an old manifest = 1."""
    katalog_pakietu = katalog / pakiet.katalog_rel if pakiet.katalog_rel else katalog
    manifest = katalog_pakietu / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        dane = json.loads(manifest.read_text(encoding="utf-8"))
        return int(dane.get("wersja", 1))
    except (OSError, ValueError):
        return 1


# links must not lead outside the models directory

PUBLIKOWANY = ".publikowany"


def _otworz_nowy(sciezka: Path) -> int:
    """Fresh file without following links: O_CREAT|O_EXCL, O_NOFOLLOW
    where available (POSIX); on Windows O_EXCL still defeats planted names."""
    flagi = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return os.open(sciezka, flagi, 0o600)


def _jest_dowiazaniem(sciezka: Path) -> bool:
    """Symlink (POSIX) or reparse point/junction (Windows)."""
    try:
        st = sciezka.lstat()
    except OSError:
        return False
    atrybuty = getattr(st, "st_file_attributes", 0)
    return stat.S_ISLNK(st.st_mode) or bool(
        atrybuty & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _odrzuc_dowiazania(katalog: Path, nazwa_rel: str) -> None:
    """A link in any intermediate directory of the path = write refused."""
    biezacy = katalog
    for czlon in Path(nazwa_rel).parts[:-1]:
        biezacy = biezacy / czlon
        if _jest_dowiazaniem(biezacy):
            raise BladPakietu("ścieżka modeli zawiera dowiązanie; odmowa zapisu")


def _opublikuj(
    bajty: bytes, cel: Path, suma_oczekiwana: str, katalog: Path
) -> None:
    """Publish verified bytes: the hash is taken from EXACTLY the bytes that
    are written, written to a fresh O_EXCL file and then moved with an
    atomic os.replace (rename does NOT follow a symlink at the destination,
    so a planted manifest/target is replaced, not written through).
    """
    if hashlib.sha256(bajty).hexdigest() != suma_oczekiwana:
        raise BladPakietu(f"SHA-256 niezgodny dla {cel.name}; plik nie trafił do katalogu wag")
    opublikuj_bez_hasza(bajty, cel, katalog)


def _podziel_postep(postep, rozmiary: list[int]):
    """Converts per-file progress into progress of the whole package (total bytes)."""
    if postep is None:
        return None
    calosc = sum(rozmiary)
    licznik = {"gotowe": 0}

    def wywolaj(pobrane: int, razem: int) -> None:
        postep(licznik["gotowe"] + pobrane, calosc)

    def po_pliku(rozmiar: int) -> None:
        licznik["gotowe"] += rozmiar

    return wywolaj, po_pliku


# controlled redirects

_SKOKI_MAKS = 5


def _host_prywatny(host: str) -> bool:
    """Loopback/private/link-local/reserved networks; an unrecognised host
    is treated cautiously as private."""
    try:
        adresy = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            adresy = [
                ipaddress.ip_address(pozycja[4][0]) for pozycja in socket.getaddrinfo(host, None)
            ]
        except (socket.gaierror, OSError, ValueError):
            return True
    return any(
        a.is_loopback or a.is_private or a.is_link_local or a.is_reserved or a.is_multicast
        for a in adresy
    )


def _waliduj_przekierowanie(adres: str, host_zrodla: str) -> None:
    """Every redirect hop: HTTPS, unless the target is the host of the configured
    IT mirror (NIEWIDKA_MODELE_ZRODLO may be http, loopback included);
    never private networks outside the mirror (blind SSRF)."""
    u = httpx.URL(adres)
    host = u.host or ""
    na_lustre = host == host_zrodla
    if u.scheme == "https":
        if not na_lustre and _host_prywatny(host):
            raise BladPakietu("przekierowanie do sieci prywatnej odrzucone")
        return
    if u.scheme == "http" and na_lustre:
        return
    raise BladPakietu("przekierowanie poza HTTPS (poza lustrem IT) odrzucone")


def _pobierz_plik(
    klient: httpx.Client,
    url: str,
    cel: Path,
    suma_oczekiwana: str,
    katalog: Path,
    rozmiar: int,
    host_zrodla: str,
    limit_czasu_s: int = 1800,
    przerwano=None,
    postep=None,
) -> None:
    """Stream one file with resume; publish the verified bytes (_opublikuj).
    The partial file is opened without following links.
    Hard byte limit = size from the catalog (also with Range);
    total time limit and cancellation are checked on EVERY chunk.
    Redirects are followed MANUALLY with validation of each
    hop (_waliduj_przekierowanie) - follow_redirects=False."""
    czesciowy = cel.with_name(cel.name + CZESCIOWY)
    if _jest_dowiazaniem(czesciowy):
        czesciowy.unlink()  # a planted link is not our partial file
    naglowki = {}
    start = czesciowy.stat().st_size if czesciowy.is_file() else 0
    if start > rozmiar:
        raise BladPakietu(f"plik częściowy większy niż rozmiar z katalogu: {cel.name}")
    if start:
        naglowki["range"] = f"bytes={start}-"
    cel.parent.mkdir(parents=True, exist_ok=True)
    for skok in range(_SKOKI_MAKS):
        with klient.stream("GET", url, headers=naglowki, follow_redirects=False) as odpowiedz:
            if odpowiedz.status_code in (301, 302, 303, 307, 308):
                lokalizacja = odpowiedz.headers.get("location")
                if not lokalizacja:
                    raise BladPakietu("przekierowanie bez lokalizacji")
                nastepny = str(httpx.URL(url).join(lokalizacja))
                _waliduj_przekierowanie(nastepny, host_zrodla)
                url = nastepny
                continue
            odpowiedz.raise_for_status()
            if odpowiedz.status_code != 206:
                start = 0  # server without Range support: start over
                czesciowy.unlink(missing_ok=True)
            try:
                z = int(odpowiedz.headers.get("content-length", "0"))
            except ValueError:
                z = 0
            razem = start + z
            # an interrupted download leaves a partial file: the next one resumes it;
            # O_APPEND|O_NOFOLLOW: never write through a planted symlink
            try:
                fd = (
                    os.open(
                        czesciowy,
                        os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
                    )
                    if start
                    else _otworz_nowy(czesciowy)
                )
            except OSError as blad:
                raise BladPakietu(f"plik częściowy nieosiągalny: {cel.name}") from blad
            with os.fdopen(fd, "ab" if start else "wb") as uchwyt:
                gotowe = start
                start_czasu = time.monotonic()
                for kawalek in odpowiedz.iter_bytes():
                    if przerwano is not None and przerwano():
                        raise BladPakietu("pobieranie przerwane")
                    if time.monotonic() - start_czasu > limit_czasu_s:
                        raise BladPakietu(
                            "pobieranie przekroczyło całkowity limit czasu; kolejna próba wznowi"
                        )
                    if gotowe + len(kawalek) > rozmiar:
                        raise BladPakietu(
                            f"serwer wysłał więcej bajtów niż rozmiar z katalogu pakietów: {cel.name}"
                        )
                    uchwyt.write(kawalek)
                    gotowe += len(kawalek)
                    if postep is not None:
                        postep(gotowe, razem)
            break  # content downloaded; further hops only follow redirects
    else:
        raise BladPakietu("za dużo przekierowań")
    try:
        _opublikuj(czesciowy.read_bytes(), cel, suma_oczekiwana, katalog)
    except BladPakietu:
        # hash mismatch = poisoned partial file: resuming from it would not help
        czesciowy.unlink(missing_ok=True)
        raise
    else:
        czesciowy.unlink(missing_ok=True)


def _zapisz_manifest(pakiet: Pakiet, katalog: Path) -> None:
    """Informational manifest; atomic write: fresh O_EXCL + os.replace,
    so a planted manifest.json symlink is REPLACED, not written through."""
    katalog_pakietu = katalog / pakiet.katalog_rel if pakiet.katalog_rel else katalog
    manifest = {
        "pakiet": pakiet.id,
        "wersja": pakiet.wersja,
        "pliki": {Path(p.nazwa).name: p.sha256 for p in pakiet.pliki},
    }
    tresc = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    opublikuj_bez_hasza(tresc, katalog_pakietu / "manifest.json", katalog)


def opublikuj_bez_hasza(bajty: bytes, cel: Path, katalog: Path) -> None:
    """Atomic file publication: fresh
    O_EXCL + os.replace, permissions 0600, a symlink at the destination is
    REPLACED, not written through."""
    _odrzuc_dowiazania(katalog, str(cel.relative_to(katalog)))
    cel.parent.mkdir(parents=True, exist_ok=True)
    tymczasowy = cel.with_name(cel.name + PUBLIKOWANY)
    try:
        with os.fdopen(_otworz_nowy(tymczasowy), "wb") as uchwyt:
            uchwyt.write(bajty)
        os.replace(tymczasowy, cel)
    except BaseException:
        tymczasowy.unlink(missing_ok=True)
        raise


def pobierz(
    pakiet: Pakiet,
    katalog: Path,
    zrodlo_bazowe: str,
    klient: httpx.Client | None = None,
    postep=None,
    limit_czasu_s: int | None = None,
    przerwano=None,
) -> None:
    """Downloads all package files; skips those already matching their SHA-256."""
    wlasny = klient is None
    # redirects are followed manually (each hop validated)
    klient = klient or httpx.Client(follow_redirects=False, timeout=600)
    host_zrodla = httpx.URL(zrodlo_bazowe).host or ""
    limit = limit_czasu_s if limit_czasu_s is not None else limit_czasu_domyslny()
    try:
        para = _podziel_postep(postep, [p.rozmiar for p in pakiet.pliki])
        postep_pliku, po_pliku = para if para else (None, None)
        for plik in pakiet.pliki:
            if przerwano is not None and przerwano():
                raise BladPakietu("pobieranie przerwane")
            cel = katalog / plik.nazwa
            if cel.is_file() and not cel.is_symlink() and _sha256(cel) == plik.sha256:
                if po_pliku is not None:
                    po_pliku(plik.rozmiar)
                continue
            _pobierz_plik(
                klient,
                f"{zrodlo_bazowe.rstrip('/')}/{plik.zrodlo}",
                cel,
                plik.sha256,
                katalog,
                rozmiar=plik.rozmiar,
                host_zrodla=host_zrodla,
                limit_czasu_s=limit,
                przerwano=przerwano,
                postep=postep_pliku,
            )
            if po_pliku is not None:
                po_pliku(cel.stat().st_size)
        _zapisz_manifest(pakiet, katalog)
    finally:
        if wlasny:
            klient.close()


def usun(pakiet: Pakiet, katalog: Path) -> None:
    """Removes the package files and manifest; cleans empty directories up to the root."""
    for plik in pakiet.pliki:
        (katalog / plik.nazwa).unlink(missing_ok=True)
    katalog_pakietu = katalog / pakiet.katalog_rel if pakiet.katalog_rel else katalog
    manifest = katalog_pakietu / "manifest.json"
    if manifest.is_file():
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("pakiet") == pakiet.id:
                manifest.unlink()
        except (OSError, ValueError):
            pass
    biezacy = katalog_pakietu
    while biezacy != katalog and biezacy != biezacy.parent:
        try:
            biezacy.rmdir()
        except OSError:
            break
        biezacy = biezacy.parent


def instaluj_z_katalogu(
    pakiet: Pakiet,
    katalog: Path,
    zrodlo_katalog: Path,
    postep=None,
    limit_czasu_s: int | None = None,
    przerwano=None,
) -> None:
    """Offline install (IT): a directory with files named as at the source;
    SHA-256 verified before writing, atomic like a download (the same bytes are hashed and published, links are not followed).
    Byte limit = size from the weights catalog (a larger mirror file is
    refused BEFORE copying); time limit and cancellation as for downloads.
    This is the IT mirror path (versions pinned in the built-in catalog);
    updates with a folder and signature go through aktualizacje.MenedzerAktualizacji."""
    limit = limit_czasu_s if limit_czasu_s is not None else limit_czasu_domyslny()
    start_czasu = time.monotonic()

    for plik in pakiet.pliki:
        if przerwano is not None and przerwano():
            raise BladPakietu("instalacja przerwana")
        if time.monotonic() - start_czasu > limit:
            raise BladPakietu("instalacja przekroczyła całkowity limit czasu")
        wzor = zrodlo_katalog / plik.zrodlo
        if wzor.is_symlink() or not wzor.is_file():
            raise BladPakietu(f"brak pliku {plik.zrodlo} w katalogu źródłowym")
        if wzor.stat().st_size != plik.rozmiar:
            raise BladPakietu(
                f"plik w katalogu źródłowym ma inny rozmiar niż katalog pakietów: {plik.zrodlo}"
            )
        bajty = wzor.read_bytes()
        if len(bajty) != plik.rozmiar:
            raise BladPakietu(f"plik źródłowy zmienił rozmiar w trakcie odczytu: {plik.zrodlo}")
        _opublikuj(bajty, katalog / plik.nazwa, plik.sha256, katalog)
        if postep is not None:
            postep(plik.rozmiar, pakiet.rozmiar)
    _zapisz_manifest(pakiet, katalog)


@dataclass
class PostepPobierania:
    """State of the current operation (download or install) for the API and UI."""

    pakiet: str | None = None  # id of the package in progress; None = idle
    pobrane: int = 0
    razem: int = 0
    blad: str | None = None


class MenedzerPakietow:
    """Package state + one download at a time in a background thread.

    Core operations (`pobierz`, `usun`, `instaluj_z_katalogu`) are called from a thread;
    progress is published in `PostepPobierania` for GET /api/pakiety. `poziomy_dostepne`
    guards the required package: without it no slider level works.
    Package state is CACHED - SHA verification runs
    at startup and after every change, in a background thread; GET returns the cache
    (a fingerprint of file presence, stat without hashing, detects weights added externally).
    """

    @property
    def katalog(self) -> Path:
        return self._katalog

    def __init__(
        self,
        lista: list[Pakiet],
        katalog: Path,
        zrodlo_bazowe: str,
        klient: httpx.Client | None = None,
        on_zmiana: callable | None = None,  # type: ignore[valid-type] # invalidates the detector cache
    ):
        self._pakiety = {p.id: p for p in lista}
        self._katalog = Path(katalog)
        self._zrodlo = zrodlo_bazowe
        self._klient = klient
        self._zajete = threading.Lock()
        self._w_toku = False
        self._przerwano = threading.Event()
        self.postep = PostepPobierania()
        self._on_zmiana = on_zmiana
        self._stan_cache: list[dict] = []
        self._poziomy_cache: list[int] = []
        self._brakujacy_cache: list[str] = []
        self._odcisk = ""
        self._odswiezanie = threading.Lock()
        self._odswiezanie_w_toku = False
        self.odswiez_w_tle()  # verify once at startup, in the background

    def _obecne(self) -> str:
        """File-presence fingerprint (stat, no SHA) used to detect external changes."""
        return repr(
            [
                (plik.nazwa, (self._katalog / plik.nazwa).is_file())
                for p in self._pakiety.values()
                for plik in p.pliki
            ]
        )

    def _przelicz(self) -> None:
        """Full verification (SHA of all files) into the cache; background/operation thread."""
        with self._odswiezanie:
            self._stan_cache = [
                {
                    "id": p.id,
                    "nazwa": p.nazwa,
                    "opis": p.opis,
                    "wymagany": p.wymagany,
                    "poziomy": p.poziomy,
                    "wymaga": p.wymaga,
                    "rozmiar_bajtow": p.rozmiar,
                    "model_hf": p.model_hf,
                    "licencja": p.licencja,
                    "licencja_url": p.licencja_url,
                    "licencja_uwagi": p.licencja_uwagi,
                    "stan": stan(p, self._katalog),
                }
                for p in self._pakiety.values()
            ]
            self._poziomy_cache = next(
                (w["poziomy"] for w in self._stan_cache if w["wymagany"] and w["stan"] == "zainstalowany"),
                [],
            )
            self._brakujacy_cache = [
                w["id"] for w in self._stan_cache if w["wymagany"] and w["stan"] != "zainstalowany"
            ]
            self._odcisk = self._obecne()

    def odswiez(self) -> None:
        """Synchronous cache recompute (operation thread, after the operation ends)."""
        self._przelicz()

    def odswiez_w_tle(self) -> None:
        """Cache recompute in a background thread (startup, change on disk)."""
        if self._odswiezanie_w_toku:
            return
        self._odswiezanie_w_toku = True

        def praca():
            try:
                stary_odcisk = self._odcisk
                self._przelicz()
                # change made externally (not startup): detectors built
                # earlier from the old state must be discarded
                if stary_odcisk and self._odcisk != stary_odcisk:
                    self._zglos_zmiane()
            finally:
                self._odswiezanie_w_toku = False

        threading.Thread(target=praca, name="niewidka-pakiety-stan", daemon=True).start()

    def podmien_pakiety(self, lista: list[Pakiet]) -> None:
        """An accepted (signed) update catalog replaces the built-in one;
        from now on state and SHA-256 guard the new versions. Refresh runs in the background."""
        self._pakiety = {p.id: p for p in lista}
        self.odswiez_w_tle()

    def ustaw_zwrot_zmiany(self, on_zmiana: callable) -> None:  # type: ignore[valid-type]
        """callback invoked after every finished operation (the API hooks
        detector cache clearing here so the new package state is visible)."""
        self._on_zmiana = on_zmiana

    def _zglos_zmiane(self) -> None:
        if self._on_zmiana is not None:
            self._on_zmiana()

    def stan_pakietu(self, identyfikator: str) -> str | None:
        """Package state from the cache; None = package not in the catalog."""
        wpis = next((w for w in self.lista() if w["id"] == identyfikator), None)
        return wpis["stan"] if wpis else None

    def lista(self) -> list[dict]:
        """Cached state; a change in file presence triggers a background
        refresh, never hashing on request."""
        if self._obecne() != self._odcisk:
            self.odswiez_w_tle()
        if not self._stan_cache:  # the first recompute is still running
            return [
                {
                    "id": p.id,
                    "nazwa": p.nazwa,
                    "opis": p.opis,
                    "wymagany": p.wymagany,
                    "poziomy": p.poziomy,
                    "wymaga": p.wymaga,
                    "rozmiar_bajtow": p.rozmiar,
                    "model_hf": p.model_hf,
                    "licencja": p.licencja,
                    "licencja_url": p.licencja_url,
                    "licencja_uwagi": p.licencja_uwagi,
                    "stan": "brak"
                    if all(
                        not (self._katalog / plik.nazwa).is_file() for plik in p.pliki
                    )
                    else "sprawdzanie",
                }
                for p in self._pakiety.values()
            ]
        return [dict(w) for w in self._stan_cache]

    def poziomy_dostepne(self) -> list[int]:
        """From the cache; empty until the first recompute finishes (cautious)."""
        return list(self._poziomy_cache)

    def brakujacy_wymagany(self) -> list[str]:
        if self._stan_cache:
            return list(self._brakujacy_cache)
        # first recompute in progress: at least one missing file (stat) is certainly
        # a missing package - cautious, because 409 leads to Settings
        return [
            p.id
            for p in self._pakiety.values()
            if p.wymagany
            and any(not (self._katalog / plik.nazwa).is_file() for plik in p.pliki)
        ]

    def zakonczone(self) -> bool:
        return not self._w_toku

    def pobierz(self, identyfikator: str) -> bool:
        """Starts a download in a background thread; False when another one is running
        or the package is unknown."""
        pakiet = self._pakiety.get(identyfikator)
        if pakiet is None:
            return False
        return self._uruchom_w_tle(
            pakiet,
            lambda: pobierz(
                pakiet,
                self._katalog,
                self._zrodlo,
                klient=self._klient,
                postep=self._przyjmij_postep,
                przerwano=self._przerwano.is_set,
            ),
            "pobieranie",
        )

    def anuluj(self) -> None:
        """asks the current operation to stop (checked on every chunk);
        the effects show in postep.blad after it ends."""
        self._przerwano.set()

    def instaluj(self, identyfikator: str, katalog_zrodlowy: Path) -> bool:
        """Offline install in the background (a local copy used to block
        the API loop); False when another operation is running. Byte/time limits as for
        downloads; errors end up in postep.blad."""
        pakiet = self._pakiety[identyfikator]
        return self._uruchom_w_tle(
            pakiet,
            lambda: instaluj_z_katalogu(
                pakiet,
                self._katalog,
                katalog_zrodlowy,
                postep=self._przyjmij_postep,
                przerwano=self._przerwano.is_set,
            ),
            "instalacja",
        )

    def _uruchom_w_tle(self, pakiet: Pakiet, operacja, etykieta: str) -> bool:
        with self._zajete:
            if self._w_toku:
                return False
            self._w_toku = True
        self.postep = PostepPobierania(pakiet=pakiet.id, razem=pakiet.rozmiar)
        self._przerwano.clear()

        def praca():
            try:
                operacja()
            except BladPakietu as blad:
                self.postep.blad = str(blad)
            except httpx.HTTPStatusError as blad:
                # controlled message - no URL (may contain the mirror's
                # login:password) and no exception text; only the HTTP code
                self.postep.blad = (
                    f"{pakiet.id}: {etykieta} nie powiodło się (HTTP {blad.response.status_code})"
                )
            except (httpx.HTTPError, OSError):
                self.postep.blad = f"{pakiet.id}: {etykieta} nie powiodła się (błąd sieci)"
            finally:
                # fresh state BEFORE the _w_toku flag disappears - czekaj()
                # and the UI polling must see the state after the operation, not before the refresh.
                # The end (pakiet=None) is announced LAST: the UI then
                # immediately starts the next package
                self.odswiez()
                self._zglos_zmiane()
                self._w_toku = False
                self.postep.pakiet = None

        threading.Thread(target=praca, name="niewidka-pakiety", daemon=True).start()
        return True

    def usun(self, identyfikator: str) -> None:
        usun(self._pakiety[identyfikator], self._katalog)
        self.odswiez()
        self._zglos_zmiane()

    def _przyjmij_postep(self, pobrane: int, razem: int) -> None:
        self.postep.pobrane = pobrane
        self.postep.razem = razem

    def czekaj(self, limit_s: float = 60) -> None:
        """Tests only: waits for the operation to end and the state to refresh."""
        koniec = time.monotonic() + limit_s
        while (self._w_toku or self._odswiezanie_w_toku) and time.monotonic() < koniec:
            time.sleep(0.01)
