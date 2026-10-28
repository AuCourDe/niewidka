"""Testy kalibracji R95 (K2, LLD §11) i odczytu w jakosc."""

from __future__ import annotations

import json

import pytest

from narzedzia.kalibracja import r95_gorna
from niewidka.jakosc import r95_z_kalibracji


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
                    "poziom": 1,
                    "r95": {"OSOBA": 0.21, "PESEL": 0.45},
                }
            ),
            encoding="utf-8",
        )
        assert r95_z_kalibracji(1, "OSOBA", katalog_danych=tmp_path) == pytest.approx(0.21)
        assert r95_z_kalibracji(1, "NIP", katalog_danych=tmp_path) is None

    def test_inny_poziom_brak_wartosci(self, tmp_path):
        (tmp_path / "r95.json").write_text(
            json.dumps({"poziom": 1, "r95": {"OSOBA": 0.21}}), encoding="utf-8"
        )
        assert r95_z_kalibracji(2, "OSOBA", katalog_danych=tmp_path) is None
