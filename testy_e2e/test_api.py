#!/usr/bin/env python3
"""Testy E2E API Niewidki na korpisie fikcyjnych dokumentów.

Wyłącznie biblioteka standardowa Pythona 3.13; uruchamialny na Windows i Linux.

Użycie:
    python test_api.py --baza http://127.0.0.1:8871 --wyjscie raport.json [--poziomy 1,2,3]

Kontrakt API (odczytany z `niewidka/api.py` i `niewidka/web/apka.js`):
- token sesji przychodzi w meta strony głównej: GET / -> <meta name="niewidka-token" content="...">,
- każde żądanie idzie jak z przeglądarki: nagłówek Origin równy bazie oraz X-Niewidka-Token,
- POST /api/ukryj: multipart (poziom, plik albo tekst) -> 200 z archiwum ZIP
  (wynik `ZANONIMIZOWANY_<id>.<ext>` + mapa `<id>.nwidka`) i nagłówkami x-niewidka-*;
  wynik zablokowany przez kontrolę = 422 z {"status": "zablokowany", "typy": {...}},
- POST /api/przywroc: multipart (wynik, mapa) -> przywrócony dokument,
- brak/odmowa: 403 (token/Host/Origin), 413, 415 (format), 422, 503.

Testy: T1 bezpieczeństwo, T2 ukrywanie per dokument i poziom (wycieki/nadmiar),
T3 przywrócenie identyczne, T4 mapa z innego dokumentu -> odmowa, T5 zły format
i pusty tekst -> czytelny błąd 4xx. Kod wyjścia 1, gdy wyciek albo błąd.
Błędy aplikacji są WYNIKIEM testu, nie czymś do naprawiania w tym skrypcie.
"""

from __future__ import annotations

import argparse
import http.client
import io
import json
import re
import sys
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

_NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DOPISEK_POCZATEK = "ZANONIMIZOWANY"


# --------------------------- warstwa HTTP ---------------------------


