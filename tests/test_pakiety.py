"""Testy katalogu i pobierania pakietów modeli (K7b).

Pobieranie na httpx.MockTransport (bez sieci); struktura katalogu wag zgodna z
adapterami detektorów (bardsai w katalogu głównym, LFM2.5 w lfm25/q4-bl32/).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from niewidka import pakiety
from niewidka.pakiety import BladPakietu


@pytest.fixture()
def katalog_testowy(tmp_path):
    """Tymczasowy katalog pakietów: pliki mają SHA-256 TREŚCI TESTOWYCH, więc
    pobieranie może się powieść bez prawdziwych wag."""
    pliki_b = [
        {"nazwa": "model.onnx", "zrodlo": "podstawowy-model.onnx"},
        {"nazwa": "tokenizer.json", "zrodlo": "podstawowy-tokenizer.json"},
        {"nazwa": "config.json", "zrodlo": "podstawowy-config.json"},
    ]
    pliki_r = [
        {"nazwa": "lfm25/q4-bl32/model.onnx", "zrodlo": "rozszerzony-model.onnx"},
        {"nazwa": "lfm25/q4-bl32/tokenizer.json", "zrodlo": "rozszerzony-tokenizer.json"},
        {"nazwa": "lfm25/q4-bl32/config.json", "zrodlo": "rozszerzony-config.json"},
    ]
    tresci: dict[str, bytes] = {}
    for grupa in (pliki_b, pliki_r):
        for wpis in grupa:
            tresc = f"tresc-{wpis['zrodlo']}".encode()
            tresci[wpis["zrodlo"]] = tresc
            wpis["rozmiar"] = len(tresc)
            wpis["sha256"] = __import__("hashlib").sha256(tresc).hexdigest()
    dane = {
        "zrodlo_domyslne": "http://x/",
        "pakiety": [
            {
                "id": "podstawowy",
                "nazwa": "Podstawowy",
                "opis": "testowy",
                "wymagany": True,
                "poziomy": [1, 2, 3],
                "katalog_rel": "",
                "pliki": pliki_b,
            },
            {
                "id": "rozszerzony",
                "nazwa": "Rozszerzony",
                "opis": "testowy",
                "wymagany": False,
                "poziomy": [3],
                "katalog_rel": "lfm25/q4-bl32",
                "wymaga": "podstawowy",
                "pliki": pliki_r,
            },
        ],
    }
    plik = tmp_path / "pakiety.json"
    plik.write_text(json.dumps(dane), encoding="utf-8")
    return {"plik": plik, "lista": pakiety.wczytaj_pakiety(plik), "tresci": tresci}


def _transport(tresci: dict[str, bytes], obsluzone: list[httpx.Request] | None = None):
    """MockTransport serwujący pliki po nazwie zrodlo; obsługa Range dla wznowień."""

    def handler(request: httpx.Request) -> httpx.Response:
        if obsluzone is not None:
            obsluzone.append(request)
        nazwa = str(request.url).rsplit("/", 1)[-1]
        tresc = tresci.get(nazwa)
        if tresc is None:
            return httpx.Response(404)
        zakres = request.headers.get("range")
        if zakres and zakres.startswith("bytes="):
            start = int(zakres[6:].split("-")[0])
            naglowki = {"content-range": f"bytes {start}-{len(tresc)-1}/{len(tresc)}"}
            return httpx.Response(206, content=tresc[start:], headers=naglowki)
        return httpx.Response(200, content=tresc)

    return httpx.MockTransport(handler)


def test_wczytaj_pakiety_dwa_pakiety_z_plikami():
    pakiety_lista = pakiety.wczytaj_pakiety()
    identyfikatory = [p.id for p in pakiety_lista]
    assert identyfikatory == ["podstawowy", "rozszerzony"]
    podstawowy = pakiety_lista[0]
    assert podstawowy.wymagany is True
    assert podstawowy.poziomy == [1, 2, 3]
    nazwy = [plik.nazwa for plik in podstawowy.pliki]
    assert nazwy == ["model.onnx", "tokenizer.json", "config.json"]
    for plik in podstawowy.pliki:
        assert len(plik.sha256) == 64 and plik.rozmiar > 0
        assert plik.zrodlo.startswith("podstawowy-")
    rozszerzony = pakiety_lista[1]
    assert rozszerzony.wymagany is False
    assert rozszerzony.poziomy == [3]
    assert [plik.nazwa for plik in rozszerzony.pliki] == [
        "lfm25/q4-bl32/model.onnx",
        "lfm25/q4-bl32/tokenizer.json",
        "lfm25/q4-bl32/config.json",
    ]


def test_katalog_modeli_env_wygrywa(monkeypatch, tmp_path):
    monkeypatch.setenv("NIEWIDKA_MODELE_KATALOG", str(tmp_path / "wagi"))
    assert pakiety.katalog_modeli() == tmp_path / "wagi"


def test_katalog_modeli_domyslny_posix(monkeypatch):
    monkeypatch.delenv("NIEWIDKA_MODELE_KATALOG", raising=False)
    monkeypatch.setattr(pakiety.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/dane")
    katalog = pakiety.katalog_modeli()
    assert katalog == Path("/dane/Niewidka/modele")


def test_katalog_modeli_domyslny_windows(monkeypatch):
    monkeypatch.delenv("NIEWIDKA_MODELE_KATALOG", raising=False)
    monkeypatch.setattr(pakiety.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\k\AppData\Local")
    katalog = pakiety.katalog_modeli()
    assert str(katalog).replace("\\", "/").endswith("AppData/Local/Niewidka/modele")


def test_zrodlo_env_wygrywa_a_domyslne_istnieje(monkeypatch):
    monkeypatch.setenv("NIEWIDKA_MODELE_ZRODLO", "http://lustro.it:8000")
    assert pakiety.zrodlo() == "http://lustro.it:8000"
    monkeypatch.delenv("NIEWIDKA_MODELE_ZRODLO")
    assert pakiety.zrodlo().startswith("http")


def test_stan_brak_i_uszkodzony(tmp_path):
    podstawowy = pakiety.wczytaj_pakiety()[0]
    katalog = tmp_path / "modele"
    assert pakiety.stan(podstawowy, katalog) == "brak"
    for plik in podstawowy.pliki:
        cel = katalog / plik.nazwa
        cel.parent.mkdir(parents=True, exist_ok=True)
        cel.write_bytes(b"dane " * 100)
    assert pakiety.stan(podstawowy, katalog) == "uszkodzony"


def test_stan_i_instalacja_offline_po_katalogu_testowym(katalog_testowy, tmp_path):
    podstawowy = katalog_testowy["lista"][0]
    katalog = tmp_path / "modele"
    zrodlo = tmp_path / "lustrz"
    for pakiet_t in katalog_testowy["lista"]:
        for plik in pakiet_t.pliki:
            zrodlo.mkdir(parents=True, exist_ok=True)
            (zrodlo / plik.zrodlo).write_bytes(katalog_testowy["tresci"][plik.zrodlo])
    pakiety.instaluj_z_katalogu(podstawowy, katalog, zrodlo)
    assert pakiety.stan(podstawowy, katalog) == "zainstalowany"
    # rozszerzony ląduje w podkatalogu lfm25/q4-bl32 z własnym manifestem
    rozszerzony = katalog_testowy["lista"][1]
    pakiety.instaluj_z_katalogu(rozszerzony, katalog, zrodlo)
    assert pakiety.stan(rozszerzony, katalog) == "zainstalowany"
    manifest = json.loads(
        (katalog / "lfm25/q4-bl32/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["pakiet"] == "rozszerzony"


def test_pobierz_poprawny_przebieg(katalog_testowy, tmp_path):
    pakiet = katalog_testowy["lista"][0]
    klient = httpx.Client(transport=_transport(katalog_testowy["tresci"]))
    katalog = tmp_path / "m"
    postepy: list[tuple[int, int]] = []
    pakiety.pobierz(pakiet, katalog, "http://x/", klient=klient, postep=lambda a, b: postepy.append((a, b)))
    assert pakiety.stan(pakiet, katalog) == "zainstalowany"
    manifest = json.loads((katalog / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["pliki"]) == {plik.nazwa for plik in pakiet.pliki}
    assert manifest["pakiet"] == "podstawowy"
    assert not list(katalog.rglob("*.częściowy")), "po pobraniu nie ma plików częściowych"
    assert postepy and postepy[-1][0] == postepy[-1][1]  # postęp kończy się 100%
    # pominięcie: ponowne pobieranie nie odzywa się do serwera
    obsluzone: list[httpx.Request] = []
    klient2 = httpx.Client(transport=_transport(katalog_testowy["tresci"], obsluzone))
    pakiety.pobierz(pakiet, katalog, "http://x/", klient=klient2)
    assert not obsluzone


def test_pobierz_zly_hash_usuwa_i_zgłasza(katalog_testowy, tmp_path):
    pakiet = katalog_testowy["lista"][0]
    tresci = {plik.zrodlo: b"zle dane" for plik in pakiet.pliki}
    katalog = tmp_path / "m"
    klient = httpx.Client(transport=_transport(tresci))
    with pytest.raises(BladPakietu):
        pakiety.pobierz(pakiet, katalog, "http://x/", klient=klient)
    assert pakiety.stan(pakiet, katalog) == "brak"
    if katalog.exists():
        assert not list(katalog.rglob("*.częściowy"))
        assert not [p for p in pakiet.pliki if (katalog / p.nazwa).exists()]


def test_pobierz_wznawia_od_czesciowego(katalog_testowy, tmp_path):
    pakiet = katalog_testowy["lista"][0]
    plik = pakiet.pliki[0]
    tresci = katalog_testowy["tresci"]
    katalog = tmp_path / "m"
    cel = katalog / plik.nazwa
    cel.parent.mkdir(parents=True)
    calosc = tresci[plik.zrodlo]
    cel.with_name(cel.name + ".częściowy").write_bytes(calosc[: len(calosc) // 2])
    obsluzone: list[httpx.Request] = []
    klient = httpx.Client(transport=_transport(tresci, obsluzone))
    pakiety.pobierz(pakiet, katalog, "http://x/", klient=klient)
    zadanie_plik = next(r for r in obsluzone if str(r.url).endswith(plik.zrodlo))
    assert zadanie_plik.headers.get("range") == f"bytes={len(calosc) // 2}-"
    assert pakiety.stan(pakiet, katalog) == "zainstalowany"


def test_pobierz_serwer_bez_range_zaczyna_od_nowa(katalog_testowy, tmp_path):
    pakiet = katalog_testowy["lista"][0]
    plik = pakiet.pliki[0]
    tresci = katalog_testowy["tresci"]
    katalog = tmp_path / "m"
    cel = katalog / plik.nazwa
    cel.parent.mkdir(parents=True)
    cel.with_name(cel.name + ".częściowy").write_bytes(b"obce resztki")

    def handler_bez_range(request: httpx.Request) -> httpx.Response:
        nazwa = str(request.url).rsplit("/", 1)[-1]
        return httpx.Response(200, content=tresci.get(nazwa, b""))

    klient = httpx.Client(transport=httpx.MockTransport(handler_bez_range))
    pakiety.pobierz(pakiet, katalog, "http://x/", klient=klient)
    assert pakiety.stan(pakiet, katalog) == "zainstalowany"


def test_usun_pakiet(tmp_path):
    lista = pakiety.wczytaj_pakiety()
    pakiet = lista[0]
    katalog = tmp_path / "m"
    for plik in pakiet.pliki:
        cel = katalog / plik.nazwa
        cel.parent.mkdir(parents=True, exist_ok=True)
        cel.write_bytes(b"x")
    (katalog / "manifest.json").write_text("{}", encoding="utf-8")
    pakiety.usun(pakiet, katalog)
    assert pakiety.stan(pakiet, katalog) == "brak"


def test_instaluj_z_katalogu_zly_plik_zglasza_blad(tmp_path):
    lista = pakiety.wczytaj_pakiety()
    pakiet = lista[0]
    zrodlo = tmp_path / "lustrz"
    zrodlo.mkdir()
    for plik in pakiet.pliki:
        (zrodlo / plik.zrodlo).write_bytes(b"nie ten plik")
    with pytest.raises(BladPakietu):
        pakiety.instaluj_z_katalogu(pakiet, tmp_path / "m", zrodlo)



# --- K7b: MenedzerPakietow (stan dla API/UI, jedno pobieranie naraz) ----------

from niewidka.pakiety import MenedzerPakietow


@pytest.fixture()
def menedzer(katalog_testowy, tmp_path):
    klient = httpx.Client(transport=_transport(katalog_testowy["tresci"]))
    return MenedzerPakietow(
        katalog_testowy["lista"], tmp_path / "m", "http://x/", klient=klient
    )


def test_menedzer_lista_stanow(menedzer):
    wpisy = menedzer.lista()
    assert [w["id"] for w in wpisy] == ["podstawowy", "rozszerzony"]
    assert wpisy[0]["stan"] == "brak" and wpisy[0]["wymagany"] is True
    assert wpisy[0]["rozmiar_bajtow"] > 0 and wpisy[0]["poziomy"] == [1, 2, 3]


def test_menedzer_pobierz_i_poziomy_dostepne(menedzer):
    assert menedzer.poziomy_dostepne() == []  # bez pakietu żadnego poziomu nie ma
    assert menedzer.brakujacy_wymagany() == ["podstawowy"]
    assert menedzer.pobierz("podstawowy") is True
    menedzer.czekaj()
    assert menedzer.poziomy_dostepne() == [1, 2, 3]
    assert menedzer.brakujacy_wymagany() == []
    wpisy = {w["id"]: w for w in menedzer.lista()}
    assert wpisy["podstawowy"]["stan"] == "zainstalowany"
    assert menedzer.postep.pakiet is None  # pobieranie się skończyło


def test_menedzer_jedno_pobieranie_naraz(menedzer):
    assert menedzer.pobierz("podstawowy") is True
    assert menedzer.pobierz("rozszerzony") is False  # w toku
    menedzer.czekaj()
    assert menedzer.pobierz("rozszerzony") is True
    menedzer.czekaj()
    wpisy = {w["id"]: w for w in menedzer.lista()}
    assert wpisy["rozszerzony"]["stan"] == "zainstalowany"


def test_menedzer_postep_w_toku(menedzer):
    # zsynchronizujmy się z wątkiem pobierania przez postęp
    menedzer.pobierz("podstawowy")
    while menedzer.postep.pakiet is None and not menedzer.zakonczone():
        pass  # wątek startował
    widoczny = menedzer.postep
    assert widoczny.razem > 0
    menedzer.czekaj()


def test_menedzer_blad_pobierania_jest_jawny(tmp_path, katalog_testowy):
    def handler_404(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    menedzer = MenedzerPakietow(
        katalog_testowy["lista"], tmp_path / "m", "http://x/", klient=httpx.Client(
            transport=httpx.MockTransport(handler_404)
        )
    )
    menedzer.pobierz("podstawowy")
    menedzer.czekaj()
    assert "podstawowy" in (menedzer.postep.blad or "")


def test_menedzer_usun(menedzer):
    menedzer.pobierz("podstawowy")
    menedzer.czekaj()
    menedzer.usun("podstawowy")
    wpisy = {w["id"]: w for w in menedzer.lista()}
    assert wpisy["podstawowy"]["stan"] == "brak"


def test_menedzer_nieznany_pakiet(menedzer):
    assert menedzer.pobierz("nie-ma") is False
    with pytest.raises(KeyError):
        menedzer.usun("nie-ma")


def test_menedzer_instaluj_z_katalogu(menedzer, katalog_testowy, tmp_path):
    lustro = tmp_path / "lustrz"
    for tresc in katalog_testowy["tresci"].values():
        # nazwy plików w lustrze pochodzą z pola zrodlo
        for plik in [p for pakiet in katalog_testowy["lista"] for p in pakiet.pliki]:
            if katalog_testowy["tresci"][plik.zrodlo] == tresc:
                lustro.mkdir(parents=True, exist_ok=True)
                (lustro / plik.zrodlo).write_bytes(tresc)
    menedzer.instaluj("podstawowy", lustro)
    wpisy = {w["id"]: w for w in menedzer.lista()}
    assert wpisy["podstawowy"]["stan"] == "zainstalowany"


# --- K7c pkt 1: stan pakietu dla rdzenia + zwrot zmiany (invalidacja cache) ---

def test_menedzer_stan_pakietu(menedzer):
    assert menedzer.stan_pakietu("podstawowy") == "brak"
    assert menedzer.stan_pakietu("rozszerzony") == "brak"
    assert menedzer.stan_pakietu("nie-ma") is None
    menedzer.pobierz("podstawowy")
    menedzer.czekaj()
    assert menedzer.stan_pakietu("podstawowy") == "zainstalowany"


def test_menedzer_on_zmiana_po_kazdej_operacji(katalog_testowy, tmp_path):
    zmiany: list[str] = []
    menedzer = MenedzerPakietow(
        katalog_testowy["lista"],
        tmp_path / "m",
        "http://x/",
        klient=httpx.Client(transport=_transport(katalog_testowy["tresci"])),
        on_zmiana=lambda: zmiany.append("zmiana"),
    )
    menedzer.pobierz("podstawowy")
    menedzer.czekaj()
    menedzer.usun("podstawowy")
    menedzer.instaluj("podstawowy", _lustro(katalog_testowy, tmp_path))
    assert zmiany == ["zmiana", "zmiana", "zmiana"]


def _lustro(katalog_testowy, tmp_path):
    lustro = tmp_path / "lustro"
    lustro.mkdir(exist_ok=True)
    for plik in [p for pakiet in katalog_testowy["lista"] for p in pakiet.pliki]:
        (lustro / plik.zrodlo).write_bytes(katalog_testowy["tresci"][plik.zrodlo])
    return lustro
