"""Kwantyzacja int4 weight-only ONNX: onnxruntime MatMulNBits, parametry z CLI.

Pakiety modeli w klasie Q4 (mniejsze pobieranie po instalacji, decyzja właściciela
2026-10-28). Wejściem jest zawsze ONNX float32 (`bardsai-fp32/` z repo HF albo
`lfm25/fp32/` z eksportu) — INT8 dynamiczny ma już wagi całkowite, nie jest
sensownym źródłem. Wynik: katalog z model.onnx + tokenizer.json + config.json +
manifest.json (SHA-256 w formacie `narzedzia.pobierz_model`, więc OnnxDetektor
weryfikuje go jak zwykle). Sanity porównuje logits z źródłem fp32 i pada przy
NaN/złym kształcie; granicę jakości stanowi pomiar na korpusie.

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
    """Grafy < opset 18 stają się nieważne po forsowanej przez kwantyzator
    zmianie opset_import na 21 (ReduceMean-17 ma `axes` jako atrybut, ReduceMean-18+
    jako wejście); konwersja przed kwantyzacją. LFM2.5 był eksportowany na opset 17.
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
    zwraca czas w s.

    `block_size` musi dzielić się przez 8 (ograniczenie jądra MatMulNBits);
    `symetryczny=True` — standardowy wybór weight-only (jak dawny
    MatMul4BitsQuantizer), odnotowany w manifeście. `gather=True` kwantyzuje
    też tabele embeddingów — bez tego dominujący rozmiar (u bardsai 732 MB
    fp32) zostawałby nietknięty i Q4 byłoby większe od INT8.
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
    """Logits wariantu vs źródło fp32 na stałych przykładach; NaN/zły kształt = STOP."""
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
    """Tokenizer + config skopiowane ze źródła; manifest SHA-256 (format pobierz_model)."""
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
    parser = argparse.ArgumentParser(description="Kwantyzacja int4 weight-only ONNX (K7a)")
    parser.add_argument(
        "--zrodlo", type=Path, required=True,
        help="katalog z model.onnx (fp32) + tokenizer.json + config.json",
    )
    parser.add_argument("--cel", type=Path, required=True, help="katalog wynikowy")
    parser.add_argument(
        "--block-size", type=int, default=128, choices=(32, 128),
        help="rozmiar bloku kwantyzacji (K7a mierzy 32 i 128)",
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
