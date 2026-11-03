"""Map store with retention: the encrypted map of each hiding in the data directory (`<id>.nwidka`
+ metadata `<id>.json` without personal data), deletion after the retention deadline and an event
journal (`dziennik.jsonl`, never content or file names).

The clock is injected; writes are atomic. The API holds `MagazynMap.blokada` around changes to the registry of
issued maps so they do not collide with cleanup."""

from __future__ import annotations

import getpass
import hashlib
import json
import re
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from niewidka import __version__
from niewidka.mapa import BladMapy, Mapa, naglowek
from niewidka.pakiety import opublikuj_bez_hasza

# the core issues ids with secrets.token_hex(16); a strict pattern closes path
# traversal (every `../`, separator and backslash is rejected before the id touches a path)
_WZORZEC_ID = re.compile(r"[a-f0-9]{32}")

DOMYSLNY_ZEGAR: Callable[[], datetime] = lambda: datetime.now().astimezone()


def kontekst_domyslny() -> dict:
    """Audit environment fields: system user and program version."""
    return {"uzytkownik": getpass.getuser(), "wersja": __version__}


def wersje_pakietow(katalog_wag: Path | str | None) -> dict[str, str] | None:
    """Model package versions from the manifests in the weights directory; None when the manifests
        do not give them (older directories) or the directory does not exist."""
    if not katalog_wag:
        return None
    katalog = Path(katalog_wag)
    if not katalog.is_dir():
        return None
    wynik: dict[str, str] = {}
    for manifest in sorted(katalog.glob("*/manifest.json")) + [katalog / "manifest.json"]:
        try:
            dane = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if "wersja" in dane:
            wynik[str(dane.get("pakiet") or manifest.parent.name)] = str(dane["wersja"])
    return wynik or None


def _skrot_poprzedniej_linii(sciezka: Path) -> str:
    """SHA-256 of the last non-empty journal line; an empty string when the file does not exist
        (the first entry of the chain)."""
    if not sciezka.is_file():
        return ""
    linie = [l for l in sciezka.read_text(encoding="utf-8").splitlines() if l.strip()]
    return hashlib.sha256(linie[-1].encode("utf-8")).hexdigest() if linie else ""


def zweryfikuj_lancuch(sciezka: Path) -> tuple[bool, list[str]]:
    """Journal chain verification: each entry points to the SHA-256 hash of
        the previous line, so editing the content or deleting a row breaks the
        next one. Returns (consistent, problems) with line numbers - without entry content."""
    problemy: list[str] = []
    if not Path(sciezka).is_file():
        return True, problemy
    poprzednia = ""
    for numer, linia in enumerate(Path(sciezka).read_text(encoding="utf-8").splitlines(), start=1):
        if not linia.strip():
            continue
        try:
            zgloszony = str(json.loads(linia).get("poprzedni"))
        except ValueError:
            problemy.append(f"linia {numer}: nie jest poprawnym JSON")
            poprzednia = linia
            continue
        oczekiwany = hashlib.sha256(poprzednia.encode("utf-8")).hexdigest() if poprzednia else ""
        if zgloszony != oczekiwany:
            problemy.append(f"linia {numer}: zerwany łańcuch skrótów")
        poprzednia = linia
    return not problemy, problemy


def sprawdz_id(identyfikator: str) -> str:
    """An identifier allowed in a path; otherwise ValueError."""
    if not _WZORZEC_ID.fullmatch(identyfikator or ""):
        raise ValueError("zły identyfikator mapy")
    return identyfikator


