"""Pobranie wag modelu z HuggingFace przez httpx + manifest SHA-256 (K2, LLD §4).

Środowisko B: wyłącznie httpx, żadnego huggingface_hub; uruchamiane ręcznie,
nigdy w automated build. Wagi lądują w katalogu z `NIEWIDKA_MODELE_KATALOG`
(na tej maszynie: ~/models/niewidka) — nigdy w repo.

    .venv/bin/python -m narzedzia.pobierz_model --katalog ~/models/niewidka
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import httpx

REPO = "bardsai/eu-pii-anonimization-multilang"
REWIZJA = "main"
# Nazwy w katalogu docelowym; `model.onnx` = ONNX INT8 (model_quantized) z repo.
PLIKI: dict[str, str] = {
    "model.onnx": "onnx/model_quantized.onnx",
    "tokenizer.json": "tokenizer.json",
    "config.json": "config.json",
    "tokenizer_config.json": "tokenizer_config.json",
}


def url_pliku(repo: str, plik: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{plik}"


def policz_sha256(plik: Path) -> str:
    skrot = hashlib.sha256()
    with plik.open("rb") as f:
        for kawalek in iter(lambda: f.read(1 << 20), b""):
            skrot.update(kawalek)
    return skrot.hexdigest()


def pobierz_plik(klient: httpx.Client, url: str, cel: Path) -> None:
    with klient.stream("GET", url, follow_redirects=True, timeout=600) as odpowiedz:
        odpowiedz.raise_for_status()
        with tempfile.NamedTemporaryFile(dir=cel.parent, delete=False) as tmp:
            sciezka = Path(tmp.name)
            for kawalek in odpowiedz.iter_bytes():
                tmp.write(kawalek)
    sciezka.replace(cel)  # atomowe dopiero po pełnym pobraniu


def sprobij_pominac(plik: Path, suma_z_manifestu: str) -> bool:
    """Plik obecny i zgodny z manifestem — pobieranie pomijalne (wznowienie)."""
    return plik.is_file() and policz_sha256(plik) == suma_z_manifestu


def zapisz_manifest(katalog: Path, repo: str, pliki: tuple[str, ...], rewizja: str) -> None:
    manifest = {
        "repo": repo,
        "rewizja": rewizja,
        "pliki": {nazwa: policz_sha256(katalog / nazwa) for nazwa in pliki},
    }
    (katalog / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pobranie wag modelu Niewidki (httpx)")
    parser.add_argument("--repo", default=REPO)
    parser.add_argument(
        "--katalog",
        type=Path,
        default=Path(os.environ.get("NIEWIDKA_MODELE_KATALOG", "")) or None,
    )
    argumenty = parser.parse_args(argv)
    if argumenty.katalog is None:
        parser.error("brak katalogu: --katalog albo NIEWIDKA_MODELE_KATALOG")
    katalog = argumenty.katalog
    katalog.mkdir(parents=True, exist_ok=True)

    stary = {}
    manifest_plik = katalog / "manifest.json"
    if manifest_plik.is_file():
        stary = json.loads(manifest_plik.read_text(encoding="utf-8")).get("pliki", {})

    with httpx.Client(follow_redirects=True, timeout=600) as klient:
        for nazwa, zrodlo in PLIKI.items():
            suma_stara = stary.get(nazwa)
            if suma_stara and sprobij_pominac(katalog / nazwa, suma_stara):
                print(f"pomijam {nazwa} (zgodny z manifestem)")
                continue
            url = url_pliku(argumenty.repo, zrodlo)
            print(f"pobieram {url} -> {katalog / nazwa}")
            pobierz_plik(klient, url, katalog / nazwa)

    zapisz_manifest(katalog, argumenty.repo, tuple(PLIKI), REWIZJA)
    print(f"manifest: {manifest_plik}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
