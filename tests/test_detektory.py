"""Testy detektorów (LLD §4): okna przesuwne, dekodowanie BIO, mapowanie etykiet.

Testy okien i BIO działają na atrapach — bez modelu i onnxruntime. Testy na żywym
modelu mają marker `model` i są pomijane, gdy wag nie ma w katalogu modeli.
"""

from __future__ import annotations

import pytest

from niewidka.detektory import okna_tokenow, zdekoduj_bio
from niewidka.model import TypEncji
from niewidka.scalanie import scal


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
        for (a_start, a_koniec), (b_start, b_koniec) in itertools.pairwise(okna):
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


# --- Krok G (K2b): BIOES — schemat LFM2.5 (B/I/E/S) ---

class TestZdekodujBioes:
    mapa: ClassVar[dict] = {("PERSON_NAME",): TypEncji.OSOBA}

    def test_b_i_e_jedna_encja(self):
        tokeny: list[Etykieta] = [
            ("O", (0, 4), 0.9),
            ("B-PERSON_NAME", (5, 8), 0.9),
            ("I-PERSON_NAME", (9, 12), 0.8),
            ("E-PERSON_NAME", (13, 20), 0.7),
            ("O", (21, 24), 0.9),
        ]
        zakresy = zdekoduj_bio(tokeny, self.mapa)
        assert [(s, k, t) for s, k, t, _ in zakresy] == [(5, 20, TypEncji.OSOBA)]
        assert zakresy[0][3] == pytest.approx(0.7)  # min z B/I/E

    def test_s_pojedynczy_token_cala_encja(self):
        tokeny: list[Etykieta] = [
            ("O", (0, 4), 0.9),
            ("S-PERSON_NAME", (5, 10), 0.85),
            ("O", (11, 13), 0.9),
        ]
        assert [(s, k, t) for s, k, t, _ in zdekoduj_bio(tokeny, self.mapa)] == [
            (5, 10, TypEncji.OSOBA)
        ]

    def test_e_bez_b_pominieta(self):
        tokeny: list[Etykieta] = [
            ("O", (0, 4), 0.9),
            ("E-PERSON_NAME", (5, 10), 0.9),
        ]
        assert zdekoduj_bio(tokeny, self.mapa) == []

    def test_e_innego_typu_zamyka_i_nie_dokleja(self):
        tokeny: list[Etykieta] = [
            ("B-PERSON_NAME", (0, 4), 0.9),
            ("E-LOCATION", (5, 12), 0.9),
        ]
        zakresy = zdekoduj_bio(tokeny, self.mapa)
        assert [(s, k, t) for s, k, t, _ in zakresy] == [(0, 4, TypEncji.OSOBA)]

    def test_s_po_b_zamyka_i_startuje_osobna(self):
        # niepoprawna sekwencja modelu: B..., potem S — zamknij B (bez S w środku),
        # S = osobna encja jedno-tokenowa.
        tokeny: list[Etykieta] = [
            ("B-PERSON_NAME", (0, 4), 0.9),
            ("S-PERSON_NAME", (5, 10), 0.8),
        ]
        assert [(s, k, t) for s, k, t, _ in zdekoduj_bio(tokeny, self.mapa)] == [
            (0, 4, TypEncji.OSOBA),
            (5, 10, TypEncji.OSOBA),
        ]

    def test_bez_e_sekwencja_b_i_zamyka_sie_na_O(self):
        # BIO czysty nadal działa bez E/S (kompatybilność bardsai).
        tokeny: list[Etykieta] = [
            ("B-PERSON_NAME", (0, 4), 0.9),
            ("I-PERSON_NAME", (5, 12), 0.8),
            ("O", (13, 16), 0.9),
        ]
        assert [(s, k, t) for s, k, t, _ in zdekoduj_bio(tokeny, self.mapa)] == [
            (0, 12, TypEncji.OSOBA)
        ]


# --- Krok B: interfejs Detektor, OnnxDetektor, adapter bardsai (atrapy) ---

import hashlib
import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from niewidka.detektory import (
    ADAPTER_BARDSAI,
    BladDetektora,
    OnnxDetektor,
    RegulyDetektor,
)
from niewidka.reguly import znajdz as znajdz_reguly


