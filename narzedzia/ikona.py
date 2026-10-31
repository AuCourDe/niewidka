"""Niewidka program icon: a card with a black redaction bar, PNG and .ico written from scratch
(pure stdlib, no Pillow). A placeholder until a logo is chosen: palette from styl.css (card #FBFBF9, ink #23282D, accent #2D4A6B).

Run: python narzedzia/ikona.py --wyjscie ikona.ico
"""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

KARTA = (251, 251, 249, 255)  # document background (styl.css)
TUSZ = (35, 40, 45, 255)      # marker redaction bar (styl.css)
BIEL = (255, 255, 255, 255)   # strokes of the hidden word
PRZEZRROCZyste = (0, 0, 0, 0)


def _w_karcie(x: int, y: int, rozmiar: int) -> bool:
    """Rounded square of the card with a margin."""
    m = max(1, rozmiar // 12)
    promien = rozmiar // 5
    x0, y0, x1, y1 = m, m, rozmiar - 1 - m, rozmiar - 1 - m
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    # corners: distance from the centre of the rounding
    for cx, cy in ((x0 + promien, y0 + promien), (x1 - promien, y0 + promien),
                   (x0 + promien, y1 - promien), (x1 - promien, y1 - promien)):
        w_rogu = (x < x0 + promien or x > x1 - promien) and (y < y0 + promien or y > y1 - promien)
        if w_rogu and (x - cx) ** 2 + (y - cy) ** 2 > promien**2:
            return False
    return True


def rysuj(rozmiar: int) -> list[list[tuple[int, int, int, int]]]:
    """Card with a horizontal bar and three white strokes of the hidden word."""
    piksele = [[PRZEZRROCZyste for _ in range(rozmiar)] for _ in range(rozmiar)]
    m = max(1, rozmiar // 12)
    for y in range(rozmiar):
        for x in range(rozmiar):
            if _w_karcie(x, y, rozmiar):
                piksele[y][x] = KARTA
    pasek = max(2, rozmiar // 5)
    y0 = (rozmiar - pasek) // 2
    x0 = m + max(1, rozmiar // 16)
    x1 = rozmiar - 1 - m - max(1, rozmiar // 16)
    gr = max(1, rozmiar // 34)
    for y in range(y0, y0 + pasek):
        for x in range(x0, x1 + 1):
            piksele[y][x] = TUSZ
    srodek = rozmiar // 2
    for y in range(srodek - gr, srodek + gr):
        # three strokes like a shortened word
        granice = ((x0 + pasek, x0 + (x1 - x0) // 3), (x0 + (x1 - x0) // 3 + pasek // 2, x0 + 2 * (x1 - x0) // 3),
                   (x0 + 2 * (x1 - x0) // 3 + pasek // 2, x1 - pasek))
        for a, b in granice:
            for x in range(a, b + 1):
                if 0 <= x < rozmiar:
                    piksele[y][x] = BIEL
    return piksele


def _pomniejsz(piksele: list[list[tuple[int, int, int, int]]], cel: int) -> list[list[tuple[int, int, int, int]]]:
    """Nearest-neighbour: the icon has flat colours, so no filtering."""
    zrodlo = len(piksele)
    skala = zrodlo / cel
    return [[piksele[int(y * skala)][int(x * skala)] for x in range(cel)] for y in range(cel)]


def _png(piksele: list[list[tuple[int, int, int, int]]]) -> bytes:
    wys = len(piksele)
    szer = len(piksele[0])
    surowe = b"".join(b"\x00" + bytes(kanal for piksel in wiersz for kanal in piksel) for wiersz in piksele)

    def kawalek(typ: bytes, dane: bytes) -> bytes:
        return (
            struct.pack(">I", len(dane)) + typ + dane
            + struct.pack(">I", zlib.crc32(typ + dane) & 0xFFFFFFFF)
        )

    naglowek = struct.pack(">IIBBBBB", szer, wys, 8, 6, 0, 0, 0)  # 8 bit/channel, RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + kawalek(b"IHDR", naglowek)
        + kawalek(b"IDAT", zlib.compress(surowe, 9))
        + kawalek(b"IEND", b"")
    )


def zapisz_ico(sciezka: Path, rozmiary: tuple[int, ...] = (256, 64, 32, 16)) -> None:
    """.ico file: entry directory + PNG images (Vista+ format)."""
    baza = rysuj(256)
    obrazy = [_png(baza if r == 256 else _pomniejsz(baza, r)) for r in rozmiary]
    naglowek = struct.pack("<HHH", 0, 1, len(obrazy))
    cialo = b"".join(obrazy)
    wpisy = b""
    offset = 6 + 16 * len(obrazy)
    for r, png in zip(rozmiary, obrazy):
        wpisy += struct.pack("<4B2H2I", r % 256, r % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    sciezka.write_bytes(naglowek + wpisy + cialo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ikona Niewidki (.ico, bez zależności)")
    parser.add_argument("--wyjscie", type=Path, default=Path("ikona.ico"))
    argumenty = parser.parse_args(argv)
    zapisz_ico(argumenty.wyjscie)
    print(f"ikona zapisana: {argumenty.wyjscie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
