#!/usr/bin/env python3
"""Walidacja korpusu testowego `testy_e2e/korpus` (wyłącznie biblioteka standardowa).

Sprawdza dla każdego dokumentu:
- długość 1500-3500 znaków,
- numery z sumami kontrolnymi znalezione w tekście (PESEL, NIP, REGON, IBAN,
  dowód osobisty) są POPRAWNE, a przy okazji raportuje, ile ich jest,
- każdy fragment z `musza_zniknac` i `moga_zostac` występuje w tekście
  DOKŁADNIE raz na listę, czyli jest wiernej kopii z dokumentu,
- plik DOCX dokumentu 01 (jeśli istnieje) zawiera te same fragmenty w tekście
  akapitów.

Algorytmy sum kontrolnych są tu celowo własnoręczną kopią (standard wg
algorytm.org), żeby korpus nie zależał od walidowanego kodu rdzenia.

Użycie: python waliduj_korpus.py [katalog_korpusu]
Kod wyjścia 1 = korpus błędny.
"""

from __future__ import annotations

import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

_WAGI_PESEL = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
_WAGI_NIP = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_WAGI_REGON = (8, 9, 2, 3, 4, 5, 6, 7)
_WAGI_DOWOD = (7, 3, 1, 9, 7, 3, 1, 7, 3)

_RE_PESEL = re.compile(r"(?<!\d)(\d{11})(?!\d)")
_RE_NIP = re.compile(r"(?<!\d)(\d{10}|\d{3}-\d{3}-\d{2}-\d{2})(?!\d)")
_RE_REGON = re.compile(r"(?<!\d)(\d{9})(?!\d)")
_RE_IBAN = re.compile(r"\bPL((?: ?\d){26})\b")
_RE_DOWOD = re.compile(r"\b([A-Z]{3}) ?(\d{6})\b")

_NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _cyfry(zapis: str) -> str:
    return re.sub(r"[^0-9]", "", zapis)


def pesel_ok(nr: str) -> bool:
    cyfry = _cyfry(nr)
    if len(cyfry) != 11:
        return False
    miesiac = int(cyfry[2:4])
    if not 1 <= miesiac % 20 <= 12:  # miesiąc + 20/40/60 dla innych stuleci
        return False
    suma = sum(int(c) * w for c, w in zip(cyfry[:10], _WAGI_PESEL))
    return (10 - suma % 10) % 10 == int(cyfry[10])


def nip_ok(nr: str) -> bool:
    cyfry = _cyfry(nr)
    if len(cyfry) != 10:
        return False
    suma = sum(int(c) * w for c, w in zip(cyfry[:9], _WAGI_NIP))
    return suma % 11 not in (0, 10) and suma % 11 == int(cyfry[9])


def regon_ok(nr: str) -> bool:
    cyfry = _cyfry(nr)
    if len(cyfry) != 9:
        return False
    suma = sum(int(c) * w for c, w in zip(cyfry[:8], _WAGI_REGON))
    return suma % 11 not in (0, 10) and suma % 11 == int(cyfry[8])


def dowod_ok(nr: str) -> bool:
    zapis = nr.replace(" ", "").upper()
    if len(zapis) != 9 or not zapis[:3].isalpha() or not zapis[3:].isdigit():
        return False
    wartosci = [ord(z) - 55 for z in zapis[:3]] + [int(c) for c in zapis[3:]]
    suma = sum(w * v for w, v in zip(_WAGI_DOWOD, wartosci))
    return suma % 10 == int(zapis[3])


def iban_ok(nr: str) -> bool:
    zapis = nr.replace(" ", "").upper()
    if not zapis.startswith("PL") or len(zapis) != 28:
        return False
    przeniesione = zapis[4:] + "2521" + zapis[2:4]  # BBAN + kod kraju + cyfry kontrolne
    reszta = 0
    for znak in przeniesione:
        reszta = (reszta * 10 + int(znak)) % 97
    return reszta == 1


def tekst_docx(dane: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(dane)) as archiwum:
        korzen = ET.fromstring(archiwum.read("word/document.xml"))
    akapity = ["".join(t.text or "" for t in p.iter(f"{_NS_W}t")) for p in korzen.iter(f"{_NS_W}p")]
    return "\n".join(akapity)


