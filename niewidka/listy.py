"""Fixed lists "Always hide" and "Never hide" ("Zawsze ukrywaj" / "Nigdy nie ukrywaj").

Two sources: the administrator list from configuration (`[listy] zawsze/nigdy`, not editable
from the program) and the user list in a JSON file in the data directory (edited in Settings).
`tylko_administrator` blocks editing of the user list. The lists apply on every
hide and every correction like "Ukryj wszędzie" and "To nie dane", without running the model again.

Numbers with a checksum (PESEL, NIP, ...) cannot go on "Nigdy nie ukrywaj":
they are certain personal data (the same restriction as "To nie dane" in the preview).

SIMPLIFICATION: "Nigdy nie ukrywaj" removes a detection only when the whole detected text is
a list item in any inflected form ("Biura Rachunkowego" for "Biuro Rachunkowe"); a longer detection
("Urząd Miasta Krakowa") stays hidden. When to extend: when users report
a need for partial matches.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

from niewidka.detektory import RegulyDetektor
from niewidka.pakiety import opublikuj_bez_hasza
from niewidka.poprawki import TYPY_Z_SUMA, BladPoprawki, sprawdz_liste, znajdz_wystapienia
from niewidka.rdzen import Detekcje


def z_suma_kontrolna(fragment: str) -> bool:
    """Whether the rules see a number with a checksum in the fragment."""
    return any(z.typ in TYPY_Z_SUMA for z in RegulyDetektor().znajdz(fragment))


def sprawdz_listy(zawsze: object, nigdy: object) -> tuple[list[str], list[str]]:
    """Validation of both lists (limits as in corrections, disjointness, no checksum numbers on "nigdy")."""
    zawsze_ok = sprawdz_liste("zawsze", zawsze)
    nigdy_ok = sprawdz_liste("nigdy", nigdy)
    if set(zawsze_ok) & set(nigdy_ok):
        raise BladPoprawki("ten sam fragment nie może być na obu listach")
    if any(z_suma_kontrolna(f) for f in nigdy_ok):
        raise BladPoprawki(
            "numerów z sumą kontrolną (PESEL, NIP, REGON, IBAN, karta, dowód) nie można dodać do „Nigdy nie ukrywaj”"
        )
    return zawsze_ok, nigdy_ok


@dataclass(frozen=True)
class Listy:
    zawsze: list[str]
    nigdy: list[str]

    def znaczniki_nigdy(self, detekcje: Detekcje) -> list[str]:
        """Detection markers whose whole text is a "nigdy" item (without checksum types)."""
        wynik: list[str] = []
        for encje in detekcje.encje:
            for encja in encje:
                if encja.oznaczenie in wynik or encja.zakres.typ in TYPY_Z_SUMA:
                    continue
                tekst = encja.tekst
                if any(znajdz_wystapienia(tekst, f) == [(0, len(tekst))] for f in self.nigdy):
                    wynik.append(encja.oznaczenie)
        return wynik


class ListyStale:
    """Administrator list (from configuration) + user list (JSON file)."""

    def __init__(
        self,
        plik: Path,
        admin_zawsze: tuple[str, ...] = (),
        admin_nigdy: tuple[str, ...] = (),
        tylko_administrator: bool = False,
    ):
        self.plik = plik
        # an error in the administrator list stops startup (like other bad configuration values)
        self.admin = Listy(*sprawdz_listy(list(admin_zawsze), list(admin_nigdy)))
        self.tylko_administrator = tylko_administrator
        self._blokada = threading.Lock()

    def uzytkownika(self) -> Listy:
        try:
            dane = json.loads(self.plik.read_text(encoding="utf-8"))
            return Listy(*sprawdz_listy(dane.get("zawsze"), dane.get("nigdy")))
        except FileNotFoundError:
            return Listy([], [])
        except (OSError, ValueError, AttributeError) as blad:
            # an empty list in place of a corrupted one would silently drop the "Zawsze ukrywaj" protection
            raise BladPoprawki(
                "lista użytkownika jest nieczytelna lub uszkodzona; napraw albo usuń plik list"
            ) from blad

    def razem(self) -> Listy:
        """Both lists; on a conflict the administrator wins."""
        uzytkownik = self.uzytkownika()
        zawsze = self.admin.zawsze + [
            f for f in uzytkownik.zawsze if f not in self.admin.zawsze + self.admin.nigdy
        ]
        nigdy = self.admin.nigdy + [
            f for f in uzytkownik.nigdy if f not in self.admin.nigdy + self.admin.zawsze
        ]
        return Listy(zawsze, nigdy)

    def zapisz(self, zawsze: object, nigdy: object) -> Listy:
        if self.tylko_administrator:
            raise PermissionError("listy ustawia administrator")
        listy = Listy(*sprawdz_listy(zawsze, nigdy))
        tresc = json.dumps(
            {"zawsze": listy.zawsze, "nigdy": listy.nigdy}, ensure_ascii=False, indent=2
        )
        with self._blokada:
            opublikuj_bez_hasza((tresc + "\n").encode("utf-8"), self.plik, self.plik.parent)
        return listy
