"""Narzędzie wydawcy do podpisywania katalogu pakietów Ed25519.

Klucz prywatny czytany WYŁĄCZNIE ze ścieżki w zmiennej środowiskowej
`NIEWIDKA_KLUCZ_PODPISU` (nigdy z argumentu CLI, nigdy w logach).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import sys
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)


def generuj_pare(plik_prywatny: Path) -> str:
    """Generuje parę kluczy Ed25519; klucz prywatny zapisuje z uprawnieniami 0600,
    a klucz publiczny zwraca jako string base64 surowych bajtów."""
    klucz_prywatny = ed25519.Ed25519PrivateKey.generate()
    surowe_prywatne = klucz_prywatny.private_bytes_raw()

    plik_prywatny.parent.mkdir(parents=True, exist_ok=True)
    # Zapis z uprawnieniami 0600
    fd = os.open(plik_prywatny, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as uchwyt:
            uchwyt.write(surowe_prywatne)
    finally:
        try:
            os.chmod(plik_prywatny, 0o600)
        except OSError:
            pass

    klucz_publiczny = klucz_prywatny.public_key()
    surowe_publiczne = klucz_publiczny.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(surowe_publiczne).decode("ascii")


def wczytaj_klucz_prywatny_z_pliku(sciezka: Path) -> ed25519.Ed25519PrivateKey:
    """Wczytuje klucz prywatny Ed25519 z pliku (surowe 32 bajty, PEM lub base64)."""
    if not sciezka.is_file():
        raise FileNotFoundError(f"Plik klucza prywatnego nie istnieje: {sciezka}")
    bajty = sciezka.read_bytes()
    if len(bajty) == 32:
        return ed25519.Ed25519PrivateKey.from_private_bytes(bajty)
    try:
        klucz = load_pem_private_key(bajty, password=None)
        if isinstance(klucz, ed25519.Ed25519PrivateKey):
            return klucz
    except (ValueError, TypeError, UnsupportedAlgorithm):
        pass
    try:
        zdekodowane = base64.b64decode(bajty.strip())
        if len(zdekodowane) == 32:
            return ed25519.Ed25519PrivateKey.from_private_bytes(zdekodowane)
    except (ValueError, binascii.Error):
        pass
    raise ValueError("Nieznany format klucza prywatnego Ed25519 (oczekiwano 32 bajtów lub PEM)")


def podpisz_plik_katalogu(plik_katalogu: Path, klucz_prywatny: ed25519.Ed25519PrivateKey) -> Path:
    """Podpisuje plik katalogu i zapisuje podpis do <plik_katalogu>.sig."""
    if not plik_katalogu.is_file():
        raise FileNotFoundError(f"Plik katalogu nie istnieje: {plik_katalogu}")
    dane = plik_katalogu.read_bytes()
    podpis = klucz_prywatny.sign(dane)
    plik_podpisu = plik_katalogu.with_name(plik_katalogu.name + ".sig")
    plik_podpisu.write_bytes(podpis)
    return plik_podpisu


def buduj_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Podpisywanie katalogu pakietów Ed25519 dla Niewidki.",
        epilog="Klucz prywatny pobierany jest WYŁĄCZNIE ze zmiennej NIEWIDKA_KLUCZ_PODPISU.",
    )
    parser.add_argument(
        "katalog",
        nargs="?",
        default="katalog-pakietow.json",
        help="Ścieżka do pliku katalogu (domyślnie: katalog-pakietow.json)",
    )
    parser.add_argument(
        "--generuj-pare",
        dest="generuj_pare",
        metavar="PLIK_PRYWATNY",
        help="Generuje nową parę kluczy Ed25519, zapisuje klucz prywatny (0600) i wypisuje klucz publiczny",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = buduj_parser()
    args = parser.parse_args(argv)

    if args.generuj_pare:
        plik_prywatny = Path(args.generuj_pare)
        klucz_pub_b64 = generuj_pare(plik_prywatny)
        sys.stdout.write(f"{klucz_pub_b64}\n")
        return 0

    sciezka_klucza_env = os.environ.get("NIEWIDKA_KLUCZ_PODPISU")
    if not sciezka_klucza_env:
        sys.stderr.write(
            "BŁĄD: Zmienna środowiskowa NIEWIDKA_KLUCZ_PODPISU nie jest ustawiona.\n"
            "Podaj ścieżkę do pliku z kluczem prywatnym przez zmienną środowiskową.\n"
        )
        return 1

    try:
        klucz_prywatny = wczytaj_klucz_prywatny_z_pliku(Path(sciezka_klucza_env))
        plik_katalogu = Path(args.katalog)
        plik_podpisu = podpisz_plik_katalogu(plik_katalogu, klucz_prywatny)
        sys.stdout.write(f"Podpisano pomyślnie: {plik_podpisu}\n")
        return 0
    except (OSError, ValueError) as blad:
        sys.stderr.write(f"BŁĄD podpisywania: {blad}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
