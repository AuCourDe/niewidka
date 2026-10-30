"""Aktualizacje modeli: katalog pakietów podpisany Ed25519, instalacja z weryfikacją SHA-256,
próbką kontrolną i atomową zamianą, powrót do poprzedniej wersji (blokada `min_wersja`).
Bez klucza publicznego w programie działa katalog wbudowany, bez wyjątku przy starcie.
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

from niewidka.detektory import DetektorKompozyt, RegulyDetektor, wczytaj_bardsai, wczytaj_lfm25
from niewidka.pakiety import (
    KATALOG_PAKIETOW,
    BladPakietu,
    MenedzerPakietow,
    Pakiet,
    _opublikuj,
    _waliduj_przekierowanie,
    _zapisz_manifest,
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
NAZWA_KATALOGU = "katalog-pakietow.json"
NAZWA_PODPISU = "katalog-pakietow.json.sig"


class BladAktualizacji(Exception):
    """Błąd logiki aktualizacji (sieć, tryb, brak wersji) — komunikat dla osoby
    opiekującej się programem, bez treści plików i bez URL-i."""


class BladIntegralnosci(BladAktualizacji):
    """Zły podpis albo uszkodzony katalog pakietów — fail-closed."""


class TrybNarzucony(BladAktualizacji):
    """Zmiana trybu zablokowana przez konfigurację administratora."""


# --- podpis Ed25519 -----------------------------------------------------------


def wczytaj_klucze_publiczne(
    zrodlo: Path | str | list[str] | None = None,
) -> list[ed25519.Ed25519PublicKey]:
    """Klucze publiczne wydawcy: po jednym base64 (surowe 32 B) w linii, linie
    z # to komentarze. Kilka kluczy = rotacja: nowy klucz wchodzi
    w wydaniu programu, stary może jeszcze podpisywać katalogi."""
    if zrodlo is None:
        sciezka = KLUCZ_PUBLICZNY_DOMYSLNY
        if not sciezka.is_file():
            return []
        linie = sciezka.read_text(encoding="utf-8").splitlines()
    elif isinstance(zrodlo, Path):
        if not zrodlo.is_file():
            return []
        linie = zrodlo.read_text(encoding="utf-8").splitlines()
    elif isinstance(zrodlo, str):
        linie = zrodlo.splitlines()
    else:
        linie = list(zrodlo)

    klucze: list[ed25519.Ed25519PublicKey] = []
    for linia in linie:
        czysta = linia.strip()
        if not czysta or czysta.startswith("#"):
            continue
        try:
            surowe = base64.b64decode(czysta)
        except (ValueError, binascii.Error):
            continue
        if len(surowe) == 32:
            try:
                klucze.append(ed25519.Ed25519PublicKey.from_public_bytes(surowe))
            except ValueError:
                continue
    return klucze


def weryfikuj_podpis(
    dane: bytes,
    podpis: bytes,
    klucze: list[ed25519.Ed25519PublicKey],
) -> bool:
    """Prawda, gdy podpis (surowe 64 B albo base64) pasuje do któregokolwiek klucza."""
    if not klucze:
        return False
    surowy = podpis
    if len(podpis) != 64:
        try:
            zdekodowany = base64.b64decode(podpis.strip())
        except (ValueError, binascii.Error):
            return False
        if len(zdekodowany) == 64:
            surowy = zdekodowany
    if len(surowy) != 64:
        return False
    return any(_pasuje(klucz, surowy, dane) for klucz in klucze)


def _pasuje(klucz: ed25519.Ed25519PublicKey, podpis: bytes, dane: bytes) -> bool:
    try:
        klucz.verify(podpis, dane)
    except InvalidSignature:
        return False
    return True


def podpisz_dane(dane: bytes, klucz_prywatny: ed25519.Ed25519PrivateKey) -> bytes:
    """Surowy 64-bajtowy podpis Ed25519 (narzędzie wydawcy i testy)."""
    return klucz_prywatny.sign(dane)


def klucz_publiczny_do_b64(klucz_publiczny: ed25519.Ed25519PublicKey) -> str:
    """Base64 surowych 32 bajtów klucza — format pliku klucz-katalogu.pub."""
    surowe = klucz_publiczny.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(surowe).decode("ascii")


# --- ustawienia w katalogu danych -----------------------------------------------


def wczytaj_ustawienia(katalog: Path) -> dict[str, Any]:
    plik = katalog / PLIK_USTAWIEN
    if not plik.is_file():
        return {}
    try:
        dane = json.loads(plik.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dane if isinstance(dane, dict) else {}


def zapisz_ustawienia(katalog: Path, ustawienia: dict[str, Any]) -> None:
    katalog.mkdir(parents=True, exist_ok=True)
    plik = katalog / PLIK_USTAWIEN
    tymczasowy = plik.with_name(PLIK_USTAWIEN + ".tmp")
    tymczasowy.write_text(json.dumps(ustawienia, indent=2, ensure_ascii=False) + "\n", "utf-8")
    os.replace(tymczasowy, plik)


# --- weryfikacja katalogu -------------------------------------------------------


def weryfikuj_katalog(
    katalog_bajty: bytes,
    podpis_bajty: bytes,
    klucze: list[ed25519.Ed25519PublicKey],
    minimalna_wersja_katalogu: int = 0,
    pozwalaj_rowna: bool = False,
) -> dict[str, Any]:
    """Podpis, format JSON, wersja_katalogu i schemat (tyle, by wczytaj_pakiety
    nie mogło trafić na brak pola). Katalog o wersji niższej od progu, a bez
    `pozwalaj_rowna` także o równej, jest odrzucany: ochrona przed cofnięciem
    do starej wersji. Równą dopuszcza weryfikacja przy starcie (to jest
    właśnie ten przyjęty katalog)."""
    if not weryfikuj_podpis(katalog_bajty, podpis_bajty, klucze):
        raise BladIntegralnosci("Niepoprawny podpis katalogu pakietów")
    try:
        dane = json.loads(katalog_bajty.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as blad:
        raise BladIntegralnosci(f"Uszkodzony format JSON katalogu: {blad}") from blad
    if not isinstance(dane, dict):
        raise BladIntegralnosci("Katalog musi być obiektem JSON")

    wersja = dane.get("wersja_katalogu")
    if not isinstance(wersja, int) or isinstance(wersja, bool):
        raise BladIntegralnosci("Brak albo niepoprawna wersja_katalogu w katalogu pakietów")
    if wersja < minimalna_wersja_katalogu or (
        wersja == minimalna_wersja_katalogu and not pozwalaj_rowna
    ):
        raise BladAktualizacji(
            f"Odrzucono wersję katalogu {wersja}: wymagana wersja wyższa niż "
            f"{minimalna_wersja_katalogu}"
        )

    pakiety = dane.get("pakiety")
    if not isinstance(pakiety, list):
        raise BladIntegralnosci("Katalog nie zawiera listy pakietów")
    for wpis in pakiety:
        _sprawdz_schemat_pakietu(wpis)
    return dane


def _sprawdz_schemat_pakietu(wpis: object) -> None:
    if not isinstance(wpis, dict):
        raise BladIntegralnosci("Wpis pakietu musi być obiektem JSON")
    for pole in ("id", "nazwa", "opis", "pliki"):
        if pole not in wpis:
            raise BladIntegralnosci(f"Wpis pakietu bez pola {pole}")
    if not isinstance(wpis["pliki"], list):
        raise BladIntegralnosci(f"Pakiet {wpis['id']}: lista plików musi być tablicą")
    for plik in wpis["pliki"]:
        if not isinstance(plik, dict):
            raise BladIntegralnosci(f"Pakiet {wpis['id']}: wpis pliku musi być obiektem")
        for pole in ("nazwa", "zrodlo", "rozmiar", "sha256"):
            if pole not in plik:
                raise BladIntegralnosci(f"Pakiet {wpis['id']}: plik bez pola {pole}")
        rozmiar = plik["rozmiar"]
        if not isinstance(rozmiar, int) or isinstance(rozmiar, bool) or rozmiar < 0:
            raise BladIntegralnosci(f"Pakiet {wpis['id']}: niepoprawny rozmiar pliku")
        suma = plik["sha256"]
        if (
            not isinstance(suma, str)
            or len(suma) != 64
            or any(znak not in "0123456789abcdef" for znak in suma)
        ):
            raise BladIntegralnosci(f"Pakiet {wpis['id']}: niepoprawny SHA-256 pliku")
    for pole in ("wersja", "min_wersja"):
        wartosc = wpis.get(pole, 1)
        if not isinstance(wartosc, int) or isinstance(wartosc, bool) or wartosc < 1:
            raise BladIntegralnosci(f"Pakiet {wpis['id']}: niepoprawne pole {pole}")
    if not isinstance(wpis.get("katalog_rel", ""), str):
        raise BladIntegralnosci(f"Pakiet {wpis['id']}: niepoprawne katalog_rel")


def ocen_probke_kontrolna(
    detektor: Any,
    plik_probki: Path = PROBKA_KONTROLNA_DOMYSLNA,
) -> tuple[bool, list[str]]:
    """Próbka kontrolna: nowa wersja jest oceniana względem PLIKU,
    nie względem starej wersji. Zaliczona, gdy wykrywa każdy fragment z
    musi_wykryc (zakres musi go pokrywać) i nic z nie_moze_wykryc."""
    if not plik_probki.is_file():
        raise FileNotFoundError(f"Brak pliku próbki kontrolnej: {plik_probki}")
    dane_probki = json.loads(plik_probki.read_text(encoding="utf-8"))
    bledy: list[str] = []
    for numer, probka in enumerate(dane_probki.get("probki", []), 1):
        tekst = probka["tekst"]
        zakresy = detektor.znajdz(tekst)
        for oczekiwany in probka.get("musi_wykryc", []):
            poz = tekst.find(oczekiwany)
            if poz == -1:
                bledy.append(f"Próbka {numer}: fragment {oczekiwany!r} nie ma w tekście próbki")
                continue
            koniec = poz + len(oczekiwany)
            if not any(z.start <= poz and z.koniec >= koniec for z in zakresy):
                bledy.append(f"Próbka {numer}: brak wymaganego wykrycia {oczekiwany!r}")
        for zakazany in probka.get("nie_moze_wykryc", []):
            poz = tekst.find(zakazany)
            if poz == -1:
                continue
            koniec = poz + len(zakazany)
            if any(max(z.start, poz) < min(z.koniec, koniec) for z in zakresy):
                bledy.append(f"Próbka {numer}: niepożądane wykrycie (fałszywy alarm) na {zakazany!r}")
    return not bledy, bledy


def pobierz_zdalny_katalog(
    zrodlo_url: str,
    klient: httpx.Client | None = None,
    limit_bajtow: int = LIMIT_KATALOGU_BAJTOW,
) -> tuple[bytes, bytes]:
    """Katalog i podpis ze źródła; limit 1 MB, przekierowania prowadzone ręcznie
    z tą samą walidacją co `_pobierz_plik` (reużyte `_waliduj_przekierowanie`)."""
    wlasny = klient is None
    klient = klient or httpx.Client(follow_redirects=False, timeout=30)
    baza = zrodlo_url.rstrip("/")
    host_zrodla = httpx.URL(zrodlo_url).host or ""

    def jedno(nazwa: str) -> bytes:
        url = f"{baza}/{nazwa}"
        for _ in range(5):
            odpowiedz = klient.get(url, follow_redirects=False)
            if odpowiedz.status_code in (301, 302, 303, 307, 308):
                lokalizacja = odpowiedz.headers.get("location")
                if not lokalizacja:
                    raise BladPakietu("Przekierowanie bez lokalizacji")
                nastepny = str(httpx.URL(url).join(lokalizacja))
                _waliduj_przekierowanie(nastepny, host_zrodla)
                url = nastepny
                continue
            odpowiedz.raise_for_status()
            if len(odpowiedz.content) > limit_bajtow:
                raise BladAktualizacji(f"Plik {nazwa} przekracza limit {limit_bajtow} B")
            return odpowiedz.content
        raise BladPakietu("Za dużo przekierowań")

    try:
        return jedno(NAZWA_KATALOGU), jedno(NAZWA_PODPISU)
    finally:
        if wlasny:
            klient.close()


class MenedzerAktualizacji:
    """Sprawdzanie, instalacja i cofanie aktualizacji modeli (stan dla API i UI)."""

    def __init__(
        self,
        katalog_modeli_sciezka: Path,
        katalog_danych_sciezka: Path,
        zrodlo_url: str,
        menedzer_pakietow: MenedzerPakietow,
        konfig_tryb: str | None = None,
        klucze_publiczne: list[ed25519.Ed25519PublicKey] | None = None,
        probka_plik: Path = PROBKA_KONTROLNA_DOMYSLNA,
        fabryka_detektora: Callable[[Pakiet, Path], Any] | None = None,
        klient: httpx.Client | None = None,
    ):
        self._katalog_modeli = Path(katalog_modeli_sciezka)
        self._katalog_danych = Path(katalog_danych_sciezka)
        self._zrodlo = zrodlo_url
        self._pakiety_mgr = menedzer_pakietow
        self._konfig_tryb = konfig_tryb
        self._klucze = (
            klucze_publiczne if klucze_publiczne is not None else wczytaj_klucze_publiczne()
        )
        self._probka_plik = probka_plik
        self._fabryka_detektora = fabryka_detektora or self._detektor_probki
        self._klient = klient
        self._zajete = threading.Lock()
        self._w_toku = False
        self.stan = "aktualny"
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

    # --- stan dla API ------------------------------------------------------------

    @property
    def ma_klucze(self) -> bool:
        """Program z placeholderem klucza (przed wydaniem): aktualizacje zdalne
        niedostępne, ale program działa na katalogu wbudowanym."""
        return bool(self._klucze)

    @property
    def narzucony(self) -> bool:
        return self._konfig_tryb is not None

    @property
    def tryb(self) -> str:
        if self._konfig_tryb is not None:
            return self._konfig_tryb
        return wczytaj_ustawienia(self._katalog_danych).get("tryb_aktualizacji", TRYB_DOMYSLNY)

    @property
    def najwyzsza_wersja_katalogu(self) -> int:
        """Próg rollbacku zapisany OSOBNO w ustawienia.json; zanim cokolwiek
        przyjęto, próg to wersja katalogu aktywnego."""
        zapisana = wczytaj_ustawienia(self._katalog_danych).get("najwyzsza_wersja_katalogu")
        if isinstance(zapisana, int) and not isinstance(zapisana, bool):
            return zapisana
        return wczytaj_wersje_katalogu(self.katalog_aktywny_plik)

    @property
    def ostatnie_sprawdzenie(self) -> str | None:
        znacznik = wczytaj_ustawienia(self._katalog_danych).get("ostatnie_sprawdzenie")
        return znacznik if isinstance(znacznik, str) else None

    # --- start -------------------------------------------------------------------

    def weryfikuj_start(self) -> None:
        """Przyjęty wcześniej katalog: podpis sprawdzany przy każdym starcie.
        Zły podpis = katalog wbudowany i widoczny stan błędu integralności
        (cofnięcie zostaje, ale nie po cichu); aktualizacje blokowane."""
        plik_katalogu = self._katalog_danych / PLIK_KATALOGU_DANYCH
        if not plik_katalogu.is_file():
            return
        plik_podpisu = self._katalog_danych / PLIK_PODPISU_DANYCH
        try:
            if not plik_podpisu.is_file():
                raise BladIntegralnosci("brak pliku podpisu przyjętego katalogu")
            bajty = plik_katalogu.read_bytes()
            weryfikuj_katalog(
                bajty,
                plik_podpisu.read_bytes(),
                self._klucze,
                minimalna_wersja_katalogu=self.najwyzsza_wersja_katalogu,
                pozwalaj_rowna=True,
            )
        except (BladAktualizacji, OSError, ValueError) as blad:
            self.stan = "blad_integralnosci"
            self.blad = f"Błąd integralności katalogu aktualizacji: {blad}"
            self.katalog_aktywny_plik = KATALOG_PAKIETOW
            return
        self.katalog_aktywny_plik = plik_katalogu
        self._przyjmij_pakiety(plik_katalogu)

    def _przyjmij_pakiety(self, plik_katalogu: Path) -> None:
        self._pakiety_mgr.podmien_pakiety(wczytaj_pakiety(plik_katalogu))

    # --- tryb ----------------------------------------------------------------------

    def ustaw_tryb(self, nowy_tryb: str) -> None:
        if self.narzucony:
            raise TrybNarzucony(
                "Tryb aktualizacji narzuca administrator w konfiguracji i nie może być zmieniony"
            )
        if nowy_tryb not in TRYBY_AKTUALIZACJI:
            raise ValueError(
                f"Nieznany tryb aktualizacji: {nowy_tryb!r}; dozwolone: {', '.join(TRYBY_AKTUALIZACJI)}"
            )
        ustawienia = wczytaj_ustawienia(self._katalog_danych)
        ustawienia["tryb_aktualizacji"] = nowy_tryb
        zapisz_ustawienia(self._katalog_danych, ustawienia)

    # --- sprawdzanie -------------------------------------------------------------

    def sprawdz_przy_starcie(self) -> None:
        """Tryby sprawdzaj i automatyczne: najwyżej raz na dobę (znacznik czasu
        w ustawienia.json). Bez klucza wydawcy, po błędzie integralności i w trybie
        wyłączonym: bez żądania sieciowego i bez wyjątku przy starcie."""
        if self.stan == "blad_integralnosci" or not self._klucze:
            return
        if self.tryb not in ("sprawdzaj", "automatyczne"):
            return
        znacznik = self.ostatnie_sprawdzenie
        if znacznik:
            try:
                minelo = datetime.now(UTC) - datetime.fromisoformat(znacznik)
            except (ValueError, TypeError):
                minelo = None
            if minelo is not None and minelo.total_seconds() < DOBA_SEKUNDY:
                return
        threading.Thread(target=self._sprawdz_i_byc_moze_instaluj, name="niewidka-akt-start", daemon=True).start()

    def _sprawdz_i_byc_moze_instaluj(self) -> None:
        try:
            self.sprawdz_aktualizacje()
            if self.tryb == "automatyczne" and self.stan == "dostepna_aktualizacja":
                self.instaluj_aktualizacje(w_tle=False)
        except (httpx.HTTPError, BladAktualizacji, OSError) as blad:
            logger.warning("Automatyczne sprawdzenie aktualizacji nie powiodło się: %s", blad)

    def sprawdz_aktualizacje(self) -> dict[str, Any]:
        """Pobiera zdalny katalog, weryfikuje (podpis, próg rollbacku, schemat),
        zapisuje przyjęty w katalogu danych i liczy stan dostępności aktualizacji."""
        self._straznik_sprawdzania()
        with self._zajete:
            if self._w_toku:
                raise BladAktualizacji("Inna operacja aktualizacji właśnie trwa")
            self._w_toku = True
        self.stan = "sprawdzanie"
        self.blad = None
        try:
            katalog_bajty, podpis_bajty = pobierz_zdalny_katalog(self._zrodlo, klient=self._klient)
            dane = weryfikuj_katalog(
                katalog_bajty,
                podpis_bajty,
                self._klucze,
                minimalna_wersja_katalogu=self.najwyzsza_wersja_katalogu,
            )
            self._zapisz_przyjety_katalog(katalog_bajty, podpis_bajty, dane)
            self._przelicz_stan()
            return dane
        except Exception as blad:
            self.stan = "blad"
            self.blad = str(blad)
            raise
        finally:
            self._w_toku = False

    def _straznik_sprawdzania(self) -> None:
        if self.stan == "blad_integralnosci":
            raise BladAktualizacji(
                "Aktualizacje są zablokowane: przyjęty katalog ma błąd integralności. "
                "Skasuj plik katalogu w katalogu danych albo zainstaluj program ponownie."
            )
        if not self._klucze:
            raise BladAktualizacji(
                "W programie nie ma klucza publicznego wydawcy, więc aktualizacje "
                "są niedostępne. Skorzystaj z instalacji z folderu przygotowanego przez IT."
            )
        if self.tryb == "wylaczone":
            raise BladAktualizacji("Aktualizacje są wyłączone w ustawieniach")

    def _zapisz_przyjety_katalog(self, katalog_bajty: bytes, podpis_bajty: bytes, dane: dict) -> None:
        self._katalog_danych.mkdir(parents=True, exist_ok=True)
        plik_katalogu = self._katalog_danych / PLIK_KATALOGU_DANYCH
        plik_podpisu = self._katalog_danych / PLIK_PODPISU_DANYCH
        tmp_katalogu = plik_katalogu.with_name(PLIK_KATALOGU_DANYCH + ".tmp")
        tmp_podpisu = plik_podpisu.with_name(PLIK_PODPISU_DANYCH + ".tmp")
        tmp_katalogu.write_bytes(katalog_bajty)
        tmp_podpisu.write_bytes(podpis_bajty)
        os.replace(tmp_katalogu, plik_katalogu)
        os.replace(tmp_podpisu, plik_podpisu)
        self.katalog_aktywny_plik = plik_katalogu
        self._przyjmij_pakiety(plik_katalogu)
        ustawienia = wczytaj_ustawienia(self._katalog_danych)
        ustawienia["najwyzsza_wersja_katalogu"] = max(
            self.najwyzsza_wersja_katalogu, int(dane["wersja_katalogu"])
        )
        ustawienia["ostatnie_sprawdzenie"] = datetime.now(UTC).isoformat()
        zapisz_ustawienia(self._katalog_danych, ustawienia)

    # --- instalacja offline (folder od IT) ---------------------------------------

    def przyjmij_katalog_z_folderu(self, folder: Path) -> dict[str, Any]:
        """Sieć offline: katalog i podpis z folderu na pendrive od IT.
        Ta sama weryfikacja co przy pobieraniu zdalnym."""
        if not self._klucze:
            raise BladAktualizacji(
                "W programie nie ma klucza publicznego wydawcy, więc nie da się "
                "zweryfikować katalogu z folderu."
            )
        plik_katalogu = folder / NAZWA_KATALOGU
        plik_podpisu = folder / NAZWA_PODPISU
        if not plik_katalogu.is_file() or not plik_podpisu.is_file():
            raise BladAktualizacji(
                "Folder nie zawiera katalog-pakietow.json z podpisem (.sig); "
                "poproś IT o komplet plików aktualizacji"
            )
        bajty = plik_katalogu.read_bytes()
        if len(bajty) > LIMIT_KATALOGU_BAJTOW:
            raise BladIntegralnosci("Katalog z folderu przekracza limit 1 MB")
        dane = weryfikuj_katalog(
            bajty,
            plik_podpisu.read_bytes(),
            self._klucze,
            minimalna_wersja_katalogu=self.najwyzsza_wersja_katalogu,
        )
        self._zapisz_przyjety_katalog(bajty, plik_podpisu.read_bytes(), dane)
        return dane

    # --- lista i instalacja --------------------------------------------------------

    def lista_pakietow(self) -> list[dict[str, Any]]:
        """Stan per pakiet: wersja zainstalowana (z manifest.json), dostępna,
        rozmiar i możliwość powrotu do poprzedniej wersji."""
        wynik = []
        for pakiet in wczytaj_pakiety(self.katalog_aktywny_plik):
            zainstalowana = odczytaj_zainstalowana_wersje(pakiet, self._katalog_modeli)
            wynik.append(
                {
                    "id": pakiet.id,
                    "nazwa": pakiet.nazwa,
                    "wersja_zainstalowana": zainstalowana,
                    "wersja_dostepna": pakiet.wersja,
                    "rozmiar_aktualizacji": pakiet.rozmiar,
                    "dostepna": zainstalowana is not None and pakiet.wersja > zainstalowana,
                    "mozliwe_cofniecie": self._mozna_cofnac(pakiet),
                }
            )
        return wynik

    def _mozna_cofnac(self, pakiet: Pakiet) -> bool:
        manifest = self._katalog_modeli / ".poprzednie" / pakiet.id / "manifest.json"
        if not manifest.is_file():
            return False
        try:
            wersja = int(json.loads(manifest.read_text(encoding="utf-8")).get("wersja", 1))
        except (OSError, ValueError):
            return False
        return wersja >= pakiet.min_wersja

    def instaluj_aktualizacje(
        self,
        pakiet_id: str | None = None,
        w_tle: bool = True,
        folder: Path | None = None,
    ) -> bool:
        """Instaluje aktualizację (albo wszystkie dostępne, gdy bez pakiet_id).
        Z folderem: najpierw przyjęcie podpisanego katalogu z folderu. False gdy
        inna operacja trwa; błędy lądują w postep.blad i w self.blad."""
        self._straznik_sprawdzania()
        if folder is not None:
            self.przyjmij_katalog_z_folderu(folder)
        pakiety = {p.id: p for p in wczytaj_pakiety(self.katalog_aktywny_plik)}
        if pakiet_id is not None:
            if pakiet_id not in pakiety:
                raise BladAktualizacji(f"Nieznany pakiet: {pakiet_id}")
            cele = [pakiety[pakiet_id]]
        else:
            cele = [
                p
                for p in pakiety.values()
                if (zainstalowana := odczytaj_zainstalowana_wersje(p, self._katalog_modeli))
                and p.wersja > zainstalowana
            ]
            if not cele:
                raise BladAktualizacji("Brak pakietów z dostępną aktualizacją")
        with self._zajete:
            if self._w_toku:
                return False
            self._w_toku = True
        self.blad = None
        self.postep = {
            "akcja": "instalowanie",
            "pakiet": cele[0].id,
            "pobrane": 0,
            "razem": cele[0].rozmiar,
            "blad": None,
        }

        def operacja():
            try:
                for pakiet in cele:
                    self._wykonaj_instalacje(pakiet, folder)
                self._przelicz_stan()
            except (BladPakietu, BladAktualizacji, httpx.HTTPError, OSError) as blad:
                self.postep["blad"] = str(blad)
                self.blad = str(blad)
                logger.error("Instalacja aktualizacji nie powiodła się: %s", blad)
            finally:
                self._w_toku = False
                self.postep["pakiet"] = None
                self._pakiety_mgr.odswiez()
                self._pakiety_mgr._zglos_zmiane()

        if w_tle:
            threading.Thread(target=operacja, name="niewidka-akt-instaluj", daemon=True).start()
            return True
        operacja()
        return self.postep["blad"] is None

    def _detektor_probki(self, pakiet: Pakiet, katalog: Path) -> Any:
        """Domyślny detektor próbki: wyłącznie warstwy dotknięte pakietem, budowane
        z katalogu przejściowego. Hasze plików weryfikuje PRZYJĘTY katalog
        (wbudowany pinuje stare wersje, więc nowe by nie przeszły)."""
        if pakiet.wymaga:  # pakiet rozszerzający wnosi wyłącznie model LFM (IP, KARTA, SWIFT, LOGIN)
            return DetektorKompozyt(
                "probka-lfm",
                [
                    wczytaj_lfm25(
                        katalog,
                        wariant="q4-bl32",
                        rozszerzony=True,
                        katalog_pakietow=self.katalog_aktywny_plik,
                    )
                ],
            )
        return DetektorKompozyt(
            "probka",
            [
                RegulyDetektor(),
                wczytaj_bardsai(katalog, katalog_pakietow=self.katalog_aktywny_plik),
            ],
        )

    def _wykonaj_instalacje(self, pakiet: Pakiet, folder: Path | None) -> None:
        """Pliki nowej wersji do .nowe/<pakiet>, SHA-256, próbka kontrolna,
        dopiero potem zamiana (fail-closed: bez zaliczonej próbki nie ma zamiany)."""
        przejsciowy = self._katalog_modeli / ".nowe" / pakiet.id
        shutil.rmtree(przejsciowy, ignore_errors=True)
        przejsciowy.mkdir(parents=True, exist_ok=True)
        self.postep.update(pakiet=pakiet.id, pobrane=0, razem=pakiet.rozmiar)
        try:
            if folder is not None:
                self._skopiuj_z_folderu(pakiet, folder, przejsciowy)
                _zapisz_manifest(pakiet, przejsciowy)
            else:
                pobierz(
                    pakiet,
                    przejsciowy,
                    self._zrodlo,
                    klient=self._klient,
                    postep=self._przyjmij_postep,
                )
            detektor = self._fabryka_detektora(pakiet, przejsciowy)
            zaliczona, bledy = ocen_probke_kontrolna(detektor, self._probka_plik)
            if not zaliczona:
                raise BladAktualizacji(
                    "Nowa wersja odrzucona przez próbkę kontrolną: " + "; ".join(bledy)
                )
            self._zamien_wersje(pakiet, przejsciowy)
        finally:
            shutil.rmtree(przejsciowy, ignore_errors=True)

    def _przyjmij_postep(self, pobrane: int, razem: int) -> None:
        self.postep["pobrane"] = pobrane
        self.postep["razem"] = razem

    def _skopiuj_z_folderu(self, pakiet: Pakiet, folder: Path, przejsciowy: Path) -> None:
        """Pliki z folderu od IT pod nazwami źródłowymi; SHA-256 z przyjętego
        katalogu pilnuje każdego bajtu (ten sam `_opublikuj` co przy pobieraniu)."""
        gotowe = 0
        for plik in pakiet.pliki:
            wzor = folder / plik.zrodlo
            if wzor.is_symlink() or not wzor.is_file():
                raise BladAktualizacji(f"W folderze nie ma pliku {plik.zrodlo}")
            if wzor.stat().st_size != plik.rozmiar:
                raise BladAktualizacji(f"Plik {plik.zrodlo} w folderze ma inny rozmiar niż katalog")
            bajty = wzor.read_bytes()
            if len(bajty) != plik.rozmiar:
                raise BladAktualizacji(f"Plik {plik.zrodlo} zmienił rozmiar w trakcie odczytu")
            _opublikuj(bajty, przejsciowy / plik.nazwa, plik.sha256, przejsciowy)
            gotowe += plik.rozmiar
            self._przyjmij_postep(gotowe, pakiet.rozmiar)

    def _zamien_wersje(self, pakiet: Pakiet, przejsciowy: Path) -> None:
        """Poprzednia wersja do .poprzednie/<pakiet>, potem atomowa zamiana plików
        i manifestu. Pliki pakietu mają stałe ścieżki względne, więc
        przeniesienie po nazwie jest bezpieczne."""
        katalog_docelowy = (
            self._katalog_modeli / pakiet.katalog_rel if pakiet.katalog_rel else self._katalog_modeli
        )
        poprzednie = self._katalog_modeli / ".poprzednie" / pakiet.id
        shutil.rmtree(poprzednie, ignore_errors=True)
        poprzednie.mkdir(parents=True, exist_ok=True)
        for plik in pakiet.pliki:
            stary = self._katalog_modeli / plik.nazwa
            if stary.is_file():
                shutil.copy2(stary, poprzednie / Path(plik.nazwa).name)
        stary_manifest = katalog_docelowy / "manifest.json"
        if stary_manifest.is_file():
            shutil.copy2(stary_manifest, poprzednie / "manifest.json")

        for plik in pakiet.pliki:
            cel = self._katalog_modeli / plik.nazwa
            cel.parent.mkdir(parents=True, exist_ok=True)
            os.replace(przejsciowy / plik.nazwa, cel)
        nowy_manifest = (
            przejsciowy / pakiet.katalog_rel / "manifest.json"
            if pakiet.katalog_rel
            else przejsciowy / "manifest.json"
        )
        if nowy_manifest.is_file():
            os.replace(nowy_manifest, katalog_docelowy / "manifest.json")

    # --- cofanie -------------------------------------------------------------------

    def cofnij_aktualizacje(self, pakiet_id: str) -> None:
        """Powrót do wersji z .poprzednie/<pakiet>; poniżej min_wersja pakietu
        zablokowany. Działa także przy błędzie integralności: przywrócenie
        znanego stanu to droga wyjścia, nie aktualizacja."""
        with self._zajete:
            if self._w_toku:
                raise BladAktualizacji("Inna operacja aktualizacji właśnie trwa")
        pakiety = {p.id: p for p in wczytaj_pakiety(self.katalog_aktywny_plik)}
        if pakiet_id not in pakiety:
            raise BladAktualizacji(f"Nieznany pakiet: {pakiet_id}")
        pakiet = pakiety[pakiet_id]
        poprzednie = self._katalog_modeli / ".poprzednie" / pakiet_id
        manifest = poprzednie / "manifest.json"
        if not poprzednie.is_dir() or not manifest.is_file():
            raise BladAktualizacji(f"Brak poprzedniej wersji pakietu {pakiet_id}")
        try:
            wersja = int(json.loads(manifest.read_text(encoding="utf-8")).get("wersja", 1))
        except (OSError, ValueError) as blad:
            raise BladAktualizacji(f"Uszkodzony manifest poprzedniej wersji: {blad}") from blad
        if wersja < pakiet.min_wersja:
            raise BladAktualizacji(
                f"Cofnięcie zablokowane: wersja {wersja} jest niższa niż dopuszczalna "
                f"min_wersja {pakiet.min_wersja}"
            )
        katalog_docelowy = (
            self._katalog_modeli / pakiet.katalog_rel if pakiet.katalog_rel else self._katalog_modeli
        )
        katalog_docelowy.mkdir(parents=True, exist_ok=True)
        for element in sorted(poprzednie.iterdir()):
            if element.is_file():
                shutil.copy2(element, katalog_docelowy / element.name)
        shutil.rmtree(poprzednie, ignore_errors=True)
        self._pakiety_mgr.odswiez()
        self._pakiety_mgr._zglos_zmiane()
        self._przelicz_stan()

    def _przelicz_stan(self) -> None:
        if self.stan == "blad_integralnosci":
            return
        dostepna = any(w["dostepna"] for w in self.lista_pakietow())
        self.stan = "dostepna_aktualizacja" if dostepna else "aktualny"
