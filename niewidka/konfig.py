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

# K2d (docs/WYNIK-K2d.md): próg pewności OSOBA poziomów 2-3 (wariant A/B); 0.2 i 0.3
# dawały identyczne wyniki na korpusie 182, przyjęto niższy.
PROG_OSOBA_DOMYSLNY = 0.2

# K4b pkt 2: polityka obrazów w DOCX — bez OCR nie dają się zweryfikować.
# „usun" (domyślnie) usuwa obrazy z ostrzeżeniem w raporcie, „blokuj" odrzuca
# dokument, „zostaw" to świadome ryzyko (obraz zostaje, raport ostrzega).
POLITYKI_OBRAZOW = ("usun", "blokuj", "zostaw")


@dataclass(frozen=True)
class Konfig:
    host: str = "127.0.0.1"
    port: int = 8390
    poziom: int = 1
    prog_osoba: float = PROG_OSOBA_DOMYSLNY
    modele_katalog: Path | None = None
    provider: str = "CPUExecutionProvider"
    klucz_plik: str | None = None
    keyring_usluga: str = "niewidka"
    max_rozmiar_mb: int = 25
    max_rozpakowane_mb: int = 200
    max_tekst_mb: int = 1
    kontrola_blokada: bool = True
    obrazy: str = "usun"
    kolejka: int = 4
    zlecenia: int = 8  # K4b pkt 12: maks. żądań w toku (odrzucane przed parsowaniem body)
    timeout_s: int = 120
    wykrywaj_date: bool = True
    # rejestr wydanych map w pliku (skróty SHA-256 + identyfikatory, bez danych):
    # mapa przywraca się po restarcie programu; None = tylko w obrębie sesji (K4b pkt 7)
    rejestr_map: Path | None = None


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


def _jako_float(env: Mapping[str, str], zmienna: str, domyslna: float) -> float:
    if zmienna not in env:
        return domyslna
    try:
        return float(env[zmienna])
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
    obrazy = env.get("NIEWIDKA_OBRAZY", kontrola.get("obrazy", "usun"))
    if obrazy not in POLITYKI_OBRAZOW:
        raise ValueError(
            f"NIEWIDKA_OBRAZY: nieznana polityka obrazów {obrazy!r}; dozwolone: {', '.join(POLITYKI_OBRAZOW)}"
        )
    host = env.get("NIEWIDKA_HOST", serwer.get("host", "127.0.0.1"))
    # K4b pkt 14: lokalne MVP nasłuchuje wyłącznie na loopbacku — nasłuch LAN
    # udostępniałby odszyfrowanie bez uwierzytelnienia użytkownika (audyt pkt 14)
    if host not in ("127.0.0.1", "localhost", "::1") and not host.startswith("127."):
        raise ValueError(
            f"NIEWIDKA_HOST: dozwolony jest wyłącznie nasłuch na loopbacku (127.0.0.1), jest {host!r}; "
            "udostępnianie w sieci lokalnej wymaga osobnego uwierzytelnienia i autoryzacji odszyfrowania"
        )
    return Konfig(
        host=host,
        port=_jako_int(env, "NIEWIDKA_PORT", int(serwer.get("port", 8390))),
        poziom=_jako_int(env, "NIEWIDKA_POZIOM", int(detekcja.get("poziom", 1))),
        prog_osoba=_jako_float(
            env, "NIEWIDKA_PROG_OSOBA", float(detekcja.get("prog_osoba", PROG_OSOBA_DOMYSLNY))
        ),
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
        obrazy=obrazy,
        kolejka=_jako_int(env, "NIEWIDKA_KOLEJKA", int(limity.get("kolejka", 4))),
        zlecenia=_jako_int(env, "NIEWIDKA_ZLECENIA", int(limity.get("zlecenia", 8))),
        timeout_s=_jako_int(env, "NIEWIDKA_TIMEOUT_S", int(limity.get("timeout_s", 120))),
        wykrywaj_date=_jako_bool(env.get("NIEWIDKA_WYKRYWAJ_DATE", detekcja.get("wykrywaj_date", True))),
        rejestr_map=_jako_sciezka(env, "NIEWIDKA_REJESTR_MAP"),
    )
