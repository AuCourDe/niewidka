"""Wspólne fixture testów; wagi modeli poza repo (K2)."""

from __future__ import annotations

import os
from pathlib import Path

import keyring
import pytest


@pytest.fixture(scope="session")
def katalog_modeli() -> Path:
    """Katalog wag z NIEWIDKA_MODELE_KATALOG; bez wag testy z markerem `model` skaczą."""
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
    """Katalog wag, gdy wyeksportowany ONNX LFM2.5 jest; inaczej skok (K2b)."""
    if not (katalog_modeli / "lfm25" / "int8" / "model.onnx").is_file():
        pytest.skip("ONNX LFM2.5 niewyeksportowany (narzedzia/eksport_lfm25.py)")
    return katalog_modeli


@pytest.fixture(scope="session")
def model_lfm25(wagi_lfm25: Path):
    from niewidka.detektory import wczytaj_lfm25

    return wczytaj_lfm25(wagi_lfm25)


class PamięciowyBackend(keyring.backend.KeyringBackend):
    """Backend testowy keyringa (K6): hasła tylko w słowniku procesu."""

    priority = 1

    def __init__(self):
        self.dane: dict[tuple[str, str], str] = {}

    def set_password(self, usluga: str, konto: str, haslo: str) -> None:
        self.dane[(usluga, konto)] = haslo

    def get_password(self, usluga: str, konto: str) -> str | None:
        return self.dane.get((usluga, konto))


@pytest.fixture()
def keyring_pamieciowy():
    """Magazyn haseł w pamięci zamiast systemowego; po teście poprzedni wraca."""
    stary = keyring.get_keyring()
    backend = PamięciowyBackend()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(stary)
