"""Konfiguracja (LLD §14): plik TOML + zmienne środowiskowe; env ma pierwszeństwo.

Nic na sztywno — każdy port, ścieżka, limit i provider idzie z konfiguracji.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DOMYSLNY_PLIK = Path("niewidka.toml")


@dataclass(frozen=True)
class Konfig:
    host: str = "127.0.0.1"
    port: int = 8390
    poziom: int = 1
    modele_katalog: Path | None = None
    provider: str = "CPUExecutionProvider"
    klucz_plik: str | None = None
    keyring_usluga: str = "niewidka"
    max_rozmiar_mb: int = 25
    max_rozpakowane_mb: int = 200
    max_tekst_mb: int = 1
    kontrola_blokada: bool = True
    kolejka: int = 4
    timeout_s: int = 120
    wykrywaj_date: bool = True


def _jako_bool(wartosc: object) -> bool:
    if isinstance(wartosc, bool):
        return wartosc
    return str(wartosc).strip().lower() in ("1", "true", "tak", "yes", "on")


def _jako_int(env: Mapping[str, str], zmienna: str, domyslna: int) -> int:
    if zmienna not in env:
        return domyslna
    try:
        return int(env[zmienna])
    except ValueError:
        raise ValueError(f"{zmienna}: oczekiwano liczby, jest {env[zmienna]!r}") from None


def _jako_sciezka(env: Mapping[str, str], zmienna: str) -> Path | None:
    wartosc = env.get(zmienna)
    return Path(wartosc) if wartosc else None


def wczytaj_konfig(sciezka: Path | None = None, env: Mapping[str, str] | None = None) -> Konfig:
    """TOML z `sciezki` (domyślnie ./niewidka.toml, brak pliku = wartości domyślne),
    nadpisywane zmiennymi NIEWIDKA_* z `env` (domyślnie os.environ)."""
    env = os.environ if env is None else env
    plik = DOMYSLNY_PLIK if sciezka is None else Path(sciezka)
    toml: dict = {}
    if plik.is_file():
        with plik.open("rb") as uchwyt:
            toml = tomllib.load(uchwyt)
    serwer = toml.get("serwer", {})
    detekcja = toml.get("detekcja", {})
    klucze = toml.get("klucze", {})
    limity = toml.get("limity", {})
    kontrola = toml.get("kontrola", {})
    return Konfig(
        host=env.get("NIEWIDKA_HOST", serwer.get("host", "127.0.0.1")),
        port=_jako_int(env, "NIEWIDKA_PORT", int(serwer.get("port", 8390))),
        poziom=_jako_int(env, "NIEWIDKA_POZIOM", int(detekcja.get("poziom", 1))),
        modele_katalog=_jako_sciezka(env, "NIEWIDKA_MODELE_KATALOG")
        or (Path(detekcja["modele_katalog"]) if detekcja.get("modele_katalog") else None),
        provider=env.get("NIEWIDKA_PROVIDER", detekcja.get("provider", "CPUExecutionProvider")),
        klucz_plik=env.get("NIEWIDKA_KLUCZ_PLIK", klucze.get("plik")) or None,
        keyring_usluga=env.get("NIEWIDKA_KEYRING_USLUGA", klucze.get("usluga", "niewidka")),
        max_rozmiar_mb=_jako_int(env, "NIEWIDKA_MAX_ROZMIAR_MB", int(limity.get("rozmiar_mb", 25))),
        max_rozpakowane_mb=_jako_int(
            env, "NIEWIDKA_MAX_ROZPAKOWANE_MB", int(limity.get("rozpakowane_mb", 200))
        ),
        max_tekst_mb=_jako_int(env, "NIEWIDKA_MAX_TEKST_MB", int(limity.get("tekst_mb", 1))),
        kontrola_blokada=_jako_bool(env.get("NIEWIDKA_KONTROLA_BLOKADA", kontrola.get("blokada", True))),
        kolejka=_jako_int(env, "NIEWIDKA_KOLEJKA", int(limity.get("kolejka", 4))),
        timeout_s=_jako_int(env, "NIEWIDKA_TIMEOUT_S", int(limity.get("timeout_s", 120))),
        wykrywaj_date=_jako_bool(env.get("NIEWIDKA_WYKRYWAJ_DATE", detekcja.get("wykrywaj_date", True))),
    )
