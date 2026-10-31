"""int4 weight-only ONNX quantisation: onnxruntime MatMulNBits, parameters from the CLI.

Model packages in the Q4 class (smaller download after installation, decision of
2026-10-28). The input is always a float32 ONNX (`bardsai-fp32/` from the HF repo or
`lfm25/fp32/` from the export) - dynamic INT8 already has integer weights and is not
a sensible source. Output: a directory with model.onnx + tokenizer.json + config.json +
manifest.json (SHA-256 in the `narzedzia.pobierz_model` format, so OnnxDetektor
verifies it as usual). The sanity check compares logits with the fp32 source and fails on
NaN/a wrong shape; the quality boundary is the measurement on the corpus.

    .venv/bin/python -m narzedzia.kwantyzuj_q4 \
        --zrodlo ~/models/niewidka/bardsai-fp32 \
        --cel ~/models/niewidka/bardsai-q4-bl32 --block-size 32
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from narzedzia.pobierz_model import policz_sha256

PLIKI_WARIANTU = ("model.onnx", "tokenizer.json", "config.json")


def _podnies_opset_do_18(model):  # type: ignore[no-untyped-def]
    """Graphs below opset 18 become invalid after the quantiser forces
    opset_import to 21 (ReduceMean-17 has `axes` as an attribute, ReduceMean-18+
    as an input); convert before quantisation. LFM2.5 was exported at opset 17.
    """
    opset = max(
        (o.version for o in model.opset_import if o.domain in ("", "ai.onnx")), default=0
    )
    if opset >= 18:
        return model
    from onnx import version_converter

    return version_converter.convert_version(model, 18)


def kwantyzuj(
    zrodlo_onnx: Path,
    cel_onnx: Path,
    block_size: int,
    symetryczny: bool = True,
    gather: bool = True,
) -> float:
    """int4 weight-only (MatMul -> MatMulNBits, Gather -> GatherBlockQuantized);
    returns the time in s.

    `block_size` must be divisible by 8 (a MatMulNBits kernel constraint);
    `symetryczny=True` is the standard weight-only choice (like the former
    MatMul4BitsQuantizer), recorded in the manifest. `gather=True` quantises
    the embedding tables too - without it the dominant size (732 MB of fp32
    for bardsai) would stay untouched and Q4 would be larger than INT8.
    """
    if block_size % 8 != 0:
        raise ValueError(f"block_size musi dzielić się przez 8: {block_size}")
    import onnx
    from onnxruntime.quantization.matmul_nbits_quantizer import (
        DefaultWeightOnlyQuantConfig,
        MatMulNBitsQuantizer,
    )

    model = _podnies_opset_do_18(onnx.load(str(zrodlo_onnx)))
    opy = ("MatMul", "Gather") if gather else ("MatMul",)
    konfig = DefaultWeightOnlyQuantConfig(
        block_size=block_size, is_symmetric=symetryczny, op_types_to_quantize=opy
    )
    kwantyzator = MatMulNBitsQuantizer(model=model, bits=4, algo_config=konfig)
    start = time.monotonic()
    kwantyzator.process()
    cel_onnx.parent.mkdir(parents=True, exist_ok=True)
    kwantyzator.model.save_model_to_file(str(cel_onnx), use_external_data_format=False)
    return time.monotonic() - start


def sanity(wariant_onnx: Path, referencja_onnx: Path, feedy: list[dict[str, np.ndarray]]) -> dict[str, float | int]:
    """Logits of the variant vs the fp32 source on fixed examples; NaN/wrong shape = STOP."""
    import onnxruntime as ort

    sesja_q4 = ort.InferenceSession(str(wariant_onnx), providers=["CPUExecutionProvider"])
    sesja_fp32 = ort.InferenceSession(str(referencja_onnx), providers=["CPUExecutionProvider"])
    max_diff, roznice_argmax, tokeny = 0.0, 0, 0
    for feed in feedy:
        q4 = np.asarray(sesja_q4.run(None, feed)[0][0])
        fp32 = np.asarray(sesja_fp32.run(None, feed)[0][0])
        if q4.shape != fp32.shape:
            raise SystemExit(f"sanity: zły kształt wyjścia {q4.shape} vs {fp32.shape} — NIE publikować")
        if not np.isfinite(q4).all():
            raise SystemExit("sanity: NaN/Inf w wyjściu — NIE publikować")
        max_diff = max(max_diff, float(np.abs(q4 - fp32).max()))
        roznice_argmax += int((q4.argmax(axis=-1) != fp32.argmax(axis=-1)).sum())
        tokeny += q4.shape[0]
    return {"max_abs_diff": max_diff, "roznice_argmax": roznice_argmax, "tokeny": tokeny}


def zbuduj_katalog_wariantu(
    zrodlo: Path, cel: Path, block_size: int, symetryczny: bool, gather: bool = True
) -> None:
    """Tokenizer + config copied from the source; SHA-256 manifest (pobierz_model format)."""
    for nazwa in PLIKI_WARIANTU[1:]:
        shutil.copyfile(zrodlo / nazwa, cel / nazwa)
    pochodzenie: dict[str, str] = {}
    manifest_zrodla = zrodlo / "manifest.json"
    if manifest_zrodla.is_file():
        meta = json.loads(manifest_zrodla.read_text(encoding="utf-8"))
        pochodzenie = {k: v for k in ("repo", "rewizja") if (v := meta.get(k))}
    manifest = {
        **pochodzenie,
        "pliki": {nazwa: policz_sha256(cel / nazwa) for nazwa in PLIKI_WARIANTU},
        "kwantyzacja": {
            "bity": 4,
            "block_size": block_size,
            "symetryczny": symetryczny,
            "gather": gather,
            "narzedzie": "onnxruntime MatMulNBitsQuantizer (weight-only)",
        },
    }
    (cel / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kwantyzacja int4 weight-only ONNX")
    parser.add_argument(
        "--zrodlo", type=Path, required=True,
        help="katalog z model.onnx (fp32) + tokenizer.json + config.json",
    )
    parser.add_argument("--cel", type=Path, required=True, help="katalog wynikowy")
    parser.add_argument(
        "--block-size", type=int, default=128, choices=(32, 128),
        help="rozmiar bloku kwantyzacji (zmierzone: 32 i 128)",
    )
    parser.add_argument(
        "--asymetryczny", action="store_true",
        help="kwantyzacja asymetryczna (domyślnie symetryczna)",
    )
    parser.add_argument("--nadpisz", action="store_true", help="zezwól na nadpisanie istniejącego celu")
    parser.add_argument(
        "--bez-gather", action="store_true",
        help="NIE kwantyzuj embeddingów (Gather); zostają fp32 — duży plik",
    )
    parser.add_argument("--pomin-sanity", action="store_true", help="pomiń porównanie logits ze źródłem")
    argumenty = parser.parse_args(argv)

    zrodlo_onnx = argumenty.zrodlo / "model.onnx"
    if not zrodlo_onnx.is_file():
        raise SystemExit(f"brak {zrodlo_onnx}")
    cel = argumenty.cel
    if (cel / "model.onnx").is_file() and not argumenty.nadpisz:
        raise SystemExit(f"cel istnieje: {cel / 'model.onnx'} (--nadpisz, by nadpisać)")
    cel.mkdir(parents=True, exist_ok=True)

    def mb(plik: Path) -> float:
        return plik.stat().st_size / (1 << 20)

    symetryczny = not argumenty.asymetryczny
    gather = not argumenty.bez_gather
    print(
        f"kwantyzacja int4 (block {argumenty.block_size}, "
        f"{'asymetryczna' if not symetryczny else 'symetryczna'}, "
        f"{'z' if gather else 'bez'} gather): "
        f"{zrodlo_onnx} ({mb(zrodlo_onnx):.0f} MB) -> {cel}"
    )
    czas = kwantyzuj(zrodlo_onnx, cel / "model.onnx", argumenty.block_size, symetryczny, gather)
    print(f"  czas: {czas:.1f} s, wynik: {mb(cel / 'model.onnx'):.1f} MB")
    if not argumenty.pomin_sanity:
        from narzedzia.eksport_lfm25 import _feedy

        raport = sanity(cel / "model.onnx", zrodlo_onnx, _feedy(argumenty.zrodlo))
        print(f"  sanity vs fp32: {raport}")
    zbuduj_katalog_wariantu(argumenty.zrodlo, cel, argumenty.block_size, symetryczny, gather)
    print(f"  manifest: {cel / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
