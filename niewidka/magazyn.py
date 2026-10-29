"""Magazyn map z retencją (docs/MAPY-I-AKTUALIZACJE.md §2): automatyczny zapis
zaszyfrowanej mapy każdego ukrycia w katalogu danych użytkownika, usuwanie po
terminie retencji (RODO) i dziennik zdarzeń do audytu.

Na zadanie dwa pliki: `<id>.nwidka` (szyfrogram AES-256-GCM, jak przy pobraniu)
i `<id>.json` (metadane: utworzono, wygasa, poziom, liczby per typ - żadnych
danych osobowych). Kradzież katalogu bez klucza z magazynu systemowego nic nie
daje. Dziennik `dziennik.jsonl`: czas, zdarzenie, 12-znakowy skrót
identyfikatora, poziom, liczby per typ - nigdy treści ani nazw plików.

Zegar wstrzyknięty (testy retencji bez czekania). Zapis atomowy przez
`opublikuj_bez_hasza` (wspólna z pakietami). Jedna blokada procesu na magazyn,
dziennik i rejestr wydanych map (przegląd Argona pkt 9): API trzyma
`MagazynMap.blokada` wokół zmian rejestru, żeby zapis magazynu i dopisek do
rejestru nie potłukły się z równoległym sprzątaniem albo usuwaniem.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from niewidka.mapa import BladMapy, Mapa, naglowek
from niewidka.pakiety import opublikuj_bez_hasza

# rdzeń wydaje identyfikatory secrets.token_hex(16); ścisły wzorzec zamyka path
# traversal (każdy `../`, separator i backslash odpada, zanim id dotknie ścieżki)
_WZORZEC_ID = re.compile(r"[a-f0-9]{32}")

DOMYSLNY_ZEGAR: Callable[[], datetime] = lambda: datetime.now().astimezone()


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
    ):
        self.katalog = Path(katalog)
        self.retencja_dni = int(retencja_dni)
        self.zegar = zegar or DOMYSLNY_ZEGAR
        self.blokada = threading.Lock()

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

    # --- dziennik ---------------------------------------------------------------

    def _dopisz(
        self,
        zdarzenie: str,
        identyfikator: str,
        poziom: int | None,
        statystyki: dict[str, int] | None,
        teraz: datetime,
    ) -> None:
        """Wiersz audytu BEZ danych osobowych: skrót id zamiast treści mapy."""
        wpis = {
            "czas": teraz.isoformat(timespec="seconds"),
            "zdarzenie": zdarzenie,
            "skrot_id": identyfikator[:12],
            "poziom": poziom,
            "statystyki": statystyki,
        }
        self.katalog.mkdir(parents=True, exist_ok=True)
        with (self.katalog / "dziennik.jsonl").open("a", encoding="utf-8") as dziennik:
            dziennik.write(json.dumps(wpis, ensure_ascii=False) + "\n")


__all__ = ["BladMapy", "MagazynMap", "sprawdz_id"]
