"""System aktualizacji modeli (K7/akt, docs/MAPY-I-AKTUALIZACJE.md §5, §8 w. 7-8, §9 w. 6).

- Podpis Ed25519 katalogu pakietów, weryfikacja wielu kluczy publicznych (rotacja).
- Wersjonowanie katalogu (wersja_katalogu > znanej) i ochrona przed rollbackiem.
- Stan błędu integralności (fail-closed do katalogu wbudowanego, ale widoczny w UI i API).
- Próbka kontrolna (probka-kontrolna.json z musi_wykryc i nie_moze_wykryc).
- Instalacja atomowa z katalogiem przejściowym (.nowe) i kopią bezpieczeństwa (.poprzednie).
- Cofnięcie z blokadą min_wersja.
- Tryby aktualizacji: reczne, sprawdzaj (domyślny, raz na dobę), automatyczne, wylaczone.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import shutil
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from niewidka.detektory import zbuduj_poziom
from niewidka.pakiety import (
    KATALOG_PAKIETOW,
    BladPakietu,
    MenedzerPakietow,
    Pakiet,
    _waliduj_przekierowanie,
    odczytaj_zainstalowana_wersje,
    pobierz,
    wczytaj_pakiety,
    wczytaj_wersje_katalogu,
)

logger = logging.getLogger("niewidka.aktualizacje")

KLUCZ_PUBLICZNY_DOMYSLNY = Path(__file__).parent / "dane" / "klucz-katalogu.pub"
PROBKA_KONTROLNA_DOMYSLNA = Path(__file__).parent / "dane" / "probka-kontrolna.json"
PLIK_USTAWIEN = "ustawienia.json"
PLIK_KATALOGU_DANYCH = "katalog-pakietow.json"
PLIK_PODPISU_DANYCH = "katalog-pakietow.json.sig"
LIMIT_KATALOGU_BAJTOW = 1024 * 1024  # 1 MB
TRYBY_AKTUALIZACJI = ("reczne", "sprawdzaj", "automatyczne", "wylaczone")
TRYB_DOMYSLNY = "sprawdzaj"
DOBA_SEKUNDY = 86400


class BladAktualizacji(Exception):
    """Błąd logiki lub weryfikacji aktualizacji."""


class BladIntegralnosci(BladAktualizacji):
    """Niezgodny podpis lub uszkodzony katalog pakietów."""


class TrybNarzucony(BladAktualizacji):
    """Próba zmiany trybu zablokowana przez konfigurację administratora."""


def wczytaj_klucze_publiczne(
    zrodlo: Path | str | list[str] | None = None,
) -> list[ed25519.Ed25519PublicKey]:
    """Wczytuje listę kluczy publicznych Ed25519 (rotacja: po jednym base64 w linii)."""
    linie: list[str] = []
    if zrodlo is None or isinstance(zrodlo, Path):
        sciezka = KLUCZ_PUBLICZNY_DOMYSLNY if zrodlo is None else zrodlo
        if not sciezka.is_file():
            return []
        linie = sciezka.read_text(encoding="utf-8").splitlines()
    elif isinstance(zrodlo, str):
        linie = zrodlo.splitlines()
    elif isinstance(zrodlo, list):
        linie = zrodlo

    klucze: list[ed25519.Ed25519PublicKey] = []
    for linia in linie:
        czysta = linia.strip()
        if not czysta or czysta.startswith("#"):
            continue
        try:
            surowe = base64.b64decode(czysta)
            if len(surowe) == 32:
                klucze.append(ed25519.Ed25519PublicKey.from_public_bytes(surowe))
        except (ValueError, binascii.Error):
            continue
    return klucze


def weryfikuj_podpis(
    dane: bytes,
    podpis: bytes,
    klucze: list[ed25519.Ed25519PublicKey],
) -> bool:
    """Weryfikuje podpis Ed25519 względem listy zaufanych kluczy publicznych."""
    if not klucze:
        return False
    # Obsługa podpisu w surowych 64 bajtach lub base64
    surowy_podpis = podpis
    if len(podpis) != 64:
        try:
            zdekodowany = base64.b64decode(podpis.strip())
            if len(zdekodowany) == 64:
                surowy_podpis = zdekodowany
        except (ValueError, binascii.Error):
            pass

    if len(surowy_podpis) != 64:
        return False

    for klucz in klucze:
        try:
            klucz.verify(surowy_podpis, dane)
            return True
        except InvalidSignature:
            continue
    return False


def podpisz_dane(dane: bytes, klucz_prywatny: ed25519.Ed25519PrivateKey) -> bytes:
    """Tworzy surowy 64-bajtowy podpis Ed25519."""
    return klucz_prywatny.sign(dane)


def klucz_publiczny_do_b64(klucz_publiczny: ed25519.Ed25519PublicKey) -> str:
    """Zwraca klucz publiczny w formacie base64 surowych bajtów."""
    surowe = klucz_publiczny.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(surowe).decode("ascii")


def wczytaj_ustawienia(katalog: Path) -> dict[str, Any]:
    """Wczytuje ustawienia programu z katalogu danych użytkownika."""
    plik = katalog / PLIK_USTAWIEN
    if not plik.is_file():
        return {}
    try:
        return json.loads(plik.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def zapisz_ustawienia(katalog: Path, ustawienia: dict[str, Any]) -> None:
    """Atomowy zapis ustawień w katalogu danych."""
    katalog.mkdir(parents=True, exist_ok=True)
    plik = katalog / PLIK_USTAWIEN
    tymczasowy = plik.with_suffix(".tmp")
    tresc = json.dumps(ustawienia, indent=2, ensure_ascii=False) + "\n"
    tymczasowy.write_text(tresc, encoding="utf-8")
    os.replace(tymczasowy, plik)


def weryfikuj_katalog(
    katalog_bajty: bytes,
    podpis_bajty: bytes,
    klucze: list[ed25519.Ed25519PublicKey],
    minimalna_wersja_katalogu: int = 0,
) -> dict[str, Any]:
    """Weryfikuje podpis Ed25519, format JSON, wersja_katalogu oraz schemat."""
    if not weryfikuj_podpis(katalog_bajty, podpis_bajty, klucze):
        raise BladIntegralnosci("Niepoprawny podpis katalogu pakietów")
    try:
        dane = json.loads(katalog_bajty.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as blad:
        raise BladIntegralnosci(f"Uszkodzony format JSON katalogu: {blad}") from blad

    if not isinstance(dane, dict):
        raise BladIntegralnosci("Katalog musi być obiektem JSON")

    wersja_katalogu = dane.get("wersja_katalogu")
    if not isinstance(wersja_katalogu, int):
        raise BladIntegralnosci("Brak lub niepoprawna wersja_katalogu w katalogu pakietów")

    if wersja_katalogu <= minimalna_wersja_katalogu:
        raise BladAktualizacji(
            f"Odrzucono wersję katalogu {wersja_katalogu}: wymagana wersja wyższa niż {minimalna_wersja_katalogu}"
        )

    if "pakiety" not in dane or not isinstance(dane["pakiety"], list):
        raise BladIntegralnosci("Katalog nie zawiera listy pakietów")

    for p in dane["pakiety"]:
        if not isinstance(p, dict) or "id" not in p or "pliki" not in p:
            raise BladIntegralnosci("Niepoprawna struktura wpisu pakietu")

    return dane


def ocen_probke_kontrolna(
    detektor: Any,
    plik_probki: Path = PROBKA_KONTROLNA_DOMYSLNA,
) -> tuple[bool, list[str]]:
    """Weryfikuje jakość detektora na próbce kontrolnej.

    Zwraca (True, []) gdy model wykrył wszystkie fragmenty z musi_wykryc
    i żaden z nie_moze_wykryc. W przeciwnym razie (False, lista_bledow).
    """
    if not plik_probki.is_file():
        raise FileNotFoundError(f"Brak pliku próbki kontrolnej: {plik_probki}")

    dane_probki = json.loads(plik_probki.read_text(encoding="utf-8"))
    probki = dane_probki.get("probki", [])
    bledy: list[str] = []

    for idx, probka in enumerate(probki, 1):
        tekst = probka["tekst"]
        musi_wykryc = probka.get("musi_wykryc", [])
        nie_moze_wykryc = probka.get("nie_moze_wykryc", [])

        zakresy = detektor.znajdz(tekst)

        # Sprawdzenie musi_wykryc
        for oczekiwany in musi_wykryc:
            # Fragment oczekiwany musi być pokryty przez przynajmniej jeden wykryty zakres
            poz = tekst.find(oczekiwany)
            if poz == -1:
                bledy.append(f"Próbka #{idx}: błąd specyfikacji, brak fragmentu {oczekiwany!r} w tekście")
                continue
            poz_koniec = poz + len(oczekiwany)
            pokryty = any(
                (z.start <= poz and z.koniec >= poz_koniec)
                or (tekst[z.start:z.koniec] == oczekiwany)
                for z in zakresy
            )
            if not pokryty:
                bledy.append(f"Próbka #{idx}: brak wymaganego wykrycia {oczekiwany!r}")

        # Sprawdzenie nie_moze_wykryc
        for zakazany in nie_moze_wykryc:
            poz = tekst.find(zakazany)
            if poz == -1:
                continue
            poz_koniec = poz + len(zakazany)
            # Nie może być zakresu nachodzącego na ten fragment
            naruszony = any(
                max(z.start, poz) < min(z.koniec, poz_koniec) for z in zakresy
            )
            if naruszony:
                bledy.append(f"Próbka #{idx}: niepożądane wykrycie (fałszywy alarm) na {zakazany!r}")

    return len(bledy) == 0, bledy


def pobierz_zdalny_katalog(
    zrodlo_url: str,
    klient: httpx.Client | None = None,
    limit_bajtow: int = LIMIT_KATALOGU_BAJTOW,
) -> tuple[bytes, bytes]:
    """Pobiera katalog-pakietow.json oraz .sig ze źródła z limitem rozmiaru i walidacją hostów."""
    wlasny_klient = klient is None
    klient = klient or httpx.Client(follow_redirects=False, timeout=30)
    baza = zrodlo_url.rstrip("/")
    host_zrodla = httpx.URL(zrodlo_url).host or ""

    try:
        def _pobierz_jedno(nazwa: str) -> bytes:
            url = f"{baza}/{nazwa}"
            naglowki: dict[str, str] = {}
            for _ in range(5):
                resp = klient.get(url, headers=naglowki, follow_redirects=False)
                if resp.status_code in (301, 302, 303, 307, 308):
                    lokalizacja = resp.headers.get("location")
                    if not lokalizacja:
                        raise BladPakietu("Przekierowanie bez lokalizacji")
                    nastepny = str(httpx.URL(url).join(lokalizacja))
                    _waliduj_przekierowanie(nastepny, host_zrodla)
                    url = nastepny
                    continue
                resp.raise_for_status()
                zawartosc = resp.content
                if len(zawartosc) > limit_bajtow:
                    raise BladAktualizacji(f"Plik {nazwa} przekracza limit rozmiaru {limit_bajtow} B")
                return zawartosc
            raise BladPakietu("Za dużo przekierowań")

        katalog_bajty = _pobierz_jedno("katalog-pakietow.json")
        podpis_bajty = _pobierz_jedno("katalog-pakietow.json.sig")
        return katalog_bajty, podpis_bajty
    finally:
        if wlasny_klient:
            klient.close()


class MenedzerAktualizacji:
    """Zarządza sprawdzaniem, instalacją i cofaniem aktualizacji modeli."""

    def __init__(
        self,
        katalog_modeli_sciezka: Path,
        katalog_danych_sciezka: Path,
        zrodlo_url: str,
        menedzer_pakietow: MenedzerPakietow,
        konfig_tryb: str | None = None,
        klucze_publiczne: list[ed25519.Ed25519PublicKey] | None = None,
        probka_plik: Path = PROBKA_KONTROLNA_DOMYSLNA,
        fabryka_detektora: Callable[[int, Path], Any] | None = None,
        klient: httpx.Client | None = None,
    ):
        self._katalog_modeli = Path(katalog_modeli_sciezka)
        self._katalog_danych = Path(katalog_danych_sciezka)
        self._zrodlo = zrodlo_url
        self._pakiety_mgr = menedzer_pakietow
        self._konfig_tryb = konfig_tryb
        self._klucze_publiczne = (
            klucze_publiczne if klucze_publiczne is not None else wczytaj_klucze_publiczne()
        )
        self._probka_plik = probka_plik
        self._fabryka_detektora = fabryka_detektora or (lambda poz, kat: zbuduj_poziom(poz, kat))
        self._klient = klient

        self._zajete = threading.Lock()
        self._w_toku = False
        self.stan: str = "aktualny"
        self.blad: str | None = None
        self.katalog_aktywny_plik: Path = KATALOG_PAKIETOW
        self.postep: dict[str, Any] = {
            "akcja": None,
            "pakiet": None,
            "pobrane": 0,
            "razem": 0,
            "blad": None,
        }

        self.weryfikuj_start()

    @property
    def narzucony(self) -> bool:
        return self._konfig_tryb is not None

    @property
    def tryb(self) -> str:
        if self._konfig_tryb is not None:
            return self._konfig_tryb
        ustawienia = wczytaj_ustawienia(self._katalog_danych)
        return ustawienia.get("tryb_aktualizacji", TRYB_DOMYSLNY)

    @property
    def najwyzsza_wersja_katalogu(self) -> int:
        ustawienia = wczytaj_ustawienia(self._katalog_danych)
        return int(
            ustawienia.get("najwyzsza_wersja_katalogu", wczytaj_wersje_katalogu(self.katalog_aktywny_plik))
        )

    @property
    def ostatnie_sprawdzenie(self) -> str | None:
        ustawienia = wczytaj_ustawienia(self._katalog_danych)
        return ustawienia.get("ostatnie_sprawdzenie")

    def weryfikuj_start(self) -> None:
        """Weryfikacja przyjętego katalogu przy starcie programu (fail-closed, błąd widoczny)."""
        plik_katalogu = self._katalog_danych / PLIK_KATALOGU_DANYCH
        plik_podpisu = self._katalog_danych / PLIK_PODPISU_DANYCH

        if plik_katalogu.is_file():
            if not plik_podpisu.is_file():
                self.stan = "blad_integralnosci"
                self.blad = "Błąd integralności: brak pliku podpisu dla zapisanego katalogu pakietów"
                self.katalog_aktywny_plik = KATALOG_PAKIETOW
                return

            try:
                katalog_bajty = plik_katalogu.read_bytes()
                podpis_bajty = plik_podpisu.read_bytes()
                weryfikuj_katalog(
                    katalog_bajty,
                    podpis_bajty,
                    self._klucze_publiczne,
                    minimalna_wersja_katalogu=0,
                )
                self.katalog_aktywny_plik = plik_katalogu
                # Przeładowanie definicji pakietów z zapisanego katalogu
                nowe_pakiety = wczytaj_pakiety(plik_katalogu)
                self._pakiety_mgr._pakiety = {p.id: p for p in nowe_pakiety}
                self._pakiety_mgr.odswiez_w_tle()
            except BladIntegralnosci as blad:
                self.stan = "blad_integralnosci"
                self.blad = f"Błąd integralności katalogu pakietów: {blad}"
                self.katalog_aktywny_plik = KATALOG_PAKIETOW
            except (OSError, ValueError, BladAktualizacji) as blad:
                self.stan = "blad_integralnosci"
                self.blad = f"Błąd wczytywania zapisanego katalogu pakietów: {blad}"
                self.katalog_aktywny_plik = KATALOG_PAKIETOW
        else:
            self.katalog_aktywny_plik = KATALOG_PAKIETOW

        # Inicjalizacja najwyższej wersji w ustawieniach, jeśli brak
        ustawienia = wczytaj_ustawienia(self._katalog_danych)
        if "najwyzsza_wersja_katalogu" not in ustawienia:
            ustawienia["najwyzsza_wersja_katalogu"] = wczytaj_wersje_katalogu(self.katalog_aktywny_plik)
            zapisz_ustawienia(self._katalog_danych, ustawienia)

    def ustaw_tryb(self, nowy_tryb: str) -> None:
        """Zapisuje wybrany tryb aktualizacji; rzuca TrybNarzucony gdy tryb narzucił administrator."""
        if self.narzucony:
            raise TrybNarzucony("Tryb aktualizacji jest narzucony przez konfigurację i nie może być zmieniony")
        if nowy_tryb not in TRYBY_AKTUALIZACJI:
            raise ValueError(f"Nieznany tryb aktualizacji: {nowy_tryb}; dozwolone: {TRYBY_AKTUALIZACJI}")
        ustawienia = wczytaj_ustawienia(self._katalog_danych)
        ustawienia["tryb_aktualizacji"] = nowy_tryb
        zapisz_ustawienia(self._katalog_danych, ustawienia)

    def sprawdz_przy_starcie(self) -> None:
        """Sprawdzenie aktualizacji przy starcie: najwyżej raz na dobę w trybach sprawdzaj i automatyczne."""
        if self.stan == "blad_integralnosci":
            return
        aktualny_tryb = self.tryb
        if aktualny_tryb not in ("sprawdzaj", "automatyczne"):
            return

        ostatnie = self.ostatnie_sprawdzenie
        if ostatnie:
            try:
                dt_ostatnie = datetime.fromisoformat(ostatnie)
                if (datetime.now(UTC) - dt_ostatnie).total_seconds() < DOBA_SEKUNDY:
                    return  # Nie minęła doba
            except (ValueError, TypeError):
                logger.debug("Nieprawidłowy znacznik czasu ostatniego sprawdzenia")

        threading.Thread(target=self._sprawdz_asynchronicznie, name="niewidka-akt-start", daemon=True).start()

    def _sprawdz_asynchronicznie(self) -> None:
        try:
            self.sprawdz_aktualizacje()
            if self.tryb == "automatyczne" and self.stan == "dostepna_aktualizacja":
                for info in self.lista_pakietow():
                    if info["wersja_dostepna"] > info["wersja_zainstalowana"]:
                        self.instaluj_aktualizacje(info["id"], w_tle=False)
        except (httpx.HTTPError, BladAktualizacji, OSError) as blad:
            logger.warning("Błąd automatycznego sprawdzania aktualizacji: %s", blad)

    def sprawdz_aktualizacje(self) -> dict[str, Any]:
        """Pobiera i weryfikuje zdalny katalog, zapisuje przyjęty i wykrywa dostępne aktualizacje."""
        if self.stan == "blad_integralnosci":
            raise BladAktualizacji("Aktualizacje są zablokowane z powodu błędu integralności katalogu")

        self.stan = "sprawdzanie"
        self.blad = None
        try:
            katalog_bajty, podpis_bajty = pobierz_zdalny_katalog(self._zrodlo, klient=self._klient)
            prog = self.najwyzsza_wersja_katalogu

            # Weryfikacja pobranego katalogu
            dane_katalogu = weryfikuj_katalog(
                katalog_bajty,
                podpis_bajty,
                self._klucze_publiczne,
                minimalna_wersja_katalogu=prog,
            )

            # Zapis przyjętego katalogu i podpisu
            self._katalog_danych.mkdir(parents=True, exist_ok=True)
            plik_kat = self._katalog_danych / PLIK_KATALOGU_DANYCH
            plik_sig = self._katalog_danych / PLIK_PODPISU_DANYCH

            tmp_kat = plik_kat.with_suffix(".tmp")
            tmp_sig = plik_sig.with_suffix(".tmp")
            tmp_kat.write_bytes(katalog_bajty)
            tmp_sig.write_bytes(podpis_bajty)
            os.replace(tmp_kat, plik_kat)
            os.replace(tmp_sig, plik_sig)

            self.katalog_aktywny_plik = plik_kat
            wersja_kat = int(dane_katalogu["wersja_katalogu"])

            # Zaktualizowanie najwyższej wersji i daty sprawdzenia w ustawieniach
            ustawienia = wczytaj_ustawienia(self._katalog_danych)
            ustawienia["najwyzsza_wersja_katalogu"] = max(prog, wersja_kat)
            ustawienia["ostatnie_sprawdzenie"] = datetime.now(UTC).isoformat()
            zapisz_ustawienia(self._katalog_danych, ustawienia)

            # Odświeżenie definicji pakietów w menedżerze pakietów
            nowe_pakiety = wczytaj_pakiety(plik_kat)
            self._pakiety_mgr._pakiety = {p.id: p for p in nowe_pakiety}
            self._pakiety_mgr.odswiez_w_tle()

            # Sprawdzenie czy są dostępne aktualizacje
            dostepne = False
            for p in nowe_pakiety:
                zainstalowana = odczytaj_zainstalowana_wersje(p, self._katalog_modeli)
                if zainstalowana is not None and p.wersja > zainstalowana:
                    dostepne = True

            self.stan = "dostepna_aktualizacja" if dostepne else "aktualny"
            return dane_katalogu
        except Exception as blad:
            self.stan = "blad"
            self.blad = str(blad)
            raise

    def lista_pakietow(self) -> list[dict[str, Any]]:
        """Zwraca stan aktualizacji poszczególnych pakietów dla API i UI."""
        wynik = []
        pakiety = wczytaj_pakiety(self.katalog_aktywny_plik)
        for p in pakiety:
            zainstalowana = odczytaj_zainstalowana_wersje(p, self._katalog_modeli)
            # Sprawdzenie czy istnieje poprzednia wersja możliwa do cofnięcia
            katalog_poprz = self._katalog_modeli / ".poprzednie" / p.id
            manifest_poprz = katalog_poprz / "manifest.json"
            mozliwe_cofniecie = False
            if manifest_poprz.is_file():
                try:
                    dane_m = json.loads(manifest_poprz.read_text(encoding="utf-8"))
                    wersja_poprz = int(dane_m.get("wersja", 1))
                    mozliwe_cofniecie = wersja_poprz >= p.min_wersja
                except (OSError, ValueError):
                    mozliwe_cofniecie = False

            wynik.append(
                {
                    "id": p.id,
                    "nazwa": p.nazwa,
                    "opis": p.opis,
                    "wersja_zainstalowana": zainstalowana or 1,
                    "wersja_dostepna": p.wersja,
                    "rozmiar_aktualizacji": p.rozmiar,
                    "dostepna": zainstalowana is not None and p.wersja > zainstalowana,
                    "mozliwe_cofniecie": mozliwe_cofniecie,
                }
            )
        return wynik

    def instaluj_aktualizacje(self, pakiet_id: str, w_tle: bool = True) -> bool:
        """Pobiera i instaluje aktualizację z próbką kontrolną i atomową zamianą."""
        with self._zajete:
            if self._w_toku:
                return False
            self._w_toku = True

        pakiety_slownik = {p.id: p for p in wczytaj_pakiety(self.katalog_aktywny_plik)}
        pakiet = pakiety_slownik.get(pakiet_id)
        if pakiet is None:
            self._w_toku = False
            raise BladAktualizacji(f"Nieznany pakiet: {pakiet_id}")

        self.postep = {
            "akcja": "instalowanie",
            "pakiet": pakiet_id,
            "pobrane": 0,
            "razem": pakiet.rozmiar,
            "blad": None,
        }

        def operacja():
            try:
                self._wykonaj_instalacje(pakiet)
            except (BladPakietu, BladAktualizacji, httpx.HTTPError, OSError) as blad:
                self.postep["blad"] = str(blad)
                self.blad = str(blad)
                logger.error("Błąd instalacji aktualizacji %s: %s", pakiet_id, blad)
            finally:
                self._w_toku = False
                self.postep["pakiet"] = None
                self._pakiety_mgr.odswiez()

        if w_tle:
            threading.Thread(target=operacja, name=f"niewidka-akt-{pakiet_id}", daemon=True).start()
            return True
        else:
            operacja()
            return self.postep["blad"] is None

    def _wykonaj_instalacje(self, pakiet: Pakiet) -> None:
        """Właściwy proces instalacji w katalogu przejściowym, próbka kontrolna i zamiana."""
        katalog_nowe = self._katalog_modeli / ".nowe" / pakiet.id
        if katalog_nowe.exists():
            shutil.rmtree(katalog_nowe, ignore_errors=True)
        katalog_nowe.mkdir(parents=True, exist_ok=True)

        def postep_pobierania(pobrane: int, razem: int):
            self.postep["pobrane"] = pobrane
            self.postep["razem"] = razem

        try:
            # 1. Pobranie plików nowej wersji do katalogu przejściowego
            pobierz(
                pakiet,
                katalog_nowe,
                self._zrodlo,
                klient=self._klient,
                postep=postep_pobierania,
            )

            # 2. Próbka kontrolna
            # Przygotowujemy katalog testowy z modelami: jeśli pakiet to rozszerzony,
            # musi widzieć też pakiet podstawowy.
            detektor = self._fabryka_detektora(1, katalog_nowe)
            zaliczona, bledy = ocen_probke_kontrolna(detektor, self._probka_plik)
            if not zaliczona:
                raise BladAktualizacji(
                    f"Nowy model odrzucony przez próbkę kontrolną: {'; '.join(bledy)}"
                )

            # 3. Kopia bezpieczeństwa dotychczasowej wersji do .poprzednie/<pakiet.id>
            katalog_docelowy = (
                self._katalog_modeli / pakiet.katalog_rel if pakiet.katalog_rel else self._katalog_modeli
            )
            katalog_poprzednie = self._katalog_modeli / ".poprzednie" / pakiet.id
            if katalog_poprzednie.exists():
                shutil.rmtree(katalog_poprzednie, ignore_errors=True)
            katalog_poprzednie.mkdir(parents=True, exist_ok=True)

            # Kopiujemy dotychczasowe pliki do .poprzednie
            for plik in pakiet.pliki:
                istniejacy = katalog_docelowy / Path(plik.nazwa).name
                if istniejacy.is_file():
                    shutil.copy2(istniejacy, katalog_poprzednie / istniejacy.name)
            manifest_istniejacy = katalog_docelowy / "manifest.json"
            if manifest_istniejacy.is_file():
                shutil.copy2(manifest_istniejacy, katalog_poprzednie / "manifest.json")

            # 4. Atomowe przeniesienie z .nowe do katalogu docelowego
            for plik in pakiet.pliki:
                zrodlo_plik = katalog_nowe / plik.nazwa
                cel_plik = self._katalog_modeli / plik.nazwa
                cel_plik.parent.mkdir(parents=True, exist_ok=True)
                os.replace(zrodlo_plik, cel_plik)

            # Przeniesienie manifestu
            manifest_nowy = katalog_nowe / pakiet.katalog_rel / "manifest.json" if pakiet.katalog_rel else katalog_nowe / "manifest.json"
            if manifest_nowy.is_file():
                cel_manifest = katalog_docelowy / "manifest.json"
                os.replace(manifest_nowy, cel_manifest)

            # 5. Unieważnienie cache detektorów
            self._pakiety_mgr._zglos_zmiane()
            self.stan = "aktualny"
        finally:
            shutil.rmtree(katalog_nowe, ignore_errors=True)

    def cofnij_aktualizacje(self, pakiet_id: str) -> None:
        """Cofa pakiet do poprzedniej wersji z .poprzednie/<pakiet.id>, sprawdzając min_wersja."""
        pakiety_slownik = {p.id: p for p in wczytaj_pakiety(self.katalog_aktywny_plik)}
        pakiet = pakiety_slownik.get(pakiet_id)
        if pakiet is None:
            raise BladAktualizacji(f"Nieznany pakiet: {pakiet_id}")

        katalog_poprzednie = self._katalog_modeli / ".poprzednie" / pakiet_id
        manifest_poprz = katalog_poprzednie / "manifest.json"
        if not katalog_poprzednie.is_dir() or not manifest_poprz.is_file():
            raise BladAktualizacji(f"Brak poprzedniej wersji dla pakietu {pakiet_id}")

        try:
            dane_m = json.loads(manifest_poprz.read_text(encoding="utf-8"))
            wersja_poprz = int(dane_m.get("wersja", 1))
        except (OSError, ValueError) as blad:
            raise BladAktualizacji(f"Uszkodzony manifest poprzedniej wersji: {blad}") from blad

        if wersja_poprz < pakiet.min_wersja:
            raise BladAktualizacji(
                f"Cofnięcie zablokowane: wersja {wersja_poprz} jest niższa niż dopuszczalna min_wersja {pakiet.min_wersja}"
            )

        katalog_docelowy = (
            self._katalog_modeli / pakiet.katalog_rel if pakiet.katalog_rel else self._katalog_modeli
        )
        # Przywracamy pliki z .poprzednie
        for element in katalog_poprzednie.iterdir():
            if element.is_file():
                shutil.copy2(element, katalog_docelowy / element.name)

        # Usunięcie katalogu .poprzednie po udanym cofnięciu
        shutil.rmtree(katalog_poprzednie, ignore_errors=True)

        self._pakiety_mgr.odswiez()
        self._pakiety_mgr._zglos_zmiane()

