"""Testy kalibracji R95 (K2, LLD §11) i odczytu w jakosc (struktura per poziom, K2d)."""

from __future__ import annotations

import json

import pytest

from narzedzia.kalibracja import r95_gorna, zapisz_poziom
from niewidka.jakosc import r95_poziomy, r95_z_kalibracji


class TestR95Gorna:
    def test_wzor_cloppera_pearsona(self):
        from scipy.stats import beta

        assert r95_gorna(0, 5) == pytest.approx(float(beta.ppf(0.95, 1, 5)))
        assert r95_gorna(1, 23) == pytest.approx(float(beta.ppf(0.95, 2, 22)))

    def test_wiecej_probek_ciaśniej(self):
        assert r95_gorna(0, 100) < r95_gorna(0, 5)

    def test_wszystkie_uciekly_to_jeden(self):
        assert r95_gorna(5, 5) == 1.0

    def test_zero_probek_to_jeden(self):
        assert r95_gorna(0, 0) == 1.0


class TestR95ZKalibracji:
    def test_odczyt_z_pliku(self, tmp_path):
        (tmp_path / "r95.json").write_text(
            json.dumps(
                {
                    "poziomy": {
                        "1": {"detektor": "poziom1", "r95": {"OSOBA": 0.21, "PESEL": 0.45}},
                        "2": {"detektor": "poziom2", "prog_osoba": 0.2, "r95": {"OSOBA": 0.15}},
                    }
                }
            ),
            encoding="utf-8",
        )
        assert r95_z_kalibracji(1, "OSOBA", katalog_danych=tmp_path) == pytest.approx(0.21)
        assert r95_z_kalibracji(1, "NIP", katalog_danych=tmp_path) is None
        assert r95_z_kalibracji(2, "OSOBA", katalog_danych=tmp_path) == pytest.approx(0.15)

    def test_poziom_bez_kalibracji_brak_wartosci(self, tmp_path):
        (tmp_path / "r95.json").write_text(
            json.dumps({"poziomy": {"1": {"detektor": "poziom1", "r95": {"OSOBA": 0.21}}}}),
            encoding="utf-8",
        )
        assert r95_z_kalibracji(3, "OSOBA", katalog_danych=tmp_path) is None

    def test_brak_pliku(self, tmp_path):
        assert r95_z_kalibracji(1, "OSOBA", katalog_danych=tmp_path) is None
        assert r95_poziomy(katalog_danych=tmp_path) == {}

    def test_r95_poziomy_dla_interfejsu(self, tmp_path):
        (tmp_path / "r95.json").write_text(
            json.dumps(
                {
                    "poziomy": {
                        "1": {"detektor": "poziom1", "r95": {"OSOBA": 0.21}},
                        "2": {"detektor": "poziom2", "prog_osoba": 0.2, "r95": {"OSOBA": 0.15}},
                    }
                }
            ),
            encoding="utf-8",
        )
        assert r95_poziomy(katalog_danych=tmp_path) == {1: {"OSOBA": 0.21}, 2: {"OSOBA": 0.15}}


class TestZapiszPoziom:
    def test_scala_poziomy_i_zachowuje_pozostale(self, tmp_path):
        plik = tmp_path / "r95.json"
        zapisz_poziom(plik, 1, {"detektor": "poziom1", "r95": {"OSOBA": 0.1}}, 182)
        zapisz_poziom(plik, 2, {"detektor": "poziom2", "prog_osoba": 0.2, "r95": {"OSOBA": 0.05}}, 182)
        dane = json.loads(plik.read_text(encoding="utf-8"))
        assert dane["poziomy"]["1"]["r95"] == {"OSOBA": 0.1}
        assert dane["poziomy"]["2"]["prog_osoba"] == 0.2
        assert dane["korpus_probek"] == 182
        assert dane["wzor"].startswith("beta.ppf")

    def test_nadpisuje_wlasny_poziom(self, tmp_path):
        plik = tmp_path / "r95.json"
        zapisz_poziom(plik, 1, {"detektor": "poziom1", "r95": {"OSOBA": 0.2}}, 182)
        zapisz_poziom(plik, 1, {"detektor": "poziom1", "r95": {"OSOBA": 0.15}}, 182)
        dane = json.loads(plik.read_text(encoding="utf-8"))
        assert dane["poziomy"]["1"]["r95"] == {"OSOBA": 0.15}
        assert len(dane["poziomy"]) == 1
