"""Klucz mapy (LLD §8): plik z NIEWIDKA_KLUCZ_PLIK albo keyring — zero fallbacku
i cichego generowania; brak obu źródeł = `BrakKlucza`. Treść klucza nigdy nie
trafia do logów, wyjątków ani repr.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import secrets
import stat
import sys
from pathlib import Path

import keyring

from niewidka.konfig import Konfig, wczytaj_konfig

DLOGOSC = 32  # bajty, AES-256
KONTO = "mapa"


class BrakKlucza(Exception):
    """Brak albo wadliwy klucz mapy — jawny błąd, bez tworzenia nowego po cichu."""


class KluczJuzIstnieje(Exception):
    """Wpis klucza już jest w magazynie: nie nadpisujemy bez wyraźnego ceku
    (nadpisanie odebrałoby dostęp do map zaszyfrowanych starym kluczem)."""


def utworz_klucz_w_keyringu(usluga: str, nadpisz: bool = False) -> None:
    """Nowy klucz wprost do magazynu systemowego (desktop K6, Windows: Menedżer
    poświadczeń). Istniejący wpis blokuje — zamiana tylko świadomie (nadpisz=True).
    """
    if not nadpisz and _z_keyringa(usluga):
        raise KluczJuzIstnieje(
            f"klucz już jest w magazynie (usługa: {usluga}); zamiana odebrałaby dostęp do starych map"
        )
    keyring.set_password(usluga, KONTO, base64.b64encode(secrets.token_bytes(DLOGOSC)).decode())


def _z_pliku(sciezka: Path) -> bytes:
    try:
        tryb = stat.S_IMODE(sciezka.stat().st_mode)
        if tryb & 0o077 and hasattr(os, "chmod"):  # 0600 wymagane tylko na POSIX
            raise BrakKlucza(f"plik klucza ma uprawnienia {oct(tryb)}, wymagane 0600")
        zdekodowane = base64.b64decode(sciezka.read_bytes(), validate=True)
    except BrakKlucza:
        raise
    except OSError as blad:
        raise BrakKlucza(f"plik klucza nieczytelny: {blad.strerror}") from None
    except binascii.Error:
        raise BrakKlucza("plik klucza nie zawiera poprawnego base64") from None
    if len(zdekodowane) != DLOGOSC:
        raise BrakKlucza(f"klucz w pliku ma {len(zdekodowane)} B, wymagane {DLOGOSC} B")
    return zdekodowane


def _z_keyringa(usluga: str) -> str | None:
    try:
        return keyring.get_password(usluga, KONTO)
    except Exception:  # noqa: BLE001 — dowolny pad backendu = brak źródła, nie awaria
        return None


def pobierz_klucz(konfig: Konfig, z_keyringa=_z_keyringa) -> bytes:
    """Klucz 32 B: 1) plik z konfig.klucz_plik, 2) keyring[usluga/KONTO].

    Wywoływany przy szyfrowaniu/odszyfrowywaniu — aplikacja nie trzyma klucza
    dłużej niż na czas operacji.
    """
    if konfig.klucz_plik:
        sciezka = Path(konfig.klucz_plik).expanduser()
        if sciezka.is_file():
            return _z_pliku(sciezka)
    haslo = z_keyringa(konfig.keyring_usluga)
    if haslo:
        try:
            zdekodowane = base64.b64decode(haslo, validate=True)
        except binascii.Error:
            raise BrakKlucza("wpis klucza w keyringu nie jest poprawnym base64") from None
        if len(zdekodowane) != DLOGOSC:
            raise BrakKlucza(f"klucz w keyringu ma {len(zdekodowane)} B, wymagane {DLOGOSC} B")
        return zdekodowane
    raise BrakKlucza(
        "brak klucza mapy: zapisz go plikiem (python -m niewidka.klucze nowy-plik <ścieżka>, "
        "NIEWIDKA_KLUCZ_PLIK) albo w keyringu (python -m niewidka.klucze do-keyringa)"
    )


def _zapisz_plik(sciezka: Path) -> None:
    dane = base64.b64encode(secrets.token_bytes(DLOGOSC))
    uchwyt = os.open(sciezka, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(uchwyt, "wb") as plik:
        plik.write(dane)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m niewidka.klucze", description="Zarządzanie kluczem mapy Niewidki"
    )
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    plik = polecenia.add_parser("nowy-plik", help="nowy klucz do pliku (base64, uprawnienia 0600)")
    plik.add_argument("sciezka", type=Path)
    do_keyringa = polecenia.add_parser("do-keyringa", help="nowy klucz do keyringu (usługa z konfiguracji)")
    do_keyringa.add_argument(
        "--nadpisz", action="store_true", help="zamień istniejący klucz (stare mapy staną się nieczytelne)"
    )
    argumenty = parser.parse_args(argv)

    if argumenty.polecenie == "nowy-plik":
        if argumenty.sciezka.exists():
            print(f"plik istnieje, nie nadpisuję: {argumenty.sciezka}", file=sys.stderr)
            return 1
        _zapisz_plik(argumenty.sciezka)
        print(f"klucz zapisany: {argumenty.sciezka}")
        return 0
    konfig = wczytaj_konfig()
    try:
        utworz_klucz_w_keyringu(konfig.keyring_usluga, nadpisz=argumenty.nadpisz)
    except KluczJuzIstnieje:
        print(
            f"klucz już istnieje (usługa: {konfig.keyring_usluga}); zamiana tylko z --nadpisz",
            file=sys.stderr,
        )
        return 1
    print(f"klucz zapisany w keyringu (usługa: {konfig.keyring_usluga})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
