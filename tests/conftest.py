"""Shared test fixtures; model weights live outside the repo."""

from __future__ import annotations

import os
from pathlib import Path

import keyring
import pytest


@pytest.fixture(scope="session")
def katalog_modeli() -> Path:
    """Weights directory from NIEWIDKA_MODELE_KATALOG; without weights, tests marked `model` are skipped."""
    katalog = os.environ.get("NIEWIDKA_MODELE_KATALOG", "")
    if not katalog or not (Path(katalog) / "manifest.json").is_file():
        pytest.skip("wagi niepobrane: ustaw NIEWIDKA_MODELE_KATALOG (narzedzia/pobierz_model)")
    return Path(katalog)


@pytest.fixture(scope="session")
def model_bardsai(katalog_modeli: Path):
    from niewidka.detektory import wczytaj_bardsai

    return wczytaj_bardsai(katalog_modeli)


@pytest.fixture(scope="session")
def wagi_lfm25(katalog_modeli: Path) -> Path:
    """Weights directory when the exported LFM2.5 ONNX exists; otherwise skip."""
    if not (katalog_modeli / "lfm25" / "int8" / "model.onnx").is_file():
        pytest.skip("ONNX LFM2.5 niewyeksportowany (narzedzia/eksport_lfm25.py)")
    return katalog_modeli


@pytest.fixture(scope="session")
def model_lfm25(wagi_lfm25: Path):
    from niewidka.detektory import wczytaj_lfm25

    return wczytaj_lfm25(wagi_lfm25)


class PamięciowyBackend(keyring.backend.KeyringBackend):
    """Test keyring backend: passwords kept only in a process dictionary."""

    priority = 1

    def __init__(self):
        self.dane: dict[tuple[str, str], str] = {}

    def set_password(self, usluga: str, konto: str, haslo: str) -> None:
        self.dane[(usluga, konto)] = haslo

    def get_password(self, usluga: str, konto: str) -> str | None:
        return self.dane.get((usluga, konto))


@pytest.fixture()
def keyring_pamieciowy():
    """In-memory password store instead of the system one; the previous one is restored after the test."""
    stary = keyring.get_keyring()
    backend = PamięciowyBackend()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(stary)


def dowiazanie(link: Path, cel: Path) -> None:
    """Link for attack tests. Windows without symlink privileges (WinError 1314):
    a directory gets a junction (also a reparse point, no privileges needed), a file = test skipped
    (full coverage on Linux and the CI runner)."""
    try:
        link.symlink_to(cel)
    except OSError as blad:
        if os.name != "nt" or getattr(blad, "winerror", None) != 1314:
            raise
        if not cel.is_dir():
            pytest.skip("Windows bez uprawnień do dowiązań symbolicznych plików")
        import _winapi

        _winapi.CreateJunction(str(cel), str(link))
