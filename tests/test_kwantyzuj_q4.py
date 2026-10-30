"""Testy kwantyzacji int4 weight-only: malutki ONNX z MatMul, bez sieci i wag."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

onnx = pytest.importorskip("onnx")  # grupa eksport
pytest.importorskip("onnx_ir")  # kwantyzator NBits w ort 1.31 go wymaga

from narzedzia.kwantyzuj_q4 import kwantyzuj, main, sanity, zbuduj_katalog_wariantu
from narzedzia.pobierz_model import policz_sha256


def _malutki_onnx(sciezka: Path, reducemean_opset17: bool = False) -> Path:
    """Y = X @ W + b + Gather(E, idx) — cel kwantyzatora i tabela embeddingów.

    `reducemean_opset17=True` dokłada ReduceMean z atrybutem `axes` (semantyka
    opset 17) — przypadek LFM2.5: kwantyzator forsuje opset 21 i bez podniesienia
    do 18 graf staje się nieważny.
    """
    from onnx import TensorProto, helper, numpy_helper

    rng = np.random.default_rng(7)
    X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, "seq", 64])
    Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, "seq", 32])
    Z = helper.make_tensor_value_info("emb", TensorProto.FLOAT, [2, 32])
    w = numpy_helper.from_array(rng.normal(size=(64, 32)).astype(np.float32), "W")
    b = numpy_helper.from_array(rng.normal(size=(32,)).astype(np.float32), "b")
    e = numpy_helper.from_array(rng.normal(size=(64, 32)).astype(np.float32), "E")
    idx = numpy_helper.from_array(np.asarray([1, 3], dtype=np.int64), "idx")
    wezly = [
        helper.make_node("MatMul", ["X", "W"], ["mm"]),
        helper.make_node("Add", ["mm", "b"], ["Y"]),
        helper.make_node("Gather", ["E", "idx"], ["emb"], axis=0),
    ]
    wyjscia = [Y, Z]
    if reducemean_opset17:
        M = helper.make_tensor_value_info("mean", TensorProto.FLOAT, [1, "seq"])
        wezly.append(helper.make_node("ReduceMean", ["Y"], ["mean"], axes=[2], keepdims=0))
        wyjscia.append(M)
    graf = helper.make_graph(wezly, "g", [X], wyjscia, [w, b, e, idx])
    model = helper.make_model(graf, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 10  # onnx 1.23 pisze IR 14; onnxruntime 1.31 czyta do 13
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(sciezka))
    return sciezka


@pytest.fixture()
def zrodlo(tmp_path: Path) -> Path:
    _malutki_onnx(tmp_path / "zrodlo" / "model.onnx")
    (tmp_path / "zrodlo" / "tokenizer.json").write_text("{}", encoding="utf-8")
    (tmp_path / "zrodlo" / "config.json").write_text("{}", encoding="utf-8")
    return tmp_path / "zrodlo"


@pytest.fixture()
def feedy() -> list[dict[str, np.ndarray]]:
    rng = np.random.default_rng(11)
    return [{"X": rng.normal(size=(1, 5, 64)).astype(np.float32)}]


class TestKwantyzuj:
    def test_daje_matmul_nbits_bez_matmul(self, zrodlo: Path, tmp_path: Path):
        cel = tmp_path / "cel" / "model.onnx"
        kwantyzuj(zrodlo / "model.onnx", cel, block_size=32)
        model = onnx.load(str(cel))
        typy = {n.op_type for n in model.graph.node}
        assert "MatMulNBits" in typy
        assert "MatMul" not in typy

    def test_embedding_gather_też_kwantyzowany(self, zrodlo: Path, tmp_path: Path):
        """Gather -> GatherBlockQuantized (int4): bez tego embedding fp32 dominuje rozmiar."""
        cel = tmp_path / "cel" / "model.onnx"
        kwantyzuj(zrodlo / "model.onnx", cel, block_size=32)
        typy = {n.op_type for n in onnx.load(str(cel)).graph.node}
        assert "GatherBlockQuantized" in typy
        assert "Gather" not in typy

    def test_bez_gather_zostawia_embedding(self, zrodlo: Path, tmp_path: Path):
        cel = tmp_path / "cel" / "model.onnx"
        kwantyzuj(zrodlo / "model.onnx", cel, block_size=32, gather=False)
        typy = {n.op_type for n in onnx.load(str(cel)).graph.node}
        assert "MatMulNBits" in typy
        assert "GatherBlockQuantized" not in typy
        assert "Gather" in typy

    def test_wynik_daje_ogholiczny_wynik(self, zrodlo: Path, tmp_path: Path):
        cel = tmp_path / "cel" / "model.onnx"
        kwantyzuj(zrodlo / "model.onnx", cel, block_size=32)
        import onnxruntime as ort

        sesja = ort.InferenceSession(str(cel), providers=["CPUExecutionProvider"])
        y = sesja.run(None, {"X": np.ones((1, 3, 64), dtype=np.float32)})[0]
        assert y.shape == (1, 3, 32)
        assert np.isfinite(y).all()

    def test_blok_niedzielnik_przez_8_podnosi(self, zrodlo: Path, tmp_path: Path):
        with pytest.raises(ValueError, match="8"):
            kwantyzuj(zrodlo / "model.onnx", tmp_path / "c.onnx", block_size=50)

    def test_opset17_z_reducemean_prowadzi_do_waznego_modelu(self, tmp_path: Path):
        """Podniesienie opsetu przed kwantyzacją (Lfm25: ReduceMean-17 axes jako
        atrybut; forsowany opset 21 czyniłoby taki graf nieważnym)."""
        import onnxruntime as ort

        zrodlo17 = tmp_path / "zrodlo17"
        _malutki_onnx(zrodlo17 / "model.onnx", reducemean_opset17=True)
        (zrodlo17 / "tokenizer.json").write_text("{}", encoding="utf-8")
        (zrodlo17 / "config.json").write_text("{}", encoding="utf-8")
        cel = tmp_path / "cel"
        assert main(["--zrodlo", str(zrodlo17), "--cel", str(cel), "--block-size", "32",
                     "--pomin-sanity"]) == 0
        sesja = ort.InferenceSession(str(cel / "model.onnx"), providers=["CPUExecutionProvider"])
        y = sesja.run(None, {"X": np.ones((1, 3, 64), dtype=np.float32)})
        assert y[0].shape == (1, 3, 32)  # Y; nie odpalać = graf ważny po forsowanym opsecie 21


class TestSanity:
    def test_identyczne_modele_zero_roznic(self, zrodlo: Path, tmp_path: Path, feedy):
        raport = sanity(zrodlo / "model.onnx", zrodlo / "model.onnx", feedy)
        assert raport["max_abs_diff"] == 0.0
        assert raport["roznice_argmax"] == 0
        assert raport["tokeny"] == 5

    def test_q4_rozni_sie_ale_dziala(self, zrodlo: Path, tmp_path: Path, feedy):
        cel = tmp_path / "cel" / "model.onnx"
        kwantyzuj(zrodlo / "model.onnx", cel, block_size=32)
        raport = sanity(cel, zrodlo / "model.onnx", feedy)
        assert raport["tokeny"] == 5
        assert np.isfinite(raport["max_abs_diff"])

    def test_nan_podnosi(self, zrodlo: Path):
        zle = [{"X": np.full((1, 5, 64), np.nan, dtype=np.float32)}]
        with pytest.raises(SystemExit, match="NaN"):
            sanity(zrodlo / "model.onnx", zrodlo / "model.onnx", zle)


class TestZbudujKatalogWariantu:
    def test_manifest_zgodny_z_weryfikacja_detektora(self, zrodlo: Path, tmp_path: Path):
        cel = tmp_path / "cel"
        cel.mkdir()
        kwantyzuj(zrodlo / "model.onnx", cel / "model.onnx", block_size=32)
        zbuduj_katalog_wariantu(zrodlo, cel, block_size=32, symetryczny=True)
        manifest = json.loads((cel / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["kwantyzacja"]["bity"] == 4
        assert manifest["kwantyzacja"]["block_size"] == 32
        assert manifest["kwantyzacja"]["symetryczny"] is True
        assert manifest["kwantyzacja"]["gather"] is True
        assert manifest["pliki"]["model.onnx"] == hashlib.sha256(
            (cel / "model.onnx").read_bytes()
        ).hexdigest()
        # format pliki -> SHA-256 akceptowany przez OnnxDetektor (to samo co pobierz_model)
        from niewidka.detektory import OnnxDetektor

        OnnxDetektor._sprawdz_manifest(cel)

    def test_tokenizer_i_config_skopiowane(self, zrodlo: Path, tmp_path: Path):
        cel = tmp_path / "cel"
        cel.mkdir()
        (cel / "model.onnx").write_bytes(b"wagi")
        zbuduj_katalog_wariantu(zrodlo, cel, block_size=128, symetryczny=False)
        assert (cel / "tokenizer.json").read_text(encoding="utf-8") == "{}"
        assert (cel / "config.json").read_text(encoding="utf-8") == "{}"
        manifest = json.loads((cel / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["kwantyzacja"]["block_size"] == 128
        assert manifest["kwantyzacja"]["symetryczny"] is False

    def test_pochodzenie_z_manifestu_zrodla(self, zrodlo: Path, tmp_path: Path):
        (zrodlo / "manifest.json").write_text(
            json.dumps({"repo": "r/model", "rewizja": "main", "pliki": {}}), encoding="utf-8"
        )
        cel = tmp_path / "cel"
        cel.mkdir()
        (cel / "model.onnx").write_bytes(b"wagi")
        zbuduj_katalog_wariantu(zrodlo, cel, block_size=32, symetryczny=True)
        manifest = json.loads((cel / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["repo"] == "r/model"
        assert manifest["rewizja"] == "main"


class TestMain:
    def test_pelen_przeplyw(self, zrodlo: Path, tmp_path: Path):
        cel = tmp_path / "cel"
        kod = main(
            ["--zrodlo", str(zrodlo), "--cel", str(cel), "--block-size", "32", "--pomin-sanity"]
        )
        assert kod == 0
        assert (cel / "model.onnx").is_file()
        assert (cel / "manifest.json").is_file()
        assert (cel / "tokenizer.json").is_file()
        assert policz_sha256(cel / "model.onnx") == json.loads(
            (cel / "manifest.json").read_text(encoding="utf-8")
        )["pliki"]["model.onnx"]

    def test_odmowa_nadpisania(self, zrodlo: Path, tmp_path: Path):
        cel = tmp_path / "cel"
        cel.mkdir()
        (cel / "model.onnx").write_bytes(b"stary")
        with pytest.raises(SystemExit, match="nadpisz"):
            main(["--zrodlo", str(zrodlo), "--cel", str(cel), "--block-size", "32"])
        assert (cel / "model.onnx").read_bytes() == b"stary"

    def test_nadpisz_zezwala(self, zrodlo: Path, tmp_path: Path):
        cel = tmp_path / "cel"
        cel.mkdir()
        (cel / "model.onnx").write_bytes(b"stary")
        main(
            ["--zrodlo", str(zrodlo), "--cel", str(cel), "--block-size", "32",
             "--nadpisz", "--pomin-sanity"]
        )
        assert (cel / "model.onnx").read_bytes() != b"stary"

    def test_brak_zrodla_podnosi(self, tmp_path: Path):
        with pytest.raises(SystemExit, match="model.onnx"):
            main(["--zrodlo", str(tmp_path / "pusty"), "--cel", str(tmp_path / "cel")])