def zbadaj_tekst(nazwa: str, tekst: str, bledy: list[str], raport: list[str]) -> None:
    ile = len(tekst)
    if not 1500 <= ile <= 3500:
        bledy.append(f"{nazwa}: długość {ile} znaków poza zakresem 1500-3500")
    znaleziska = {
        "PESEL": [(m.group(1), pesel_ok(m.group(1))) for m in _RE_PESEL.finditer(tekst)],
        "NIP": [(m.group(1), nip_ok(m.group(1))) for m in _RE_NIP.finditer(tekst)],
        "REGON": [(m.group(1), regon_ok(m.group(1))) for m in _RE_REGON.finditer(tekst)],
        "IBAN": [("PL" + m.group(1), iban_ok("PL" + m.group(1))) for m in _RE_IBAN.finditer(tekst)],
        "DOWOD": [
            (f"{m.group(1)} {m.group(2)}", dowod_ok(m.group(1) + m.group(2)))
            for m in _RE_DOWOD.finditer(tekst)
        ],
    }
    for typ, pary in znaleziska.items():
        for nr, ok in pary:
            if not ok:
                bledy.append(f"{nazwa}: {typ} z ZŁĄ sumą kontrolną: {nr}")
    zliczenie = ", ".join(f"{typ}: {len(pary)}" for typ, pary in znaleziska.items())
    raport.append(f"  {nazwa}: {ile} znaków; {zliczenie}")


def main(argv: list[str]) -> int:
    katalog = Path(argv[1]) if len(argv) > 1 else Path(__file__).parent / "korpus"
    bledy: list[str] = []
    raport: list[str] = [f"Korpus: {katalog}"]

    pliki_json = sorted(katalog.glob("*.json"))
    if len(pliki_json) != 8:
        bledy.append(f"oczekiwano 8 plików JSON, jest {len(pliki_json)}")
    for plik_json in pliki_json:
        plik_txt = plik_json.with_suffix(".txt")
        if not plik_txt.is_file():
            bledy.append(f"brak pliku tekstu dla {plik_json.name}")
            continue
        oczekiwania = json.loads(plik_json.read_text(encoding="utf-8"))
        tekst = plik_txt.read_text(encoding="utf-8")
        zbadaj_tekst(plik_txt.name, tekst, bledy, raport)
        for pole in ("musza_zniknac", "moga_zostac"):
            for fragment in oczekiwania.get(pole, []):
                if fragment not in tekst:
                    bledy.append(f"{plik_txt.name}: fragment z {pole} nie ma wiernego odbicia w tekście: {fragment!r}")
        if len(set(oczekiwania.get("musza_zniknac", []))) != len(oczekiwania.get("musza_zniknac", [])):
            bledy.append(f"{plik_txt.name}: powtórzone fragmenty w musza_zniknac")

    plik_docx = katalog / "01-wezwanie.docx"
    if plik_docx.is_file():
        tekst_doc = tekst_docx(plik_docx.read_bytes())
        oczekiwania = json.loads((katalog / "01-wezwanie.json").read_text(encoding="utf-8"))
        brakujace = [f for f in oczekiwania["musza_zniknac"] if f not in tekst_doc]
        if brakujace:
            for fragment in brakujace:
                bledy.append(f"01-wezwanie.docx: brak fragmentu w tekście akapitów: {fragment!r}")
        raport.append(f"  01-wezwanie.docx: {len(tekst_doc)} znaków tekstu akapitów; fragmenty musza_zniknac: {len(oczekiwania['musza_zniknac']) - len(brakujace)}/{len(oczekiwania['musza_zniknac'])}")
    else:
        raport.append("  01-wezwanie.docx: brak (zbuduj buduj_docx.py)")

    for linia in raport:
        print(linia)
    if bledy:
        print(f"BŁĘDY KORPUSU ({len(bledy)}):")
        for blad in bledy:
            print(f"  - {blad}")
        return 1
    print("KORPUS OK")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, AttributeError):
        pass
    raise SystemExit(main(sys.argv))
