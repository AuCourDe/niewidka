"""Testy wydania: akcje przypięte do pełnych SHA, podział
uprawnień (budowa read / publikacja write), lockfile z haszami wspólny dla
workflow i skryptu budowy Windows."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "wydanie.yml"
LOCKFILE = ROOT / "narzedzia" / "wymagania-budowy.txt"
SKRYPT_BUDOWY = ROOT / "narzedzia" / "zbuduj_windows.ps1"


def _tresc(sciezka: Path, komentarze: str = "utf-8") -> str:
    return sciezka.read_text(encoding=komentarze)


def test_akcje_przypiete_do_pelnych_sha_z_komentarzem_wersji():
    """Ruchomy tag akcji = kod trzeci z contents: write po przejęciu."""
    tresc = _tresc(WORKFLOW)
    wiersze_uses = [w for w in tresc.splitlines() if re.search(r"uses:\s*\S+@", w)]
    assert wiersze_uses, "workflow bez akcji?"
    for wiersz in wiersze_uses:
        uses = re.search(r"uses:\s*(\S+)", wiersz).group(1)
        nazwa, _, ref = uses.partition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", ref), f"akcja nieprzypięta do SHA: {uses}"
        assert re.search(r"#\s*v[\w.]+\s*$", wiersz), f"brak komentarza wersji: {wiersz.strip()}"
        assert nazwa.startswith("actions/"), f"nowa akcja zewnętrzna wymaga przemyślenia: {nazwa}"


def test_budowa_read_publikacja_write_w_osobnym_zadaniu():
    tresc = _tresc(WORKFLOW)
    assert re.search(r"^  windows:", tresc, re.MULTILINE), "brak zadania budowy"
    assert re.search(r"^  publikacja:", tresc, re.MULTILINE), "publikacja ma być osobnym zadaniem"
    budowa = tresc.split("  publikacja:", 1)[0]
    publikacja = "  publikacja:" + tresc.split("  publikacja:", 1)[1]
    assert "contents: read" in budowa, "budowa ma mieć tylko read"
    assert "contents: write" not in budowa, "budowa NIE może mieć write"
    assert "persist-credentials: false" in budowa, "checkout bez utrwalania poświadczeń"
    assert "contents: write" in publikacja, "publikacja potrzebuje write"
    assert re.search(r"needs:\s*\[?windows", publikacja), "publikacja po budowie"


def test_lockfile_z_haszami_wspolny_dla_workflow_i_skryptu():
    lock = _tresc(LOCKFILE)
    for pakiet in (
        "fastapi==",
        "pywebview==",
        "pyinstaller==",
        "pythonnet==",
        "onnxruntime==",
        "tokenizers==",
        "httpx==",
        "cryptography==",
    ):
        assert pakiet in lock, f"brak {pakiet} w lockfile"
    wpisy = re.findall(r"^([A-Za-z0-9._-]+)==", lock, re.MULTILINE)
    assert len(wpisy) > 30, "lockfile ma obejmować też zależności przechodnie"
    assert lock.count("--hash=sha256:") >= len(wpisy), "każdy wpis ma mieć hasze"
    workflow = _tresc(WORKFLOW)
    assert "--require-hashes" in workflow and "wymagania-budowy.txt" in workflow
    skrypt = _tresc(SKRYPT_BUDOWY, "utf-8")
    assert "--require-hashes" in skrypt and "wymagania-budowy.txt" in skrypt
    # workflow i skrypt instalują z TEGO SAMEGO pliku
    assert re.search(r"-r\s+\S*wymagania-budowy\.txt", workflow)
    assert re.search(r"-r\s+\S*wymagania-budowy\.txt", skrypt)


def test_workflow_jest_poprawnym_yaml():
    """Nazwy kroków z dwukropkiem bez cudzysłowów = GitHub odrzuca cały plik."""
    yaml = pytest.importorskip("yaml")
    dane = yaml.safe_load(_tresc(WORKFLOW))
    assert set(dane["jobs"]) >= {"windows", "publikacja"}
    assert dane["jobs"]["publikacja"]["needs"] == ["windows"]
    assert dane["permissions"]["contents"] == "read"
    assert dane["jobs"]["windows"]["permissions"]["contents"] == "read"
    assert dane["jobs"]["publikacja"]["permissions"]["contents"] == "write"
