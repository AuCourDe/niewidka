"""Testy systemu aktualizacji modeli (K7/akt).

- Dobry podpis, zły podpis, podmieniony bajt
- Ochrona przed rollbackiem (wersja_katalogu <= znanej)
- Błąd integralności zapisanego katalogu przy starcie -> katalog wbudowany
- Próbka kontrolna (musi_wykryc, nie_moze_wykryc)
- Instalacja z katalogiem przejściowym i atomową zamianą
- Kopia bezpieczeństwa (.poprzednie) i cofnięcie wersji
- Blokada cofnięcia poniżej min_wersja
- Sprawdzanie raz na dobę
- Narzędzie wydawcy narzedzia/podpisz_katalog.py
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from niewidka import pakiety
from niewidka.aktualizacje import (
    BladAktualizacji,
    MenedzerAktualizacji,
    TrybNarzucony,
    klucz_publiczny_do_b64,
    ocen_probke_kontrolna,
    podpisz_dane,
    wczytaj_klucze_publiczne,
    wczytaj_ustawienia,
    weryfikuj_katalog,
    weryfikuj_podpis,
    zapisz_ustawienia,
)
from niewidka.model import TypEncji, Zakres
from niewidka.pakiety import MenedzerPakietow


class FalszywyDetektor:
    """Prosty detektor do testów próbki kontrolnej."""

    def __init__(self, trafienia: dict[str, list[tuple[int, int, TypEncji]]]):
        self.trafienia = trafienia

    def znajdz(self, tekst: str) -> list[Zakres]:
        wynik = []
        for fragment, lista in self.trafienia.items():
            if fragment in tekst:
                for start, koniec, typ in lista:
                    wynik.append(Zakres(start, koniec, typ, 1.0, "test"))
        return wynik


@pytest.fixture()
def para_kluczy():
    prywatny = ed25519.Ed25519PrivateKey.generate()
    publiczny = prywatny.public_key()
    return prywatny, publiczny


@pytest.fixture()
def srodowisko_testowe(tmp_path, monkeypatch, para_kluczy):
    kat_danych = tmp_path / "dane"
    kat_modeli = tmp_path / "modele"
    kat_danych.mkdir(parents=True)
    kat_modeli.mkdir(parents=True)

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("NIEWIDKA_MODELE_KATALOG", str(kat_modeli))

    prywatny, publiczny = para_kluczy
    klucz_pub_b64 = klucz_publiczny_do_b64(publiczny)
    plik_pub = kat_danych / "klucz.pub"
    plik_pub.write_text(f"# Testowy klucz\n{klucz_pub_b64}\n", encoding="utf-8")

    return {
        "dane": kat_danych,
        "modele": kat_modeli,
        "klucz_prywatny": prywatny,
        "klucz_publiczny": publiczny,
        "plik_pub": plik_pub,
    }


def test_podpis_dobry_zly_i_podmieniony_bajt(para_kluczy):
    prywatny, publiczny = para_kluczy
    obcy_prywatny = ed25519.Ed25519PrivateKey.generate()
    dane = b"Dane katalogu pakietow do weryfikacji"

    podpis = podpisz_dane(dane, prywatny)
    assert weryfikuj_podpis(dane, podpis, [publiczny]) is True

    # Zły klucz publiczny
    assert weryfikuj_podpis(dane, podpis, [obcy_prywatny.public_key()]) is False

    # Podmieniony bajt w danych
    dane_zmienione = bytearray(dane)
    dane_zmienione[0] ^= 0xFF
    assert weryfikuj_podpis(bytes(dane_zmienione), podpis, [publiczny]) is False

    # Podmieniony bajt w podpisie
    podpis_zmieniony = bytearray(podpis)
    podpis_zmieniony[5] ^= 0xFF
    assert weryfikuj_podpis(dane, bytes(podpis_zmieniony), [publiczny]) is False


def test_wczytaj_wiele_kluczy_publicznych_rotacja(para_kluczy):
    _, pub1 = para_kluczy
    pub2 = ed25519.Ed25519PrivateKey.generate().public_key()
    b64_1 = klucz_publiczny_do_b64(pub1)
    b64_2 = klucz_publiczny_do_b64(pub2)

    tekst = f"# Komentarz\n{b64_1}\n\n# Kolejny klucz\n{b64_2}\n"
    klucze = wczytaj_klucze_publiczne(tekst)
    assert len(klucze) == 2


def test_weryfikuj_katalog_rollback_odrzucony(para_kluczy):
    prywatny, publiczny = para_kluczy
    katalog_v1 = {
        "wersja_katalogu": 1,
        "pakiety": [{"id": "podstawowy", "wersja": 1, "pliki": []}],
    }
    katalog_v2 = {
        "wersja_katalogu": 2,
        "pakiety": [{"id": "podstawowy", "wersja": 2, "pliki": []}],
    }

    bajty_v1 = json.dumps(katalog_v1).encode("utf-8")
    sig_v1 = podpisz_dane(bajty_v1, prywatny)

    bajty_v2 = json.dumps(katalog_v2).encode("utf-8")
    sig_v2 = podpisz_dane(bajty_v2, prywatny)

    # Sukces dla wersji 2 przy progu 1
    dane = weryfikuj_katalog(bajty_v2, sig_v2, [publiczny], minimalna_wersja_katalogu=1)
    assert dane["wersja_katalogu"] == 2

    # Próba rollbacku: wersja 1 przy progu 2 zostaje odrzucona
    with pytest.raises(BladAktualizacji, match="wymagana wersja wyższa"):
        weryfikuj_katalog(bajty_v1, sig_v1, [publiczny], minimalna_wersja_katalogu=2)


def test_start_z_uszkodzonym_katalogiem_w_danych(srodowisko_testowe):
    kat_modeli = srodowisko_testowe["modele"]
    publiczny = srodowisko_testowe["klucz_publiczny"]

    # Zapisujemy katalog z uszkodzonym podpisem
    plik_kat = kat_danych / "katalog-pakietow.json"
    plik_sig = kat_danych / "katalog-pakietow.json.sig"
    plik_kat.write_text('{"wersja_katalogu": 99, "pakiety": []}', encoding="utf-8")
    plik_sig.write_bytes(b"niepoprawny_podpis" * 4)

    menedzer_pakiety = MenedzerPakietow([], kat_modeli, "http://x")
    menedzer_akt = MenedzerAktualizacji(
        katalog_modeli_sciezka=kat_modeli,
        katalog_danych_sciezka=kat_danych,
        zrodlo_url="http://x",
        menedzer_pakietow=menedzer_pakiety,
        klucze_publiczne=[publiczny],
    )

    # Fail-closed do wbudowanego, ale widoczny stan błędu integralności
    assert menedzer_akt.stan == "blad_integralnosci"
    assert "Błąd integralności" in menedzer_akt.blad
    assert menedzer_akt.katalog_aktywny_plik == pakiety.KATALOG_PAKIETOW


def test_probka_kontrolna_kryteria(tmp_path):
    probka_plik = tmp_path / "probka.json"
    zawartosc = {
        "probki": [
            {
                "tekst": "Pismo do Jana Kowalskiego.",
                "musi_wykryc": ["Jana Kowalskiego"],
                "nie_moze_wykryc": ["Pismo"],
            }
        ]
    }
    probka_plik.write_text(json.dumps(zawartosc), encoding="utf-8")

    # 1. Dobry detektor: wykrywa Jana Kowalskiego i nic więcej
    detektor_ok = FalszywyDetektor({"Jana Kowalskiego": [(9, 25, TypEncji.OSOBA)]})
    zaliczona, bledy = ocen_probke_kontrolna(detektor_ok, probka_plik)
    assert zaliczona is True
    assert bledy == []

    # 2. Gorszy detektor: nie wykrył Jana Kowalskiego
    detektor_pusty = FalszywyDetektor({})
    zaliczona, bledy = ocen_probke_kontrolna(detektor_pusty, probka_plik)
    assert zaliczona is False
    assert any("brak wymaganego wykrycia" in b for b in bledy)

    # 3. Zły detektor: wykrył zabronione "Pismo" (fałszywy alarm)
    detektor_fa = FalszywyDetektor({
        "Jana Kowalskiego": [(9, 25, TypEncji.OSOBA)],
        "Pismo": [(0, 5, TypEncji.OSOBA)],
    })
    zaliczona, bledy = ocen_probke_kontrolna(detektor_fa, probka_plik)
    assert zaliczona is False
    assert any("niepożądane wykrycie" in b for b in bledy)


def test_instalacja_aktualizacji_i_cofniecie(srodowisko_testowe, tmp_path):
    kat_modeli = srodowisko_testowe["modele"]
    prywatny = srodowisko_testowe["klucz_prywatny"]
    publiczny = srodowisko_testowe["klucz_publiczny"]

    # Przygotowanie plików starej wersji w katalogu modeli
    stary_plik = kat_modeli / "model.onnx"
    stary_plik.write_text("stary-model", encoding="utf-8")
    manifest_stary = kat_modeli / "manifest.json"
    manifest_stary.write_text(json.dumps({"pakiet": "podstawowy", "wersja": 1}), encoding="utf-8")

    # Nowa wersja w zdalnym źródle
    nowa_tresc = b"nowy-model-v2"
    nowy_sha = __import__("hashlib").sha256(nowa_tresc).hexdigest()

    nowy_katalog = {
        "wersja_katalogu": 2,
        "pakiety": [
            {
                "id": "podstawowy",
                "nazwa": "Podstawowy",
                "opis": "testowy",
                "wymagany": True,
                "poziomy": [1],
                "katalog_rel": "",
                "wersja": 2,
                "min_wersja": 1,
                "pliki": [
                    {
                        "nazwa": "model.onnx",
                        "zrodlo": "model-v2.onnx",
                        "rozmiar": len(nowa_tresc),
                        "sha256": nowy_sha,
                    }
                ],
            }
        ],
    }
    katalog_bajty = json.dumps(nowy_katalog).encode("utf-8")
    podpis_bajty = podpisz_dane(katalog_bajty, prywatny)

    # Serwer mockujący zdalne źródło
    zasoby = {
        "katalog-pakietow.json": katalog_bajty,
        "katalog-pakietow.json.sig": podpis_bajty,
        "model-v2.onnx": nowa_tresc,
    }

    def transport_handler(request: httpx.Request) -> httpx.Response:
        sciezka = str(request.url).rsplit("/", 1)[-1]
        if sciezka in zasoby:
            return httpx.Response(200, content=zasoby[sciezka])
        return httpx.Response(404)

    klient = httpx.Client(transport=httpx.MockTransport(transport_handler))

    # Fabryka zwracająca poprawny detektor
    class MockDetektorOk:
        def znajdz(self, tekst):
            # Udajemy wykrycie wszystkiego z probka-kontrolna.json
            return [
                Zakres(0, len(tekst), TypEncji.OSOBA, 1.0, "mock"),
                Zakres(0, len(tekst), TypEncji.PESEL, 1.0, "mock"),
                Zakres(0, len(tekst), TypEncji.ADRES, 1.0, "mock"),
                Zakres(0, len(tekst), TypEncji.EMAIL, 1.0, "mock"),
            ]

    # Prosta próbka kontrolna
    probka_plik = tmp_path / "probka.json"
    probka_plik.write_text(
        json.dumps({
            "probki": [
                {
                    "tekst": "Jan Kowalski",
                    "musi_wykryc": ["Jan Kowalski"],
                    "nie_moze_wykryc": ["xyz"],
                }
            ]
        }),
        encoding="utf-8",
    )

    menedzer_pakiety = MenedzerPakietow([], kat_modeli, "http://x", klient=klient)
    menedzer_akt = MenedzerAktualizacji(
        katalog_modeli_sciezka=kat_modeli,
        katalog_danych_sciezka=kat_danych,
        zrodlo_url="http://x",
        menedzer_pakietow=menedzer_pakiety,
        klucze_publiczne=[publiczny],
        probka_plik=probka_plik,
        fabryka_detektora=lambda poz, kat: MockDetektorOk(),
        klient=klient,
    )

    # Sprawdzenie aktualizacji
    dane_kat = menedzer_akt.sprawdz_aktualizacje()
    assert dane_kat["wersja_katalogu"] == 2
    assert menedzer_akt.stan == "dostepna_aktualizacja"

    # Instalacja aktualizacji
    sukces = menedzer_akt.instaluj_aktualizacje("podstawowy", w_tle=False)
    assert sukces is True
    assert stary_plik.read_text(encoding="utf-8") == "nowy-model-v2"

    # Sprawdzenie, że poprzednia wersja została zachowana w .poprzednie/podstawowy
    plik_poprzedni = kat_modeli / ".poprzednie" / "podstawowy" / "model.onnx"
    assert plik_poprzedni.is_file()
    assert plik_poprzedni.read_text(encoding="utf-8") == "stary-model"

    # Cofnięcie wersji
    menedzer_akt.cofnij_aktualizacje("podstawowy")
    assert stary_plik.read_text(encoding="utf-8") == "stary-model"


def test_blokada_cofniecia_ponizej_min_wersja(srodowisko_testowe, tmp_path):
    kat_modeli = srodowisko_testowe["modele"]
    publiczny = srodowisko_testowe["klucz_publiczny"]

    # Pakiet w katalogu ma min_wersja: 2
    katalog = {
        "wersja_katalogu": 1,
        "pakiety": [
            {
                "id": "podstawowy",
                "nazwa": "Podstawowy",
                "opis": "test",
                "wymagany": True,
                "poziomy": [1],
                "katalog_rel": "",
                "wersja": 3,
                "min_wersja": 2,
                "pliki": [{"nazwa": "m.onnx", "zrodlo": "m.onnx", "rozmiar": 5, "sha256": "x"}],
            }
        ],
    }
    plik_kat = kat_danych / "katalog-pakietow.json"
    plik_kat.write_text(json.dumps(katalog), encoding="utf-8")

    # W .poprzednie leży wersja 1
    katalog_poprz = kat_modeli / ".poprzednie" / "podstawowy"
    katalog_poprz.mkdir(parents=True)
    (katalog_poprz / "manifest.json").write_text(
        json.dumps({"pakiet": "podstawowy", "wersja": 1}), encoding="utf-8"
    )

    menedzer_pakiety = MenedzerPakietow([], kat_modeli, "http://x")
    menedzer_akt = MenedzerAktualizacji(
        katalog_modeli_sciezka=kat_modeli,
        katalog_danych_sciezka=kat_danych,
        zrodlo_url="http://x",
        menedzer_pakietow=menedzer_pakiety,
        klucze_publiczne=[publiczny],
    )
    menedzer_akt.katalog_aktywny_plik = plik_kat

    with pytest.raises(BladAktualizacji, match="niższa niż dopuszczalna min_wersja"):
        menedzer_akt.cofnij_aktualizacje("podstawowy")


def test_tryb_narzucony_przez_konfiguracje(srodowisko_testowe):
    kat_modeli = srodowisko_testowe["modele"]
    publiczny = srodowisko_testowe["klucz_publiczny"]

    menedzer_pakiety = MenedzerPakietow([], kat_modeli, "http://x")
    menedzer_akt = MenedzerAktualizacji(
        katalog_modeli_sciezka=kat_modeli,
        katalog_danych_sciezka=kat_danych,
        zrodlo_url="http://x",
        menedzer_pakietow=menedzer_pakiety,
        konfig_tryb="wylaczone",
        klucze_publiczne=[publiczny],
    )

    assert menedzer_akt.narzucony is True
    assert menedzer_akt.tryb == "wylaczone"

    with pytest.raises(TrybNarzucony):
        menedzer_akt.ustaw_tryb("reczne")


def test_sprawdzanie_raz_na_dobe(srodowisko_testowe, monkeypatch):
    kat_modeli = srodowisko_testowe["modele"]
    publiczny = srodowisko_testowe["klucz_publiczny"]

    ustawienia = wczytaj_ustawienia(kat_danych)
    # Sprawdzenie sprzed 1 godziny
    godzina_temu = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    ustawienia["ostatnie_sprawdzenie"] = godzina_temu
    ustawienia["tryb_aktualizacji"] = "sprawdzaj"
    zapisz_ustawienia(kat_danych, ustawienia)

    menedzer_pakiety = MenedzerPakietow([], kat_modeli, "http://x")
    menedzer_akt = MenedzerAktualizacji(
        katalog_modeli_sciezka=kat_modeli,
        katalog_danych_sciezka=kat_danych,
        zrodlo_url="http://x",
        menedzer_pakietow=menedzer_pakiety,
        klucze_publiczne=[publiczny],
    )

    zawolano = []
    monkeypatch.setattr(menedzer_akt, "sprawdz_aktualizacje", lambda: zawolano.append(True))
    menedzer_akt.sprawdz_przy_starcie()
    assert zawolano == []  # Nie powinno wywołać sprawdzenia

    # Sprawdzenie sprzed 25 godzin
    wczoraj = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    ustawienia["ostatnie_sprawdzenie"] = wczoraj
    zapisz_ustawienia(kat_danych, ustawienia)

    menedzer_akt.sprawdz_przy_starcie()
    # Dajemy chwilę wątkowi
    import time
    time.sleep(0.05)
    assert len(zawolano) == 1


def test_narzedzie_podpisz_katalog_brak_klucza_z_argumentu(tmp_path):
    skrypt = Path(__file__).resolve().parent.parent / "narzedzia" / "podpisz_katalog.py"

    # 1. Argumenty zawierające flagę klucza są odrzucane
    proc = subprocess.run(
        [sys.executable, str(skrypt), "--klucz", "tajne"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "unrecognized arguments: --klucz" in proc.stderr

    # 2. Brak zmiennej NIEWIDKA_KLUCZ_PODPISU -> exit 1
    env_bez = dict(os.environ)
    env_bez.pop("NIEWIDKA_KLUCZ_PODPISU", None)
    proc2 = subprocess.run(
        [sys.executable, str(skrypt), "katalog.json"],
        check=False,
        capture_output=True,
        text=True,
        env=env_bez,
    )
    assert proc2.returncode == 1
    assert "NIEWIDKA_KLUCZ_PODPISU" in proc2.stderr

    # 3. --generuj-pare tworzy plik 0600 i wypisuje klucz publiczny w base64
    plik_priv = tmp_path / "test.priv"
    proc3 = subprocess.run(
        [sys.executable, str(skrypt), "--generuj-pare", str(plik_priv)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc3.returncode == 0
    klucz_pub_b64 = proc3.stdout.strip()
    assert len(klucz_pub_b64) == 44  # 32 bajty w base64
    assert plik_priv.is_file()
    # Prawa 0600 na POSIX
    if sys.platform != "win32":
        tryptic = stat.S_IMODE(plik_priv.stat().st_mode)
        assert tryptic == 0o600

    # 4. Podpisanie pliku przy ustawionym NIEWIDKA_KLUCZ_PODPISU
    plik_kat = tmp_path / "katalog.json"
    plik_kat.write_text('{"wersja_katalogu": 1}', encoding="utf-8")
    env_z = dict(os.environ)
    env_z["NIEWIDKA_KLUCZ_PODPISU"] = str(plik_priv)

    proc4 = subprocess.run(
        [sys.executable, str(skrypt), str(plik_kat)],
        check=False,
        capture_output=True,
        text=True,
        env=env_z,
    )
    assert proc4.returncode == 0
    plik_sig = tmp_path / "katalog.json.sig"
    assert plik_sig.is_file()
    assert len(plik_sig.read_bytes()) == 64


@pytest.mark.anyio
async def test_api_aktualizacje_autoryzacja_i_get(srodowisko_testowe):
    from niewidka.api import create_app
    from niewidka.konfig import Konfig

    kat_modeli = srodowisko_testowe["modele"]

    konfig = Konfig(modele_katalog=kat_modeli)
    app = create_app(konfig, detektor=FalszywyDetektor({}))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{konfig.port}"
    ) as klient:
        # Bez tokenu -> 403
        r_bez = await klient.get("/api/aktualizacje")
        assert r_bez.status_code == 403

        # Z poprawnym tokenem -> 200
        naglowki = {"X-Niewidka-Token": app.state.token}
        r = await klient.get("/api/aktualizacje", headers=naglowki)
        assert r.status_code == 200
        dane = r.json()
        assert "tryb" in dane
        assert dane["tryb"] == "sprawdzaj"
        assert dane["narzucony"] is False
        assert "wersja_katalogu" in dane
        assert isinstance(dane["pakiety"], list)


@pytest.mark.anyio
async def test_api_post_tryb_oraz_409_gdy_narzucony(srodowisko_testowe):
    from niewidka.api import create_app
    from niewidka.konfig import Konfig

    kat_modeli = srodowisko_testowe["modele"]

    # 1. Zwykły tryb: zmiana działa
    konfig = Konfig(modele_katalog=kat_modeli)
    app = create_app(konfig, detektor=FalszywyDetektor({}))
    naglowki = {"X-Niewidka-Token": app.state.token}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{konfig.port}"
    ) as klient:
        r = await klient.post("/api/aktualizacje", json={"akcja": "tryb", "tryb": "reczne"}, headers=naglowki)
        assert r.status_code == 200
        assert r.json()["tryb"] == "reczne"

        r_get = await klient.get("/api/aktualizacje", headers=naglowki)
        assert r_get.json()["tryb"] == "reczne"

    # 2. Narzucony tryb: zmiana zwraca 409
    konfig_narzucony = Konfig(modele_katalog=kat_modeli, aktualizacje_tryb="wylaczone")
    app_narzucona = create_app(konfig_narzucony, detektor=FalszywyDetektor({}))
    naglowki_n = {"X-Niewidka-Token": app_narzucona.state.token}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_narzucona), base_url=f"http://127.0.0.1:{konfig_narzucony.port}"
    ) as klient:
        r2 = await klient.post("/api/aktualizacje", json={"akcja": "tryb", "tryb": "reczne"}, headers=naglowki_n)
        assert r2.status_code == 409


@pytest.mark.anyio
async def test_api_instaluj_offline_ze_zlym_podpisem(srodowisko_testowe, tmp_path):
    from niewidka.api import create_app
    from niewidka.konfig import Konfig

    kat_modeli = srodowisko_testowe["modele"]
    konfig = Konfig(modele_katalog=kat_modeli)
    app = create_app(konfig, detektor=FalszywyDetektor({}))
    naglowki = {"X-Niewidka-Token": app.state.token}

    # Folder offline ze złośliwym lub uszkodzonym podpisem katalogu
    folder_offline = tmp_path / "offline_pendrive"
    folder_offline.mkdir()
    (folder_offline / "katalog-pakietow.json").write_text('{"wersja_katalogu": 5}', encoding="utf-8")
    (folder_offline / "katalog-pakietow.json.sig").write_bytes(b"zly_podpis" * 6)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{konfig.port}"
    ) as klient:
        r = await klient.post(
            "/api/pakiety",
            json={"akcja": "instaluj", "pakiet": "podstawowy", "katalog": str(folder_offline)},
            headers=naglowki,
        )
        assert r.status_code == 202

        # Czekamy na zakończenie operacji w tle
        app.state.pakiety.czekaj()
        r_pakiety = await klient.get("/api/pakiety", headers=naglowki)
        # Błąd powinien trafić do postep.blad
        assert "zły podpis" in (r_pakiety.json()["postep"]["blad"] or "")

