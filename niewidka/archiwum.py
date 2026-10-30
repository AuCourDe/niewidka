"""Bezpieczny odczyt ZIP: nagłówki mogą kłamać, więc odczyt porcjami pod wspólnym budżetem
rzeczywistych bajtów, kontrola długości względem deklaracji, metody inne niż stored/deflate
odrzucane (fail-closed).
"""

from __future__ import annotations

import io
import zipfile

PORCJA = 64 * 1024
_METODY = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)


class ArchiwumZaDuze(Exception):
    """Rzeczywista rozpakowana treść ponad budżet (zip bomb → 413)."""


class BladArchiwum(Exception):
    """Archiwum, którego nie wolno czytać: obca metoda kompresji, kłamiące nagłówki."""


def wczytaj_czesci(dane: bytes, limit_bajtow: int | None = None) -> list[tuple[str, bytes]]:
    """Części archiwum porcjami pod wspólnym budżetem dekompresji.

    `limit_bajtow` dotyczy RZECZYWISTYCH rozpakowanych bajtów całego archiwum
    (deklaracje nagłówków nie są wiarygodne). Po przekroczeniu budżetu,
    przy niezgodnej długości albo obcej metodzie kompresji — wyjątek.
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
                    # nagłówek zadeklarował WIĘCEJ niż strumień ma (cięcie, uszkodzenie)
                    if len(zawartosc) != info.file_size:
                        raise BladArchiwum(
                            f"część {info.filename}: nagłówek deklaruje {info.file_size} B, "
                            f"strumień ma {len(zawartosc)} B"
                        )
                    # nagłówek zadeklarował MNIEJ (wektor audytu): jeszcze jeden bajt
                    # za deklaracją — jeśli strumień dalej żyje, nagłówek kłamie
                    if strumien.read(1):
                        raise BladArchiwum(
                            f"część {info.filename}: strumień dłuższy niż deklaracja {info.file_size} B"
                        )
            except zipfile.BadZipFile as blad:
                # zipfile sam wykrywa m.in. nakładające się wpisy („possible zip bomb")
                raise BladArchiwum(f"część {info.filename}: {blad}") from None
            czesci.append((info.filename, zawartosc))
    return czesci
