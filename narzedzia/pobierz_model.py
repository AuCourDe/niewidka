"""Pobranie wag modelu z HuggingFace przez httpx + manifest SHA-256.

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
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class ModelSpec:
    """Repo HF i zestaw plików jednego modelu (nazwa_lokalna -> ścieżka w repo)."""

    repo: str
    rewizja: str
    pliki: dict[str, str]
    podkatalog: str = ""  # "" = bezpośrednio w NIEWIDKA_MODELE_KATALOG


# bardsai (poziom 1): gotowy ONNX INT8 z repo; `model.onnx` = model_quantized.
_BARDSAI = ModelSpec(
    repo="bardsai/eu-pii-anonimization-multilang",
    rewizja="main",
    pliki={
        "model.onnx": "onnx/model_quantized.onnx",
        "tokenizer.json": "tokenizer.json",
        "config.json": "config.json",
        "tokenizer_config.json": "tokenizer_config.json",
    },
)

# bardsai fp32: nieskwantyzowany ONNX z repo — wejście kwantyzacji int4
# (narzedzia/kwantyzuj_q4.py); model_quantized.onnx ma już wagi całkowite, więc
# nie jest sensownym źródłem dla Q4.
_BARDSAI_FP32 = ModelSpec(
    repo="bardsai/eu-pii-anonimization-multilang",
    rewizja="main",
    pliki={
        "model.onnx": "onnx/model.onnx",
        "tokenizer.json": "tokenizer.json",
        "config.json": "config.json",
        "tokenizer_config.json": "tokenizer_config.json",
    },
    podkatalog="bardsai-fp32",
)

# LFM2.5 (poziom 2): brak ONNX w repo — pobieramy PEŁNE źródła (wagi + kod
# custom przeglądany przed użyciem), eksport ONNX robi
# narzedzia/eksport_lfm25.py do podkatalogów fp32/ i int8/.
_LFM25 = ModelSpec(
    repo="LiquidAI/LFM2.5-Encoder-350M-PII-Detector",
    rewizja="main",
    pliki={
        "model.safetensors": "model.safetensors",
        "config.json": "config.json",
        "tokenizer.json": "tokenizer.json",
        "tokenizer_config.json": "tokenizer_config.json",
        "label_schema.json": "label_schema.json",
        "modeling_phase2_tc.py": "modeling_phase2_tc.py",
        "context_cued.py": "context_cued.py",
        "pii_hybrid_decode.py": "pii_hybrid_decode.py",
        "README.md": "README.md",
        "LICENSE": "LICENSE",
    },
    podkatalog="lfm25",
)

MODELE: dict[str, ModelSpec] = {
    "bardsai": _BARDSAI,
    "bardsai-fp32": _BARDSAI_FP32,
    "lfm25": _LFM25,
}

# Nazwy w katalogu docelowym (kompatybilność: główne pobranie poziomu 1).
REPO = _BARDSAI.repo
REWIZJA = _BARDSAI.rewizja
PLIKI: dict[str, str] = _BARDSAI.pliki


def spec_modelu(nazwa: str) -> ModelSpec:
    try:
        return MODELE[nazwa]
    except KeyError:
        raise ValueError(f"nieznany model: {nazwa} (dostępne: {', '.join(MODELE)})") from None


def katalog_docelowy(baza: Path, spec: ModelSpec) -> Path:
    return baza / spec.podkatalog if spec.podkatalog else baza


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
    parser.add_argument("--model", default="bardsai", choices=sorted(MODELE))
    parser.add_argument("--repo", default=None, help="nadpisanie repo (domyślnie wg --model)")
    parser.add_argument(
        "--katalog",
        type=Path,
        default=Path(z_env) if (z_env := os.environ.get("NIEWIDKA_MODELE_KATALOG")) else None,
    )
    argumenty = parser.parse_args(argv)
    if argumenty.katalog is None:
        parser.error("brak katalogu: --katalog albo NIEWIDKA_MODELE_KATALOG")
    spec = spec_modelu(argumenty.model)
    repo = argumenty.repo or spec.repo
    katalog = katalog_docelowy(argumenty.katalog, spec)
    katalog.mkdir(parents=True, exist_ok=True)

    stary = {}
    manifest_plik = katalog / "manifest.json"
    if manifest_plik.is_file():
        stary = json.loads(manifest_plik.read_text(encoding="utf-8")).get("pliki", {})

    with httpx.Client(follow_redirects=True, timeout=600) as klient:
        for nazwa, zrodlo in spec.pliki.items():
            suma_stara = stary.get(nazwa)
            if suma_stara and sprobij_pominac(katalog / nazwa, suma_stara):
                print(f"pomijam {nazwa} (zgodny z manifestem)")
                continue
            url = url_pliku(repo, zrodlo)
            print(f"pobieram {url} -> {katalog / nazwa}")
            pobierz_plik(klient, url, katalog / nazwa)

    zapisz_manifest(katalog, repo, tuple(spec.pliki), spec.rewizja)
    print(f"manifest: {manifest_plik}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
