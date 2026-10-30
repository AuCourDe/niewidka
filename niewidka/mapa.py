"""Mapa przywracania: JSON szyfrowany AES-256-GCM, przywracanie po (oznaczenie, wariant).
Format: b"NWID" + wersja(1B) + nonce(12B) + długość_id(1B) + id + ciphertext; identyfikator
jest AAD, więc podmiana id w nagłówku psuje tag GCM.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"NWID"
WERSJA = 1
WARIANT_DOMYSLNY = "F1"  # znacznik [PESEL_1] bez sufiksu _Fk mapuje się na F1

WZORZEC_ZNACZNIKA = re.compile(r"\[([A-Z]+)_(\d+)(?:_(F\d+))?\]")


class BladMapy(Exception):
    """Zła/uszkodzona mapa, zły tag GCM, wersja albo niezgodny identyfikator."""


@dataclass
class Wpis:
    typ: str
    oznaczenie: str
    formy: dict[str, str]  # wariant "Fk" -> oryginalna forma powierzchniowa


@dataclass
class Wystapienie:
    kolejny: int  # numer porządkowy do weryfikacji kompletności, nie do dopasowania
    oznaczenie: str
    wariant: str
    oryginal: str


@dataclass
class Mapa:
    identyfikator: str
    utworzono: str
    poziom: int
    wpisy: list[Wpis] = field(default_factory=list)
    wystapienia: list[Wystapienie] = field(default_factory=list)
    wersja: int = WERSJA

    @staticmethod
    def z_slownika(d: dict) -> Mapa:
        try:
            return Mapa(
                wersja=int(d["wersja"]),
                identyfikator=str(d["identyfikator"]),
                utworzono=str(d["utworzono"]),
                poziom=int(d["poziom"]),
                wpisy=[
                    Wpis(str(w["typ"]), str(w["oznaczenie"]), {str(k): str(v) for k, v in w["formy"].items()})
                    for w in d["wpisy"]
                ],
                wystapienia=[
                    Wystapienie(int(w["kolejny"]), str(w["oznaczenie"]), str(w["wariant"]), str(w["oryginal"]))
                    for w in d["wystapienia"]
                ],
            )
        except (KeyError, TypeError, ValueError) as blad:
            raise BladMapy(f"mapa o nieznanym formacie: {blad}") from None


@dataclass(frozen=True)
class Rozbieznosc:
    typ: str  # "znacznik_bez_wpisu" | "wpis_niewykorzystany"
    opis: str


def slownik(mapa: Mapa) -> dict:
    return {
        "wersja": mapa.wersja,
        "identyfikator": mapa.identyfikator,
        "utworzono": mapa.utworzono,
        "poziom": mapa.poziom,
        "wpisy": [
            {"typ": w.typ, "oznaczenie": w.oznaczenie, "formy": dict(w.formy)} for w in mapa.wpisy
        ],
        "wystapienia": [
            {
                "kolejny": w.kolejny,
                "oznaczenie": w.oznaczenie,
                "wariant": w.wariant,
                "oryginal": w.oryginal,
            }
            for w in mapa.wystapienia
        ],
    }


# --- szyfrowanie -------------------------------------------------------------


def naglowek(dane: bytes) -> tuple[int, str]:
    """(wersja, identyfikator) z nagłówka zaszyfrowanej mapy; zły format = BladMapy."""
    if len(dane) < 18 or dane[:4] != MAGIC:
        raise BladMapy("to nie jest mapa Niewidki (nagłówek NWID)")
    wersja = dane[4]
    if wersja != WERSJA:
        raise BladMapy(f"nieznana wersja mapy: {wersja}")
    dlugosc_id = dane[17]
    if len(dane) < 18 + dlugosc_id:
        raise BladMapy("ucięty nagłówek mapy")
    return wersja, dane[18 : 18 + dlugosc_id].decode("utf-8", errors="replace")


def zaszyfruj(mapa: Mapa, klucz: bytes) -> bytes:
    id_bajty = mapa.identyfikator.encode()
    nonce = os.urandom(12)
    szystem = AESGCM(klucz)
    szyfrogram = szystem.encrypt(nonce, json.dumps(slownik(mapa)).encode(), id_bajty)
    return MAGIC + bytes([WERSJA]) + nonce + bytes([len(id_bajty)]) + id_bajty + szyfrogram


def odszyfruj(dane: bytes, klucz: bytes) -> Mapa:
    _, identyfikator = naglowek(dane)
    id_bajty = identyfikator.encode()
    nonce = dane[5:17]
    szyfrogram = dane[18 + len(id_bajty) :]
    try:
        jawna = AESGCM(klucz).decrypt(nonce, szyfrogram, id_bajty)
    except InvalidTag:
        raise BladMapy("mapa uszkodzona, zły klucz albo niezgodny identyfikator") from None
    mapa = Mapa.z_slownika(json.loads(jawna))
    if mapa.identyfikator != identyfikator:
        raise BladMapy("identyfikator w treści niezgodny z nagłówkiem")
    return mapa


# --- przywracanie ------------------------------------------------------------


def znajdz_znaczniki(tekst: str) -> list[tuple[int, int, str, str | None]]:
    """(start, koniec, oznaczenie, wariant|None) znaczników w tekście segmentu."""
    return [
        (m.start(), m.end(), f"{m.group(1)}_{m.group(2)}", m.group(3))
        for m in WZORZEC_ZNACZNIKA.finditer(tekst)
    ]


def przygotuj_zamiany(
    tekst: str, mapa: Mapa
) -> tuple[list[tuple[int, int, str]], list[Rozbieznosc], set[str]]:
    """(zamiany, rozbieżności znaczników, użyte oznaczenia) dla tekstu segmentu."""
    formy = {(w.oznaczenie, wariant): oryginal for w in mapa.wpisy for wariant, oryginal in w.formy.items()}
    rozbieznosci: list[Rozbieznosc] = []
    zamiany: list[tuple[int, int, str]] = []
    uzyte: set[str] = set()
    for start, koniec, oznaczenie, wariant in znajdz_znaczniki(tekst):
        oryginal = formy.get((oznaczenie, wariant or WARIANT_DOMYSLNY))
        if oryginal is None:
            rozbieznosci.append(Rozbieznosc("znacznik_bez_wpisu", tekst[start:koniec]))
            continue
        zamiany.append((start, koniec, oryginal))
        uzyte.add(oznaczenie)
    return zamiany, rozbieznosci, uzyte


def rozbieznosci_wpisow(mapa: Mapa, uzyte: set[str]) -> list[Rozbieznosc]:
    """Wpisy mapy bez żadnej użytej formy (nieużyta forma w częściowo użytym wpisie jest normalna)."""
    return [
        Rozbieznosc("wpis_niewykorzystany", w.oznaczenie) for w in mapa.wpisy if w.oznaczenie not in uzyte
    ]


def przywroc_tekst(tekst: str, mapa: Mapa) -> tuple[str, list[Rozbieznosc]]:
    """Zamiana znaczników na oryginały wg (oznaczenie, wariant); rozbieżności na wyjściu."""
    zamiany, rozbieznosci, uzyte = przygotuj_zamiany(tekst, mapa)
    for start, koniec, oryginal in reversed(zamiany):
        tekst = tekst[:start] + oryginal + tekst[koniec:]
    rozbieznosci.extend(rozbieznosci_wpisow(mapa, uzyte))
    return tekst, rozbieznosci
