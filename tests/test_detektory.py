"""Testy detektorów (LLD §4): okna przesuwne, dekodowanie BIO, mapowanie etykiet.

Testy okien i BIO działają na atrapach — bez modelu i onnxruntime. Testy na żywym
modelu mają marker `model` i są pomijane, gdy wag nie ma w katalogu modeli.
"""

from __future__ import annotations

import pytest

from niewidka.detektory import okna_tokenow, zdekoduj_bio
from niewidka.model import TypEncji


class TestOknaTokenow:
    def test_tekst_krotszy_niz_okno_jedno_okno(self):
        assert okna_tokenow(100, okno=510, krok=448) == [(0, 100)]

    def test_dokladnie_okno(self):
        assert okna_tokenow(510, okno=510, krok=448) == [(0, 510)]

    def test_dwa_okna_z_zaklada(self):
        # 1000 tokenów: [0,510), następne start 448; ostatnie dociągnięte do końca.
        okna = okna_tokenow(1000, okno=510, krok=448)
        assert okna[0] == (0, 510)
        assert okna[-1] == (490, 1000)  # krok przestaje się zmieścić — okno przyklejone do końca
        for start, koniec in okna:
            assert koniec - start == 510

    def test_kazdy_token_pokryty(self):
        n, okno, krok = 1200, 510, 448
        pokryte = set()
        for start, koniec in okna_tokenow(n, okno=okno, krok=krok):
            assert start < koniec
            pokryte.update(range(start, koniec))
        assert pokryte == set(range(n))

    def test_zakladka_ciagla_bez_dziur(self):
        # Sąsiednie okna nachodzą dokładnie o (okno - krok) tokenów.
        okna = okna_tokenow(1500, okno=510, krok=448)
        for (a_start, a_koniec), (b_start, b_koniec) in zip(okna, okna[1:]):
            assert b_start == a_koniec - (510 - 448) or b_koniec == 1500
            assert b_start < a_koniec  # zakładka niepusta

    def test_zero_tokenow(self):
        assert okna_tokenow(0, okno=510, krok=448) == []


Etykieta = tuple[str, tuple[int, int], float]  # (etykieta, offsety znakowe, pewność)


class TestZdekodujBio:
    def test_pojedyncza_etykieta_b_i(self):
        tokeny: list[Etykieta] = [
            ("O", (0, 5), 0.9),
            ("B-PERSON_NAME", (6, 9), 0.8),
            ("I-PERSON_NAME", (10, 17), 0.6),
            ("O", (18, 25), 0.9),
        ]
        zakresy = zdekoduj_bio(tokeny, {("PERSON_NAME",): TypEncji.OSOBA})
        assert len(zakresy) == 1
        start, koniec, typ, pewnosc = zakresy[0]
        assert (start, koniec) == (6, 17)
        assert typ is TypEncji.OSOBA
        assert pewnosc == pytest.approx(0.6)  # minimum z tokenów encji

    def test_dwie_sasiednie_encje_roznych_typow(self):
        tokeny: list[Etykieta] = [
            ("B-PERSON_NAME", (0, 4), 0.9),
            ("B-POSTAL_ADDRESS", (5, 20), 0.7),
        ]
        mapa = {
            ("PERSON_NAME",): TypEncji.OSOBA,
            ("POSTAL_ADDRESS",): TypEncji.ADRES,
        }
        zakresy = zdekoduj_bio(tokeny, mapa)
        assert [(s, k, t) for s, k, t, _ in zakresy] == [
            (0, 4, TypEncji.OSOBA),
            (5, 20, TypEncji.ADRES),
        ]

    def test_etykieta_niemapowana_pomijana(self):
        # LOCATION nie ma w mapie adaptera — nie produkuje Zakres (decyzja poziomu 1).
        tokeny: list[Etykieta] = [
            ("B-PERSON_NAME", (0, 4), 0.9),
            ("B-LOCATION", (5, 12), 0.99),
            ("I-LOCATION", (13, 20), 0.99),
        ]
        zakresy = zdekoduj_bio(tokeny, {("PERSON_NAME",): TypEncji.OSOBA})
        assert [(s, k, t) for s, k, t, _ in zakresy] == [(0, 4, TypEncji.OSOBA)]

    def test_i_bez_poprzedzajacego_b_nie_zaczyna_encji(self):
        tokeny: list[Etykieta] = [
            ("O", (0, 3), 0.9),
            ("I-PERSON_NAME", (4, 10), 0.8),
        ]
        assert zdekoduj_bio(tokeny, {("PERSON_NAME",): TypEncji.OSOBA}) == []

    def test_i_innego_typu_konczy_encje(self):
        tokeny: list[Etykieta] = [
            ("B-PERSON_NAME", (0, 4), 0.9),
            ("I-POSTAL_ADDRESS", (5, 9), 0.8),
            ("I-PERSON_NAME", (10, 14), 0.8),
        ]
        mapa = {
            ("PERSON_NAME",): TypEncji.OSOBA,
            ("POSTAL_ADDRESS",): TypEncji.ADRES,
        }
        zakresy = zdekoduj_bio(tokeny, mapa)
        # (5,9) — I innego typu: pominięte; (10,14) — nowa encja OSOBA bez B: pominięta.
        assert [(s, k, t) for s, k, t, _ in zakresy] == [(0, 4, TypEncji.OSOBA)]

    def test_tokeny_puste_offsety_specjalne_pomijane(self):
        # <s>/</s> mają offsety (0,0) i etykietę O — nie wpływają na dekodowanie.
        tokeny: list[Etykieta] = [
            ("O", (0, 0), 1.0),
            ("B-PERSON_NAME", (0, 4), 0.9),
            ("I-PERSON_NAME", (5, 12), 0.9),
            ("O", (0, 0), 1.0),
        ]
        zakresy = zdekoduj_bio(tokeny, {("PERSON_NAME",): TypEncji.OSOBA})
        assert [(s, k, t) for s, k, t, _ in zakresy] == [(0, 12, TypEncji.OSOBA)]

    def test_pewnosc_to_minimum_tokenow(self):
        tokeny: list[Etykieta] = [
            ("B-PERSON_NAME", (0, 4), 0.95),
            ("I-PERSON_NAME", (5, 12), 0.40),
        ]
        zakresy = zdekoduj_bio(tokeny, {("PERSON_NAME",): TypEncji.OSOBA})
        assert zakresy[0][3] == pytest.approx(0.40)
