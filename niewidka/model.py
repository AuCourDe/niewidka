"""Core data model. Offsets are always in segment characters."""

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
    # new types (rules: IP and a card with the Luhn checksum; the Extended LFM2.5 package
    # adds SWIFT and LOGIN where the rules are silent).
    IP = "IP"
    KARTA = "KARTA"
    SWIFT = "SWIFT"
    LOGIN = "LOGIN"
    INNE = "INNE"


@dataclass
class Zakres:
    start: int  # character index in segment.tekst, inclusive
    koniec: int  # exclusive
    typ: TypEncji
    pewnosc: float  # 0..1; rules with a checksum = 1.0, suspicious = 0.5
    zrodlo: str  # "regula", "onnx:bardsai", "onnx:lfm25"
    suma_kontrolna: bool = False
    podejrzana: bool = False  # pattern matches, checksum wrong


@dataclass
class Encja:
    zakres: Zakres
    tekst: str  # surface text of the finding
    oznaczenie: str | None = None  # "OSOBA_1" after grouping and numbering
    klucz_grupy: str | None = None  # person grouping key
    wariant: str | None = None  # "F2" - stable number of the surface form (people)


@dataclass
class RunInfo:
    tekst: str
    element: Any  # node handle (lxml / python-docx run / spreadsheet cell)


@dataclass
class Segment:
    tekst: str  # text joined from runs
    runs: list[RunInfo] = field(default_factory=list)
    starts: list[int] = field(default_factory=list)  # starts[i] = offset of runs[i].tekst


@dataclass
class Dokument:
    format: str  # "docx", "odt", ...
    segmenty: list[Segment]
    zasoby: Any = None  # format adapter state (package parts, XML tree)