@dataclass
class AtrapaEncoding:
    ids: list[int]
    offsets: list[tuple[int, int]]
    special_tokens_mask: list[int]


class AtrapaTokenizer:
    """Encoding: token (id=i+1) na każdym słowie; <s>/</s> z maską (0,0)."""

    def __init__(self, slowa: list[str]):
        self.slowa = slowa

    def encode(self, tekst: str, add_special_tokens: bool = True):
        start = 0
        ids, offsets, maska = [], [], []
        if add_special_tokens:
            ids.append(0)
            offsets.append((0, 0))
            maska.append(1)
        for slowo in self.slowa:
            start = tekst.index(slowo, start)
            ids.append(len(ids))
            offsets.append((start, start + len(slowo)))
            maska.append(0)
            start += len(slowo)
        if add_special_tokens:
            ids.append(0)
            offsets.append((0, 0))
            maska.append(1)
        return AtrapaEncoding(ids, offsets, maska)


class AtrapaSesja:
    """Logity: etykieta o zadanym id = 4.0, reszta 0.0 → pewność ~0.982."""

    def __init__(self, etykieta_na_token: list[int], n_etykiet: int = 69):
        self.etykieta_na_token = etykieta_na_token
        self.n_etykiet = n_etykiet
        self.wejscia = ["input_ids", "attention_mask"]

    def run(self, wyjscia, feed):
        n = len(feed["input_ids"][0])
        return [
            [
                [
                    [4.0 if k == e else 0.0 for k in range(self.n_etykiet)]
                    for e in self.etykieta_na_token[:n]
                ]
            ]
        ]


ID_O = 0
ID_B_KLASA1 = 1  # B-KLASA1 w atrapie konfiguracji (B: 1-4, I: 5-8)
ID_I_KLASA1 = 5  # I-KLASA1


def zbuduj_onnx(
    tmp_path, slowa, etykieta_na_token, tokenizer=None, sesja=None, próg=None, pół_krok=False
):
    config = {
        "id2label": {
            i: e
            for i, e in enumerate(
                ["O"] + [f"B-KLASA{i}" for i in range(1, 5)] + [f"I-KLASA{i}" for i in range(1, 5)]
            )
        }
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    pliki = {}
    for nazwa in ("model.onnx", "tokenizer.json"):
        (tmp_path / nazwa).write_bytes(b"dane-" + nazwa.encode())
        pliki[nazwa] = hashlib.sha256(b"dane-" + nazwa.encode()).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps({"pliki": pliki}), encoding="utf-8")
    return OnnxDetektor(
        nazwa="onnx:test",
        model=tmp_path / "model.onnx",
        tokenizer=tmp_path / "tokenizer.json",
        etykiety={("KLASA1",): TypEncji.OSOBA},
        id2etykieta=config["id2label"],
        sesja=sesja or AtrapaSesja(etykieta_na_token),
        tokenizer_obj=tokenizer or AtrapaTokenizer(slowa),
        laduj_manifest=True,
        próg=próg,
        pół_krok=pół_krok,
    )


class TestAdapterBardsai:
    def test_osoba_mapowana(self):
        assert ADAPTER_BARDSAI.zwroc_typ("B-PERSON_NAME") is TypEncji.OSOBA
        assert ADAPTER_BARDSAI.zwroc_typ("I-PERSON_NAME") is TypEncji.OSOBA

    def test_alias_osoby_to_osoba(self):
        assert ADAPTER_BARDSAI.zwroc_typ("B-PERSON_ALIAS") is TypEncji.OSOBA

    def test_location_i_pozostale_pomijane(self):
        assert ADAPTER_BARDSAI.zwroc_typ("B-LOCATION") is None
        assert ADAPTER_BARDSAI.zwroc_typ("B-EMAIL_ADDRESS") is None
        assert ADAPTER_BARDSAI.zwroc_typ("O") is None

    def test_typy_adaptera(self):
        assert TypEncji.OSOBA in ADAPTER_BARDSAI.typy


class TestRegulyDetektor:
    def test_protocol_i_wynik_jak_reguly_plus_scalanie(self):
        d = RegulyDetektor()
        assert d.nazwa == "reguly"
        tekst = "PESEL 44051401359."
        assert d.znajdz(tekst) == scal(tekst, znajdz_reguly(tekst))
        assert d.znajdz(tekst)[0].typ is TypEncji.PESEL


