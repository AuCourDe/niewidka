"""Safe ZIP reading: headers can lie, so reading is in chunks under a shared budget of
real bytes, length is checked against the declaration, and methods other than stored/deflate
are rejected (fail-closed)."""

from __future__ import annotations

import io
import zipfile

PORCJA = 64 * 1024
_METODY = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)


class ArchiwumZaDuze(Exception):
    """Real decompressed content over the budget (zip bomb -> 413)."""


class BladArchiwum(Exception):
    """An archive that must not be read: a foreign compression method, lying headers."""


def wczytaj_czesci(dane: bytes, limit_bajtow: int | None = None) -> list[tuple[str, bytes]]:
    """Archive parts in chunks under a shared decompression budget.

        `limit_bajtow` applies to the REAL decompressed bytes of the whole archive
        (header declarations are not trustworthy). Exceeding the budget,
        a length mismatch or a foreign compression method raises an exception.
        """
    rozpakowane_razem = 0
    czesci: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(dane)) as paczka:
        for info in paczka.infolist():
            if info.compress_type not in _METODY:
                raise BladArchiwum(f"część {info.filename}: nieznana metoda kompresji")
            try:
                with paczka.open(info, "r") as strumien:
                    kawalki: list[bytes] = []
                    while kawalek := strumien.read(PORCJA):
                        rozpakowane_razem += len(kawalek)
                        if limit_bajtow is not None and rozpakowane_razem > limit_bajtow:
                            raise ArchiwumZaDuze(
                                f"rozpakowana treść archiwum przekracza limit {limit_bajtow} B"
                            )
                        kawalki.append(kawalek)
                    zawartosc = b"".join(kawalki)
                    # the header declared MORE than the stream has (truncation, damage)
                    if len(zawartosc) != info.file_size:
                        raise BladArchiwum(
                            f"część {info.filename}: nagłówek deklaruje {info.file_size} B, "
                            f"strumień ma {len(zawartosc)} B"
                        )
                    # the header declared LESS (audit vector): one more byte
                    # past the declaration - if the stream is still alive, the header lies
                    if strumien.read(1):
                        raise BladArchiwum(
                            f"część {info.filename}: strumień dłuższy niż deklaracja {info.file_size} B"
                        )
            except zipfile.BadZipFile as blad:
                # zipfile itself detects e.g. overlapping entries ("possible zip bomb")
                raise BladArchiwum(f"część {info.filename}: {blad}") from None
            czesci.append((info.filename, zawartosc))
    return czesci
