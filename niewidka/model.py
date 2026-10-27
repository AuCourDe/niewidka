"""Model danych rdzenia (LLD §2). Offsety zawsze w znakach segmentu."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class TypEncji(enum.StrEnum):
    OSOBA = "OSOBA"
    PESEL = "PESEL"
    NIP = "NIP"
    REGON = "REGON"
    ADRES = "ADRES"
    TELEFON = "TELEFON"
    EMAIL = "EMAIL"
    IBAN = "IBAN"
    DOKUMENT = "DOKUMENT"
    DATA = "DATA"
    INNE = "INNE"


@dataclass
class Zakres:
    start: int  # znak w segment.tekst, włącznie
    koniec: int  # wyłącznie
    typ: TypEncji
    pewnosc: float  # 0..1; reguły z sumą kontrolną = 1.0
    zrodlo: str  # "regula", "onnx:bardsai", "onnx:lfm25"
    suma_kontrolna: bool = False


@dataclass
class Encja:
    zakres: Zakres
    tekst: str  # tekst powierzchniowy znaleziska
    oznaczenie: str | None = None  # "OSOBA_1" po grupowaniu i numeracji
    klucz_grupy: str | None = None  # klucz grupowania osób


@dataclass
class RunInfo:
    tekst: str
    element: Any  # uchwyt węzła (lxml/run python-docx/komórka arkusza)


@dataclass
class Segment:
    tekst: str  # tekst złączony z runów
    runs: list[RunInfo] = field(default_factory=list)
    starts: list[int] = field(default_factory=list)  # starts[i] = offset runs[i].tekst


@dataclass
class Dokument:
    format: str  # "docx", "odt", ...
    segmenty: list[Segment]