class TestOnnxDetektor:
    def test_znajdz_zwraca_zakresy_bardsai(self, tmp_path):
        # "Jan Kowalski i Anna Nowak": tokeny 1,2 (Jan, Kowalski) i 4,5 —
        # atrapa sesji: B-KLASA1 na 1, I-KLASA1 na 2, B-KLASA1 na 4, I-KLASA1 na 5.
        sesja = AtrapaSesja([ID_O, ID_B_KLASA1, ID_I_KLASA1, ID_O, ID_B_KLASA1, ID_I_KLASA1, ID_O])
        d = zbuduj_onnx(tmp_path, ["Jan", "Kowalski", "i", "Anna", "Nowak"], None, sesja=sesja)
        wynik = d.znajdz("Jan Kowalski i Anna Nowak")
        assert [(z.start, z.koniec, z.typ) for z in wynik] == [
            (0, 12, TypEncji.OSOBA),
            (15, 25, TypEncji.OSOBA),
        ]
        assert all(z.zrodlo == "onnx:test" for z in wynik)
        assert all(0 < z.pewnosc <= 1 for z in wynik)

    def test_dlugi_tekst_wiecz_zwola_okna(self, tmp_path):
        # 1100 tokenów okna [0,510) i [448,958) i [590,1100); licznik wywołań sesji.
        n = 1100
        slowa = [f"w{i}" for i in range(n)]
        wywolania = []

        class LiczacaSesja(AtrapaSesja):
            def run(self, wyjscia, feed):
                wywolania.append(len(feed["input_ids"][0]))
                return super().run(wyjscia, feed)

        sesja = LiczacaSesja([ID_O] * (n + 2))
        d = zbuduj_onnx(tmp_path, slowa, None, sesja=sesja)
        wynik = d.znajdz(" ".join(slowa))
        assert wywolania == [510, 510, 510]  # okna po 510 tokenów, feed as-is
        assert wynik == []

    def test_okno_przycina_tokeny_specjalne(self, tmp_path):
        # <s> O, środek B-KLASA1 — encja w środku okna wyłapana poprawnie.
        sesja = AtrapaSesja([ID_O, 1, ID_O, ID_O])
        d = zbuduj_onnx(tmp_path, ["Jan", "biegł"], None, sesja=sesja)
        wynik = d.znajdz("Jan biegł")
        assert [(z.start, z.koniec) for z in wynik] == [(0, 3)]

    def test_manifest_rozbiezny_sha_blad(self, tmp_path):
        config = {"id2label": {"0": "O"}}
        (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (tmp_path / "model.onnx").write_bytes(b"x")
        (tmp_path / "tokenizer.json").write_bytes(b"y")
        (tmp_path / "manifest.json").write_text(
            json.dumps({"pliki": {"model.onnx": "0" * 64, "tokenizer.json": "0" * 64}}),
            encoding="utf-8",
        )
        with pytest.raises(BladDetektora, match="manifest"):
            OnnxDetektor(
                nazwa="onnx:test",
                model=tmp_path / "model.onnx",
                tokenizer=tmp_path / "tokenizer.json",
                etykiety={},
                id2etykieta=config["id2label"],
                sesja=AtrapaSesja([0]),
                tokenizer_obj=AtrapaTokenizer(["a"]),
                laduj_manifest=True,
            )

    def test_blad_inferencji_fail_closed(self, tmp_path):
        class PadajacaSesja:
            wejscia: ClassVar[list[str]] = ["input_ids", "attention_mask"]

            def run(self, wyjscia, feed):
                raise RuntimeError("padł model")

        d = zbuduj_onnx(tmp_path, ["Jan"], None, sesja=PadajacaSesja())
        with pytest.raises(BladDetektora, match="padł model"):
            d.znajdz("Jan")


# --- Krok D: wczytaj_bardsai (żywy model, marker `model`) + DetektorKompozyt ---

from niewidka.detektory import ADAPTER_LFM25


class TestWczytajBardsai:
    @pytest.mark.model
    def test_zywy_model_osoba(self, model_bardsai):
        wynik = model_bardsai.znajdz("Wczoraj Jan Kowalski poszedł do sklepu po chleb.")
        assert [(z.start, z.koniec, z.typ) for z in wynik] == [(8, 20, TypEncji.OSOBA)]
        assert wynik[0].zrodlo == "onnx:bardsai"
        assert wynik[0].pewnosc > 0.9

    @pytest.mark.model
    def test_zywy_model_dlugi_tekst_okna(self, model_bardsai):
        tekst = "Uczestnik Jan Kowalski. " * 120  # ~1200 tokenów
        wynik = model_bardsai.znajdz(tekst)
        oczekiwane = 120
        assert sum(1 for z in wynik if z.typ is TypEncji.OSOBA) >= oczekiwane * 0.9


class AtrapaDetektor:
    def __init__(self, nazwa, zakresy):
        self.nazwa = nazwa
        self.zakresy = zakresy
        self.typy = frozenset(z.typ for z in zakresy)

    def znajdz(self, tekst):
        return self.zakresy


class TestDetektorKompozyt:
    def test_unia_czesci_scalona(self):
        from niewidka.detektory import DetektorKompozyt
        from niewidka.model import Zakres

        a = AtrapaDetektor("a", [Zakres(0, 12, TypEncji.OSOBA, 0.9, "a")])
        b = AtrapaDetektor("b", [Zakres(8, 20, TypEncji.OSOBA, 0.9, "b")])
        kompozyt = DetektorKompozyt("poziom1", [a, b])
        assert kompozyt.nazwa == "poziom1"
        wynik = kompozyt.znajdz("0123456789ABCDEFGHIJ")
        # Nakładające się zakresy -> jedna grupa, maskowana unią [0,20).
        assert [(z.start, z.koniec) for z in wynik] == [(0, 20)]
        assert kompozyt.typy == {TypEncji.OSOBA}

    def test_pusta_lista(self):
        from niewidka.detektory import DetektorKompozyt
        from niewidka.model import Zakres  # noqa: F401 — spójność sekcji

        assert DetektorKompozyt("poziom1", []).znajdz("cokolwiek") == []


# --- Krok H (K2b): adapter LFM2.5 — mapowanie etykiet, poziom 2 ---

class TestAdapterLfm25:
    def test_osoba_we_wszystkich_literach_bioes(self):
        for litera in "BIES":
            assert ADAPTER_LFM25.zwroc_typ(f"{litera}-identity.person_name") is TypEncji.OSOBA

    def test_identity_person_name_dokladnie(self):
        assert ADAPTER_LFM25.zwroc_typ("B-identity.person_name") is TypEncji.OSOBA

    def test_pozostale_typy_pomijane(self):
        # reguły mają PESEL/NIP/IBAN/telefon/e-mail z dokładnymi granicami (pewność 1.0);
        # modelowe odpowiedniki rozmyłyby granice (unia scalania, KRYTERIA §1.3)
        for etykieta in (
            "B-identity.national_id",
            "B-identity.tax_id",
            "B-financial.iban",
            "B-contact.email",
            "B-contact.phone",
            "B-contact.address",
            "B-identity.passport",
            "O",
        ):
            assert ADAPTER_LFM25.zwroc_typ(etykieta) is None

    def test_typy_adaptera_tylko_osoba(self):
        assert ADAPTER_LFM25.typy == frozenset({TypEncji.OSOBA})


class TestWczytajLfm25:
    @pytest.mark.model
    def test_zywy_model_int8_osoba(self, model_lfm25):
        wynik = model_lfm25.znajdz("Wczoraj Jan Kowalski poszedł do sklepu po chleb.")
        assert [(z.start, z.koniec, z.typ) for z in wynik] == [(8, 20, TypEncji.OSOBA)]
        assert wynik[0].zrodlo == "onnx:lfm25"

    @pytest.mark.model
    @pytest.mark.xfail(reason="LFM2.5 degraduje na powtarzalnych długich tekstach "
                             "(pomiar K2b: docs/WYNIK-K2b.md); kompozyt poziomu 2 nie "
                             "wychodzi, mechanizm okien pokryty atrapami", strict=False)
    def test_zywy_model_dlugi_tekst_okna(self, model_lfm25):
        tekst = "Uczestnik Jan Kowalski. " * 120  # ~1200 tokenów
        wynik = model_lfm25.znajdz(tekst)
        assert sum(1 for z in wynik if z.typ is TypEncji.OSOBA) >= 120 * 0.9


class TestPoziom2:
    @pytest.mark.model
    def test_poziom2_zwiera_reguly_i_dwa_modele(self, wagi_lfm25):
        from niewidka.detektory import wczytaj_poziom2

        poziom2 = wczytaj_poziom2(wagi_lfm25)
        assert poziom2.nazwa == "poziom2"
        assert [d.nazwa for d in poziom2.czesci] == ["reguly", "onnx:bardsai", "onnx:lfm25"]
        wynik = poziom2.znajdz("Jan Kowalski, PESEL 44051401359.")
        typy = {z.typ for z in wynik}
        assert TypEncji.OSOBA in typy and TypEncji.PESEL in typy


# --- Krok F: rozciągnięcie zakresów modelu do granic słowa (artefakty subword) ---

from niewidka.detektory import rozciagnij_do_slow


class TestRozciagnijDoSlow:
    def test_ucieta_koncowa_subtokenu(self):
        # 'Róża' tokenizowane 'Róż'+'a' — model oznaczył tylko pierwszy.
        assert rozciagnij_do_slow([(0, 3)], "Róża kupiła róże.") == [(0, 4)]

    def test_ucieta_srodkowa(self):
        # 'Nowak' w środku: 'Now'+'ak' — nie rozciąga się na sąsiednie słowa.
        tekst = "Nowak to nazwisko; Nowak podpisuje."
        assert rozciagnij_do_slow([(19, 22)], tekst) == [(19, 24)]

    def test_dwa_b_w_jednym_slowie_daja_identyczne(self):
        # 'Kowal' = 'Ko'+'wal', model dał B na obu subtokenach.
        assert rozciagnij_do_slow([(0, 2), (2, 5)], "Kowal to zawód.") == [(0, 5), (0, 5)]

    def test_pelen_zakres_slowny_niezmieniony(self):
        assert rozciagnij_do_slow([(0, 12)], "Jan Kowalski poszedł.") == [(0, 12)]

    def test_nie_rosnie_po_spacji_i_przecinku(self):
        assert rozciagnij_do_slow([(0, 3)], "Jan, Kowalski i in.") == [(0, 3)]

    def test_nie_przekracza_tekstu(self):
        # po trimie whitespace (K2b) końcowa spacja nie wchodzi w zakres
        assert rozciagnij_do_slow([(0, 4)], "Jan ") == [(0, 3)]

    def test_diacritiki_i_cyfry(self):
        assert rozciagnij_do_slow([(0, 2)], "Żółć3.") == [(0, 5)]

    def test_puste(self):
        assert rozciagnij_do_slow([], "cokolwiek") == []


class TestRozciagnijDoSlowTrim:
    """Tokeny BPE (LFM2.5, K2b) mają offsety z wiodącą spacją ('ĠPiot' -> (14,19));
    bez przycięcia whitespace rozciągnięcie ucieka na poprzednie słowo."""

    def test_offset_z_wiodaca_spacja_nie_ucieka_na_poprzednie_slowo(self):
        tekst = "Umowę podpisał Piotr Nowak w obecności."
        # 'ĠPiot' offset (14,19): 14 = spacja; start musi się przesunąć na 15, nie na 6.
        assert rozciagnij_do_slow([(14, 19)], tekst) == [(15, 20)]

    def test_offset_z_wewnetrzna_spacja_dwa_slowa(self):
        tekst = "Umowę podpisał Piotr Nowak w obecności."
        # 'ĠPiotr Nowak' offset (14,26) — po przycięciu: 'Piotr Nowak' = (15,26).
        assert rozciagnij_do_slow([(14, 26)], tekst) == [(15, 26)]

    def test_zwykle_zakresy_niezmienione(self):
        tekst = "Jan Kowalski poszedł."
        assert rozciagnij_do_slow([(0, 12)], tekst) == [(0, 12)]


# --- K2d (wariant A/B): próg pewności OSOBA, półkrokowe okna, słownik imion ---

from niewidka.detektory import SlownikImionDetektor


class AtrapaSesjaLogity:
    """Logity per token: {id tokenu: {id etykiety: logit}}; reszta 0.0."""

    wejscia: ClassVar[list[str]] = ["input_ids", "attention_mask"]

    def __init__(self, logity: dict[int, dict[int, float]], n_etykiet: int = 9):
        self._logity = logity
        self._n = n_etykiet

    def run(self, _, feed):
        idy = list(feed["input_ids"][0])
        return [
            [
                [
                    [self._logity.get(id, {}).get(k, 0.0) for k in range(self._n)]
                    for id in idy
                ]
            ]
        ]


class TestProgPewnosciOSOBA:
    # O = 4.5 (argmax), B-KLASA1 = 4.0 -> p(KLASA1) ≈ 0.34: kandydat PONIŻEJ argmaxu.
    LOGITY_JAN: ClassVar[dict[int, dict[int, float]]] = {1: {0: 4.5, 1: 4.0}}

    def test_powyzej_progu_dodaje_osoba_bez_argmaxu(self, tmp_path):
        d = zbuduj_onnx(
            tmp_path, ["Jan", "biegł"], None, sesja=AtrapaSesjaLogity(self.LOGITY_JAN), próg=0.2
        )
        wynik = d.znajdz("Jan biegł")
        assert [(z.start, z.koniec, z.typ) for z in wynik] == [(0, 3, TypEncji.OSOBA)]
        assert wynik[0].zrodlo == "onnx:test"

    def test_ponizej_progu_brak_osoby(self, tmp_path):
        d = zbuduj_onnx(
            tmp_path, ["Jan", "biegł"], None, sesja=AtrapaSesjaLogity(self.LOGITY_JAN), próg=0.4
        )
        assert d.znajdz("Jan biegł") == []

    def test_bez_progu_zachowanie_niezmienione(self, tmp_path):
        d = zbuduj_onnx(tmp_path, ["Jan", "biegł"], None, sesja=AtrapaSesjaLogity(self.LOGITY_JAN))
        assert d.znajdz("Jan biegł") == []  # argmax = O -> bez detekcji, jak przed K2d

    def test_kontynuacja_kleje_b_i_i(self, tmp_path):
        logity = {1: {0: 4.5, 1: 4.0}, 2: {0: 4.5, 1: 4.0}}
        d = zbuduj_onnx(
            tmp_path, ["Jan", "Kowalski", "biegł"], None, sesja=AtrapaSesjaLogity(logity), próg=0.2
        )
        wynik = d.znajdz("Jan Kowalski biegł")
        assert [(z.start, z.koniec, z.typ) for z in wynik] == [(0, 12, TypEncji.OSOBA)]

    def test_prog_poza_zakresem_blad(self, tmp_path):
        with pytest.raises(BladDetektora, match="próg"):
            zbuduj_onnx(tmp_path, ["Jan"], None, próg=1.5)


class TestPolKrokOkien:
    def test_encja_na_granicy_okien_lapana_przesunieciem(self, tmp_path):
        # n=1100; encja B/I…/I na tokenach 445-515 (71 tokenów > zakładki 62
        # tokenów). Okno (0,510) ma tylko część, okno (448,958) zaczyna się DALEJ
        # niż B-token -> tam wszystko I bez swojego B, odpada; przesunięte okno
        # (224,734) obejmuje całą encję -> pełny łańcuch B..I.
        n = 1100
        slowa = [f"w{i:04d}" for i in range(n)]
        tekst = " ".join(slowa)
        # id tokenu = indeks słowa + 1 (id 0 = <s>); B na słowie 445, I na 446-515
        logity = {446: {1: 4.0}}
        logity.update({id: {5: 4.0} for id in range(447, 517)})
        sesja = AtrapaSesjaLogity(logity)
        s = tekst.index("w0445")  # każde słowo 5 znaków + spacja: słowa co 6 znaków
        d_bez = zbuduj_onnx(tmp_path, slowa, None, sesja=sesja, pół_krok=False)
        fragment = [(z.start, z.koniec) for z in scal(tekst, d_bez.znajdz(tekst))]
        assert fragment == [(s, s + 63 * 6 + 5)], fragment  # słowa 445-508 (fragment)
        d_z = zbuduj_onnx(tmp_path, slowa, None, sesja=AtrapaSesjaLogity(logity), pół_krok=True)
        calość = [(z.start, z.koniec) for z in scal(tekst, d_z.znajdz(tekst))]
        assert calość == [(s, s + 70 * 6 + 5)], calość  # słowa 445-515 (całość)


def mini_slownik(tmp_path: Path, tresc: str = "# nagłówek\nJan\t516\nAnna\t1063\nPiotr\t700\n") -> Path:
    plik = tmp_path / "imiona.txt"
    plik.write_text(tresc, encoding="utf-8")
    return plik


class TestSlownikImion:
    @pytest.mark.parametrize(
        "forma,nazwisko",
        [("Jan", "Kowalski"), ("Jana", "Kowalskiego"), ("Janem", "Kowalskim"),
         ("Piotr", "Kowalski"), ("Piotra", "Kowalskiego"), ("Piotrem", "Kowalskim")],
    )
    def test_odmiany_meskie(self, tmp_path, forma, nazwisko):
        d = SlownikImionDetektor(plik=mini_slownik(tmp_path))
        tekst = f"{forma} {nazwisko} podpisał."
        assert [(z.start, z.koniec, z.typ) for z in d.znajdz(tekst)] == [
            (0, len(f"{forma} {nazwisko}"), TypEncji.OSOBA)
        ]

    @pytest.mark.parametrize("forma", ["Anna", "Anny", "Annie"])
    def test_odmiany_zenskie(self, tmp_path, forma):
        d = SlownikImionDetektor(plik=mini_slownik(tmp_path))
        assert [(z.start, z.koniec, z.typ) for z in d.znajdz(f"{forma} Kowalska podpisała.")] == [
            (0, len(f"{forma} Kowalska"), TypEncji.OSOBA)
        ]

    def test_nastepne_slowo_wielka_litera(self, tmp_path):
        d = SlownikImionDetektor(plik=mini_slownik(tmp_path))
        assert d.znajdz("Jan podpisał.") == []  # następne słowo z małej litery
        assert [(z.start, z.koniec) for z in d.znajdz("biegł Jan Kowalski.")] == [(6, 18)]

    def test_osoba_nieobecna_w_slowniku(self, tmp_path):
        d = SlownikImionDetektor(plik=mini_slownik(tmp_path))
        assert d.znajdz("Marek Kowalski podpisał.") == []

    def test_dwie_osoby_w_jednym_tekście(self, tmp_path):
        d = SlownikImionDetektor(plik=mini_slownik(tmp_path))
        tekst = "Jan Kowalski i Anna Nowak"
        assert [(z.start, z.koniec) for z in d.znajdz(tekst)] == [(0, 12), (15, 25)]

    def test_interpunkcja_nie_rozszerza_zakresu(self, tmp_path):
        d = SlownikImionDetektor(plik=mini_slownik(tmp_path))
        assert [(z.start, z.koniec) for z in d.znajdz("Jan Kowalski, PESEL 44051401359.")] == [(0, 12)]

    def test_przedział_środek_bez_bialego(self, tmp_path):
        d = SlownikImionDetektor(plik=mini_slownik(tmp_path))
        # przecinek bez spacji między słowami - to nie jest para imię+nazwisko
        assert d.znajdz("Jan,Kowalski podpisał.") == []

    def test_janina_nie_pasuje_do_jana(self, tmp_path):
        d = SlownikImionDetektor(plik=mini_slownik(tmp_path))
        assert d.znajdz("Janina Kowalska podpisała.") == []

    def test_puste_fragmenty_i_pomijanie_komentarzy(self, tmp_path):
        d = SlownikImionDetektor(plik=mini_slownik(tmp_path))
        assert d.znajdz(".") == []

    def test_pusty_slownik_blad(self, tmp_path):
        with pytest.raises(BladDetektora, match="pusty"):
            SlownikImionDetektor(plik=mini_slownik(tmp_path, tresc="# tylko nagłówek\n"))

    def test_brak_slownika_blad(self, tmp_path):
        with pytest.raises(BladDetektora, match="brak"):
            SlownikImionDetektor(plik=tmp_path / "nie-ma.txt")
