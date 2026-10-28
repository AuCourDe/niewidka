"""Testy klucza mapy (K4, LLD §8): plik base64 32 B z 0600 albo keyring; zero fallbacku.

Klucz NIE może trafić do logów, wyjątków ani repr (treść sekretu = wyciek).
"""

from __future__ import annotations

import base64
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from niewidka.klucze import BrakKlucza, pobierz_klucz
from niewidka.konfig import Konfig

KLUCZ = bytes(range(32))


def _plik_klucza(tmp_path: Path, tryb: int = 0o600, zawartosc: bytes | None = None) -> str:
    sciezka = tmp_path / "klucz.b64"
    sciezka.write_bytes(zawartosc or base64.b64encode(KLUCZ))
    sciezka.chmod(tryb)
    return str(sciezka)


def test_brak_obu_zrodel_brak_klucza():
    with pytest.raises(BrakKlucza, match="klucz"):
        pobierz_klucz(Konfig(), z_keyringa=lambda usluga: None)


def test_klucz_z_pliku_ok(tmp_path: Path):
    konfig = Konfig(klucz_plik=_plik_klucza(tmp_path))
    assert (
        pobierz_klucz(konfig, z_keyringa=lambda usluga: pytest.fail("plik ma pierwszeństwo")) == KLUCZ
    )


def test_keyring_gdy_brak_pliku():
    konfig = Konfig(klucz_plik=None)
    assert pobierz_klucz(konfig, z_keyringa=lambda usluga: base64.b64encode(KLUCZ).decode()) == KLUCZ


def test_plik_ustawiony_a_nieobecny_siega_keyringa():
    konfig = Konfig(klucz_plik="/tmp/nie-ma.b64")
    assert pobierz_klucz(konfig, z_keyringa=lambda usluga: base64.b64encode(KLUCZ).decode()) == KLUCZ


def test_zla_dlugosc_klucza_w_pliku(tmp_path: Path):
    konfig = Konfig(klucz_plik=_plik_klucza(tmp_path, zawartosc=base64.b64encode(b"za krotki")))
    with pytest.raises(BrakKlucza, match="32"):
        pobierz_klucz(konfig, z_keyringa=lambda usluga: None)


def test_nie_base64_w_pliku(tmp_path: Path):
    konfig = Konfig(klucz_plik=_plik_klucza(tmp_path, zawartosc=b"\xff\xfe nie-base64"))
    with pytest.raises(BrakKlucza):
        pobierz_klucz(konfig, z_keyringa=lambda usluga: None)


@pytest.mark.skipif(not hasattr(os, "chmod"), reason="uprawnienia POSIX")
def test_zbyt_otwarte_uprawnienia_pliku(tmp_path: Path):
    konfig = Konfig(klucz_plik=_plik_klucza(tmp_path, tryb=0o644))
    with pytest.raises(BrakKlucza, match="0600"):
        pobierz_klucz(konfig, z_keyringa=lambda usluga: None)


def test_klucz_nie_w_wyjatku(tmp_path: Path):
    """Komunikat błędu nie zawiera treści pliku (base64 ani hex)."""
    zawartosc = base64.b64encode(b"\x01" * 16)  # poprawne base64, zła długość
    konfig = Konfig(klucz_plik=_plik_klucza(tmp_path, zawartosc=zawartosc))
    with pytest.raises(BrakKlucza) as blad:
        pobierz_klucz(konfig, z_keyringa=lambda usluga: None)
    komunikat = str(blad.value)
    assert zawartosc.decode() not in komunikat
    assert (b"\x01" * 16).hex() not in komunikat


def test_cli_nowy_plik(tmp_path: Path):
    sciezka = tmp_path / "nowy.b64"
    wynik = subprocess.run(
        [sys.executable, "-m", "niewidka.klucze", "nowy-plik", str(sciezka)],
        capture_output=True,
        check=False,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
    )
    assert wynik.returncode == 0, wynik.stderr
    tryb = stat.S_IMODE(sciezka.stat().st_mode)
    assert tryb == 0o600, oct(tryb)
    assert len(base64.b64decode(sciezka.read_bytes())) == 32


def test_cli_do_keyringa(monkeypatch):
    zapisane: dict[tuple[str, str], str] = {}

    from niewidka import klucze

    monkeypatch.setattr(
        klucze.keyring,
        "set_password",
        lambda usluga, konto, wartosc: zapisane.setdefault((usluga, konto), wartosc),
    )
    klucze.main(["do-keyringa"])
    assert len(base64.b64decode(zapisane[("niewidka", "mapa")])) == 32
