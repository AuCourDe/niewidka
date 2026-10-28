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
import stat
import sys
import threading
import time
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


def wczytaj_bajty_pakietu(
    identyfikator: str,
    katalog: Path,
    katalog_pakietow: Path = KATALOG_PAKIETOW,
) -> dict[str, bytes]:
    """K7c pkt 2/3 (audyt #2/#3): ZAUFANY katalog pakietów (wbudowany w aplikację)
    decyduje, które pliki pakietu są wymagane i jakie mają SHA-256; lokalny
    manifest.json nie wyznacza oczekiwanych sum. Każdy plik czytany DO PAMIĘCI
    dokładnie raz: hasz liczony z tych samych bajtów, które wracają do loadera
    (koniec okna sprawdź-użyj). Komplet wymaganych plików obowiązkowy.
    """
    pakiet = next(
        (p for p in wczytaj_pakiety(katalog_pakietow) if p.id == identyfikator), None
    )
    if pakiet is None:
        raise BladPakietu(f"nieznany pakiet {identyfikator} w zaufanym katalogu pakietów")
    wynik: dict[str, bytes] = {}
    for plik in pakiet.pliki:
        sciezka = katalog / plik.nazwa
        if sciezka.is_symlink() or not sciezka.is_file():
            raise BladPakietu(f"pakiet {identyfikator}: brak pliku {plik.nazwa}")
        bajty = sciezka.read_bytes()
        if len(bajty) != plik.rozmiar or hashlib.sha256(bajty).hexdigest() != plik.sha256:
            raise BladPakietu(f"pakiet {identyfikator}: rozbieżny SHA-256 dla {plik.nazwa}")
        wynik[plik.nazwa] = bajty
    return wynik


def zrodlo(env: dict[str, str] | None = None) -> str:
    """Baza URL pobierania: NIEWIDKA_MODELE_ZRODLO albo załączniki wydania."""
    env = os.environ if env is None else env
    return env.get("NIEWIDKA_MODELE_ZRODLO") or ZRODLO_DOMYSLNE


def limit_czasu_domyslny(env: dict[str, str] | None = None) -> int:
    """Całkowity limit czasu JEDNEJ operacji pobierania/instalacji (K7c pkt 8,
    audyt: timeout odczytu httpx dotyczy fragmentu, nie całego transferu).
    Konfigurowalny NIEWIDKA_PAKIETY_LIMIT_CZASU_S; domyślnie 1800 s."""
    env = os.environ if env is None else env
    surowa = env.get("NIEWIDKA_PAKIETY_LIMIT_CZASU_S", "1800")
    try:
        return int(surowa)
    except ValueError:
        raise ValueError(
            f"NIEWIDKA_PAKIETY_LIMIT_CZASU_S: oczekiwano liczby, jest {surowa!r}"
        ) from None


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


# --- K7c pkt 4 (audyt #4): dowiązania nie prowadzą poza katalog modeli --------

PUBLIKOWANY = ".publikowany"


def _otworz_nowy(sciezka: Path) -> int:
    """Świeży plik bez podążania za dowiązaniami: O_CREAT|O_EXCL, O_NOFOLLOW
    gdzie dostępne (POSIX); na Windows O_EXCL i tak omija podstawiane nazwy."""
    flagi = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return os.open(sciezka, flagi, 0o600)


