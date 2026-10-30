"""Testy pobierania modeli: httpx, manifest SHA-256 — bez sieci (MockTransport)."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from narzedzia.pobierz_model import (
    katalog_docelowy,
    pobierz_plik,
    spec_modelu,
    sprobij_pominac,
    url_pliku,
    zapisz_manifest,
)


def _klient(zawartosci: dict[str, bytes]) -> httpx.Client:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=zawartosci[req.url.path])
    )
    return httpx.Client(transport=transport)


class TestUrlPliku:
    def test_url_resolve_main(self):
        assert url_pliku("repo/model", "onnx/model_quantized.onnx") == (
            "https://huggingface.co/repo/model/resolve/main/onnx/model_quantized.onnx"
        )


class TestPobierzPlik:
    def test_zapisuje_tresc(self, tmp_path):
        cel = tmp_path / "model.onnx"
        pobierz_plik(_klient({"/m.onnx": b"dane-modelu"}), "https://x.test/m.onnx", cel)
        assert cel.read_bytes() == b"dane-modelu"

    def test_bledny_status_podnosi(self, tmp_path):
        transport = httpx.MockTransport(lambda req: httpx.Response(404))
        with pytest.raises(httpx.HTTPStatusError):
            pobierz_plik(httpx.Client(transport=transport), "https://x.test/brak", tmp_path / "x")
        assert not (tmp_path / "x").exists()  # nic nie zostaje po nieudanym pobraniu


class TestSprobijPominac:
    def test_brak_pliku_nie_pomija(self, tmp_path):
        assert not sprobij_pominac(tmp_path / "m.onnx", "abc")

    def test_zgodny_sha_pomija(self, tmp_path):
        plik = tmp_path / "m.onnx"
        plik.write_bytes(b"tresc")
        sha = hashlib.sha256(b"tresc").hexdigest()
        assert sprobij_pominac(plik, sha)

    def test_inny_sha_nie_pomija(self, tmp_path):
        plik = tmp_path / "m.onnx"
        plik.write_bytes(b"tresc")
        assert not sprobij_pominac(plik, hashlib.sha256(b"inne").hexdigest())


class TestZapiszManifest:
    def test_manifest_z_sha_i_repo(self, tmp_path):
        (tmp_path / "model.onnx").write_bytes(b"a")
        (tmp_path / "tokenizer.json").write_bytes(b"b")
        zapisz_manifest(
            tmp_path,
            repo="r/model",
            pliki=("model.onnx", "tokenizer.json"),
            rewizja="main",
        )
        manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["repo"] == "r/model"
        assert manifest["rewizja"] == "main"
        assert manifest["pliki"] == {
            "model.onnx": hashlib.sha256(b"a").hexdigest(),
            "tokenizer.json": hashlib.sha256(b"b").hexdigest(),
        }

    def test_manifest_nadpisywany(self, tmp_path):
        zapisz_manifest(tmp_path, repo="r", pliki=(), rewizja="main")
        zapisz_manifest(tmp_path, repo="r2", pliki=(), rewizja="dev")
        manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["repo"] == "r2"


class TestSpecModelu:
    def test_bardsai_domyslny_katalog(self):
        spec = spec_modelu("bardsai")
        assert spec.repo == "bardsai/eu-pii-anonimization-multilang"
        assert spec.podkatalog == ""
        assert set(spec.pliki) == {
            "model.onnx",
            "tokenizer.json",
            "config.json",
            "tokenizer_config.json",
        }

    def test_bardsai_fp32_podkatalog(self):
        """Nieskwantyzowany ONNX z repo — wejście kwantyzacji int4."""
        spec = spec_modelu("bardsai-fp32")
        assert spec.repo == "bardsai/eu-pii-anonimization-multilang"
        assert spec.podkatalog == "bardsai-fp32"
        assert spec.pliki["model.onnx"] == "onnx/model.onnx"

    def test_lfm25_repo_i_pelny_zestaw_zrodlowy(self):
        spec = spec_modelu("lfm25")
        assert spec.repo == "LiquidAI/LFM2.5-Encoder-350M-PII-Detector"
        assert spec.podkatalog == "lfm25"
        # wagi + konfiguracja + KOD CUSTOM
        assert set(spec.pliki) == {
            "model.safetensors",
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "label_schema.json",
            "modeling_phase2_tc.py",
            "context_cued.py",
            "pii_hybrid_decode.py",
            "README.md",
            "LICENSE",
        }

    def test_nieznany_model_podnosi(self):
        with pytest.raises(ValueError):
            spec_modelu("cudzy-model")


class TestKatalogDocelowy:
    def test_bardsai_bez_podkatalogu(self, tmp_path):
        assert katalog_docelowy(tmp_path, spec_modelu("bardsai")) == tmp_path

    def test_lfm25_w_podkatalogu(self, tmp_path):
        assert katalog_docelowy(tmp_path, spec_modelu("lfm25")) == tmp_path / "lfm25"


class TestBrakKatalogu:
    def test_bez_katalogu_i_zmiennej_blad_zamiast_pobierania_do_biezacego(self, tmp_path, monkeypatch):
        from narzedzia import pobierz_model

        monkeypatch.delenv("NIEWIDKA_MODELE_KATALOG", raising=False)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as wyjscie:
            pobierz_model.main([])
        assert wyjscie.value.code == 2
        assert list(tmp_path.iterdir()) == []

    def test_pusta_zmienna_to_brak_katalogu(self, monkeypatch):
        from narzedzia import pobierz_model

        monkeypatch.setenv("NIEWIDKA_MODELE_KATALOG", "")
        with pytest.raises(SystemExit):
            pobierz_model.main([])
