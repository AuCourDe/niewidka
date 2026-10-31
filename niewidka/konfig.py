"""Configuration: TOML file + environment variables; env takes precedence.

Nothing hardcoded - every port, path, limit and provider comes from configuration.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DOMYSLNY_PLIK = Path("niewidka.toml")

# OSOBA confidence threshold for levels 2-3 (variant A/B); 0.2 and 0.3
# gave identical results on the 182 corpus, the lower one was chosen.
PROG_OSOBA_DOMYSLNY = 0.2

# image policy in DOCX - they cannot be verified without OCR.
# "usun" (default) removes images with a warning in the report, "blokuj" rejects
# the document, "zostaw" is a deliberate risk (the image stays, the report warns).
POLITYKI_OBRAZOW = ("usun", "blokuj", "zostaw")


def host_w_adresie(host: str) -> str:
    """Host to insert into a URL: IPv6 addresses in square brackets."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def host_z_naglowka(naglowek: str) -> str:
    """Host name from the Host header (without port and without IPv6 brackets)."""
    if naglowek.startswith("["):
        return naglowek[1:].split("]")[0]
    return naglowek.split(":")[0]


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
    zlecenia: int = 8  # max requests in progress (rejected before body parsing)
    timeout_s: int = 120
    wykrywaj_date: bool = True
    # registry of issued maps in a file (SHA-256 digests + identifiers, no data):
    # the map can be restored after a program restart; None = within the session only
    rejestr_map: Path | None = None
    # map store: automatic saving of the encrypted
    # map with retention in days; 0 = no automatic saving (downloading the file remains)
    mapy_retencja_dni: int = 30
    mapy_katalog: Path | None = None  # None = katalog_danych()/"mapy" (filled in by create_app)
    # retention and a manual "Usuń" affect the program's store;
    # only this option removes the map from the issued-map registry (downloaded copies stop working)
    mapy_uniewaznij_pobrane: bool = False
    # detection memory for preview corrections: RAM only, last jobs, short-lived
    poprawki_maks_zadan: int = 4
    poprawki_ttl_s: int = 900
    aktualizacje_tryb: str | None = None
    # fixed lists (niewidka/listy.py): user file (None = katalog_danych()/"listy.json"),
    # administrator list and a lock on user editing
    listy_plik: Path | None = None
    listy_zawsze: tuple[str, ...] = ()
    listy_nigdy: tuple[str, ...] = ()
    listy_tylko_administrator: bool = False
    # ONNX compute threads (intra_op_num_threads); 0 = onnxruntime decides
    watki: int = 0
    # central inference server (docs/SERWER-INFERENCJI.md): empty address = local models.
    # Token: only the path of the secrets file, never the value.
    inferencja_adres: str | None = None
    inferencja_token_plik: Path | None = None
    inferencja_ca_plik: Path | None = None
    inferencja_timeout_s: int = 60
    inferencja_zezwol_bez_tls: bool = False


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
    """TOML from `sciezki` (default ./niewidka.toml, no file = defaults),
    overridden by NIEWIDKA_* variables from `env` (default os.environ)."""
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
    aktualizacje = toml.get("aktualizacje", {})
    aktualizacje_tryb = env.get("NIEWIDKA_AKTUALIZACJE", aktualizacje.get("tryb"))
    if aktualizacje_tryb is not None:
        dozwolone_tryby = ("reczne", "sprawdzaj", "automatyczne", "wylaczone")
        if aktualizacje_tryb not in dozwolone_tryby:
            raise ValueError(
                f"NIEWIDKA_AKTUALIZACJE: nieznany tryb {aktualizacje_tryb!r}; dozwolone: {', '.join(dozwolone_tryby)}"
            )
    obrazy = env.get("NIEWIDKA_OBRAZY", kontrola.get("obrazy", "usun"))
    if obrazy not in POLITYKI_OBRAZOW:
        raise ValueError(
            f"NIEWIDKA_OBRAZY: nieznana polityka obrazów {obrazy!r}; dozwolone: {', '.join(POLITYKI_OBRAZOW)}"
        )
    mapy = toml.get("mapy", {})
    poprawki = toml.get("poprawki", {})
    listy = toml.get("listy", {})
    inferencja = toml.get("inferencja", {})
    mapy_retencja_dni = _jako_int(env, "NIEWIDKA_MAPY_RETENCJA_DNI", int(mapy.get("retencja_dni", 30)))
    if mapy_retencja_dni < 0:
        raise ValueError(
            f"NIEWIDKA_MAPY_RETENCJA_DNI: retencja nie może być ujemna, jest {mapy_retencja_dni}; "
            "0 oznacza brak automatycznego zapisu map"
        )
    host = env.get("NIEWIDKA_HOST", serwer.get("host", "127.0.0.1"))
    # the local MVP listens on loopback only - a LAN listener
    # would expose decryption without user authentication
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
        mapy_retencja_dni=mapy_retencja_dni,
        mapy_katalog=_jako_sciezka(env, "NIEWIDKA_MAPY_KATALOG")
        or (Path(mapy["katalog"]) if mapy.get("katalog") else None),
        mapy_uniewaznij_pobrane=_jako_bool(
            env.get("NIEWIDKA_MAPY_UNIEWAZNIJ_POBRANE", mapy.get("uniewaznij_pobrane", False))
        ),
        poprawki_maks_zadan=_jako_int(
            env, "NIEWIDKA_POPRAWKI_MAKS_ZADAN", int(poprawki.get("maks_zadan", 4))
        ),
        poprawki_ttl_s=_jako_int(env, "NIEWIDKA_POPRAWKI_TTL_S", int(poprawki.get("ttl_s", 900))),
        aktualizacje_tryb=aktualizacje_tryb,
        listy_plik=_jako_sciezka(env, "NIEWIDKA_LISTY_PLIK")
        or (Path(listy["plik"]) if listy.get("plik") else None),
        listy_zawsze=tuple(listy.get("zawsze", ())),
        listy_nigdy=tuple(listy.get("nigdy", ())),
        listy_tylko_administrator=_jako_bool(
            env.get("NIEWIDKA_LISTY_TYLKO_ADMINISTRATOR", listy.get("tylko_administrator", False))
        ),
        watki=_jako_int(env, "NIEWIDKA_WATKI", int(detekcja.get("watki", 0))),
        inferencja_adres=(env.get("NIEWIDKA_INFERENCJA_ADRES", inferencja.get("adres")) or "").strip()
        or None,
        inferencja_token_plik=_jako_sciezka(env, "NIEWIDKA_INFERENCJA_TOKEN_PLIK")
        or (Path(inferencja["token_plik"]) if inferencja.get("token_plik") else None),
        inferencja_ca_plik=_jako_sciezka(env, "NIEWIDKA_INFERENCJA_CA_PLIK")
        or (Path(inferencja["ca_plik"]) if inferencja.get("ca_plik") else None),
        inferencja_timeout_s=_jako_int(
            env, "NIEWIDKA_INFERENCJA_TIMEOUT_S", int(inferencja.get("timeout_s", 60))
        ),
        inferencja_zezwol_bez_tls=_jako_bool(
            env.get("NIEWIDKA_INFERENCJA_ZEZWOL_BEZ_TLS", inferencja.get("zezwol_bez_tls", False))
        ),
    )