def _jest_dowiazaniem(sciezka: Path) -> bool:
    """Symlink (POSIX) albo reparse point/junction (Windows)."""
    try:
        st = sciezka.lstat()
    except OSError:
        return False
    atrybuty = getattr(st, "st_file_attributes", 0)
    return stat.S_ISLNK(st.st_mode) or bool(
        atrybuty & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _odrzuc_dowiazania(katalog: Path, nazwa_rel: str) -> None:
    """Dowiązanie w dowolnym pośrednim katalogu ścieżki = odmowa zapisu."""
    biezacy = katalog
    for czlon in Path(nazwa_rel).parts[:-1]:
        biezacy = biezacy / czlon
        if _jest_dowiazaniem(biezacy):
            raise BladPakietu("ścieżka modeli zawiera dowiązanie; odmowa zapisu")


def _opublikuj(
    bajty: bytes, cel: Path, suma_oczekiwana: str, katalog: Path
) -> None:
    """Publikacja zweryfikowanych bajtów: hasz z DOKŁADNIE tych bajtów, które
    zapisujemy (K7c pkt 3, koniec okna sprawdź-użyj), zapis do świeżego pliku
    O_EXCL i atomowy os.replace (rename NIE podąża za symlinkiem w miejscu
    docelowym, więc podstawiony manifest/cel zostaje zastąpiony, nie przezpisany).
    """
    if hashlib.sha256(bajty).hexdigest() != suma_oczekiwana:
        raise BladPakietu(f"SHA-256 niezgodny dla {cel.name}; plik nie trafił do katalogu wag")
    _opublikuj_bez_hasza(bajty, cel, katalog)


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
    katalog: Path,
    rozmiar: int,
    limit_czasu_s: int = 1800,
    przerwano=None,
    postep=None,
) -> None:
    """Strumieniowe pobranie jednego pliku z wznawianiem; publikacja zweryfikowanych
    bajtów (_opublikuj). Plik częściowy otwierany bez podążania za dowiązaniami.
    K7c pkt 8 (audyt): twardy limit bajtów = rozmiar z katalogu (też przy Range),
    całkowity limit czasu i anulowanie sprawdzane przy KAŻDYM kawałku."""
    czesciowy = cel.with_name(cel.name + CZESCIOWY)
    if _jest_dowiazaniem(czesciowy):
        czesciowy.unlink()  # podstawione dowiązanie nie jest naszym plikiem częściowym
    naglowki = {}
    start = czesciowy.stat().st_size if czesciowy.is_file() else 0
    if start > rozmiar:
        raise BladPakietu(f"plik częściowy większy niż rozmiar z katalogu: {cel.name}")
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
        # przerwane pobieranie zostawia częściowy: kolejne pobranie wznowi;
        # O_APPEND|O_NOFOLLOW: nie piszemy przez podstawiony symlink
        try:
            fd = (
                os.open(
                    czesciowy,
                    os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
                )
                if start
                else _otworz_nowy(czesciowy)
            )
        except OSError as blad:
            raise BladPakietu(f"plik częściowy nieosiągalny: {cel.name}") from blad
        with os.fdopen(fd, "ab" if start else "wb") as uchwyt:
            gotowe = start
            start_czasu = time.monotonic()
            for kawalek in odpowiedz.iter_bytes():
                if przerwano is not None and przerwano():
                    raise BladPakietu("pobieranie przerwane")
                if time.monotonic() - start_czasu > limit_czasu_s:
                    raise BladPakietu(
                        "pobieranie przekroczyło całkowity limit czasu; kolejna próba wznowi"
                    )
                if gotowe + len(kawalek) > rozmiar:
                    raise BladPakietu(
                        f"serwer wysłał więcej bajtów niż rozmiar z katalogu pakietów: {cel.name}"
                    )
                uchwyt.write(kawalek)
                gotowe += len(kawalek)
                if postep is not None:
                    postep(gotowe, razem)
    try:
        _opublikuj(czesciowy.read_bytes(), cel, suma_oczekiwana, katalog)
    except BladPakietu:
        # rozbieżny hash = trujący plik częściowy: wznowienie z niego nic nie da
        czesciowy.unlink(missing_ok=True)
        raise
    else:
        czesciowy.unlink(missing_ok=True)


def _zapisz_manifest(pakiet: Pakiet, katalog: Path) -> None:
    """Manifest informacyjny; zapis atomowy (K7c pkt 4): świeży O_EXCL + os.replace,
    więc podstawiony symlink manifest.json zostaje ZASTĄPIONY, nie przezpisany."""
    katalog_pakietu = katalog / pakiet.katalog_rel if pakiet.katalog_rel else katalog
    manifest = {
        "pakiet": pakiet.id,
        "pliki": {Path(p.nazwa).name: p.sha256 for p in pakiet.pliki},
    }
    tresc = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _opublikuj_bez_hasza(tresc, katalog_pakietu / "manifest.json", katalog)


def _opublikuj_bez_hasza(bajty: bytes, cel: Path, katalog: Path) -> None:
    _odrzuc_dowiazania(katalog, str(cel.relative_to(katalog)))
    cel.parent.mkdir(parents=True, exist_ok=True)
    tymczasowy = cel.with_name(cel.name + PUBLIKOWANY)
    try:
        with os.fdopen(_otworz_nowy(tymczasowy), "wb") as uchwyt:
            uchwyt.write(bajty)
        os.replace(tymczasowy, cel)
    except BaseException:
        tymczasowy.unlink(missing_ok=True)
        raise


