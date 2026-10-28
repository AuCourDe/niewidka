"""Testy generatora ikony (K6): .ico z osadzonymi PNG, czysty stdlib."""

from __future__ import annotations

import struct
from pathlib import Path

from narzedzia.ikona import rysuj, zapisz_ico


def test_ico_zawiera_png_dla_wszystkich_rozmiarow(tmp_path: Path):
    sciezka = tmp_path / "ikona.ico"
    rozmiary = (256, 64, 32, 16)
    zapisz_ico(sciezka, rozmiary=rozmiary)
    dane = sciezka.read_bytes()
    _, typ, liczba = struct.unpack("<HHH", dane[:6])
    assert typ == 1  # ICON
    assert liczba == len(rozmiary)
    offset = 6
    wpisy = []
    for rozmiar in rozmiary:
        szer, wys, *_reszta, bajtow, obraz = struct.unpack("<4B2H2I", dane[offset : offset + 16])
        assert szer == rozmiar % 256 and wys == rozmiar % 256
        wpisy.append((rozmiar, bajtow, obraz))
        offset += 16
    for rozmiar, bajtow, obraz in wpisy:
        payload = dane[obraz : obraz + bajtow]
        assert payload[:8] == b"\x89PNG\r\n\x1a\n"
        # IHDR: szerokosc/wysokosc PNG zgodne z wpisem
        assert struct.unpack(">II", payload[16:24]) == (rozmiar, rozmiar)
    assert wpisy[-1][2] + wpisy[-1][1] == len(dane)


def test_rysuj_zwraca_rgba_i_ma_kolorowe_piksele():
    piksele = rysuj(32)
    assert len(piksele) == 32 and len(piksele[0]) == 32
    kolory = {piksel for wiersz in piksele for piksel in wiersz}
    assert len(kolory) > 1  # tło karty, zaślepka, przezroczyste rogi
    assert (0, 0, 0, 0) in kolory  # przezroczyste rogi za zaokrągleniem
