"""Jednorazowy eksport ONNX z LFM2.5-Encoder-350M-PII-Detector (K2b).

Repo HF nie ma gotowego ONNX, a model wymaga trust_remote_code — kod przejrzany
przed użyciem (docs/KOD-LFM25.md, werdykt: bezpieczny). Ten skrypt to JEDYNE
miejsce, gdzie kod z repo HF jest wykonywany; runtime Niewidki ładuje wyłącznie
wynikowe .onnx przez onnxruntime (grupa zależności `eksport`: torch/transformers/onnx
nie są potrzebne w runtime).

Wynik (w NIEWIDKA_MODELE_KATALOG):
    lfm25/fp32/model.onnx   — eksport float32
    lfm25/int8/model.onnx   — kwantyzacja dynamiczna INT8 z fp32
    oba: tokenizer.json + config.json + manifest.json (SHA-256, format jak w
    narzedzia/pobierz_model.py, więc OnnxDetektor weryfikuje jak zwykle)

    .venv/bin/python --group eksport -m narzedzia.eksport_lfm25 \
        --katalog ~/models/niewidka
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import numpy as np

REPO_LFM25 = "LiquidAI/LFM2.5-Encoder-350M-PII-Detector"
REWIZJA = "main"

PRZYKLADY = [
    "Wczoraj Jan Kowalski podpisał umowę z Anną Zielińską.",
    "PESEL 44051401359, NIP 1234563218, kontakt: jan@example.com.",
    "Sprawę prowadzi mgr Katarzyna Wiśniewska-Kowalczyk z działu HR.",
]


def policz_sha256(plik: Path) -> str:
    skrot = hashlib.sha256()
    with plik.open("rb") as f:
        for kawalek in iter(lambda: f.read(1 << 20), b""):
            skrot.update(kawalek)
    return skrot.hexdigest()


def sprawdz_manifest_zrodla(zrodlo: Path) -> None:
    """Pliki niezmienione od pobrania (druga warstwa po przeglądzie kodu)."""
    manifest = json.loads((zrodlo / "manifest.json").read_text(encoding="utf-8"))
    for nazwa, sumka in manifest.get("pliki", {}).items():
        plik = zrodlo / nazwa
        if not plik.is_file() or policz_sha256(plik) != sumka:
            raise SystemExit(f"manifest źródła: rozbieżny SHA-256 dla {nazwa} — pobierz ponownie")


def załaduj_model(zrodlo: Path):  # type: ignore[no-untyped-def]
    import torch
    from transformers import AutoModelForTokenClassification

    model = AutoModelForTokenClassification.from_pretrained(
        zrodlo, trust_remote_code=True, dtype=torch.float32
    )
    model.eval()
    return model


def eksportuj_fp32(model, cel: Path) -> float:
    """torch.onnx.export (tracing); zwraca czas w s."""
    import torch

    class WrapperLogitow(torch.nn.Module):
        """forward(input_ids, attention_mask) -> logits, bez słownika wyjścia."""

        def __init__(self, model):  # type: ignore[no-untyped-def]
            super().__init__()
            self.model = model

        def forward(self, input_ids, attention_mask):  # type: ignore[no-untyped-def]
            return self.model(
                input_ids=input_ids, attention_mask=attention_mask, use_cache=False
            ).logits

    wejscie = (
        torch.tensor([[1, 5, 6, 7, 2]], dtype=torch.int64),
        torch.ones((1, 5), dtype=torch.int64),
    )
    start = time.monotonic()
    cel.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        WrapperLogitow(model),
        wejscie,
        str(cel),
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "logits": {0: "batch", 1: "seq"},
        },
        opset_version=17,
        dynamo=False,
    )
    return time.monotonic() - start


def _feedy(zrodlo: Path) -> list[dict[str, np.ndarray]]:
    """Stałe przykłady do sanity (tokenizers jak w runtime)."""
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(zrodlo / "tokenizer.json"))
    feedy = []
    for tekst in PRZYKLADY:
        enc = tok.encode(tekst, add_special_tokens=True)
        feedy.append(
            {
                "input_ids": np.asarray([enc.ids], dtype=np.int64),
                "attention_mask": np.ones((1, len(enc.ids)), dtype=np.int64),
            }
        )
    return feedy


def sanity(onnx_sciezka: Path, feedy: list[dict[str, np.ndarray]], referencja: list[np.ndarray]) -> dict[str, float]:
    import onnxruntime as ort

    sesja = ort.InferenceSession(str(onnx_sciezka), providers=["CPUExecutionProvider"])
    max_diff, roznice_argmax, tokeny = 0.0, 0, 0
    for feed, wzor in zip(feedy, referencja):
        logits = sesja.run(None, feed)[0][0]
        max_diff = max(max_diff, float(np.abs(logits - wzor).max()))
        roznice_argmax += int((logits.argmax(axis=-1) != wzor.argmax(axis=-1)).sum())
        tokeny += logits.shape[0]
    return {"max_abs_diff": max_diff, "roznice_argmax": roznice_argmax, "tokeny": tokeny}


def kwantyzuj(zrodlo_onnx: Path, cel: Path) -> float:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    cel.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    quantize_dynamic(str(zrodlo_onnx), str(cel), weight_type=QuantType.QInt8)
    return time.monotonic() - start


def zbuduj_wariant(zrodlo: Path, wariant: Path, plik_onnx: Path) -> None:
    """Tokenizer + config + manifest SHA-256 (format zgodny z pobierz_model)."""
    wariant.mkdir(parents=True, exist_ok=True)
    for nazwa in ("tokenizer.json", "config.json"):
        shutil.copyfile(zrodlo / nazwa, wariant / nazwa)
    manifest = {
        "repo": REPO_LFM25,
        "rewizja": REWIZJA,
        "pliki": {
            nazwa: policz_sha256(wariant / nazwa) for nazwa in ("model.onnx", "tokenizer.json", "config.json")
        },
    }
    (wariant / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    mb = plik_onnx.stat().st_size / (1 << 20)
    print(f"  {wariant.name}/model.onnx: {mb:.1f} MB")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jednorazowy eksport ONNX LFM2.5 (K2b)")
    parser.add_argument(
        "--katalog",
        type=Path,
        default=Path(os.environ.get("NIEWIDKA_MODELE_KATALOG", "")) or None,
    )
    parser.add_argument("--pomin-int8", action="store_true", help="tylko fp32")
    argumenty = parser.parse_args(argv)
    if argumenty.katalog is None:
        parser.error("brak katalogu: --katalog albo NIEWIDKA_MODELE_KATALOG")

    zrodlo = argumenty.katalog / "lfm25"
    sprawdz_manifest_zrodla(zrodlo)
    print(f"manifest źródła OK: {zrodlo}")

    import torch

    start = time.monotonic()
    model = załaduj_model(zrodlo)
    print(f"model załadowany (torch {torch.__version__}): {time.monotonic() - start:.1f} s")

    feedy = _feedy(zrodlo)
    with torch.no_grad():
        referencja = [
            model(input_ids=torch.from_numpy(f["input_ids"]),
                  attention_mask=torch.from_numpy(f["attention_mask"]),
                  use_cache=False).logits[0].numpy()
            for f in feedy
        ]

    fp32 = zrodlo / "fp32" / "model.onnx"
    print(f"eksport fp32 -> {fp32}")
    czas = eksportuj_fp32(model, fp32)
    print(f"  eksport: {czas:.1f} s")
    raport = sanity(fp32, feedy, referencja)
    print(f"  sanity fp32: {raport}")
    if raport["roznice_argmax"] or raport["max_abs_diff"] > 1e-3:
        raise SystemExit("eksport fp32 niezgodny z torch — NIE publikować")
    zbuduj_wariant(zrodlo, zrodlo / "fp32", fp32)

    if argumenty.pomin_int8:
        return 0
    int8 = zrodlo / "int8" / "model.onnx"
    print(f"kwantyzacja INT8 -> {int8}")
    czas = kwantyzuj(fp32, int8)
    print(f"  kwantyzacja: {czas:.1f} s")
    raport = sanity(int8, feedy, referencja)
    print(f"  sanity int8: {raport}")
    zbuduj_wariant(zrodlo, zrodlo / "int8", int8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
