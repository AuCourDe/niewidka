"""Detektory (LLD §4): wspólny interfejs, okna przesuwne, adaptery modeli ONNX.

Adapter per model (przegląd Astry pkt 14): schemat etykiet (BIO/BIOES), tokeny
specjalne i normalizacja różnią się między modelami — konwersja do `Zakres`
żyje w adapterze modelu, nie we wspólnym kodzie. Błąd detektora = `BladDetektora`
(fail-closed, LLD §15).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from niewidka.model import TypEncji, Zakres
from niewidka.reguly import REGULY
from niewidka.reguly import znajdz as znajdz_reguly
from niewidka.scalanie import scal


class BladDetektora(Exception):
    """Awaria warstwy detekcji — fail-closed: bez dokumentu „bez warstwy"."""


class Detektor(Protocol):
    nazwa: str
    typy: frozenset[TypEncji]

    def znajdz(self, tekst: str) -> list[Zakres]: ...


class RegulyDetektor:
    """Reguły + scalanie — warstwa detekcji regułowa (K1)."""

    nazwa = "reguly"
    typy = frozenset(r.typ for r in REGULY)

    def znajdz(self, tekst: str) -> list[Zakres]:
        return scal(tekst, znajdz_reguly(tekst))


@dataclass(frozen=True)
class AdapterModelu:
    """Mapowanie etykiet modelu na typy Niewidki; klasy poza mapą są pomijane."""

    nazwa: str
    mapa: dict[tuple[str, ...], TypEncji]

    @property
    def typy(self) -> frozenset[TypEncji]:
        return frozenset(self.mapa.values())

    def zwroc_typ(self, etykieta: str) -> TypEncji | None:
        if etykieta.startswith(("B-", "I-")):
            return self.mapa.get((etykieta[2:],))
        return None


# Bardsai (poziom 1): dostarcza WYŁĄCZNIE OSOBA — typy z sumą kontrolną i
# dokładnymi granicami mają reguły (pewność 1.0); dołączenie modelowych ADRES/
# EMAIL itd. rozmywałoby granice (unia scalania = szerszy zakres = FN+FP,
# KRYTERIA §1.3). Reszta etykiet (LOCATION, ORGANIZATION_NAME, ...) pomijana.
ADAPTER_BARDSAI = AdapterModelu(
    nazwa="onnx:bardsai",
    mapa={
        ("PERSON_NAME",): TypEncji.OSOBA,
        ("PERSON_ALIAS",): TypEncji.OSOBA,
    },
)


def _sha256(plik: Path) -> str:
    h = hashlib.sha256()
    with plik.open("rb") as f:
        for kawalek in iter(lambda: f.read(1 << 20), b""):
            h.update(kawalek)
    return h.hexdigest()


class OnnxDetektor:
    """Detektor token-klasyfikacyjny ONNX za interfejsem Detektor (LLD §4).

    Tokenizacja całości (`tokenizers`, offsety znakowe), okna przesuwne
    tokenów, per okno inferencja i dekodowanie BIO adapterem. Duplikaty między
    oknami zdejmuje globalne scalanie (wyżej). `SIMPLIFICATION`: okna na
    pełnym ciągu tokenów (ze specjalnymi), bez doklejania <s>/</s> per okno —
    zakładka (okno-krok) kompensuje granice; rozbudować, gdy pomiar pokaże
    gubienie encji przy krawędziach okien.
    """

    def __init__(
        self,
        nazwa: str,
        model: Path,
        tokenizer: Path,
        etykiety: dict[tuple[str, ...], TypEncji],
        id2etykieta: dict[str, str],
        okno: int = 510,
        krok: int = 448,
        sesja: object | None = None,
        tokenizer_obj: object | None = None,
        laduj_manifest: bool = True,
        provider: str = "CPUExecutionProvider",
    ):
        self.nazwa = nazwa
        self.etykiety = etykiety
        self.typy = frozenset(etykiety.values())
        self._id2etykieta = {str(k): v for k, v in id2etykieta.items()}
        self._okno = okno
        self._krok = krok
        if laduj_manifest:
            self._sprawdz_manifest(model.parent)
        try:
            import numpy as np

            self._np = np
            if tokenizer_obj is None:
                from tokenizers import Tokenizer

                tokenizer_obj = Tokenizer.from_file(str(tokenizer))
            self._tokenizer = tokenizer_obj
            if sesja is None:
                import onnxruntime as ort

                dostepne = ort.get_available_providers()
                if provider not in dostepne:
                    provider = "CPUExecutionProvider"
                sesja = ort.InferenceSession(str(model), providers=[provider])
            wejscia = (
                [i.name for i in sesja.get_inputs()]
                if hasattr(sesja, "get_inputs")
                else list(sesja.wejscia)
            )
            if wejscia[:2] != ["input_ids", "attention_mask"]:
                raise BladDetektora(f"{nazwa}: nieobsługiwane wejścia ONNX: {wejscia}")
            self._sesja = sesja
        except BladDetektora:
            raise
        except Exception as e:  # fail-closed: każdy pad modelu/toklenizera
            raise BladDetektora(f"{nazwa}: ładowanie nie powiodło się: {e}") from e

    @staticmethod
    def _sprawdz_manifest(katalog: Path) -> None:
        manifest_plik = katalog / "manifest.json"
        if not manifest_plik.is_file():
            raise BladDetektora(f"brak manifest.json w {katalog}")
        manifest = json.loads(manifest_plik.read_text(encoding="utf-8"))
        for nazwa, sumka in manifest.get("pliki", {}).items():
            plik = katalog / nazwa
            if not plik.is_file() or _sha256(plik) != sumka:
                raise BladDetektora(f"manifest: rozbieżny SHA-256 dla {nazwa}")

    def znajdz(self, tekst: str) -> list[Zakres]:
        try:
            return self._znajdz(tekst)
        except BladDetektora:
            raise
        except Exception as e:
            raise BladDetektora(f"{self.nazwa}: inferencja nie powiodła się: {e}") from e

    def _znajdz(self, tekst: str) -> list[Zakres]:
        np = self._np
        enc = self._tokenizer.encode(tekst, add_special_tokens=True)
        tokeny = list(zip(enc.ids, enc.offsets))
        wynik: list[Zakres] = []
        for start, koniec in okna_tokenow(len(tokeny), self._okno, self._krok):
            ids = tokeny[start:koniec]
            feed = {
                "input_ids": np.asarray([ids_w for ids_w, _ in ids], dtype=np.int64)[None],
                "attention_mask": np.ones((1, len(ids)), dtype=np.int64),
            }
            logits = np.asarray(self._sesja.run(None, feed)[0][0])
            prawdopodobienstwa = _softmax(np, logits)
            najlepsze = prawdopodobienstwa.argmax(axis=-1)
            etykiety_tokenow = [
                (
                    self._id2etykieta[str(int(najlepsze[i]))],
                    offsets,  # (start, koniec) w znakach CAŁEGO tekstu
                    float(prawdopodobienstwa[i, najlepsze[i]]),
                )
                for i, (_, offsets) in enumerate(ids)
            ]
            for zn_start, zn_koniec, typ, pewnosc in zdekoduj_bio(etykiety_tokenow, self.etykiety):
                wynik.append(Zakres(zn_start, zn_koniec, typ, pewnosc, self.nazwa))
        return wynik


