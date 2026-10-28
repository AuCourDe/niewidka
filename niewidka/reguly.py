"""Reguły detekcji: wyrażenia regularne + sumy kontrolne (LLD §3).

Walidatory dostają tekst znormalizowany (bez spacji i myślników, wielkimi
literami). Znacznik `suma_kontrolna=True` oznacza najwyższy priorytet przy
scalaniu i pewność 1.0; reguły bez walidatora mają pewność 0.9. Dopasowanie
z BŁĘDNĄ sumą kontrolną nie jest odrzucane — dostaje flagę `podejrzana`
i pewność 0.5 i wchodzi do maskowania (przegląd Astry pkt 14: literówka
w prawdziwym numerze nie może zniknąć cicho).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import stdnum.iban
import stdnum.pl.nip
import stdnum.pl.pesel
import stdnum.pl.regon

from niewidka.model import TypEncji, Zakres

PEWNOŚC_BEZ_SUMY = 0.9
PEWNOŚC_PODEJRZANE = 0.5  # wzorzec pasuje, suma kontrolna błędna (LLD §3)

# Dowód osobisty: python-stdnum go nie obejmuje — własny walidator (LLD §3).
# Wagi 7,3,1,9,7,3,1,7,3; litery A=10..Z=35; suma iloczynów mod 10 równa się
# 4. znakowi (algorytm.org). W narzedzia/numery.py istnieje celowa kopia:
# korpus testowy nie może zależeć od walidowanego kodu rdzenia.
_WAGI_DOWODU = (7, 3, 1, 9, 7, 3, 1, 7, 3)


@dataclass(frozen=True)
class Regula:
    typ: TypEncji
    wzorzec: re.Pattern[str]
    walidator: Callable[[str], bool] | None  # suma kontrolna na znormalizowanym tekście
    suma_kontrolna: bool


def _znormalizuj(zapis: str) -> str:
    return zapis.replace(" ", "").replace("-", "").upper()


def _pesel_ok(zapis: str) -> bool:
    return stdnum.pl.pesel.is_valid(_znormalizuj(zapis))


def _nip_ok(zapis: str) -> bool:
    return stdnum.pl.nip.is_valid(_znormalizuj(zapis))


def _regon_ok(zapis: str) -> bool:
    nr = _znormalizuj(zapis)
    return len(nr) in (9, 14) and stdnum.pl.regon.is_valid(nr)


def _iban_ok(zapis: str) -> bool:
    return stdnum.iban.is_valid(_znormalizuj(zapis))


def _dowod_ok(zapis: str) -> bool:
    nr = _znormalizuj(zapis)
    if len(nr) != 9 or not nr[:3].isalpha() or not nr[3:].isdigit():
        return False
    wartosci = [ord(z) - 55 for z in nr[:3]] + [int(c) for c in nr[3:]]
    return sum(w * waga for w, waga in zip(wartosci, _WAGI_DOWODU)) % 10 == int(nr[3])


# K7b: tania detekcja poziomu 1 dla typów, których wcześniej reguły nie obejmowały.

def _ip_v4_ok(zapis: str) -> bool:
    return all(int(oktet) <= 255 for oktet in zapis.split("."))


def _luhn_ok(zapis: str) -> bool:
    cyfry = [int(z) for z in _znormalizuj(zapis) if z.isdigit()]
    if not 13 <= len(cyfry) <= 19:
        return False
    suma = 0
    for i, cyfra in enumerate(reversed(cyfry)):
        if i % 2:
            cyfra *= 2
            suma += cyfra - 9 if cyfra > 9 else cyfra
        else:
            suma += cyfra
    return suma % 10 == 0


# Miesiące w dopełniaczu (zapis słowny dat).
_MIESIĄCE = (
    "stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia"
    "|września|października|listopada|grudnia"
)

# Miejscowość: słowa z wielkiej litery, także wieloczłonowe („Zielona Góra”,
# „Bielsko-Biała”) — ogon adresu za kodem pocztowym (K2e).
_MIEJSCOWOSC = r"[A-ZŁŚŻŹĆĄĘÓŃ][\w\-]*(?:\s+[A-ZŁŚŻŹĆĄĘÓŃ][\w\-]*)*"
# Kod pocztowy NN-NNN; lookarouny odcinają kody zanurzone w dłuższych ciągach
# (data ISO „1982-05-13”, telefon „123-456-789”).
_KOD = r"(?<![\d-])\d{2}-\d{3}(?![\d-])"
# Słowo nazwy ulicy nie może zacząć się na kodzie pocztowym („al. Pracy 12
# 25-422 Kielce”: bez tego „25” zostaje zjedzone jako numer i kod ginie).
_NIE_KOD = rf"(?!{_KOD})"

REGULY: tuple[Regula, ...] = (
    Regula(
        typ=TypEncji.PESEL,
        wzorzec=re.compile(r"(?<!\d)\d{11}(?!\d)"),
        walidator=_pesel_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.NIP,
        wzorzec=re.compile(r"(?<!\d)\d{3}[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}(?!\d)"),
        walidator=_nip_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.REGON,
        wzorzec=re.compile(r"(?<!\d)\d{9}(?!\d)"),
        walidator=_regon_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.REGON,
        wzorzec=re.compile(r"(?<!\d)\d{14}(?!\d)"),
        walidator=_regon_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.IBAN,
        wzorzec=re.compile(r"(?<![A-Za-z0-9])PL\d{2}(?: ?[A-Z0-9]{4}){6}(?![A-Za-z0-9])"),
        walidator=_iban_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.DOKUMENT,
        wzorzec=re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}[ -]?\d{6}(?![A-Za-z0-9])"),
        walidator=_dowod_ok,
        suma_kontrolna=True,
    ),
    # Telefon PL: prefiks opcjonalny; stacjonarny 2-3-2-2 (w nawiasach albo
    # ze spacjami), komórkowy 3-3-3 (bez prefiksu tylko od cyfry 5-8, żeby nie
    # wchodzić w 9-cyfrowe REGON-y) albo stacjonarny 3-3-3 od 1-4 — ten ostatni
    # WYMAGA separatorów (ciąg 9 cyfr bez spacji to pułapka na REGON; K2b tel-085/086).
    Regula(
        typ=TypEncji.TELEFON,
        wzorzec=re.compile(
            r"(?<![\d+(])(?:\+48[ -]?|0048[ -]?)?"
            r"(?:\(\d{2}\)[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}"
            r"|\d{2}[ -]\d{3}[ -]\d{2}[ -]\d{2}"
            r"|[5-8]\d{2}[ -]?\d{3}[ -]?\d{3}"
            r"|[1-4]\d{2}[ -]\d{3}[ -]\d{3})"
            r"(?!\d)"
        ),
        walidator=None,
        suma_kontrolna=False,
    ),
    # Adres: heurystyka (LLD §3 + K2e) — ciągła całość: od wyróżnika do numeru
    # z lokalem i, jeśli dalej stoi, kod pocztowy z miejscowością (słowa
    # z wielkiej litery, także wieloczłonowe: „Zielona Góra”, „Bielsko-Biała”).
    # Sam „kod miejscowość” bez ulicy też jest adresem. Kod+miejscowość to
    # quasi-identyfikator — zostawienie go jawnego przy zamaskowanej ulicy
    # to wyciek (błąd z żywego testu UI). Zwykłe liczby z myślnikiem
    # („10-15 sztuk”) nie łapią się: kod wymaga trzech cyfr po myślniku
    # i wielkiej litery miejscowości za sobą, a lookarouny odcinają kody
    # zanurzone w dłuższych ciągach (data ISO, telefon).
    Regula(
        typ=TypEncji.ADRES,
        wzorzec=re.compile(
            r"(?:ulica|aleja|osiedle|ul\.|al\.|os\.|plac|pl\.)\s+"
            r"[A-ZŁŚŻŹĆĄĘÓŃ0-9][\w\-]*"
            rf"(?:\s+{_NIE_KOD}[A-ZŁŚŻŹĆĄĘÓŃ0-9][\w\-]*)*"
            rf"\s+{_NIE_KOD}\d+[A-Za-z]?(?:\s*(?:/\s*\d+|m\.\s*\d+))?"
            rf"(?:\s*,?\s*{_KOD}(?:\s+{_MIEJSCOWOSC})?)?"
            rf"|{_KOD}\s+{_MIEJSCOWOSC}"
        ),
        walidator=None,
        suma_kontrolna=False,
    ),
    Regula(
        typ=TypEncji.DATA,
        wzorzec=re.compile(
            rf"(?<![\d./-])(?:\d{{1,2}}[.-]\d{{1,2}}[.-]\d{{4}}"
            rf"|\d{{4}}-\d{{2}}-\d{{2}}"  # ISO RRRR-MM-DD (K2b data-094)
            rf"|\d{{1,2}}\s+(?:{_MIESIĄCE})\s+\d{{4}})(?!\d)"
        ),
        walidator=None,
        suma_kontrolna=False,
    ),
    Regula(
        typ=TypEncji.EMAIL,
        # K4b pkt 13: granica początku (lookbehind) — bez niej długie ciągi bez @
        # cofały kwadratowo z KAŻDEJ pozycji (7 s na 100 tys. znaków); z nią próba
        # startuje wyłącznie na pierwszym znaku ciągu i koszt jest liniowy
        wzorzec=re.compile(
            r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
        ),
        walidator=None,
        suma_kontrolna=False,
    ),
    # K7b: IP v4. Koniec = nie za cyfrą i nie za kropką z cyfrą („1.2.3.4.5" i
    # „.1.2.3.4" nie łapią się); zły oktet (256+) zostaje podejrzanym.
    Regula(
        typ=TypEncji.IP,
        wzorzec=re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)"),
        walidator=_ip_v4_ok,
        suma_kontrolna=False,
    ),
    # K7b: IP v6 — formy pełna (8 grup) i ze skrótem „::". SIMPLIFICATION: bez
    # pełnej gramatyki RFC 4291 (strefy %, formy mieszane); czas „12:45:30" nie
    # przechodzi (brak „::" i mniej niż 8 grup). Rozbudować, gdy pomiar pokaże FN.
    Regula(
        typ=TypEncji.IP,
        wzorzec=re.compile(
            r"(?<![0-9A-Fa-f:])"
            r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"
            r"|(?:[0-9A-Fa-f]{1,4}:){1,7}:(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4})*)?"
            r"|[0-9A-Fa-f]{0,4}::[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4})*"
            r"(?![0-9A-Fa-f:])"
        ),
        walidator=None,
        suma_kontrolna=False,
    ),
    # K7b: karta płatnicza 13-19 cyfr w grupach po 4 (separatory opcjonalne) z
    # sumą Luhna; błędna suma = podejrzana (literówka w prawdziwej karcie nie
    # może zniknąć cicho, jak PESEL). Okno od 13 cyfr nie wchodzi w NIP (10),
    # PESEL (11) i REGON-9; IBAN/REGON-14 z poprawną sumą kontrolną wygrywają
    # etykietę w scalaniu.
    Regula(
        typ=TypEncji.KARTA,
        wzorzec=re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{1,7}(?!\d)"),
        walidator=_luhn_ok,
        suma_kontrolna=True,
    ),
)


def _pewnosc(regula: Regula) -> float:
    return 1.0 if regula.suma_kontrolna else PEWNOŚC_BEZ_SUMY


def znajdz(tekst: str) -> list[Zakres]:
    """Kandydaci ze wszystkich reguł (bez scalania), sortowane wg pozycji.

    Zła suma kontrolna daje encję podejrzaną, nie odrzucenie (Astra pkt 14).
    """
    kandydaci = []
    for regula in REGULY:
        for dopasowanie in regula.wzorzec.finditer(tekst):
            suma_ok = not regula.walidator or regula.walidator(dopasowanie.group(0))
            kandydaci.append(
                Zakres(
                    start=dopasowanie.start(),
                    koniec=dopasowanie.end(),
                    typ=regula.typ,
                    pewnosc=_pewnosc(regula) if suma_ok else PEWNOŚC_PODEJRZANE,
                    zrodlo="regula",
                    suma_kontrolna=regula.suma_kontrolna and suma_ok,
                    podejrzana=not suma_ok,
                )
            )
    return sorted(kandydaci, key=lambda z: (z.start, z.koniec))
