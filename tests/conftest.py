"""Wspólne fixture testów; wagi modeli poza repo (K2)."""

from __future__ import annotations

import os
from pathlib import Path

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
