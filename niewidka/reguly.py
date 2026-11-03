"""Detection rules: regular expressions + checksums. Validators get normalized
text; a valid sum = confidence 1.0 and top priority, a wrong one = a `podejrzana`
entity (0.5), not a rejection (a typo in a number must not vanish silently)."""

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
PEWNOŚC_PODEJRZANE = 0.5  # pattern matches, checksum wrong

# ID card: python-stdnum does not cover it - own validator.
# Weights 7,3,1,9,7,3,1,7,3; letters A=10..Z=35; the sum of products mod 10 equals the
# 4th character (algorytm.org). A deliberate copy exists in narzedzia/numery.py:
# the test corpus must not depend on the core code it validates.
_WAGI_DOWODU = (7, 3, 1, 9, 7, 3, 1, 7, 3)


@dataclass(frozen=True)
class Regula:
    typ: TypEncji
    wzorzec: re.Pattern[str]
    walidator: Callable[[str], bool] | None  # checksum on the normalized text
    suma_kontrolna: bool


def _znormalizuj(zapis: str) -> str:
    return re.sub(r"[   -]", "", zapis).upper()


def _pesel_ok(zapis: str) -> bool:
    return stdnum.pl.pesel.is_valid(_znormalizuj(zapis))


def _nip_ok(zapis: str) -> bool:
    return stdnum.pl.nip.is_valid(_znormalizuj(zapis))


def _regon_ok(zapis: str) -> bool:
    nr = _znormalizuj(zapis)
    return len(nr) in (9, 14) and stdnum.pl.regon.is_valid(nr)


def _konto_ok(zapis: str) -> bool:
    """IBAN or the domestic NRB (no country code): both carry the IBAN sum of "PL" + 26 digits."""
    nr = _znormalizuj(zapis).removeprefix("PL")
    return len(nr) == 26 and nr.isdigit() and stdnum.iban.is_valid("PL" + nr)


# Currency codes before an amount ("PLN 100000") look like an ID card series, and some amounts
# even pass the sum: such a match is only a doubt, masked by default and correctable.
_WALUTY = frozenset({"PLN", "EUR", "USD", "GBP", "CHF"})


def _dowod_ok(zapis: str) -> bool:
    nr = _znormalizuj(zapis)
    if len(nr) != 9 or not nr[:3].isalpha() or not nr[3:].isdigit() or nr[:3] in _WALUTY:
        return False
    wartosci = [ord(z) - 55 for z in nr[:3]] + [int(c) for c in nr[3:]]
    return sum(w * waga for w, waga in zip(wartosci, _WAGI_DOWODU)) % 10 == 0


# cheap level-1 detection for types the rules did not cover before.

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


# Months in the genitive case (written-out dates).
_MIESIĄCE = (
    "stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia"
    "|września|października|listopada|grudnia"
)