class MagazynMap:
    """Collection of maps in the data directory + event journal; retention in days."""

    def __init__(
        self,
        katalog: Path,
        retencja_dni: int = 30,
        zegar: Callable[[], datetime] | None = None,
        kontekst: Callable[[], dict] | None = None,
    ):
        self.katalog = Path(katalog)
        self.retencja_dni = int(retencja_dni)
        self.zegar = zegar or DOMYSLNY_ZEGAR
        # audit environment fields (user, program version, package versions);
        # the API passes the version with the weight manifests, by default only the user and program
        self.kontekst = kontekst or kontekst_domyslny
        # RLock: the API holds the lock around a sequence of methods (cleanup + write +
        # registry), and the store methods also lock individually - the same thread gets in
        self.blokada = threading.RLock()

    # --- write and read ---------------------------------------------------------

    def zapisz(
        self, szyfrogram: bytes, mapa: Mapa, statystyki: dict[str, int], zadanie: str | None = None
    ) -> datetime | None:
        """Ciphertext + metadata into the store; returns the expiry date or None
                (retention 0 = no automatic write). Non-maps say "nie mapa".
                `zadanie`: the job a preview correction belongs to; every correction issues a
                new map, and all of them stay (a text copied before a correction must restore)
                as numbered versions of one job."""
        naglowek(szyfrogram)  # BladMapy before anything is created on disk
        if self.retencja_dni <= 0:
            return None
        identyfikator = sprawdz_id(mapa.identyfikator)
        teraz = self.zegar()
        wygasa = teraz + timedelta(days=self.retencja_dni)
        metadane = {
            "identyfikator": identyfikator,
            "utworzono": mapa.utworzono,
            "wygasa": wygasa.isoformat(),
            "poziom": mapa.poziom,
            "statystyki": dict(statystyki),
        }
        with self.blokada:
            if zadanie is not None:
                metadane["zadanie"] = str(zadanie)
                metadane["wersja"] = 1 + max(
                    (w["wersja"] for w in self.lista(wszystkie=True) if w.get("zadanie") == zadanie),
                    default=0,
                )
            self.katalog.mkdir(parents=True, exist_ok=True)
            opublikuj_bez_hasza(szyfrogram, self.katalog / f"{identyfikator}.nwidka", self.katalog)
            opublikuj_bez_hasza(
                (json.dumps(metadane, ensure_ascii=False) + "\n").encode("utf-8"),
                self.katalog / f"{identyfikator}.json",
                self.katalog,
            )
            self._dopisz("utworzono", identyfikator, mapa.poziom, statystyki, teraz)
        return wygasa

    def wczytaj(self, identyfikator: str) -> bytes | None:
        """The map ciphertext or None when it does not exist (expired, deleted, foreign)."""
        identyfikator = sprawdz_id(identyfikator)
        plik = self.katalog / f"{identyfikator}.nwidka"
        return plik.read_bytes() if plik.is_file() else None

    def lista(self, wszystkie: bool = False) -> list[dict]:
        """Map metadata, newest first; damaged entries skipped (fail-safe). A corrected job is
                listed once, by its newest version; `wszystkie` lists every stored map."""
        if not self.katalog.is_dir():
            return []
        wynik = []
        for plik in self.katalog.glob("*.json"):
            try:
                wpis = json.loads(plik.read_text(encoding="utf-8"))
                pozycja = {
                    "identyfikator": str(wpis["identyfikator"]),
                    "utworzono": str(wpis["utworzono"]),
                    "wygasa": str(wpis["wygasa"]),
                    "poziom": int(wpis["poziom"]),
                    "statystyki": {str(k): int(v) for k, v in wpis["statystyki"].items()},
                }
                if "zadanie" in wpis:
                    pozycja["zadanie"] = str(wpis["zadanie"])
                    pozycja["wersja"] = int(wpis["wersja"])
                wynik.append(pozycja)
            except (ValueError, KeyError, TypeError, OSError, AttributeError):
                continue
        if not wszystkie:
            najnowsze: dict[str, dict] = {}
            for pozycja in wynik:
                klucz = pozycja.get("zadanie") or pozycja["identyfikator"]
                if klucz not in najnowsze or pozycja.get("wersja", 0) > najnowsze[klucz].get("wersja", 0):
                    najnowsze[klucz] = pozycja
            wynik = list(najnowsze.values())
        wynik.sort(key=lambda w: (w["utworzono"], w.get("wersja", 0), w["identyfikator"]), reverse=True)
        return wynik

    def wersje(self, identyfikator: str) -> list[str]:
        """Ids of every stored version of the job this map belongs to, newest first (just the
                map itself when it has no job, nothing when it is not stored)."""
        identyfikator = sprawdz_id(identyfikator)
        wszystkie = self.lista(wszystkie=True)
        wpis = next((w for w in wszystkie if w["identyfikator"] == identyfikator), None)
        if wpis is None:
            return []
        # the job id is the id of its first map, which an older program stored without the field
        zadanie = wpis.get("zadanie") or wpis["identyfikator"]
        wersje = [w for w in wszystkie if w.get("zadanie") == zadanie or w["identyfikator"] == zadanie]
        wersje.sort(key=lambda w: w.get("wersja", 0), reverse=True)
        return [w["identyfikator"] for w in wersje]

    # --- deletion ---------------------------------------------------------------

    def usun(self, identyfikator: str) -> bool:
        """Manual deletion of one map; True when something was deleted."""
        return self._usun(identyfikator, "usunieto")

    def usun_wszystkie(self) -> int:
        ile = 0
        for wpis in self.lista(wszystkie=True):
            ile += int(self.usun(wpis["identyfikator"]))
        return ile

    def posprzataj(self) -> list[str]:
        """Deletes maps past the retention deadline (called at startup and before every
                store operation); returns the ids of the deleted ones."""
        if not self.katalog.is_dir():
            return []
        teraz = self.zegar()
        przeterminowane = []
        for wpis in self.lista(wszystkie=True):
            try:
                wygasa = datetime.fromisoformat(wpis["wygasa"])
            except ValueError:
                continue  # broken deadline: leave the decision to a human, do not delete
            if wygasa <= teraz:
                przeterminowane.append(wpis["identyfikator"])
        for identyfikator in przeterminowane:
            self._usun(identyfikator, "wygasla")
        return przeterminowane

    def _usun(self, identyfikator: str, zdarzenie: str) -> bool:
        identyfikator = sprawdz_id(identyfikator)
        szyfrogram = self.katalog / f"{identyfikator}.nwidka"
        metadane = self.katalog / f"{identyfikator}.json"
        if not szyfrogram.is_file() and not metadane.is_file():
            return False
        with self.blokada:
            szyfrogram.unlink(missing_ok=True)
            metadane.unlink(missing_ok=True)
            self._dopisz(zdarzenie, identyfikator, None, None, self.zegar())
        return True

    def odnotuj(
        self,
        zdarzenie: str,
        identyfikator: str,
        poziom: int | None = None,
        liczby: dict[str, int] | None = None,
    ) -> None:
        """An audit entry for an event outside the store (e.g. restored from a downloaded copy,
                corrected with entry counts). Numbers only, never content."""
        with self.blokada:
            self._dopisz(zdarzenie, sprawdz_id(identyfikator), poziom, liczby, self.zegar())

    # --- journal ---------------------------------------------------------------

    def _dopisz(
        self,
        zdarzenie: str,
        identyfikator: str,
        poziom: int | None,
        statystyki: dict[str, int] | None,
        teraz: datetime,
    ) -> None:
        """An audit row WITHOUT personal data: an id hash instead of the map content, plus the
                environment context and an SHA-256 hash chain (editing is detectable,"""
        wpis = {
            "czas": teraz.isoformat(timespec="seconds"),
            "zdarzenie": zdarzenie,
            "skrot_id": identyfikator[:12],
            "uzytkownik": self.kontekst().get("uzytkownik"),
            "wersja": self.kontekst().get("wersja"),
            "pakiety": self.kontekst().get("pakiety"),
            "poziom": poziom,
            "wynik": "ok",
            "statystyki": statystyki,
            "poprzedni": _skrot_poprzedniej_linii(self.katalog / "dziennik.jsonl"),
        }
        self.katalog.mkdir(parents=True, exist_ok=True)
        with (self.katalog / "dziennik.jsonl").open("a", encoding="utf-8") as dziennik:
            dziennik.write(json.dumps(wpis, ensure_ascii=False) + "\n")


__all__ = ["BladMapy", "MagazynMap", "sprawdz_id"]
