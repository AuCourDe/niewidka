"""Testy opisu ryzyka (K5c): próg próby, uczciwe teksty, odmiana liczebników.

Etykieta z R95 ("podwyższone" itd.) ma sens tylko przy dostatecznie dużej próbie.
Przy małej próbie (typy regułowe w korpusie mają po kilka-kilkanaście przykładów)
górna granica Cloppera-Pearsona wychodzi wysoka nawet przy zero pominięć — wtedy
mówimy uczciwie, ile przykładów było, zamiast straszyć "podwyższonym".
"""

from __future__ import annotations

import json

from niewidka.jakosc import opis_ryzyka, opisy_ryzyka


class TestOpisRyzyka:
    def test_mala_proba_bez_etykiety_ryzyka(self):
        # PESEL w kalibracji: 0 pominięć na 7 przykładów, a R95 z Cloppera-Pearsona
        # wychodzi 0.3482; mała próba nie może dostawać etykiety "podwyższone"
        opis = opis_ryzyka(0.3482, n=7, k=0)
        assert opis == "w testach: 0 pominięć na 7 przykładów"
        assert "podwyższone" not in opis

    def test_mala_proba_jedno_pominiecie(self):
        assert opis_ryzyka(0.6, n=16, k=1) == "w testach: 1 pominięcie na 16 przykładów"

    def test_mala_proba_dwa_pominiecia(self):
        assert opis_ryzyka(0.7, n=45, k=2) == "w testach: 2 pominięcia na 45 przykładów"

    def test_mala_proba_dwanascie_pominiec(self):
        assert opis_ryzyka(0.9, n=40, k=12) == "w testach: 12 pominięć na 40 przykładów"

    def test_prog_rozstrzyga_o_etykiecie(self):
        # n = 49: jeszcze uczciwa próba; n = 50: już etykieta z R95
        assert "w testach" in opis_ryzyka(0.31, n=49, k=0)
        assert "w testach" not in opis_ryzyka(0.31, n=50, k=0)
        assert opis_ryzyka(0.31, n=50, k=0).startswith("podwyższone")

    def test_duzo_probek_etykieta_z_r95(self):
        assert opis_ryzyka(0.015, n=100, k=0) == "bardzo małe: co najwyżej 1 na 50"
        assert opis_ryzyka(0.1, n=100, k=2) == "małe do umiarkowanego: co najwyżej ok. 1 na 10"
        assert opis_ryzyka(0.4, n=100, k=30) == "podwyższone: przejrzyj wynik własnym okiem"

    def test_bez_oszacowania(self):
        assert opis_ryzyka(None) == "brak oszacowania dla tego poziomu jakości"

    def test_bez_danych_proby_etykieta_z_r95(self):
        # stary r95.json bez "proba": zachowanie jak dotychczas (etykieta z R95)
        assert opis_ryzyka(0.1) == "małe do umiarkowanego: co najwyżej ok. 1 na 10"

    def test_odmiana_przykladow(self):
        assert "na 22 przykłady" in opis_ryzyka(0.5, n=22, k=0)
        assert "na 21 przykładów" in opis_ryzyka(0.5, n=21, k=0)
        assert "na 1 przykład" in opis_ryzyka(0.5, n=1, k=0)


class TestOpisyRyzyka:
    def test_buduje_opisy_dla_typow_z_dokumentu(self, tmp_path):
        (tmp_path / "r95.json").write_text(
            json.dumps(
                {
                    "poziomy": {
                        "2": {
                            "detektor": "poziom2",
                            "prog_osoba": 0.2,
                            "r95": {"OSOBA": 0.0599, "PESEL": 0.3482},
                            "proba": {"OSOBA": {"k": 2, "n": 112}, "PESEL": {"k": 0, "n": 7}},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        opisy = opisy_ryzyka(2, ["PESEL", "OSOBA"], katalog_danych=tmp_path)
        assert opisy["PESEL"] == {
            "r95": 0.3482,
            "n": 7,
            "k": 0,
            "opis": "w testach: 0 pominięć na 7 przykładów",
        }
        assert opisy["OSOBA"]["opis"] == "małe do umiarkowanego: co najwyżej ok. 1 na 17"
        assert (opisy["OSOBA"]["n"], opisy["OSOBA"]["k"]) == (112, 2)

    def test_typy_poza_dokumentem_nie_wychodza(self, tmp_path):
        (tmp_path / "r95.json").write_text(
            json.dumps({"poziomy": {"1": {"r95": {"PESEL": 0.3482, "NIP": 0.3482}}}}),
            encoding="utf-8",
        )
        opisy = opisy_ryzyka(1, ["PESEL"], katalog_danych=tmp_path)
        assert list(opisy) == ["PESEL"]

    def test_poziom_bez_kalibracji_pusta_mapa(self, tmp_path):
        assert opisy_ryzyka(3, ["PESEL"], katalog_danych=tmp_path) == {}
