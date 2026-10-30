"""Testy systemu aktualizacji modeli.

- Dobry podpis, zły podpis, podmieniony bajt, rotacja (kilka kluczy w pliku)
- Ochrona przed rollbackiem (wersja_katalogu <= znanej)
- Błąd integralności przyjętego katalogu przy starcie: katalog wbudowany, stan widoczny
- Placeholder klucza przed wydaniem: program działa, aktualizacje zdalne niedostępne
- Próbka kontrolna (musi_wykryc, nie_moze_wykryc) odrzuca gorszy model i zostawia stary
- Instalacja z katalogiem przejściowym i atomową zamianą, cofnięcie, blokada min_wersja
- Instalacja offline z folderu od IT (dobry i zły podpis, ta sama weryfikacja)
- Sprawdzanie najwyżej raz na dobę, tryb narzucony przez konfigurację
- Narzędzie wydawcy narzedzia/podpisz_katalog.py
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from niewidka import aktualizacje, pakiety
from niewidka.aktualizacje import (
    BladAktualizacji,
    BladIntegralnosci,
    MenedzerAktualizacji,
    TrybNarzucony,
    klucz_publiczny_do_b64,
    ocen_probke_kontrolna,
    podpisz_dane,
    wczytaj_klucze_publiczne,
    weryfikuj_katalog,
    weryfikuj_podpis,
    zapisz_ustawienia,
)
from niewidka.model import TypEncji, Zakres
from niewidka.pakiety import MenedzerPakietow


class DetektorProbki:
    """Atrapa detektora: wykrywa wyłącznie podane fragmenty, dokładnie na ich
    pozycjach (próbka liczy pokrycie zakresu, więc atrapa musi mieć dobre granice)."""

    def __init__(self, fragmenty: tuple[str, ...] = ("Jana Kowalskiego",)):
        self.fragmenty = fragmenty

    def znajdz(self, tekst: str) -> list[Zakres]:
        wynik = []
        for fragment in self.fragmenty:
            poz = tekst.find(fragment)
            if poz != -1:
                wynik.append(Zakres(poz, poz + len(fragment), TypEncji.OSOBA, 1.0, "test"))
        return wynik


def _podpisany_katalog(prywatny, wersja_katalogu: int, pakiety_wpisow: list[dict]) -> bytes:
    katalog = {"wersja_katalogu": wersja_katalogu, "pakiety": pakiety_wpisow}
    bajty = json.dumps(katalog).encode("utf-8")
    return bajty, podpisz_dane(bajty, prywatny)


@pytest.fixture()
def para_kluczy():
    prywatny = ed25519.Ed25519PrivateKey.generate()
    return prywatny, prywatny.public_key()


@pytest.fixture()
def srodowisko_testowe(tmp_path, monkeypatch, para_kluczy):
    # Niewidka: taka nazwa, jaką katalog_danych() wylicza z XDG_DATA_HOME/LOCALAPPDATA,
    # by API testy używały tego samego katalogu danych co rdzeń
    kat_danych = tmp_path / "Niewidka"
    kat_modeli = tmp_path / "modele"
    kat_danych.mkdir(parents=True)
    kat_modeli.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("NIEWIDKA_MODELE_KATALOG", str(kat_modeli))

    prywatny, publiczny = para_kluczy
    plik_pub = kat_danych / "klucz.pub"
    plik_pub.write_text(f"# Klucz testowy\n{klucz_publiczny_do_b64(publiczny)}\n", encoding="utf-8")

    return {
        "dane": kat_danych,
        "modele": kat_modeli,
        "klucz_prywatny": prywatny,
        "klucz_publiczny": publiczny,
        "plik_pub": plik_pub,
    }


def _menedzer(srodowisko, **dodatkowe) -> MenedzerAktualizacji:
    menedzer_pakietow = MenedzerPakietow([], srodowisko["modele"], "http://x")
    dodatkowe.setdefault("klucze_publiczne", [srodowisko["klucz_publiczny"]])
    return MenedzerAktualizacji(
        katalog_modeli_sciezka=srodowisko["modele"],
        katalog_danych_sciezka=srodowisko["dane"],
        zrodlo_url="http://x",
        menedzer_pakietow=menedzer_pakietow,
        **dodatkowe,
    )


def _stary_pakiet_w_katalogu_modeli(kat_modeli: Path) -> None:
    (kat_modeli / "model.onnx").write_text("stary-model", encoding="utf-8")
    (kat_modeli / "manifest.json").write_text(
        json.dumps({"pakiet": "podstawowy", "wersja": 1}), encoding="utf-8"
    )


def _katalog_v2(prywatny) -> tuple[bytes, bytes, bytes]:
    """Podpisany katalog v2 z pakietem podstawowy wersja 2 (jeden plik model.onnx)."""
    nowa_tresc = b"nowy-model-v2"
    wpis = {
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
                "sha256": __import__("hashlib").sha256(nowa_tresc).hexdigest(),
            }
        ],
    }
    return (*_podpisany_katalog(prywatny, 2, [wpis]), nowa_tresc)


# --- podpis ---------------------------------------------------------------------


def test_podpis_dobry_zly_i_podmieniony_bajt(para_kluczy):
    prywatny, publiczny = para_kluczy
    obcy = ed25519.Ed25519PrivateKey.generate().public_key()
    dane = b"Dane katalogu pakietow do weryfikacji"

    podpis = podpisz_dane(dane, prywatny)
    assert weryfikuj_podpis(dane, podpis, [publiczny]) is True
    assert weryfikuj_podpis(dane, podpis, [obcy]) is False
    assert weryfikuj_podpis(dane, podpis, []) is False

    dane_zmienione = bytearray(dane)
    dane_zmienione[0] ^= 0xFF
    assert weryfikuj_podpis(bytes(dane_zmienione), podpis, [publiczny]) is False

    podpis_zmieniony = bytearray(podpis)
    podpis_zmieniony[5] ^= 0xFF
    assert weryfikuj_podpis(dane, bytes(podpis_zmieniony), [publiczny]) is False

    # podpis przekazany jako base64 (format wydawcy) też przechodzi
    import base64

    assert weryfikuj_podpis(dane, base64.b64encode(podpis), [publiczny]) is True


def test_wczytaj_wiele_kluczy_publicznych_rotacja(para_kluczy):
    _, pub1 = para_kluczy
    pub2 = ed25519.Ed25519PrivateKey.generate().public_key()
    tekst = (
        f"# Komentarz\n{klucz_publiczny_do_b64(pub1)}\n\n"
        f"# Kolejny klucz\n{klucz_publiczny_do_b64(pub2)}\n"
    )
    assert len(wczytaj_klucze_publiczne(tekst)) == 2
    # placeholder (same komentarze) = brak kluczy, bez wyjątku
    assert wczytaj_klucze_publiczne("# PLACEHOLDER_KLUCZA_PUBLICZNEGO\n") == []


def test_weryfikuj_katalog_rollback_odrzucony(para_kluczy):
    prywatny, publiczny = para_kluczy
    wpis = {"id": "podstawowy", "nazwa": "P", "opis": "o", "pliki": []}
    bajty_v1, sig_v1 = _podpisany_katalog(prywatny, 1, [wpis])
    bajty_v2, sig_v2 = _podpisany_katalog(prywatny, 2, [wpis])

    assert weryfikuj_katalog(bajty_v2, sig_v2, [publiczny], minimalna_wersja_katalogu=1)[
        "wersja_katalogu"
    ] == 2
    with pytest.raises(BladAktualizacji, match="wymagana wersja wyższa"):
        weryfikuj_katalog(bajty_v1, sig_v1, [publiczny], minimalna_wersja_katalogu=2)
    # wersja równa progowi też jest odrzucona przy przyjmowaniu (tylko nowsze przechodzą)
    with pytest.raises(BladAktualizacji, match="wymagana wersja wyższa"):
        weryfikuj_katalog(bajty_v2, sig_v2, [publiczny], minimalna_wersja_katalogu=2)
    # ale przy starcie (weryfikacja przyjętego) równa przechodzi
    assert (
        weryfikuj_katalog(
            bajty_v2, sig_v2, [publiczny], minimalna_wersja_katalogu=2, pozwalaj_rowna=True
        )["wersja_katalogu"]
        == 2
    )
    # zły podpis to błąd integralności, nie rollback
    with pytest.raises(BladIntegralnosci):
        weryfikuj_katalog(bajty_v2, b"zepsuty" * 10, [publiczny], minimalna_wersja_katalogu=1)


def test_schemat_katalogu_bez_pola_pliku_odrzucony(para_kluczy):
    prywatny, publiczny = para_kluczy
    zepsuty = {"wersja_katalogu": 2, "pakiety": [{"id": "podstawowy", "nazwa": "P", "opis": "o"}]}
    bajty = json.dumps(zepsuty).encode("utf-8")
    with pytest.raises(BladIntegralnosci, match="pliki"):
        weryfikuj_katalog(bajty, podpisz_dane(bajty, prywatny), [publiczny])


def test_start_z_uszkodzonym_katalogiem_w_danych(srodowisko_testowe):
    kat_danych = srodowisko_testowe["dane"]
    publiczny = srodowisko_testowe["klucz_publiczny"]

    (kat_danych / "katalog-pakietow.json").write_text('{"wersja_katalogu": 99, "pakiety": []}', "utf-8")
    (kat_danych / "katalog-pakietow.json.sig").write_bytes(b"niepoprawny_podpis" * 4)

    menedzer = _menedzer(srodowisko_testowe, klucze_publiczne=[publiczny])

    # fail-closed do katalogu wbudowanego, ale stan błędu jest widoczny
    assert menedzer.stan == "blad_integralnosci"
    assert "Błąd integralności" in menedzer.blad
    assert menedzer.katalog_aktywny_plik == pakiety.KATALOG_PAKIETOW


def test_start_nie_obniza_progu_najwyzszej_wersji(srodowisko_testowe):
    """Najwyższa przyjęta wersja zapisana osobno w ustawienia.json;
    brak pliku katalogu w danych nie cofa progu."""
    zapisz_ustawienia(srodowisko_testowe["dane"], {"najwyzsza_wersja_katalogu": 7})
    menedzer = _menedzer(srodowisko_testowe)
    assert menedzer.najwyzsza_wersja_katalogu == 7


def test_placeholder_klucza_program_dziala_aktualizacje_niedostepne(srodowisko_testowe):
    """Program bez klucza wydawcy (przed wydaniem) działa: katalog wbudowany,
    sprawdzenie i folder offline dają czytelny komunikat, start bez wyjątku."""
    menedzer = _menedzer(srodowisko_testowe, klucze_publiczne=[])
    assert menedzer.ma_klucze is False
    assert menedzer.stan == "aktualny"
    menedzer.sprawdz_przy_starcie()  # bez żądania i bez wyjątku
    with pytest.raises(BladAktualizacji, match="klucz"):
        menedzer.sprawdz_aktualizacje()
    with pytest.raises(BladAktualizacji, match="klucz"):
        menedzer.przyjmij_katalog_z_folderu(srodowisko_testowe["dane"])


# --- próbka kontrolna -------------------------------------------------------------


def test_probka_kontrolna_kryteria(tmp_path):
    probka_plik = tmp_path / "probka.json"
    probka_plik.write_text(
        json.dumps(
            {
                "probki": [
                    {
                        "tekst": "Pismo do Jana Kowalskiego.",
                        "musi_wykryc": ["Jana Kowalskiego"],
                        "nie_moze_wykryc": ["Pismo"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    zaliczona, bledy = ocen_probke_kontrolna(DetektorProbki(), probka_plik)
    assert zaliczona is True and bledy == []

    # gorszy model: nie wykrywa wymaganego fragmentu
    zaliczona, bledy = ocen_probke_kontrolna(DetektorProbki(()), probka_plik)
    assert zaliczona is False
    assert any("brak wymaganego wykrycia" in b for b in bledy)

    # fałszywy alarm na nie_moze_wykryc
    zaliczona, bledy = ocen_probke_kontrolna(DetektorProbki(("Pismo",)), probka_plik)
    assert zaliczona is False
    assert any("fałszywy alarm" in b for b in bledy)


# --- instalacja zdalna, cofanie ---------------------------------------------------


def _transport_z_zasobami(zasoby: dict[str, bytes]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        nazwa = str(request.url).rsplit("/", 1)[-1]
        if nazwa in zasoby:
            return httpx.Response(200, content=zasoby[nazwa])
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_instalacja_aktualizacji_i_cofniecie(srodowisko_testowe, tmp_path):
    kat_modeli = srodowisko_testowe["modele"]
    prywatny = srodowisko_testowe["klucz_prywatny"]
    _stary_pakiet_w_katalogu_modeli(kat_modeli)
    katalog_bajty, podpis_bajty, nowa_tresc = _katalog_v2(prywatny)
    klient = _transport_z_zasobami(
        {
            "katalog-pakietow.json": katalog_bajty,
            "katalog-pakietow.json.sig": podpis_bajty,
            "model-v2.onnx": nowa_tresc,
        }
    )
    probka = tmp_path / "probka.json"
    probka.write_text(
        json.dumps(
            {
                "probki": [
                    {"tekst": "Pismo do Jana Kowalskiego.", "musi_wykryc": ["Jana Kowalskiego"]}
                ]
            }
        ),
        encoding="utf-8",
    )
    menedzer = _menedzer(
        srodowisko_testowe,
        probka_plik=probka,
        fabryka_detektora=lambda pakiet, katalog: DetektorProbki(),
        klient=klient,
    )

    dane = menedzer.sprawdz_aktualizacje()
    assert dane["wersja_katalogu"] == 2
    assert menedzer.stan == "dostepna_aktualizacja"
    # przyjęty katalog zapisany w katalogu danych i próg podniesiony
    assert (srodowisko_testowe["dane"] / "katalog-pakietow.json").is_file()
    assert menedzer.najwyzsza_wersja_katalogu == 2

    assert menedzer.instaluj_aktualizacje("podstawowy", w_tle=False) is True
    assert (kat_modeli / "model.onnx").read_text(encoding="utf-8") == "nowy-model-v2"
    assert json.loads((kat_modeli / "manifest.json").read_text(encoding="utf-8"))["wersja"] == 2
    # poprzednia wersja w .poprzednie, powrót możliwy
    plik_poprzedni = kat_modeli / ".poprzednie" / "podstawowy" / "model.onnx"
    assert plik_poprzedni.read_text(encoding="utf-8") == "stary-model"
    wpisy = menedzer.lista_pakietow()
    assert wpisy[0]["dostepna"] is False and wpisy[0]["mozliwe_cofniecie"] is True
    assert menedzer.stan == "aktualny"

    menedzer.cofnij_aktualizacje("podstawowy")
    assert (kat_modeli / "model.onnx").read_text(encoding="utf-8") == "stary-model"
    assert json.loads((kat_modeli / "manifest.json").read_text(encoding="utf-8"))["wersja"] == 1


def test_probka_odrzuca_gorszy_model_i_zostawia_stary(srodowisko_testowe, tmp_path):
    kat_modeli = srodowisko_testowe["modele"]
    prywatny = srodowisko_testowe["klucz_prywatny"]
    _stary_pakiet_w_katalogu_modeli(kat_modeli)
    katalog_bajty, podpis_bajty, nowa_tresc = _katalog_v2(prywatny)
    klient = _transport_z_zasobami(
        {
            "katalog-pakietow.json": katalog_bajty,
            "katalog-pakietow.json.sig": podpis_bajty,
            "model-v2.onnx": nowa_tresc,
        }
    )
    probka = tmp_path / "probka.json"
    probka.write_text(
        json.dumps(
            {"probki": [{"tekst": "Pismo do Jana Kowalskiego.", "musi_wykryc": ["Jana Kowalskiego"]}]}
        ),
        encoding="utf-8",
    )
    menedzer = _menedzer(
        srodowisko_testowe,
        probka_plik=probka,
        fabryka_detektora=lambda pakiet, katalog: DetektorProbki(()),  # gorszy: nic nie wykrywa
        klient=klient,
    )
    menedzer.sprawdz_aktualizacje()

    assert menedzer.instaluj_aktualizacje("podstawowy", w_tle=False) is False
    assert "próbk" in (menedzer.postep["blad"] or "")
    # zamiany nie było: stara wersja na miejscu
    assert (kat_modeli / "model.onnx").read_text(encoding="utf-8") == "stary-model"
    assert json.loads((kat_modeli / "manifest.json").read_text(encoding="utf-8"))["wersja"] == 1
    assert not (kat_modeli / ".poprzednie" / "podstawowy").exists()


def test_blokada_cofniecia_ponizej_min_wersja(srodowisko_testowe):
    kat_danych = srodowisko_testowe["dane"]
    kat_modeli = srodowisko_testowe["modele"]
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
                "pliki": [{"nazwa": "m.onnx", "zrodlo": "m.onnx", "rozmiar": 5, "sha256": "0" * 64}],
            }
        ],
    }
    (kat_danych / "katalog-pakietow.json").write_text(json.dumps(katalog), encoding="utf-8")
    katalog_poprz = kat_modeli / ".poprzednie" / "podstawowy"
    katalog_poprz.mkdir(parents=True)
    (katalog_poprz / "manifest.json").write_text(
        json.dumps({"pakiet": "podstawowy", "wersja": 1}), encoding="utf-8"
    )
    menedzer = _menedzer(srodowisko_testowe)
    menedzer.katalog_aktywny_plik = kat_danych / "katalog-pakietow.json"

    with pytest.raises(BladAktualizacji, match="min_wersja"):
        menedzer.cofnij_aktualizacje("podstawowy")


# --- instalacja offline z folderu ---------------------------------------------------


def _folder_offline(tmp_path, prywatny, podpisz_poprawnie: bool) -> Path:
    katalog_bajty, podpis_bajty, nowa_tresc = _katalog_v2(prywatny)
    folder = tmp_path / "pendrive"
    folder.mkdir()
    (folder / "katalog-pakietow.json").write_bytes(katalog_bajty)
    if podpisz_poprawnie:
        (folder / "katalog-pakietow.json.sig").write_bytes(podpis_bajty)
    else:
        (folder / "katalog-pakietow.json.sig").write_bytes(b"zepsuty" * 10)
    (folder / "model-v2.onnx").write_bytes(nowa_tresc)
    return folder


def test_instalacja_offline_z_folderu_od_poczatku_do_cofniecia(srodowisko_testowe, tmp_path):
    kat_modeli = srodowisko_testowe["modele"]
    prywatny = srodowisko_testowe["klucz_prywatny"]
    _stary_pakiet_w_katalogu_modeli(kat_modeli)
    folder = _folder_offline(tmp_path, prywatny, podpisz_poprawnie=True)
    menedzer = _menedzer(
        srodowisko_testowe,
        probka_plik=_probka(tmp_path),
        fabryka_detektora=lambda pakiet, katalog: DetektorProbki(),
    )

    menedzer.instaluj_aktualizacje("podstawowy", w_tle=False, folder=folder)
    assert (kat_modeli / "model.onnx").read_text(encoding="utf-8") == "nowy-model-v2"
    assert menedzer.najwyzsza_wersja_katalogu == 2
    assert (srodowisko_testowe["dane"] / "katalog-pakietow.json").is_file()

    # ten sam folder po raz drugi: wersja już przyjęta, rollback odrzucony
    with pytest.raises(BladAktualizacji, match="wymagana wersja wyższa"):
        menedzer.przyjmij_katalog_z_folderu(folder)

    menedzer.cofnij_aktualizacje("podstawowy")
    assert (kat_modeli / "model.onnx").read_text(encoding="utf-8") == "stary-model"


def _probka(tmp_path: Path) -> Path:
    probka = tmp_path / "probka.json"
    probka.write_text(
        json.dumps(
            {"probki": [{"tekst": "Pismo do Jana Kowalskiego.", "musi_wykryc": ["Jana Kowalskiego"]}]}
        ),
        encoding="utf-8",
    )
    return probka


def test_folder_offline_z_zlym_podpisem_odrzucony(srodowisko_testowe, tmp_path):
    prywatny = srodowisko_testowe["klucz_prywatny"]
    _stary_pakiet_w_katalogu_modeli(srodowisko_testowe["modele"])
    folder = _folder_offline(tmp_path, prywatny, podpisz_poprawnie=False)
    menedzer = _menedzer(srodowisko_testowe)
    with pytest.raises(BladIntegralnosci, match="podpis"):
        menedzer.przyjmij_katalog_z_folderu(folder)
    assert menedzer.stan == "aktualny"  # odrzucenie folderu nie zatruwa stanu programu


def test_folder_bez_katalogu_i_podpisu_odrzucony(srodowisko_testowe, tmp_path):
    folder = tmp_path / "pusty"
    folder.mkdir()
    menedzer = _menedzer(srodowisko_testowe)
    with pytest.raises(BladAktualizacji, match="katalog-pakietow.json"):
        menedzer.przyjmij_katalog_z_folderu(folder)


# --- tryby i sprawdzanie ------------------------------------------------------------


def test_tryb_narzucony_przez_konfiguracje(srodowisko_testowe):
    menedzer = _menedzer(srodowisko_testowe, konfig_tryb="wylaczone")
    assert menedzer.narzucony is True
    assert menedzer.tryb == "wylaczone"
    with pytest.raises(TrybNarzucony):
        menedzer.ustaw_tryb("reczne")


def test_wybor_trybu_zapisywany_w_ustawieniach(srodowisko_testowe):
    menedzer = _menedzer(srodowisko_testowe)
    menedzer.ustaw_tryb("reczne")
    assert menedzer.tryb == "reczne"
    with pytest.raises(ValueError, match="Nieznany tryb"):
        menedzer.ustaw_tryb("czasami")


def test_tryb_wylaczone_blokuje_sprawdzanie_i_instalacje(srodowisko_testowe):
    menedzer = _menedzer(srodowisko_testowe)
    menedzer.ustaw_tryb("wylaczone")
    with pytest.raises(BladAktualizacji, match="wyłączone"):
        menedzer.sprawdz_aktualizacje()
    with pytest.raises(BladAktualizacji, match="wyłączone"):
        menedzer.instaluj_aktualizacje("podstawowy")


def test_sprawdzanie_raz_na_dobe(srodowisko_testowe):
    kat_danych = srodowisko_testowe["dane"]
    ustawienia = {
        "ostatnie_sprawdzenie": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "tryb_aktualizacji": "sprawdzaj",
    }
    zapisz_ustawienia(kat_danych, ustawienia)
    menedzer = _menedzer(srodowisko_testowe)

    zawolano = []

    def atrapa_sprawdzania():
        zawolano.append(True)

    menedzer.sprawdz_przy_starcie()
    time.sleep(0.05)
    assert zawolano == []  # doba nie minęła: bez sprawdzenia

    ustawienia["ostatnie_sprawdzenie"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    zapisz_ustawienia(kat_danych, ustawienia)
    menedzer.sprawdz_aktualizacje = atrapa_sprawdzania  # type: ignore[method-assign]
    menedzer.sprawdz_przy_starcie()
    time.sleep(0.05)
    assert len(zawolano) == 1


def test_sprawdzanie_pomijane_gdy_blad_integralnosci(srodowisko_testowe, monkeypatch):
    menedzer = _menedzer(srodowisko_testowe)
    menedzer.stan = "blad_integralnosci"
    wywolania = []
    monkeypatch.setattr(
        menedzer, "sprawdz_aktualizacje", lambda: wywolania.append(True)
    )
    menedzer.sprawdz_przy_starcie()
    time.sleep(0.05)
    assert wywolania == []


# --- narzędzie wydawcy ---------------------------------------------------------------


def test_narzedzie_podpisz_katalog_brak_klucza_z_argumentu(tmp_path):
    skrypt = Path(__file__).resolve().parent.parent / "narzedzia" / "podpisz_katalog.py"

    # 1. narzędzie nie przyjmuje klucza z argumentu (tylko NIEWIDKA_KLUCZ_PODPISU)
    proc = subprocess.run(
        [sys.executable, str(skrypt), "--klucz", "tajne"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "unrecognized arguments: --klucz" in proc.stderr

    # 2. brak NIEWIDKA_KLUCZ_PODPISU = wyjście 1 z komunikatem
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

    # 3. --generuj-pare: plik prywatny 0600, publiczny base64 na wyjściu
    plik_priv = tmp_path / "wydawca.priv"
    proc3 = subprocess.run(
        [sys.executable, str(skrypt), "--generuj-pare", str(plik_priv)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc3.returncode == 0
    assert len(proc3.stdout.strip()) == 44  # 32 bajty klucza w base64
    assert plik_priv.is_file()
    if sys.platform != "win32":
        assert stat.S_IMODE(plik_priv.stat().st_mode) == 0o600

    # 4. podpisanie pliku kluczem ze zmiennej środowiskowej
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


# --- API ---------------------------------------------------------------------------


def _wstrzymaj_sprawdzanie_przy_starcie(kat_danych: Path) -> None:
    """Świeży znacznik sprawdzenia: API testy z kluczem nie startują żądania do sieci."""
    zapisz_ustawienia(kat_danych, {"ostatnie_sprawdzenie": datetime.now(UTC).isoformat()})


@pytest.mark.anyio
async def test_api_get_aktualizacje_i_placeholder_bez_klucza(srodowisko_testowe):
    from niewidka.api import create_app
    from niewidka.konfig import Konfig

    kat_modeli = srodowisko_testowe["modele"]
    app = create_app(Konfig(modele_katalog=kat_modeli), detektor=DetektorProbki())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8390"
    ) as klient:
        assert (await klient.get("/api/aktualizacje")).status_code == 403  # bez tokenu
        odpowiedz = await klient.get("/api/aktualizacje", headers={"X-Niewidka-Token": app.state.token})
        assert odpowiedz.status_code == 200
        dane = odpowiedz.json()
        assert dane["tryb"] == "sprawdzaj"
        assert dane["narzucony"] is False
        assert dane["stan"] == "aktualny"
        assert dane["klucz_wydawcy"] is False  # placeholder w repo
        assert isinstance(dane["pakiety"], list)
        # program z placeholderem działa: sprawdzanie daje czytelny 422, nie 500
        strazlik = await klient.post(
            "/api/aktualizacje", json={"akcja": "sprawdz"}, headers={"X-Niewidka-Token": app.state.token}
        )
        assert strazlik.status_code == 422
        assert "klucz" in strazlik.json()["blad"]
        # instalacja bez pakietu i bez folderu = 422
        pusta = await klient.post(
            "/api/aktualizacje", json={"akcja": "instaluj"}, headers={"X-Niewidka-Token": app.state.token}
        )
        assert pusta.status_code == 422


@pytest.mark.anyio
async def test_api_post_tryb_oraz_409_gdy_narzucony(srodowisko_testowe):
    from niewidka.api import create_app
    from niewidka.konfig import Konfig

    kat_modeli = srodowisko_testowe["modele"]

    def naglowki(app):
        return {"X-Niewidka-Token": app.state.token}

    app = create_app(Konfig(modele_katalog=kat_modeli), detektor=DetektorProbki())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8390"
    ) as klient:
        odpowiedz = await klient.post(
            "/api/aktualizacje", json={"akcja": "tryb", "tryb": "reczne"}, headers=naglowki(app)
        )
        assert odpowiedz.status_code == 200
        odczyt = await klient.get("/api/aktualizacje", headers=naglowki(app))
        assert odczyt.json()["tryb"] == "reczne"
        zly = await klient.post(
            "/api/aktualizacje", json={"akcja": "tryb", "tryb": "czasami"}, headers=naglowki(app)
        )
        assert zly.status_code == 422

    narzucona = create_app(
        Konfig(modele_katalog=kat_modeli, aktualizacje_tryb="wylaczone"), detektor=DetektorProbki()
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=narzucona), base_url="http://127.0.0.1:8390"
    ) as klient:
        blok = await klient.post(
            "/api/aktualizacje", json={"akcja": "tryb", "tryb": "reczne"}, headers=naglowki(narzucona)
        )
        assert blok.status_code == 409
        odczyt = await klient.get("/api/aktualizacje", headers=naglowki(narzucona))
        assert odczyt.json()["narzucony"] is True
        assert odczyt.json()["tryb"] == "wylaczone"


@pytest.mark.anyio
async def test_api_instaluj_offline_zly_podpis_422(srodowisko_testowe, tmp_path, monkeypatch):
    from niewidka.api import create_app
    from niewidka.konfig import Konfig

    monkeypatch.setattr(aktualizacje, "KLUCZ_PUBLICZNY_DOMYSLNY", srodowisko_testowe["plik_pub"])
    _wstrzymaj_sprawdzanie_przy_starcie(srodowisko_testowe["dane"])
    folder = _folder_offline(tmp_path, srodowisko_testowe["klucz_prywatny"], podpisz_poprawnie=False)

    app = create_app(
        Konfig(modele_katalog=srodowisko_testowe["modele"]), detektor=DetektorProbki()
    )
    naglowki = {"X-Niewidka-Token": app.state.token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8390"
    ) as klient:
        odpowiedz = await klient.post(
            "/api/aktualizacje",
            json={"akcja": "instaluj", "folder": str(folder)},
            headers=naglowki,
        )
        assert odpowiedz.status_code == 422
        assert "podpis" in odpowiedz.json()["blad"]
        odczyt = await klient.get("/api/aktualizacje", headers=naglowki)
        assert odczyt.json()["stan"] == "aktualny"  # odrzucenie nie zatruwa stanu


@pytest.mark.anyio
async def test_api_instaluj_offline_dobry_podpis_koniec_na_cofniecie(
    srodowisko_testowe, tmp_path, monkeypatch
):
    from niewidka.api import create_app
    from niewidka.konfig import Konfig

    monkeypatch.setattr(aktualizacje, "KLUCZ_PUBLICZNY_DOMYSLNY", srodowisko_testowe["plik_pub"])
    _wstrzymaj_sprawdzanie_przy_starcie(srodowisko_testowe["dane"])
    kat_modeli = srodowisko_testowe["modele"]
    _stary_pakiet_w_katalogu_modeli(kat_modeli)
    folder = _folder_offline(tmp_path, srodowisko_testowe["klucz_prywatny"], podpisz_poprawnie=True)

    app = create_app(Konfig(modele_katalog=kat_modeli), detektor=DetektorProbki())
    # detektor i próbka kontrolna wstrzyknięte (w teście bez prawdziwych wag)
    app.state.aktualizacje._fabryka_detektora = lambda pakiet, katalog: DetektorProbki()
    app.state.aktualizacje._probka_plik = _probka(tmp_path)
    naglowki = {"X-Niewidka-Token": app.state.token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8390"
    ) as klient:
        odpowiedz = await klient.post(
            "/api/aktualizacje",
            json={"akcja": "instaluj", "folder": str(folder)},
            headers=naglowki,
        )
        assert odpowiedz.status_code == 202
        for _ in range(250):  # czekaj na koniec operacji w tle (postep bez pakietu)
            odczyt = await klient.get("/api/aktualizacje", headers=naglowki)
            if odczyt.json()["postep"]["pakiet"] is None:
                break
            await asyncio.sleep(0.02)
        assert odczyt.json()["postep"]["blad"] is None
        assert (kat_modeli / "model.onnx").read_text(encoding="utf-8") == "nowy-model-v2"
        dane = odczyt.json()
        assert dane["stan"] == "aktualny"
        assert dane["pakiety"][0]["wersja_zainstalowana"] == 2
        assert dane["pakiety"][0]["mozliwe_cofniecie"] is True

        wstecz = await klient.post(
            "/api/aktualizacje",
            json={"akcja": "cofnij", "pakiet": "podstawowy"},
            headers=naglowki,
        )
        assert wstecz.status_code == 200
        assert (kat_modeli / "model.onnx").read_text(encoding="utf-8") == "stary-model"


@pytest.mark.anyio
async def test_api_cialo_json_ktore_nie_jest_obiektem_daje_422(srodowisko_testowe):
    from niewidka.api import create_app
    from niewidka.konfig import Konfig

    app = create_app(Konfig(modele_katalog=srodowisko_testowe["modele"]), detektor=DetektorProbki())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8390"
    ) as klient:
        for adres in ("/api/pakiety", "/api/aktualizacje", "/api/popraw", "/api/listy"):
            metoda = klient.put if adres == "/api/listy" else klient.post
            odpowiedz = await metoda(
                adres, json='{"akcja": "pobierz"}', headers={"X-Niewidka-Token": app.state.token}
            )
            assert odpowiedz.status_code == 422, adres