def pobierz(
    pakiet: Pakiet,
    katalog: Path,
    zrodlo_bazowe: str,
    klient: httpx.Client | None = None,
    postep=None,
    limit_czasu_s: int | None = None,
    przerwano=None,
) -> None:
    """Pobiera wszystkie pliki pakietu; pomija te już zgodne z SHA-256."""
    wlasny = klient is None
    klient = klient or httpx.Client(follow_redirects=True, timeout=600)
    limit = limit_czasu_s if limit_czasu_s is not None else limit_czasu_domyslny()
    try:
        para = _podziel_postep(postep, [p.rozmiar for p in pakiet.pliki])
        postep_pliku, po_pliku = para if para else (None, None)
        for plik in pakiet.pliki:
            if przerwano is not None and przerwano():
                raise BladPakietu("pobieranie przerwane")
            cel = katalog / plik.nazwa
            if cel.is_file() and not cel.is_symlink() and _sha256(cel) == plik.sha256:
                if po_pliku is not None:
                    po_pliku(plik.rozmiar)
                continue
            _pobierz_plik(
                klient,
                f"{zrodlo_bazowe.rstrip('/')}/{plik.zrodlo}",
                cel,
                plik.sha256,
                katalog,
                rozmiar=plik.rozmiar,
                limit_czasu_s=limit,
                przerwano=przerwano,
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
    limit_czasu_s: int | None = None,
    przerwano=None,
) -> None:
    """Instalacja offline (IT): katalog z plikami o nazwach jak w źródle;
    weryfikacja SHA-256 przed zapisem, atomowo jak przy pobieraniu (K7c pkt 3/4:
    te same bajty są haszowane i publikowane, bez podążania za dowiązaniami).
    K7c pkt 8: limit bajtów = rozmiar z katalogu wag (plik lustra większy =
    odmowa PRZED kopiowaniem), limit czasu i anulowanie jak przy pobieraniu."""
    limit = limit_czasu_s if limit_czasu_s is not None else limit_czasu_domyslny()
    start_czasu = time.monotonic()
    for plik in pakiet.pliki:
        if przerwano is not None and przerwano():
            raise BladPakietu("instalacja przerwana")
        if time.monotonic() - start_czasu > limit:
            raise BladPakietu("instalacja przekroczyła całkowity limit czasu")
        wzor = zrodlo_katalog / plik.zrodlo
        if wzor.is_symlink() or not wzor.is_file():
            raise BladPakietu(f"brak pliku {plik.zrodlo} w katalogu źródłowym")
        if wzor.stat().st_size != plik.rozmiar:
            raise BladPakietu(
                f"plik w katalogu źródłowym ma inny rozmiar niż katalog pakietów: {plik.zrodlo}"
            )
        bajty = wzor.read_bytes()
        if len(bajty) != plik.rozmiar:
            raise BladPakietu(f"plik źródłowy zmienił rozmiar w trakcie odczytu: {plik.zrodlo}")
        _opublikuj(bajty, katalog / plik.nazwa, plik.sha256, katalog)
        if postep is not None:
            postep(plik.rozmiar, pakiet.rozmiar)
    _zapisz_manifest(pakiet, katalog)


@dataclass
class PostepPobierania:
    """Stan bieżącej operacji (pobieranie albo instalacja) do API i UI."""

    pakiet: str | None = None  # id pakietu w trakcie; None = nic trwa
    pobrane: int = 0
    razem: int = 0
    blad: str | None = None


