"""Klient centralnego serwera inferencji (docs/SERWER-INFERENCJI.md).

`ZdalnyDetektor` ma ten sam interfejs co detektory lokalne (`znajdz(tekst)`), ale
tekst wysyła do serwera w sieci lokalnej, który robi WYŁĄCZNIE wykrywanie. Mapy,
klucz mapy, kontrola wyniku i listy zostają na komputerze użytkownika. Błąd sieci
albo serwera = `SerwerModeliNiedostepny` (fail-closed): nigdy wynik bez modelu.
"""

from __future__ import annotations

import base64
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from niewidka.klucze import BrakKlucza, _z_pliku, _zapisz_plik
from niewidka.konfig import Konfig
from niewidka.model import TypEncji, Zakres

LOOPBACK = ("127.0.0.1", "localhost", "::1")


class SerwerModeliNiedostepny(Exception):
    """Serwer inferencji nie odpowiedział poprawnie; komunikat bez treści dokumentu."""


class BladTokenu(Exception):
    """Plik tokenu brakuje, ma złe uprawnienia albo zły format."""


def jest_loopbackiem(host: str) -> bool:
    return host in LOOPBACK or host.startswith("127.")


def wczytaj_token(sciezka: Path | None, opis: str = "token") -> str:
    """Token z pliku sekretów (base64, 0600 na POSIX); ten sam format co klucz mapy,
    więc `python -m niewidka.serwer_inferencji nowy-token` i odczyt reużywają `klucze`."""
    if sciezka is None:
        raise BladTokenu(f"brak pliku z tokenem ({opis}): wskaż go w konfiguracji")
    plik = Path(sciezka).expanduser()
    if not plik.is_file():
        raise BladTokenu(f"plik z tokenem nie istnieje: {plik}")
    try:
        return base64.b64encode(_z_pliku(plik)).decode("ascii")
    except BrakKlucza as blad:
        raise BladTokenu(f"plik z tokenem {plik}: {blad}") from None


def zapisz_nowy_token(sciezka: Path) -> None:
    """Nowy token do pliku (0600, bez nadpisywania istniejącego)."""
    _zapisz_plik(sciezka)


def sprawdz_adres(adres: str, zezwol_bez_tls: bool) -> str:
    """Adres bazowy serwera bez końcowego ukośnika; http tylko dla loopbacku
    albo przy jawnej zgodzie administratora (`zezwol_bez_tls`)."""
    czesci = urlsplit(adres)
    if czesci.scheme not in ("http", "https") or not czesci.hostname:
        raise ValueError(f"adres serwera inferencji {adres!r}: oczekiwano https://host:port")
    if czesci.scheme == "http" and not (jest_loopbackiem(czesci.hostname) or zezwol_bez_tls):
        raise ValueError(
            f"adres serwera inferencji {adres!r}: http poza loopbackiem wymaga TLS (https://) "
            "albo jawnego zezwol_bez_tls = true w [inferencja]"
        )
    return adres.rstrip("/")


def zbuduj_klienta(konfig: Konfig, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Klient httpx do serwera inferencji: weryfikacja TLS włączona (z własnym CA, jeśli
    podano `ca_plik`), token w nagłówku, bez podążania za przekierowaniami (token nie
    wycieka na inny adres). Błędy konfiguracji zgłaszane od razu, przy starcie."""
    adres = sprawdz_adres(konfig.inferencja_adres or "", konfig.inferencja_zezwol_bez_tls)
    token = wczytaj_token(konfig.inferencja_token_plik, "inferencja.token_plik")
    verify: ssl.SSLContext | bool = True
    if konfig.inferencja_ca_plik:
        try:
            verify = ssl.create_default_context(cafile=str(konfig.inferencja_ca_plik))
        except (OSError, ssl.SSLError) as blad:
            raise ValueError(f"ca_plik {konfig.inferencja_ca_plik}: {blad}") from None
    return httpx.Client(
        base_url=adres,
        headers={"Authorization": f"Bearer {token}"},
        timeout=konfig.inferencja_timeout_s,
        verify=verify,
        follow_redirects=False,
        transport=transport,
    )


def _niedostepny(przyczyna: str) -> SerwerModeliNiedostepny:
    return SerwerModeliNiedostepny(
        f"Serwer modeli nie odpowiada ({przyczyna}). Dokument nie został ukryty; "
        "spróbuj ponownie albo zgłoś problem administratorowi."
    )


def _zapytaj(klient: httpx.Client, metoda: str, sciezka: str, **argumenty) -> dict:
    try:
        odpowiedz = klient.request(metoda, sciezka, **argumenty)
    except httpx.TimeoutException:
        raise _niedostepny("przekroczono czas oczekiwania") from None
    except httpx.HTTPError as blad:
        raise _niedostepny(f"błąd połączenia: {type(blad).__name__}") from None
    if odpowiedz.status_code in (401, 403):
        raise _niedostepny("serwer odrzucił token; poproś administratora o nowy plik tokenu")
    if odpowiedz.status_code != 200:
        raise _niedostepny(f"serwer odpowiedział kodem {odpowiedz.status_code}")
    try:
        tresc = odpowiedz.json()
    except ValueError:
        raise _niedostepny("niepoprawna odpowiedź serwera") from None
    if not isinstance(tresc, dict):
        raise _niedostepny("niepoprawna odpowiedź serwera")
    return tresc


def stan_serwera(klient: httpx.Client) -> dict:
    """GET /v1/stan: {wersja, poziomy, urzadzenie}."""
    return _zapytaj(klient, "GET", "/v1/stan")


class ZdalnyDetektor:
    """Detektor poziomu `poziom` na serwerze inferencji; `wykrywaj_date=False` odfiltrowuje
    typ DATA po stronie użytkownika (ustawienie jest lokalne, serwer zwraca wszystko)."""

    typy = frozenset(TypEncji)

    def __init__(self, poziom: int, klient: httpx.Client, wykrywaj_date: bool = True):
        self.poziom = poziom
        self.nazwa = f"serwer-inferencji:poziom{poziom}"
        self._klient = klient
        self._wykrywaj_date = wykrywaj_date

    def znajdz(self, tekst: str) -> list[Zakres]:
        tresc = _zapytaj(
            self._klient, "POST", "/v1/wykryj", json={"tekst": tekst, "poziom": self.poziom}
        )
        try:
            zakresy = [
                Zakres(
                    start=int(z["start"]),
                    koniec=int(z["koniec"]),
                    typ=TypEncji(z["typ"]),
                    pewnosc=float(z["pewnosc"]),
                    zrodlo=str(z["zrodlo"]),
                    suma_kontrolna=bool(z.get("suma_kontrolna", False)),
                    podejrzana=bool(z.get("podejrzana", False)),
                )
                for z in tresc["zakresy"]
            ]
        except (KeyError, TypeError, ValueError):
            raise _niedostepny("niepoprawna odpowiedź serwera") from None
        if any(not 0 <= z.start < z.koniec <= len(tekst) for z in zakresy):
            raise _niedostepny("serwer zwrócił zakresy poza tekstem")
        if not self._wykrywaj_date:
            zakresy = [z for z in zakresy if z.typ is not TypEncji.DATA]
        return zakresy