def _softmax(np, logits):  # type: ignore[no-untyped-def]
    z = logits - logits.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def wczytaj_bardsai(
    katalog: Path,
    provider: str = "CPUExecutionProvider",
    okno: int = 510,
    krok: int = 448,
) -> OnnxDetektor:
    """OnnxDetektor z wag bardsai w `katalog` (NIEWIDKA_MODELE_KATALOG, LLD §14)."""
    config = json.loads((katalog / "config.json").read_text(encoding="utf-8"))
    return OnnxDetektor(
        nazwa=ADAPTER_BARDSAI.nazwa,
        model=katalog / "model.onnx",
        tokenizer=katalog / "tokenizer.json",
        etykiety=ADAPTER_BARDSAI.mapa,
        id2etykieta=config.get("id2label", {}),
        okno=okno,
        krok=krok,
        provider=provider,
    )


class DetektorKompozyt:
    """Kilka detektorów za jednym interfejsem; duplikaty zdejmuje scalanie (LLD §4)."""

    def __init__(self, nazwa: str, czesci: list[Detektor]):
        self.nazwa = nazwa
        self.czesci = czesci
        self.typy: frozenset[TypEncji] = frozenset().union(*(c.typy for c in czesci))

    def znajdz(self, tekst: str) -> list[Zakres]:
        kandydaci = [z for czesc in self.czesci for z in czesc.znajdz(tekst)]
        return scal(tekst, kandydaci)


def okna_tokenow(n: int, okno: int, krok: int) -> list[tuple[int, int]]:
    """Przesuwne okna tokenów (zakładka = okno - krok); ostatnie dociągnięte do końca."""
    if n <= 0:
        return []
    if n <= okno:
        return [(0, n)]
    wynik = [(start, start + okno) for start in range(0, n - okno + 1, krok)]
    if wynik[-1][1] < n:
        wynik.append((n - okno, n))
    return wynik


def zdekoduj_bio(
    tokeny: list[tuple[str, tuple[int, int], float]],
    mapa: dict[tuple[str, ...], TypEncji],
) -> list[tuple[int, int, TypEncji, float]]:
    """BIO -> zakresy znakowe (start, koniec, typ, pewność = min. tokenów).

    `tokeny` to (etykieta, offsety znakowe, pewność); etykiety nieobecne w `mapa`
    są pomijane (adapter modelu decyduje, które typy model dostarcza). I- po
    B/I tego samego typu kontynuuje encję; I innego typu albo bez B kończy bieżącą.
    """
    wynik: list[tuple[int, int, TypEncji, float]] = []
    biezaca: tuple[int, int, TypEncji, float] | None = None
    biezaca_klasa: tuple[str, ...] | None = None
    for etykieta, (start, koniec), pewnosc in tokeny:
        if start == koniec:  # token specjalny/wypadek
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            continue
        if not etykieta.startswith(("B-", "I-")):
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            continue
        schemat, klasa = etykieta[:1], etykieta[2:]
        klucz = (klasa,)
        if klucz not in mapa:
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            continue
        if schemat == "B" or klucz != biezaca_klasa:
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            if schemat == "I":
                continue  # I bez swojego B — fragment niepełny, pomijany
            typ = mapa[klucz]
            biezaca, biezaca_klasa = (start, koniec, typ, pewnosc), klucz
        else:  # I kontynuuje bieżącą encję
            assert biezaca is not None
            biezaca = (biezaca[0], koniec, biezaca[2], min(biezaca[3], pewnosc))
    _zamknij(biezaca, wynik)
    return wynik


def _zamknij(
    biezaca: tuple[int, int, TypEncji, float] | None,
    wynik: list[tuple[int, int, TypEncji, float]],
) -> None:
    if biezaca is not None:
        wynik.append(biezaca)
