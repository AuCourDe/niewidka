"""Magazyn map z retencją: zaszyfrowana mapa każdego ukrycia w katalogu danych (`<id>.nwidka`
+ metadane `<id>.json` bez danych osobowych), usuwanie po terminie retencji i dziennik
zdarzeń (`dziennik.jsonl`, nigdy treści ani nazw plików).

Zegar wstrzyknięty; zapis atomowy. API trzyma `MagazynMap.blokada` wokół zmian rejestru
wydanych map, żeby nie kolidowały ze sprzątaniem.
"""

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

# rdzeń wydaje identyfikatory secrets.token_hex(16); ścisły wzorzec zamyka path
# traversal (każdy `../`, separator i backslash odpada, zanim id dotknie ścieżki)
_WZORZEC_ID = re.compile(r"[a-f0-9]{32}")

DOMYSLNY_ZEGAR: Callable[[], datetime] = lambda: datetime.now().astimezone()


def kontekst_domyslny() -> dict:
    """Pola środowiska audytu: użytkownik systemu i wersja programu."""
    return {"uzytkownik": getpass.getuser(), "wersja": __version__}


def wersje_pakietow(katalog_wag: Path | str | None) -> dict[str, str] | None:
    """Wersje pakietów modeli z manifestów w katalogu wag; None, gdy manifesty ich
    nie podają (starsze katalogi) albo katalogu nie ma."""
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
    """SHA-256 ostatniej niepustej linii dziennika; pusty string, gdy pliku nie ma
    (pierwszy wpis łańcucha)."""
    if not sciezka.is_file():
        return ""
    linie = [l for l in sciezka.read_text(encoding="utf-8").splitlines() if l.strip()]
    return hashlib.sha256(linie[-1].encode("utf-8")).hexdigest() if linie else ""


def zweryfikuj_lancuch(sciezka: Path) -> tuple[bool, list[str]]:
    """Weryfikacja łańcucha dziennika: każdy wpis wskazuje skrót
    SHA-256 poprzedniej linii, więc edycja treści albo usunięcie wiersza zepsuje
    następnik. Zwraca (spójny, problemy) z numerami linii - bez treści wpisów."""
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
    """Identyfikator dopuszczony do użycia w ścieżce; inaczej ValueError."""
    if not _WZORZEC_ID.fullmatch(identyfikator or ""):
        raise ValueError("zły identyfikator mapy")
    return identyfikator


class MagazynMap:
    """Kolekcja map w katalogu danych + dziennik zdarzeń; retencja w dniach."""

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
        # pola środowiska audytu (użytkownik, wersja programu, wersje pakietów);
        # API podaje wersję z manifestami wag, domyślnie sam użytkownik i program
        self.kontekst = kontekst or kontekst_domyslny
        # RLock: API trzyma blokadę wokół sekwencji metod (sprzątanie + zapis +
        # rejestr), a metody magazynu blokują też pojedynczo - ten sam wątek wejdzie
        self.blokada = threading.RLock()

    # --- zapis i odczyt ---------------------------------------------------------

    def zapisz(self, szyfrogram: bytes, mapa: Mapa, statystyki: dict[str, int]) -> datetime | None:
        """Szyfrogram + metadane do magazynu; zwraca datę wygaśnięcia albo None
        (retencja 0 = brak automatycznego zapisu). Nie-mapie mówią „nie mapa"."""
        naglowek(szyfrogram)  # BladMapy zanim cokolwiek powstanie na dysku
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
        """Szyfrogram mapy albo None, gdy jej nie ma (wygasła, usunięta, obca)."""
        identyfikator = sprawdz_id(identyfikator)
        plik = self.katalog / f"{identyfikator}.nwidka"
        return plik.read_bytes() if plik.is_file() else None

    def lista(self) -> list[dict]:
        """Metadane map od najnowszej; uszkodzone wpisy pomijane (fail-safe)."""
        if not self.katalog.is_dir():
            return []
        wynik = []
        for plik in self.katalog.glob("*.json"):
            try:
                wpis = json.loads(plik.read_text(encoding="utf-8"))
                wynik.append(
                    {
                        "identyfikator": str(wpis["identyfikator"]),
                        "utworzono": str(wpis["utworzono"]),
                        "wygasa": str(wpis["wygasa"]),
                        "poziom": int(wpis["poziom"]),
                        "statystyki": {str(k): int(v) for k, v in wpis["statystyki"].items()},
                    }
                )
            except (ValueError, KeyError, TypeError, OSError):
                continue
        wynik.sort(key=lambda w: (w["utworzono"], w["identyfikator"]), reverse=True)
        return wynik

    # --- usuwanie ---------------------------------------------------------------

    def usun(self, identyfikator: str) -> bool:
        """Ręczne usunięcie jednej mapy; True, gdy coś usunięto."""
        return self._usun(identyfikator, "usunieto")

    def usun_wszystkie(self) -> int:
        ile = 0
        for wpis in self.lista():
            ile += int(self.usun(wpis["identyfikator"]))
        return ile

    def posprzataj(self) -> list[str]:
        """Usuwa mapy po terminie retencji (wywołanie przy starcie i przed każdą
        operacją magazynu); zwraca identyfikatory usuniętych."""
        if not self.katalog.is_dir():
            return []
        teraz = self.zegar()
        przeterminowane = []
        for wpis in self.lista():
            try:
                wygasa = datetime.fromisoformat(wpis["wygasa"])
            except ValueError:
                continue  # zepsuty termin: zostawia decyzję człowiekowi, nie kasujemy
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
        """Wpis audytu o zdarzeniu spoza magazynu (np. przywrocono z pobranej kopii,
        poprawiono z liczbami pozycji). Wyłącznie liczby, nigdy treść."""
        with self.blokada:
            self._dopisz(zdarzenie, sprawdz_id(identyfikator), poziom, liczby, self.zegar())

    # --- dziennik ---------------------------------------------------------------

    def _dopisz(
        self,
        zdarzenie: str,
        identyfikator: str,
        poziom: int | None,
        statystyki: dict[str, int] | None,
        teraz: datetime,
    ) -> None:
        """Wiersz audytu BEZ danych osobowych: skrót id zamiast treści mapy, do tego
        kontekst środowiska i łańcuch skrótów SHA-256 (edycja jest wykrywalna,"""
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