# Locality: capitalized words, also multi-part ("Zielona Góra",
# "Bielsko-Biała") - the tail of an address after the postal code. Only on one line:
# with \s+ it ate the next line of a letter ("Warszawa\n\nDotyczy").
_MIEJSCOWOSC = r"[A-ZŁŚŻŹĆĄĘÓŃ][\w\-]*(?:[ \t\u00a0\u202f]+[A-ZŁŚŻŹĆĄĘÓŃ][\w\-]*)*"
# Postal code NN-NNN; lookarounds cut off codes embedded in longer strings
# (ISO date "1982-05-13", phone "123-456-789").
_KOD = r"(?<![\d-])\d{2}-\d{3}(?![\d-])"
# A street name word must not start on the postal code ("al. Pracy 12
# 25-422 Kielce": without this "25" is eaten as a number and the code is lost).
_NIE_KOD = rf"(?!{_KOD})"
# Account number: "PL61 1090 ...", "PL 61 1090 ...", the NRB "61 1090 1014 ..." without the
# country code, the same digits in IBAN print groups ("6110 9010 ... 74") or with no gaps.
_ODSTEP = r"[   -]?"
_KONTO = (
    rf"(?<![A-Za-z0-9])(?:(?:PL ?)?\d{{2}}(?:{_ODSTEP}\d{{4}}){{6}}"
    rf"|\d{{4}}(?:{_ODSTEP}\d{{4}}){{5}}{_ODSTEP}\d{{2}})(?![A-Za-z0-9])"
)

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
        wzorzec=re.compile(_KONTO),
        walidator=_konto_ok,
        suma_kontrolna=True,
    ),
    Regula(
        typ=TypEncji.DOKUMENT,
        wzorzec=re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}[ -]?\d{6}(?![A-Za-z0-9])"),
        walidator=_dowod_ok,
        suma_kontrolna=True,
    ),
    # passport: two letters + seven digits. No checksum we can verify independently, so a match
    # is masked with the confidence of a pattern and the user may take it back.
    Regula(
        typ=TypEncji.DOKUMENT,
        wzorzec=re.compile(r"(?<![A-Za-z0-9])[A-Z]{2} ?\d{7}(?![A-Za-z0-9])"),
        walidator=None,
        suma_kontrolna=False,
    ),
    # PL phone: optional prefix; landline 2-3-2-2 (in parentheses or
    # with spaces), mobile 3-3-3 (without a prefix only from digit 5-8, so as not to
    # enter 9-digit REGONs) or landline 3-3-3 from 1-4 - the latter
    # REQUIRES separators (a string of 9 digits without spaces is a REGON trap).
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
    # Address: a heuristic - one continuous whole: from the marker to the number
    # with the unit and, if it follows, the postal code with the locality (words
    # capitalized, also multi-part: "Zielona Góra", "Bielsko-Biała").
    # A bare "code locality" without a street is an address too. Code+locality is a
    # quasi-identifier - leaving it visible next to a masked street
    # is a leak. Ordinary numbers with a hyphen
    # ("10-15 sztuk") are not caught: the code needs three digits after the hyphen
    # and a capitalized locality after it, and lookarounds cut off codes
    # embedded in longer strings (ISO date, phone).
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
            rf"|\d{{4}}-\d{{2}}-\d{{2}}"  # ISO YYYY-MM-DD
            rf"|\d{{1,2}}\s+(?:{_MIESIĄCE})\s+\d{{4}})(?!\d)"
        ),
        walidator=None,
        suma_kontrolna=False,
    ),
    Regula(
        typ=TypEncji.EMAIL,
        # start boundary (lookbehind) - without it long strings without @
        # backtracked quadratically from EVERY position (7 s per 100k characters); with it the attempt
        # starts only at the first character of the string and the cost is linear
        wzorzec=re.compile(
            r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
        ),
        walidator=None,
        suma_kontrolna=False,
    ),
    # IP v4. End = not before a digit and not before a dot followed by a digit ("1.2.3.4.5" and
    # ".1.2.3.4" are not caught); a bad octet (256+) stays suspicious.
    Regula(
        typ=TypEncji.IP,
        wzorzec=re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)"),
        walidator=_ip_v4_ok,
        suma_kontrolna=False,
    ),
    # IP v6 - full forms (8 groups) and with the "::" abbreviation. SIMPLIFICATION: no
    # full RFC 4291 grammar (zones %, mixed forms); the time "12:45:30" does not
    # pass (no "::" and fewer than 8 groups). Extend when measurement shows FN.
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
    # payment card 13-19 digits in groups of 4 (separators optional) with
    # a Luhn sum; a wrong sum = suspicious (a typo in a real card must not
    # vanish silently, like a PESEL). A window from 13 digits does not enter NIP (10),
    # PESEL (11) and REGON-9; IBAN/REGON-14 with a valid checksum win the
    # label in merging.
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
    """Candidates from all rules (without merging), sorted by position.

        A wrong checksum gives a suspicious entity, not a rejection.
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
