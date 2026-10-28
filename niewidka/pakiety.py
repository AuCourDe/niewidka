"""Pakiety modeli (K7b): katalog wag pobierany PO instalacji, nie w paczce.

Katalog pakietów: `niewidka/dane/pakiety.json` (pliki z URL względem źródła,
rozmiarem i SHA-256 przypiętym do wersji). Pobieranie httpx strumieniowo
z wznawianiem (Range), weryfikacja SHA-256 PRZED użyciem (zły hash = usunięcie
+ `BladPakietu`), atomowe przeniesienie z pliku częściowego. Lustro IT:
NIEWIDKA_MODELE_ZRODLO na dowolny serwer plików albo `instaluj_z_katalogu`
dla środowisk offline. Katalog wag: %LOCALAPPDATA%\\Niewidka\\modele (Windows),
XDG data home (Linux/Mac), nadpisywany NIEWIDKA_MODELE_KATALOG.

Pobierane są wyłącznie pliki modelu (ONNX), tokenizer i konfiguracja JSON;
żaden pobrany plik nie jest wykonywany (brak importu, brak pickle — ONNX czyta
wyłącznie onnxruntime), a JSON parsuje json.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

KATALOG_PAKIETOW = Path(__file__).resolve().parent / "dane" / "pakiety.json"
ZRODLO_DOMYSLNE = "https://github.com/AuCourDe/niewidka/releases/latest/download"
CZESCIOWY = ".częściowy"


class BladPakietu(Exception):
    """Awaria pobrania albo weryfikacji pakietu — fail-closed, plik nie trafia
    do katalogu wag, dopóki nie ma poprawnego SHA-256."""


@dataclass(frozen=True)
class PlikPakietu:
    nazwa: str  # ścieżka względem katalogu wag (np. "lfm25/q4-bl32/model.onnx")
    zrodlo: str  # nazwa pliku w źródle (załącznik wydania / lustro IT)
    rozmiar: int
    sha256: str


@dataclass(frozen=True)
class Pakiet:
    id: str
    nazwa: str
    opis: str
    wymagany: bool
    poziomy: list[int]
    katalog_rel: str  # podkatalog z manifest.json ("" = katalog wag główny)
    pliki: list[PlikPakietu]
    wymaga: str | None = None  # pakiet potrzebny do działania tego pakietu

    @property
    def rozmiar(self) -> int:
        return sum(p.rozmiar for p in self.pliki)


def wczytaj_pakiety(plik: Path = KATALOG_PAKIETOW) -> list[Pakiet]:
    dane = json.loads(plik.read_text(encoding="utf-8"))
    return [
        Pakiet(
            id=wpis["id"],
            nazwa=wpis["nazwa"],
            opis=wpis["opis"],
            wymagany=wpis.get("wymagany", False),
            poziomy=wpis.get("poziomy", []),
            katalog_rel=wpis.get("katalog_rel", ""),
            wymaga=wpis.get("wymaga"),
            pliki=[
                PlikPakietu(
                    nazwa=p["nazwa"], zrodlo=p["zrodlo"], rozmiar=p["rozmiar"], sha256=p["sha256"]
                )
                for p in wpis["pliki"]
            ],
        )
        for wpis in dane["pakiety"]
    ]


def katalog_modeli(env: dict[str, str] | None = None) -> Path:
    """Katalog wag: env wygrywa; domyślnie profil użytkownika (nie katalog
    programu — paczka instalacyjna nie zawiera wag i tam ich nie pisze)."""
    env = os.environ if env is None else env
    if env.get("NIEWIDKA_MODELE_KATALOG"):
        return Path(env["NIEWIDKA_MODELE_KATALOG"])
    if sys.platform == "win32":
        baza = Path(env.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return baza / "Niewidka" / "modele"
    baza = Path(env.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return baza / "Niewidka" / "modele"


def zrodlo(env: dict[str, str] | None = None) -> str:
    """Baza URL pobierania: NIEWIDKA_MODELE_ZRODLO albo załączniki wydania."""
    env = os.environ if env is None else env
    return env.get("NIEWIDKA_MODELE_ZRODLO") or ZRODLO_DOMYSLNE


def _sha256(plik: Path) -> str:
    skrot = hashlib.sha256()
    with plik.open("rb") as uchwyt:
        for kawalek in iter(lambda: uchwyt.read(1 << 20), b""):
            skrot.update(kawalek)
    return skrot.hexdigest()


def stan(pakiet: Pakiet, katalog: Path) -> str:
    """brak = choć jednego pliku nie ma; uszkodzony = pliki są, hash rozbieżny;
    zainstalowany = wszystkie pliki zgodne z SHA-256 z katalogu pakietów."""
    braki = 0
    uszkodzone = 0
    for plik in pakiet.pliki:
        cel = katalog / plik.nazwa
        if not cel.is_file():
            braki += 1
        elif _sha256(cel) != plik.sha256:
            uszkodzone += 1
    if uszkodzone:
        return "uszkodzony"
    return "brak" if braki else "zainstalowany"


def _zapisz_atomowo(czesciowy: Path, cel: Path, suma_oczekiwana: str) -> None:
    if _sha256(czesciowy) != suma_oczekiwana:
        czesciowy.unlink(missing_ok=True)
        raise BladPakietu(f"SHA-256 niezgodny dla {cel.name}; plik usunięty")
    cel.parent.mkdir(parents=True, exist_ok=True)
    os.replace(czesciowy, cel)


def _podziel_postep(postep, rozmiary: list[int]):
    """Przelicza postęp per plik na postęp całego pakietu (bajty całości)."""
    if postep is None:
        return None
    calosc = sum(rozmiary)
    licznik = {"gotowe": 0}

    def wywolaj(pobrane: int, razem: int) -> None:
        postep(licznik["gotowe"] + pobrane, calosc)

    def po_pliku(rozmiar: int) -> None:
        licznik["gotowe"] += rozmiar

    return wywolaj, po_pliku


def _pobierz_plik(
    klient: httpx.Client,
    url: str,
    cel: Path,
    suma_oczekiwana: str,
    postep=None,
) -> None:
    """Strumieniowe pobranie jednego pliku z wznawianiem; hash przed użyciem."""
    czesciowy = cel.with_name(cel.name + CZESCIOWY)
    naglowki = {}
    start = czesciowy.stat().st_size if czesciowy.is_file() else 0
    if start:
        naglowki["range"] = f"bytes={start}-"
    cel.parent.mkdir(parents=True, exist_ok=True)
    with klient.stream("GET", url, headers=naglowki, follow_redirects=True) as odpowiedz:
        odpowiedz.raise_for_status()
        if odpowiedz.status_code != 206:
            start = 0  # serwer bez Range: od nowa
            czesciowy.unlink(missing_ok=True)
        try:
            z = int(odpowiedz.headers.get("content-length", "0"))
        except ValueError:
            z = 0
        razem = start + z
        # przerwane pobieranie zostawia częściowy: kolejne pobranie wznowi
        with czesciowy.open("ab" if start else "wb") as uchwyt:
            gotowe = start
            for kawalek in odpowiedz.iter_bytes():
                uchwyt.write(kawalek)
                gotowe += len(kawalek)
                if postep is not None:
                    postep(gotowe, razem)
    _zapisz_atomowo(czesciowy, cel, suma_oczekiwana)


def _zapisz_manifest(pakiet: Pakiet, katalog: Path) -> None:
    katalog_pakietu = katalog / pakiet.katalog_rel if pakiet.katalog_rel else katalog
    manifest = {
        "pakiet": pakiet.id,
        "pliki": {Path(p.nazwa).name: p.sha256 for p in pakiet.pliki},
    }
    (katalog_pakietu / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def pobierz(
    pakiet: Pakiet,
    katalog: Path,
    zrodlo_bazowe: str,
    klient: httpx.Client | None = None,
    postep=None,
) -> None:
    """Pobiera wszystkie pliki pakietu; pomija te już zgodne z SHA-256."""
    wlasny = klient is None
    klient = klient or httpx.Client(follow_redirects=True, timeout=600)
    try:
        para = _podziel_postep(postep, [p.rozmiar for p in pakiet.pliki])
        postep_pliku, po_pliku = para if para else (None, None)
        for plik in pakiet.pliki:
            cel = katalog / plik.nazwa
            if cel.is_file() and _sha256(cel) == plik.sha256:
                if po_pliku is not None:
                    po_pliku(plik.rozmiar)
                continue
            _pobierz_plik(
                klient,
                f"{zrodlo_bazowe.rstrip('/')}/{plik.zrodlo}",
                cel,
                plik.sha256,
                postep=postep_pliku,
            )
            if po_pliku is not None:
                po_pliku(cel.stat().st_size)
        _zapisz_manifest(pakiet, katalog)
    finally:
        if wlasny:
            klient.close()


def usun(pakiet: Pakiet, katalog: Path) -> None:
    """Usuwa pliki pakietu i jego manifest; puste katalogi sprząta do roota."""
    for plik in pakiet.pliki:
        (katalog / plik.nazwa).unlink(missing_ok=True)
    katalog_pakietu = katalog / pakiet.katalog_rel if pakiet.katalog_rel else katalog
    manifest = katalog_pakietu / "manifest.json"
    if manifest.is_file():
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("pakiet") == pakiet.id:
                manifest.unlink()
        except (OSError, ValueError):
            pass
    biezacy = katalog_pakietu
    while biezacy != katalog and biezacy != biezacy.parent:
        try:
            biezacy.rmdir()
        except OSError:
            break
        biezacy = biezacy.parent


def instaluj_z_katalogu(
    pakiet: Pakiet,
    katalog: Path,
    zrodlo_katalog: Path,
    postep=None,
) -> None:
    """Instalacja offline (IT): katalog z plikami o nazwach jak w źródle;
    weryfikacja SHA-256 przed zapisem, atomowo jak przy pobieraniu."""
    for plik in pakiet.pliki:
        wzor = zrodlo_katalog / plik.zrodlo
        if not wzor.is_file():
            raise BladPakietu(f"brak pliku {plik.zrodlo} w katalogu źródłowym")
        cel = katalog / plik.nazwa
        cel.parent.mkdir(parents=True, exist_ok=True)
        czesciowy = cel.with_name(cel.name + CZESCIOWY)
        shutil.copyfile(wzor, czesciowy)
        _zapisz_atomowo(czesciowy, cel, plik.sha256)
        if postep is not None:
            postep(plik.rozmiar, pakiet.rozmiar)
    _zapisz_manifest(pakiet, katalog)