class Serwer:
    """Klient HTTP z jawną kontrolą Host i Origin (jak przeglądarka)."""

    def __init__(self, baza: str, timeout: float = 300.0):
        czesci = urllib.parse.urlsplit(baza)
        if czesci.scheme != "http" or not czesci.hostname:
            raise ValueError(f"--baza musi być URL http://host:port, jest {baza!r}")
        self.host = czesci.hostname
        self.port = czesci.port or 80
        self.baza = baza
        self.timeout = timeout
        self.polaczenie: http.client.HTTPConnection | None = None

    def _wez_polaczenie(self) -> http.client.HTTPConnection:
        if self.polaczenie is None:
            self.polaczenie = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        return self.polaczenie

    def zadaj(
        self,
        metoda: str,
        sciezka: str,
        *,
        origin: str | None = None,
        host: str | None = None,
        token: str | None = None,
        cialo: bytes | None = None,
        naglowki: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        naglowki_zadania = dict(naglowki or {})
        if origin is not None:
            naglowki_zadania["Origin"] = origin
        if host is not None:  # jawny nadpisany Host (test T1)
            naglowki_zadania["Host"] = host
        if token is not None:
            naglowki_zadania["X-Niewidka-Token"] = token
        for proba in (1, 2):
            conn = self._wez_polaczenie()
            try:
                conn.request(metoda, sciezka, body=cialo, headers=naglowki_zadania)
                odpowiedz = conn.getresponse()
                dane = odpowiedz.read()
                return odpowiedz.status, {k.lower(): v for k, v in odpowiedz.getheaders()}, dane
            except (http.client.HTTPException, OSError):
                self.polaczenie = None
                if proba == 2:
                    raise
        raise AssertionError("nieosiągalne")


def multipart(
    pola: list[tuple[str, str]], pliki: list[tuple[str, str, bytes]]
) -> tuple[bytes, str]:
    """Ciało multipart/form-data zbudowane ręcznie (stdlib)."""
    granica = "niewidka-test-" + uuid.uuid4().hex
    bufor = io.BytesIO()
    for nazwa, wartosc in pola:
        bufor.write(
            (
                f"--{granica}\r\n"
                f'Content-Disposition: form-data; name="{nazwa}"\r\n'
                f"\r\n{wartosc}\r\n"
            ).encode()
        )
    for pole, nazwa_pliku, tresc in pliki:
        bufor.write(
            (
                f"--{granica}\r\n"
                f'Content-Disposition: form-data; name="{pole}"; filename="{nazwa_pliku}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
        )
        bufor.write(tresc)
        bufor.write(b"\r\n")
    bufor.write(f"--{granica}--\r\n".encode())
    return bufor.getvalue(), granica


def _wyslij_formularz(
    serwer: Serwer, token: str, sciezka: str, pola: list[tuple[str, str]], pliki: list[tuple[str, str, bytes]]
) -> tuple[int, dict[str, str], bytes]:
    cialo, granica = multipart(pola, pliki)
    return serwer.zadaj(
        "POST",
        sciezka,
        origin=serwer.baza,
        token=token,
        cialo=cialo,
        naglowki={"Content-Type": f"multipart/form-data; boundary={granica}"},
    )


# --------------------------- pomocnicze ---------------------------


def tekst_docx(dane: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(dane)) as archiwum:
        korzen = ET.fromstring(archiwum.read("word/document.xml"))
    return "\n".join("".join(t.text or "" for t in p.iter(f"{_NS_W}t")) for p in korzen.iter(f"{_NS_W}p"))


def tekst_wyniku(dane: bytes, rozszerzenie: str) -> str:
    if rozszerzenie == "txt":
        return dane.decode("utf-8")
    return tekst_docx(dane)


def czesci_zip(dane: bytes) -> dict[str, bytes]:
    czesci: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(dane)) as archiwum:
        for nazwa in archiwum.namelist():
            czesci[nazwa] = archiwum.read(nazwa)
    return czesci


def blad_z_odpowiedzi(dane: bytes) -> str:
    try:
        tresc = json.loads(dane.decode("utf-8"))
    except (ValueError, AttributeError):
        return dane[:200].decode("utf-8", "replace")
    return str(tresc.get("blad") or tresc.get("detail") or "")


def wczytaj_korpus(katalog: Path) -> list[dict]:
    dokumenty = []
    for plik_json in sorted(katalog.glob("*.json")):
        oczekiwania = json.loads(plik_json.read_text(encoding="utf-8"))
        formy = [("txt", plik_json.with_suffix(".txt"))]
        plik_docx = plik_json.with_suffix(".docx")
        if plik_docx.is_file():
            formy.append(("docx", plik_docx))
        dokumenty.append({"nazwa": plik_json.stem, "oczekiwania": oczekiwania, "formy": formy})
    return dokumenty


# --------------------------- testy ---------------------------


def pobierz_token(serwer: Serwer) -> str:
    status, _, dane = serwer.zadaj("GET", "/", origin=serwer.baza)
    if status != 200:
        raise RuntimeError(f"GET / -> {status}, oczekiwano strony z tokenem")
    dopasowanie = re.search(
        rb'<meta[^>]*name="niewidka-token"[^>]*content="([^"]+)"', dane
    ) or re.search(rb'<meta[^>]*content="([^"]+)"[^>]*name="niewidka-token"', dane)
    if not dopasowanie:
        raise RuntimeError("strona główna nie zawiera meta niewidka-token")
    return dopasowanie.group(1).decode("ascii")


def stan_serwera(serwer: Serwer, token: str) -> dict:
    status, _, dane = serwer.zadaj("GET", "/api/stan", origin=serwer.baza, token=token)
    if status != 200:
        return {"blad": f"GET /api/stan -> {status}: {blad_z_odpowiedzi(dane)}"}
    return json.loads(dane.decode("utf-8"))


def czekaj_na_pakiety(serwer: Serwer, token: str, poziomy: list[int], limit_s: float = 150.0) -> dict | None:
    """Serwer weryfikuje SHA-256 wag w tle; czekamy, aż wybrane poziomy będą dostępne."""
    start = time.monotonic()
    ostatni_stan = None
    while time.monotonic() - start < limit_s:
        status, _, dane = serwer.zadaj("GET", "/api/pakiety", origin=serwer.baza, token=token)
        if status == 200:
            ostatni_stan = json.loads(dane.decode("utf-8"))
            dostepne = ostatni_stan.get("poziomy_dostepne", [])
            if all(p in dostepne for p in poziomy):
                return ostatni_stan
        time.sleep(2)
    return ostatni_stan


def test_t1(serwer: Serwer, token: str) -> dict:
    wyniki = {}

    cialo, granica = _cialo_ukryj_poziom1()
    status, _, dane = serwer.zadaj("GET", "/api/pakiety", origin=serwer.baza)
    wyniki["GET /api/pakiety bez tokenu"] = {
        "oczekiwane": 403, "kod": status, "ok": status == 403, "blad": blad_z_odpowiedzi(dane),
    }

    status, _, dane = serwer.zadaj(
        "POST", "/api/ukryj", origin="https://zlosliwa-strona.example.net", token=token,
        cialo=cialo, naglowki={"Content-Type": f"multipart/form-data; boundary={granica}"},
    )
    wyniki["POST /api/ukryj z obcym Origin"] = {
        "oczekiwane": 403, "kod": status, "ok": status == 403, "blad": blad_z_odpowiedzi(dane),
    }

    cialo, granica = _cialo_ukryj_poziom1()
    status, _, dane = serwer.zadaj(
        "POST", "/api/ukryj", origin=serwer.baza, host="zlosliwa-strona.example.net", token=token,
        cialo=cialo, naglowki={"Content-Type": f"multipart/form-data; boundary={granica}"},
    )
    wyniki["POST /api/ukryj z obcym Host"] = {
        "oczekiwane": 403, "kod": status, "ok": status == 403, "blad": blad_z_odpowiedzi(dane),
    }
    return wyniki


def _cialo_ukryj_poziom1() -> tuple[bytes, str]:
    return multipart([("poziom", "1")], [("tekst", "probka.txt", "Przykładowy tekst testowy.".encode())])


def przebieg_komorki(
    serwer: Serwer, token: str, plik: Path, oczekiwania: dict, poziom: int
) -> tuple[dict, tuple[str, bytes, str, bytes] | None]:
    """T2+T3 dla jednej pary (dokument, format, poziom). Zwraca (wynik, artefakty)."""
    rozszerzenie = plik.suffix.lstrip(".")
    tresc_oryginalu = plik.read_bytes()
    wynik: dict = {"dokument": plik.name, "poziom": poziom}

    t0 = time.perf_counter()
    status, nagl, dane = _wyslij_formularz(
        serwer, token, "/api/ukryj",
        [("poziom", str(poziom))], [("plik", plik.name, tresc_oryginalu)],
    )
    wynik["czas_ukryj_s"] = round(time.perf_counter() - t0, 2)
    wynik["kod_ukryj"] = status

    if status != 200:
        tresc_bledu = {}
        try:
            tresc_bledu = json.loads(dane.decode("utf-8"))
        except (ValueError, AttributeError):
            pass
        if tresc_bledu.get("status") == "zablokowany":
            wynik["status"] = "zablokowany"
            wynik["typy_blokady"] = tresc_bledu.get("typy", {})
        else:
            wynik["status"] = "blad"
        wynik["blad"] = blad_z_odpowiedzi(dane)
        return wynik, None

    wynik["status_naglowek"] = nagl.get("x-niewidka-status")
    wynik["identyfikator"] = nagl.get("x-niewidka-identyfikator", "")
    try:
        wynik["statystyki"] = json.loads(nagl.get("x-niewidka-statystyki", "{}"))
    except (ValueError, AttributeError):
        wynik["statystyki"] = {}

    czesci = czesci_zip(dane)
    nazwa_wyniku = next((n for n in czesci if not n.endswith(".nwidka")), None)
    nazwa_mapy = next((n for n in czesci if n.endswith(".nwidka")), None)
    if not nazwa_wyniku or not nazwa_mapy:
        wynik["status"] = "blad"
        wynik["blad"] = f"ZIP bez pary wynik+mapa: {sorted(czesci)}"
        return wynik, None
    dane_wyniku, dane_mapy = czesci[nazwa_wyniku], czesci[nazwa_mapy]

    tekst = tekst_wyniku(dane_wyniku, rozszerzenie)
    wynik["dopisek_ok"] = tekst.startswith(DOPISEK_POCZATEK)
    wynik["wycieki"] = [f for f in oczekiwania["musza_zniknac"] if f in tekst]
    wynik["nadmiar"] = [f for f in oczekiwania.get("moga_zostac", []) if f not in tekst]
    if wynik["wycieki"]:
        wynik["status"] = "wyciek"
    elif not wynik["dopisek_ok"] or wynik["status_naglowek"] != "ukonczony":
        wynik["status"] = "blad"
        wynik["blad"] = (
            f"dopisek_ok={wynik['dopisek_ok']}, status_naglowek={wynik['status_naglowek']!r}"
        )
    else:
        wynik["status"] = "ok"

    # T3: przywrócenie
    t1 = time.perf_counter()
    status_p, nagl_p, dane_p = _wyslij_formularz(
        serwer, token, "/api/przywroc", [], [("wynik", nazwa_wyniku, dane_wyniku), ("mapa", nazwa_mapy, dane_mapy)]
    )
    wynik["czas_przywroc_s"] = round(time.perf_counter() - t1, 2)
    if status_p != 200:
        wynik["status"] = "blad"
        wynik["przywrocenie"] = f"blad HTTP {status_p}: {blad_z_odpowiedzi(dane_p)}"
        return wynik, (nazwa_wyniku, dane_wyniku, nazwa_mapy, dane_mapy)
    wynik["rozbieznosci"] = json.loads(nagl_p.get("x-niewidka-rozbieznosci", "[]"))
    if rozszerzenie == "txt":
        identyczne = dane_p == tresc_oryginalu
    else:
        identyczne = tekst_docx(dane_p) == tekst_docx(tresc_oryginalu)
    wynik["przywrocenie"] = bool(identyczne)
    if not identyczne or wynik["rozbieznosci"]:
        wynik["status"] = "blad"
    return wynik, (nazwa_wyniku, dane_wyniku, nazwa_mapy, dane_mapy)


def test_t4(serwer: Serwer, token: str, artefakty: dict) -> dict:
    """Mapa z innego dokumentu musi zostać odrzucona (4xx z komunikatem)."""
    pary = [(klucz, wartosci) for klucz, wartosci in sorted(artefakty.items()) if klucz[1] == "txt"]
    if len(pary) < 2:
        return {"status": "pominiety", "opis": "mniej niż dwa udane dokumenty TXT do zestawienia"}
    (dok_a, _, poziom), (nazwa_w_a, dane_w_a, _, _) = pary[0]
    inne = next(((k, a) for k, a in pary[1:] if k[0] != dok_a), None)
    if inne is None:
        return {"status": "pominiety", "opis": "tylko jeden udany dokument TXT do zestawienia"}
    (dok_b, _, _), (_, _, nazwa_m_b, dane_m_b) = inne
    status, _, dane = _wyslij_formularz(
        serwer, token, "/api/przywroc", [], [("wynik", nazwa_w_a, dane_w_a), ("mapa", nazwa_m_b, dane_m_b)]
    )
    ok = 400 <= status < 500 and bool(blad_z_odpowiedzi(dane))
    return {
        "status": "ok" if ok else "niezaliczony",
        "wynik": f"{dok_a} (poziom {poziom}) + mapa z {dok_b} -> HTTP {status}",
        "kod": status,
        "blad": blad_z_odpowiedzi(dane),
    }


def test_t5(serwer: Serwer, token: str) -> dict:
    wyniki = {}
    status, _, dane = _wyslij_formularz(
        serwer, token, "/api/ukryj", [("poziom", "1")], [("plik", "probka.exe", b"Nie jestem dokumentem.\n")]
    )
    wyniki["nieobsługiwany format (.exe)"] = {
        "kod": status, "ok": 400 <= status < 500, "blad": blad_z_odpowiedzi(dane),
    }
    status, _, dane = _wyslij_formularz(
        serwer, token, "/api/ukryj", [("poziom", "1"), ("tekst", "")], []
    )
    wyniki["pusty tekst"] = {
        "kod": status, "ok": 400 <= status < 500, "blad": blad_z_odpowiedzi(dane),
    }
    return wyniki


# --------------------------- raport ---------------------------


def tabelka(wiersze: list[dict]) -> str:
    naglowek = f"{'dokument':<28} {'poz.':<4} {'status':<12} {'wycieki':>7} {'nadmiar':>7} {'przywroc.':>9} {'ukryj[s]':>9} {'przyw[s]':>8}"
    linie = [naglowek, "-" * len(naglowek)]
    for w in wiersze:
        przywr = w.get("przywrocenie")
        przywr_tekst = {True: "tak", False: "NIE", None: "-"}.get(przywr, str(przywr))
        linie.append(
            f"{w['dokument']:<28} {w['poziom']:<4} {w['status']:<12} {len(w.get('wycieki', [])):>7} "
            f"{len(w.get('nadmiar', [])):>7} {przywr_tekst:>9} {w.get('czas_ukryj_s', 0):>9.2f} {w.get('czas_przywroc_s', 0):>8.2f}"
        )
    return "\n".join(linie)


def main() -> int:
    parser = argparse.ArgumentParser(description="Testy E2E API Niewidki")
    parser.add_argument("--baza", default="http://127.0.0.1:8871", help="baza API, np. http://127.0.0.1:8871")
    parser.add_argument("--wyjscie", default="raport.json", help="plik raportu JSON")
    parser.add_argument("--poziomy", default="1,2,3", help="poziomy suwaka do przetestowania")
    parser.add_argument("--korpus", default=str(Path(__file__).parent / "korpus"), help="katalog korpusu")
    argumenty = parser.parse_args()
    poziomy = [int(p) for p in argumenty.poziomy.split(",") if p.strip()]
    if not poziomy or any(p not in (1, 2, 3) for p in poziomy):
        parser.error("--poziomy: dozwolone wartości 1, 2, 3")

    raport: dict = {
        "baza": argumenty.baza,
        "poziomy": poziomy,
        "start": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    serwer = Serwer(argumenty.baza)
    token = pobierz_token(serwer)
    raport["stan_serwera"] = stan_serwera(serwer, token)
    if "blad" in raport["stan_serwera"]:
        print(f"Serwer nie odpowiada poprawnie: {raport['stan_serwera']['blad']}")
        return 1
    wersja = raport["stan_serwera"].get("wersja", "?")
    modele = ", ".join(raport["stan_serwera"].get("modele", [])) or "(brak)"
    print("== Testy E2E API Niewidki ==")
    print(f"Serwer: {argumenty.baza} (wersja {wersja}; modele: {modele})")

    stan_pakietow = czekaj_na_pakiety(serwer, token, poziomy)
    if stan_pakietow is None or not all(p in stan_pakietow.get("poziomy_dostepne", []) for p in poziomy):
        dostepne = (stan_pakietow or {}).get("poziomy_dostepne", [])
        print(f"UWAGA: pakiety nie potwierdziły poziomów {poziomy} (dostępne: {dostepne}); testy i tak startują")

    # T1
    raport["T1"] = test_t1(serwer, token)
    zaliczone_t1 = sum(1 for w in raport["T1"].values() if w["ok"])
    print(f"T1 bezpieczeństwo: {zaliczone_t1}/{len(raport['T1'])} zaliczone")
    for nazwa, w in raport["T1"].items():
        if not w["ok"]:
            print(f"   NIEZALICZONE: {nazwa} -> HTTP {w['kod']} ({w['blad']})")

    # T2 + T3
    dokumenty = wczytaj_korpus(Path(argumenty.korpus))
    if not dokumenty:
        print(f"Korpus pusty: {argumenty.korpus}")
        return 1
    wiersze: list[dict] = []
    artefakty: dict[tuple[str, str, int], tuple[str, bytes, str, bytes]] = {}
    for dokument in dokumenty:
        for rozszerzenie, plik in dokument["formy"]:
            for poziom in poziomy:
                wynik, artefakty_pary = przebieg_komorki(serwer, token, plik, dokument["oczekiwania"], poziom)
                wiersze.append(wynik)
                if artefakty_pary is not None and wynik["status"] == "ok":
                    artefakty[(dokument["nazwa"], rozszerzenie, poziom)] = artefakty_pary
    raport["T2_T3"] = wiersze
    print()
    print(tabelka(wiersze))
    print()

    wycieki = [(w["dokument"], w["poziom"], w["wycieki"]) for w in wiersze if w.get("wycieki")]
    if wycieki:
        print("WYCIEKI (fragmenty, które musiały zniknąć, a zostały):")
        for dokument, poziom, fragmenty in wycieki:
            for fragment in fragmenty:
                print(f"   {dokument} poziom {poziom}: {fragment!r}")
        print()

    # T4
    raport["T4"] = test_t4(serwer, token, artefakty)
    print(f"T4 mapa z innego dokumentu: {raport['T4']['status']} ({raport['T4']['wynik']})")

    # T5
    raport["T5"] = test_t5(serwer, token)
    for nazwa, w in raport["T5"].items():
        stan = "zaliczone" if w["ok"] else "NIEZALICZONE"
        print(f"T5 {nazwa}: {stan} (HTTP {w['kod']}; komunikat: {w['blad'] or '-'}")

    # podsumowanie
    ile_ok = sum(1 for w in wiersze if w["status"] == "ok")
    ile_wyciekow = sum(1 for w in wiersze if w["status"] == "wyciek")
    ile_zablokowanych = sum(1 for w in wiersze if w["status"] == "zablokowany")
    ile_bledow = sum(1 for w in wiersze if w["status"] == "blad")
    ile_nadmiaru = sum(len(w.get("nadmiar", [])) for w in wiersze)
    sukces = (
        ile_ok == len(wiersze)
        and zaliczone_t1 == len(raport["T1"])
        and all(w["ok"] for w in raport["T5"].values())
        and raport["T4"]["status"] in ("ok", "pominiety")
    )
    raport["podsumowanie"] = {
        "komorki": len(wiersze),
        "ok": ile_ok,
        "wycieki": ile_wyciekow,
        "zablokowane": ile_zablokowanych,
        "bledy": ile_bledow,
        "nadmiar_fragmentow": ile_nadmiaru,
        "T1_zaliczone": zaliczone_t1,
        "sukces": sukces,
        "koniec": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    print()
    print(
        f"PODSUMOWANIE T2+T3: komórek {len(wiersze)}, ok {ile_ok}, wycieki {ile_wyciekow}, "
        f"zablokowane {ile_zablokowanych}, błędy {ile_bledow}, nadmiar {ile_nadmiaru} fragmentów"
    )
    print(f"WYNIK CAŁOŚCI: {'SUKCES' if sukces else 'PORAŻKA'}")

    sciezka_wyjscia = Path(argumenty.wyjscie)
    sciezka_wyjscia.write_text(
        json.dumps(raport, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Raport JSON: {sciezka_wyjscia}")
    return 0 if sukces else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, AttributeError):
        pass
    raise SystemExit(main())
