"""Map key tests: base64 32 B file with 0600 or keyring; zero fallback.

The key MUST NOT reach logs, exceptions or repr (secret content = leak).
"""

from __future__ import annotations

import base64
import os
import stat
import subprocess
import sys
from pathlib import Path

import keyring
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


def test_klucz_z_pliku_z_nowa_linia(tmp_path: Path):
    # a file from `base64` / `echo` ends with "\n" (e2e 500 on every hide)
    konfig = Konfig(klucz_plik=_plik_klucza(tmp_path, zawartosc=base64.b64encode(KLUCZ) + b"\r\n"))
    assert pobierz_klucz(konfig, z_keyringa=lambda usluga: None) == KLUCZ


def test_keyring_gdy_brak_pliku():
    konfig = Konfig(klucz_plik=None)
    assert pobierz_klucz(konfig, z_keyringa=lambda usluga: base64.b64encode(KLUCZ).decode()) == KLUCZ


def test_plik_ustawiony_a_nieobecny_to_blad_bez_keyringa(tmp_path: Path):
    # the configured file is the only source: a keyring key would encrypt maps that the file
    # key cannot open once the file is back
    konfig = Konfig(klucz_plik=str(tmp_path / "nie-ma.b64"))
    wolania: list[str] = []

    def keyring(usluga: str) -> str:
        wolania.append(usluga)
        return base64.b64encode(KLUCZ).decode()

    with pytest.raises(BrakKlucza, match="pliku klucza"):
        pobierz_klucz(konfig, z_keyringa=keyring)
    assert wolania == []


def test_zla_dlugosc_klucza_w_pliku(tmp_path: Path):
    konfig = Konfig(klucz_plik=_plik_klucza(tmp_path, zawartosc=base64.b64encode(b"za krotki")))
    with pytest.raises(BrakKlucza, match="32"):
        pobierz_klucz(konfig, z_keyringa=lambda usluga: None)


def test_nie_base64_w_pliku(tmp_path: Path):
    konfig = Konfig(klucz_plik=_plik_klucza(tmp_path, zawartosc=b"\xff\xfe nie-base64"))
    with pytest.raises(BrakKlucza):
        pobierz_klucz(konfig, z_keyringa=lambda usluga: None)


@pytest.mark.skipif(os.name != "posix", reason="uprawnienia sprawdzane tylko na POSIX")
def test_zbyt_otwarte_uprawnienia_pliku(tmp_path: Path):
    konfig = Konfig(klucz_plik=_plik_klucza(tmp_path, tryb=0o644))
    with pytest.raises(BrakKlucza, match="0600"):
        pobierz_klucz(konfig, z_keyringa=lambda usluga: None)


def test_windows_ignoruje_uprawnienia_pliku(tmp_path, monkeypatch):
    """Windows: chmod has only the read-only bit (file reports 0o666); the
    0600 check must not block the key — otherwise desktop
    would reject every key from a file. We replace os ONLY in the klucze module: a global
    change of os.name would also distort pathlib (Path picks its variant by os.name)."""

    class FałszywyOs:
        name = "nt"

        def __getattr__(self, nazwa):
            return getattr(os, nazwa)

    from niewidka import klucze

    monkeypatch.setattr(klucze, "os", FałszywyOs())
    konfig = Konfig(klucz_plik=_plik_klucza(tmp_path, tryb=0o666))
    assert pobierz_klucz(konfig, z_keyringa=lambda usluga: None) == KLUCZ


def test_klucz_nie_w_wyjatku(tmp_path: Path):
    """Error message does not contain the file content (neither base64 nor hex)."""
    zawartosc = base64.b64encode(b"\x01" * 16)  # valid base64, wrong length
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
    if os.name == "posix":  # Windows: chmod gives only the R/O bit, 0600 can be checked only here
        tryb = stat.S_IMODE(sciezka.stat().st_mode)
        assert tryb == 0o600, oct(tryb)
    assert len(base64.b64decode(sciezka.read_bytes())) == 32


def test_cli_do_keyringa(keyring_pamieciowy):
    from niewidka import klucze

    assert klucze.main(["do-keyringa"]) == 0
    assert len(base64.b64decode(keyring.get_password("niewidka", klucze.KONTO))) == 32


# --- explicit key creation straight into the keyring; no overwriting ---


def test_utworz_klucz_w_keyringu_zapisuje_32_bajty(keyring_pamieciowy):
    from niewidka import klucze

    klucze.utworz_klucz_w_keyringu("niewidka-testy")
    haslo = keyring.get_password("niewidka-testy", klucze.KONTO)
    assert len(base64.b64decode(haslo)) == 32
    # key immediately readable through pobierz_klucz (same path as the app)
    assert pobierz_klucz(Konfig(keyring_usluga="niewidka-testy")) == base64.b64decode(haslo)


def test_utworz_klucz_nie_nadpisuje_istniejacego(keyring_pamieciowy):
    from niewidka import klucze

    keyring.set_password("niewidka-testy", klucze.KONTO, base64.b64encode(KLUCZ).decode())
    with pytest.raises(klucze.KluczJuzIstnieje):
        klucze.utworz_klucz_w_keyringu("niewidka-testy")
    # old key untouched: a silent overwrite would cut off access to old maps
    assert pobierz_klucz(Konfig(keyring_usluga="niewidka-testy")) == KLUCZ


def test_cli_do_keyringa_odmawia_gdy_klucz_jest(keyring_pamieciowy, capsys):
    from niewidka import klucze

    keyring.set_password("niewidka", klucze.KONTO, base64.b64encode(KLUCZ).decode())
    assert klucze.main(["do-keyringa"]) == 1
    assert keyring.get_password("niewidka", klucze.KONTO) == base64.b64encode(KLUCZ).decode()
    assert "nadpisz" in capsys.readouterr().err


def test_cli_do_keyringa_nadpisz_na_wyrazny_cek(keyring_pamieciowy):
    from niewidka import klucze

    keyring.set_password("niewidka", klucze.KONTO, base64.b64encode(KLUCZ).decode())
    assert klucze.main(["do-keyringa", "--nadpisz"]) == 0
    assert keyring.get_password("niewidka", klucze.KONTO) != base64.b64encode(KLUCZ).decode()
    assert len(base64.b64decode(keyring.get_password("niewidka", klucze.KONTO))) == 32
