"""Listy stałe „Zawsze ukrywaj” i „Nigdy nie ukrywaj” (decyzja właściciela 2026-10-29, 1a).

Dwa źródła: lista administratora z konfiguracji (`[listy] zawsze/nigdy`, nieedytowalna
z programu) i lista użytkownika w pliku JSON w katalogu danych (edycja w Ustawieniach).
`tylko_administrator` blokuje edycję listy użytkownika. Listy działają przy każdym
ukryciu i każdej poprawce jak „Ukryj wszędzie” i „To nie dane”, bez ponownego modelu.

Numery z sumą kontrolną (PESEL, NIP, ...) nie mogą trafić na „Nigdy nie ukrywaj”:
to pewne dane osobowe (to samo ograniczenie co „To nie dane” w podglądzie).

SIMPLIFICATION: „Nigdy nie ukrywaj” zdejmuje wykrycie tylko, gdy cały wykryty tekst to
pozycja listy w dowolnej odmianie („Urzędu Miasta” dla „Urząd Miasta”); wykrycie dłuższe
(„Urząd Miasta Krakowa”) zostaje ukryte. Kiedy rozbudować: gdy użytkownicy zgłoszą
potrzebę częściowych dopasowań.
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
    """Czy reguły widzą we fragmencie numer z sumą kontrolną."""
    return any(z.typ in TYPY_Z_SUMA for z in RegulyDetektor().znajdz(fragment))


def sprawdz_listy(zawsze: object, nigdy: object) -> tuple[list[str], list[str]]:
    """Walidacja obu list (limity jak w poprawkach, rozłączność, bez numerów z sumą na „nigdy”)."""
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
        """Znaczniki wykryć, których cały tekst to pozycja „nigdy” (bez typów z sumą)."""
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
    """Lista administratora (z konfiguracji) + lista użytkownika (plik JSON)."""

    def __init__(
        self,
        plik: Path,
        admin_zawsze: tuple[str, ...] = (),
        admin_nigdy: tuple[str, ...] = (),
        tylko_administrator: bool = False,
    ):
        self.plik = plik
        # błąd w liście administratora zatrzymuje start (jak inne złe wartości konfiguracji)
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
            # pusta lista w miejsce uszkodzonej cicho zdjęłaby ochronę „Zawsze ukrywaj”
            raise BladPoprawki(
                "lista użytkownika jest nieczytelna lub uszkodzona; napraw albo usuń plik list"
            ) from blad

    def razem(self) -> Listy:
        """Obie listy; przy sprzeczności wygrywa administrator."""
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
