"""Kontrola zapisu (LLD §10): weryfikacja ZAWSZE, każdy poziom suwaka (Astra pkt 8)."""

from __future__ import annotations

from niewidka.formaty import adapter_dla, podziel_segment
from niewidka.formaty.tekst import AdapterTekst
from niewidka.kontrola import kontroluj
from niewidka.model import RunInfo
from niewidka.reguly import znajdz as znajdz_reguly


def _zakryj(dane: bytes) -> bytes:
    """Wklejony tekst → reguły → znaczniki (uproszczony przebieg ukryj)."""
    adapter = AdapterTekst()
    dok = adapter.wczytaj(dane)
    segment = dok.segmenty[0]
    licznik: dict[str, int] = {}
    zamiany = []
    for z in znajdz_reguly(segment.tekst):
        licznik[z.typ.value] = licznik.get(z.typ.value, 0) + 1
        zamiany.append((z.start, z.koniec, f"[{z.typ.value}_{licznik[z.typ.value]}]"))
    fragmenty = podziel_segment(segment, zamiany)
    segment.runs = [RunInfo(t, None) for t, _ in fragmenty]
    segment.tekst = "".join(r.tekst for r in segment.runs)
    return adapter.zapisz(dok)


class TestKontroluj:
    def test_czysty_wynik_zero_ostrzezen(self):
        wynik = _zakryj(b"Jan Kowalski, PESEL 44051401359.")
        assert kontroluj(wynik, "wynik.txt", RegulyAtrapa()) == []

    def test_wyciek_w_wyniku_daje_ostrzezenie(self):
        wynik = _zakryj(b"Jan Kowalski, PESEL 44051401359.")
        brudny = wynik.replace(b"[PESEL_1]", b"PESEL 79020853217")  # wyciek w środku
        uwagi = kontroluj(brudny, "wynik.txt", RegulyAtrapa())
        assert len(uwagi) == 1
        assert uwagi[0].typ == "PESEL"
        assert uwagi[0].fragment == "79020853217"
        assert uwagi[0].segment == 0  # TXT = jeden segment (dopisek + treść)

    def test_weryfikacja_wczytuje_jak_obcy_format(self):
        # DOCX: kontrola przez ten sam adapter (ponowne wczytanie i skan)
        from narzedzia.generator_dokumentow import zapisz_podstawowy

        wzorzec = zapisz_podstawowy(Path_tmp() / "w.docx")
        adapter = adapter_dla("w.docx")
        dok = adapter.wczytaj(wzorzec.read_bytes())
        czysty = adapter.zapisz(dok)  # bez detekcji — PESEL zostaje!
        uwagi = kontroluj(czysty, "w.docx", RegulyAtrapa())
        assert any(u.typ == "PESEL" for u in uwagi)  # kontrola ZAWSZE wyłapuje


def Path_tmp():
    import tempfile
    from pathlib import Path

    return Path(tempfile.gettempdir())


class RegulyAtrapa:
    """Reguły bez modeli — kontrola działa na każdym poziomie suwaka."""

    nazwa = "reguly"
    typy = frozenset()

    def znajdz(self, tekst):
        from niewidka.scalanie import scal

        return scal(tekst, znajdz_reguly(tekst))
