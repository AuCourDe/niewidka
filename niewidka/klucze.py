"""Map key: a file from NIEWIDKA_KLUCZ_PLIK or keyring - no fallback
and no silent generation; neither source present = `BrakKlucza`. The key content never
reaches logs, exceptions or repr.
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

DLOGOSC = 32  # bytes, AES-256
KONTO = "mapa"


class BrakKlucza(Exception):
    """Missing or invalid map key - an explicit error, no silent creation of a new one."""


class KluczJuzIstnieje(Exception):
    """A key entry already exists in the store: not overwritten without explicit consent
    (overwriting would cut off access to maps encrypted with the old key)."""


def utworz_klucz_w_keyringu(usluga: str, nadpisz: bool = False) -> None:
    """New key straight into the system store (desktop, Windows: Credential
    Manager). An existing entry blocks - replace only deliberately (nadpisz=True).
    """
    if not nadpisz and _z_keyringa(usluga):
        raise KluczJuzIstnieje(
            f"klucz już jest w magazynie (usługa: {usluga}); zamiana odebrałaby dostęp do starych map"
        )
    keyring.set_password(usluga, KONTO, base64.b64encode(secrets.token_bytes(DLOGOSC)).decode())


def _z_pliku(sciezka: Path) -> bytes:
    try:
        tryb = stat.S_IMODE(sciezka.stat().st_mode)
        if tryb & 0o077 and os.name == "posix":  # 0600 required on POSIX only (Windows: only the read-only bit)
            raise BrakKlucza(f"plik klucza ma uprawnienia {oct(tryb)}, wymagane 0600")
        # a file prepared by IT (base64, echo) usually ends with a newline
        zdekodowane = base64.b64decode(sciezka.read_bytes().strip(), validate=True)
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
    except Exception:  # noqa: BLE001 - any backend failure = no source, not a crash
        return None


def pobierz_klucz(konfig: Konfig, z_keyringa=_z_keyringa) -> bytes:
    """32 B key: the file from konfig.klucz_plik when one is configured, otherwise
    keyring[usluga/KONTO].

    A configured file is the only source: when it is missing, the keyring is not asked, because
    its key would encrypt maps that the file key cannot open later.
    Called on encrypt/decrypt - the application holds the key
    no longer than the operation takes.
    """
    if konfig.klucz_plik:
        sciezka = Path(konfig.klucz_plik).expanduser()
        if not sciezka.is_file():
            raise BrakKlucza(f"brak pliku klucza mapy wskazanego w ustawieniach: {sciezka}")
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