class MenedzerPakietow:
    """Stan pakietów + jedno pobieranie naraz w wątku tła (K7b).

    Operacje rdzenia (`pobierz`, `usun`, `instaluj_z_katalogu`) wołane z wątku;
    postęp publikowany w `PostepPobierania` dla GET /api/pakiety. `poziomy_dostepne`
    pilnuje pakietu wymaganego: bez niego żaden poziom suwaka nie działa.
    """

    def __init__(
        self,
        lista: list[Pakiet],
        katalog: Path,
        zrodlo_bazowe: str,
        klient: httpx.Client | None = None,
        on_zmiana: callable | None = None,  # type: ignore[valid-type] # K7c: invalidacja cache detektorów
    ):
        self._pakiety = {p.id: p for p in lista}
        self._katalog = Path(katalog)
        self._zrodlo = zrodlo_bazowe
        self._klient = klient
        self._zajete = threading.Lock()
        self._w_toku = False
        self._przerwano = threading.Event()
        self.postep = PostepPobierania()
        self._on_zmiana = on_zmiana

    def ustaw_zwrot_zmiany(self, on_zmiana: callable) -> None:  # type: ignore[valid-type]
        """K7c: zwrot wywoływany po każdej zakończonej operacji (API podpina
        czyszczenie cache detektorów, by nowy stan pakietów był widoczny)."""
        self._on_zmiana = on_zmiana

    def _zglos_zmiane(self) -> None:
        if self._on_zmiana is not None:
            self._on_zmiana()

    def stan_pakietu(self, identyfikator: str) -> str | None:
        """Zweryfikowany stan pakietu (SHA-256); None = pakiet poza katalogiem."""
        pakiet = self._pakiety.get(identyfikator)
        return stan(pakiet, self._katalog) if pakiet else None

    def lista(self) -> list[dict]:
        return [
            {
                "id": p.id,
                "nazwa": p.nazwa,
                "opis": p.opis,
                "wymagany": p.wymagany,
                "poziomy": p.poziomy,
                "wymaga": p.wymaga,
                "rozmiar_bajtow": p.rozmiar,
                "stan": stan(p, self._katalog),
            }
            for p in self._pakiety.values()
        ]

    def poziomy_dostepne(self) -> list[int]:
        for p in self._pakiety.values():
            if p.wymagany and stan(p, self._katalog) == "zainstalowany":
                return p.poziomy
        return []

    def brakujacy_wymagany(self) -> list[str]:
        return [
            p.id
            for p in self._pakiety.values()
            if p.wymagany and stan(p, self._katalog) != "zainstalowany"
        ]

    def zakonczone(self) -> bool:
        return not self._w_toku

    def pobierz(self, identyfikator: str) -> bool:
        """Uruchamia pobieranie w wątku tła; False gdy inne już trwa albo pakiet
        nieznany (K7b: operacja długotrwała, POST odpowiada 202 od razu)."""
        pakiet = self._pakiety.get(identyfikator)
        if pakiet is None:
            return False
        return self._uruchom_w_tle(
            pakiet,
            lambda: pobierz(
                pakiet,
                self._katalog,
                self._zrodlo,
                klient=self._klient,
                postep=self._przyjmij_postep,
                przerwano=self._przerwano.is_set,
            ),
            "pobieranie",
        )

    def anuluj(self) -> None:
        """K7c pkt 8: prosi bieżącą operację o przerwanie (sprawdzane przy każdym
        kawałku); efekty widoczne w postep.blad po jej zakończeniu."""
        self._przerwano.set()

    def instaluj(self, identyfikator: str, katalog_zrodlowy: Path) -> bool:
        """Instalacja offline w tle (K7c pkt 8, audyt: kopia lokalna blokowała
        pętlę API); False gdy inna operacja trwa. Limit bajtów/czasu jak przy
        pobieraniu; błędy lądują w postep.blad."""
        pakiet = self._pakiety[identyfikator]
        return self._uruchom_w_tle(
            pakiet,
            lambda: instaluj_z_katalogu(
                pakiet,
                self._katalog,
                katalog_zrodlowy,
                postep=self._przyjmij_postep,
                przerwano=self._przerwano.is_set,
            ),
            "instalacja",
        )

    def _uruchom_w_tle(self, pakiet: Pakiet, operacja, etykieta: str) -> bool:
        with self._zajete:
            if self._w_toku:
                return False
            self._w_toku = True
        self.postep = PostepPobierania(pakiet=pakiet.id, razem=pakiet.rozmiar)
        self._przerwano.clear()

        def praca():
            try:
                operacja()
            except BladPakietu as blad:
                self.postep.blad = str(blad)
            except httpx.HTTPStatusError as blad:
                # K7c pkt 5 (audyt): kontrolowany komunikat — bez URL (bywa z
                # login:hasło lustra) i bez tekstu wyjątku; tylko kod HTTP
                self.postep.blad = (
                    f"{pakiet.id}: {etykieta} nie powiodło się (HTTP {blad.response.status_code})"
                )
            except (httpx.HTTPError, OSError):
                self.postep.blad = f"{pakiet.id}: {etykieta} nie powiodła się (błąd sieci)"
            finally:
                self.postep.pakiet = None
                self._w_toku = False
                self._zglos_zmiane()

        threading.Thread(target=praca, name="niewidka-pakiety", daemon=True).start()
        return True

    def usun(self, identyfikator: str) -> None:
        usun(self._pakiety[identyfikator], self._katalog)
        self._zglos_zmiane()

    def _przyjmij_postep(self, pobrane: int, razem: int) -> None:
        self.postep.pobrane = pobrane
        self.postep.razem = razem

    def czekaj(self, limit_s: float = 60) -> None:
        """Tylko dla testów: czeka na koniec operacji w tle."""
        koniec = time.monotonic() + limit_s
        while self._w_toku and time.monotonic() < koniec:
            time.sleep(0.01)
