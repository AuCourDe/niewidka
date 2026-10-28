"""Testy katalogu i pobierania pakietów modeli (K7b).

Pobieranie na httpx.MockTransport (bez sieci); struktura katalogu wag zgodna z
adapterami detektorów (bardsai w katalogu głównym, LFM2.5 w lfm25/q4-bl32/).
"""

from __future__ import annotations

import json
import time
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
    menedzer.czekaj()  # K7c pkt 8: instalacja idzie w tle
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
    menedzer.czekaj()  # K7c pkt 8: instalacja idzie w tle
    assert zmiany == ["zmiana", "zmiana", "zmiana"]


def _lustro(katalog_testowy, tmp_path):
    lustro = tmp_path / "lustro"
    lustro.mkdir(exist_ok=True)
    for plik in [p for pakiet in katalog_testowy["lista"] for p in pakiet.pliki]:
        (lustro / plik.zrodlo).write_bytes(katalog_testowy["tresci"][plik.zrodlo])
    return lustro


# --- K7c pkt 4: dowiązania nie prowadzą poza katalog modeli -------------------

def test_pobierz_nie_niszczy_ofiary_przez_symlink_czesciowego(katalog_testowy, tmp_path):
    """Audyt #4: model.onnx.częściowy podstawiony jako symlink do pliku ofiary;
    instalacja NIE wolno otworzyć ofiary do nadpisania."""
    pakiet = katalog_testowy["lista"][0]
    katalog = tmp_path / "m"
    katalog.mkdir()
    ofiara = tmp_path / "ofiara.dat"
    ofiara.write_bytes(b"WAzne DANE OFIARY" * 10)
    cel = katalog / pakiet.pliki[0].nazwa
    cel.symlink_to(ofiara)
    (cel.parent / (cel.name + pakiety.CZESCIOWY)).symlink_to(ofiara)
    klient = httpx.Client(transport=_transport(katalog_testowy["tresci"]))
    pakiety.pobierz(pakiet, katalog, "http://x/", klient=klient)
    assert ofiara.read_bytes() == b"WAzne DANE OFIARY" * 10
    assert pakiety.stan(pakiet, katalog) == "zainstalowany"


def test_instaluj_offline_nie_niszczy_ofiary_przez_symlink(katalog_testowy, tmp_path):
    pakiet = katalog_testowy["lista"][0]
    katalog = tmp_path / "m"
    katalog.mkdir()
    ofiara = tmp_path / "raport.txt"
    ofiara.write_bytes("treść ofiary".encode())
    for plik in pakiet.pliki:
        (katalog / (Path(plik.nazwa).name + pakiety.CZESCIOWY)).symlink_to(ofiara)
    lustro = _lustro(katalog_testowy, tmp_path)
    pakiety.instaluj_z_katalogu(pakiet, katalog, lustro)
    assert ofiara.read_bytes() == "treść ofiary".encode()
    assert pakiety.stan(pakiet, katalog) == "zainstalowany"


def test_manifest_atomowo_nie_niszczy_ofiary(katalog_testowy, tmp_path):
    """manifest.json podstawiony jako symlink: zapis atomowy replace'MUJE dowiązanie,
    nie pisze przez nie do ofiary."""
    rozszerzony = katalog_testowy["lista"][1]  # manifest w podkatalogu lfm25/q4-bl32
    katalog = tmp_path / "m"
    podkatalog = katalog / rozszerzony.katalog_rel
    podkatalog.mkdir(parents=True)
    ofiara = tmp_path / "ofiara.json"
    ofiara.write_bytes(b"{}")
    (podkatalog / "manifest.json").symlink_to(ofiara)
    lustro = _lustro(katalog_testowy, tmp_path)
    pakiety.instaluj_z_katalogu(rozszerzony, katalog, lustro)
    assert ofiara.read_bytes() == b"{}"
    assert pakiety.stan(rozszerzony, katalog) == "zainstalowany"


def test_pobierz_odrzucca_symlink_w_sciezce_podkatalogu(katalog_testowy, tmp_path):
    """Junction/symlink w PODKATALOGU ścieżki (lfm25 -> gdziekolwiek) = odmowa."""
    rozszerzony = katalog_testowy["lista"][1]
    katalog = tmp_path / "m"
    (katalog / "lfm25").mkdir(parents=True)
    obcy = tmp_path / "obcy"
    obcy.mkdir()
    (katalog / "lfm25" / "q4-bl32").symlink_to(obcy)
    klient = httpx.Client(transport=_transport(katalog_testowy["tresci"]))
    with pytest.raises(BladPakietu):
        pakiety.pobierz(rozszerzony, katalog, "http://x/", klient=klient)
    assert not (obcy / "model.onnx").exists()


def test_blad_pobierania_kontrolowany_bez_hasla_i_url(tmp_path, katalog_testowy):
    """K7c pkt 5 (audyt): 503 z lustra nie może wynieść URL z login:hasło do
    postep.blad (czytanego przez GET /api/pakiety)."""
    def handler_503(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    menedzer = MenedzerPakietow(
        katalog_testowy["lista"],
        tmp_path / "m",
        "http://login:SekretneHaslo@lustro.example/pliki",
        klient=httpx.Client(transport=httpx.MockTransport(handler_503)),
    )
    menedzer.pobierz("podstawowy")
    menedzer.czekaj()
    blad = menedzer.postep.blad or ""
    assert "SekretneHaslo" not in blad
    assert "lustro.example" not in blad
    assert "http" not in blad
    assert "podstawowy" in blad and "503" in blad


# --- K7c pkt 8: twarde limity pobierania i instalacji w tle -------------------

def test_limit_czasu_z_env():
    assert pakiety.limit_czasu_domyslny({}) == 1800
    assert pakiety.limit_czasu_domyslny({"NIEWIDKA_PAKIETY_LIMIT_CZASU_S": "60"}) == 60
    with pytest.raises(ValueError):
        pakiety.limit_czasu_domyslny({"NIEWIDKA_PAKIETY_LIMIT_CZASU_S": "duzo"})


def test_pobierz_twardy_limit_bajtow(katalog_testowy, tmp_path):
    """Audyt #8: serwer deklaruje 1 B, wysyła megabajty; zapis ma pilnować
    rozmiaru z katalogu PRZED każdym zapisem."""
    pakiet = katalog_testowy["lista"][0]
    plik = pakiet.pliki[0]

    def handler_lzik(request: httpx.Request) -> httpx.Response:
        tresc = katalog_testowy["tresci"][plik.zrodlo] + b"X" * 4096
        return httpx.Response(200, content=tresc)

    katalog = tmp_path / "m"
    klient = httpx.Client(transport=httpx.MockTransport(handler_lzik))
    with pytest.raises(BladPakietu, match="rozmiar"):
        pakiety.pobierz(pakiet, katalog, "http://x/", klient=klient)
    assert pakiety.stan(pakiet, katalog) == "brak"


def test_pobierz_limit_bajtow_przy_wznowieniu(katalog_testowy, tmp_path):
    """Limit obowiązuje też przy Range: start + nowo pobrane ≤ rozmiar z katalogu."""
    pakiet = katalog_testowy["lista"][0]
    plik = pakiet.pliki[0]
    calosc = katalog_testowy["tresci"][plik.zrodlo]
    katalog = tmp_path / "m"
    cel = katalog / plik.nazwa
    cel.parent.mkdir(parents=True)
    czesciowy = cel.with_name(cel.name + pakiety.CZESCIOWY)
    czesciowy.write_bytes(calosc[:-1])  # brakuje ostatniego bajtu

    def handler_dopisuje(request: httpx.Request) -> httpx.Response:
        # ignoruje Range, wysyła ostatni bajt + 5 bajtów za dużo
        return httpx.Response(206, content=calosc[-1:] + b"X" * 5,
                              headers={"content-range": f"bytes {len(calosc)-1}-/x"})

    klient = httpx.Client(transport=httpx.MockTransport(handler_dopisuje))
    with pytest.raises(BladPakietu, match="rozmiar"):
        pakiety.pobierz(pakiet, katalog, "http://x/", klient=klient)


def test_pobierz_calkowity_limit_czasu(katalog_testowy, tmp_path):
    """Audyt #8: timeout odczytu dotyczy fragmentu, nie całego transferu —
    strumień wysyłający kawałki częściej niż timeout ma zostać przerwany."""
    pakiet = katalog_testowy["lista"][0]
    tresc = katalog_testowy["tresci"][pakiet.pliki[0].zrodlo]

    def strumien():
        for i in range(0, len(tresc), 4):
            time.sleep(0.05)
            yield tresc[i : i + 4]

    def handler_wolny(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=strumien())

    katalog = tmp_path / "m"
    klient = httpx.Client(transport=httpx.MockTransport(handler_wolny))
    start = time.monotonic()
    with pytest.raises(BladPakietu, match="czas"):
        pakiety.pobierz(pakiet, katalog, "http://x/", klient=klient, limit_czasu_s=0.1)
    assert time.monotonic() - start < 2


def test_instaluj_z_katalogu_odrzuca_plik_inny_niz_w_katalogu(tmp_path, katalog_testowy):
    """Limit bajtów przy instalacji offline: plik źródłowy większy niż katalog
    wag = odmowa przed kopiowaniem (zapełnianie dysku przez lustro IT)."""
    pakiet = katalog_testowy["lista"][0]
    lustro = tmp_path / "lustrz"
    lustro.mkdir()
    for plik in pakiet.pliki:
        tresc = katalog_testowy["tresci"][plik.zrodlo]
        if plik is pakiet.pliki[0]:
            tresc = tresc + b"DODATKOWE BAJTY Z LUSTRA"
        (lustro / plik.zrodlo).write_bytes(tresc)
    with pytest.raises(BladPakietu, match="rozmiar"):
        pakiety.instaluj_z_katalogu(pakiet, tmp_path / "m", lustro)


def test_menedzer_instaluj_w_tle_anulowanie(katalog_testowy, tmp_path):
    """K7c pkt 8: instalacja offline idzie do wątku tła (nie blokuje pętli API)
    z tym samym limitem bajtów; anulowanie kończy operację."""
    import threading as _threading

    brama = _threading.Event()
    moze_isc = _threading.Event()
    oryginalna = pakiety.instaluj_z_katalogu

    def wolna_instalacja(*args, **kwargs):
        brama.set()
        moze_isc.wait(2)
        return oryginalna(*args, **kwargs)

    pakiety.instaluj_z_katalogu, oryginalna_kopia = wolna_instalacja, pakiety.instaluj_z_katalogu
    try:
        menedzer = MenedzerPakietow(
            katalog_testowy["lista"],
            tmp_path / "m",
            "http://x/",
            klient=httpx.Client(transport=_transport(katalog_testowy["tresci"])),
        )
        menedzer.instaluj("podstawowy", _lustro(katalog_testowy, tmp_path))
        assert brama.wait(1), "instalacja ma ruszyć w tle"
        assert not menedzer.zakonczone(), "instalacja ma być w tle (API nie blokowane)"
        assert menedzer.pobierz("rozszerzony") is False, "jedna operacja naraz"
        menedzer.anuluj()
        menedzer.czekaj()
        assert "przerwan" in (menedzer.postep.blad or "")
    finally:
        pakiety.instaluj_z_katalogu = oryginalna_kopia


def test_menedzer_anuluj_pobieranie(katalog_testowy, tmp_path):
    pakiet = katalog_testowy["lista"][0]
    tresc = katalog_testowy["tresci"][pakiet.pliki[0].zrodlo]

    def strumien():
        for i in range(0, len(tresc), 2):
            time.sleep(0.05)
            yield tresc[i : i + 2]

    def handler_wolny(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=strumien())

    menedzer = MenedzerPakietow(
        katalog_testowy["lista"],
        tmp_path / "m",
        "http://x/",
        klient=httpx.Client(transport=httpx.MockTransport(handler_wolny)),
    )
    assert menedzer.pobierz("podstawowy") is True
    menedzer.anuluj()
    menedzer.czekaj()
    assert "przerwan" in (menedzer.postep.blad or "")
    assert menedzer.postep.pakiet is None  # można ponowić (pkt 11)


# --- K7c pkt 9: zapamiętany stan, weryfikacja w tle ---------------------------

def test_menedzer_lista_z_cache_bez_haszowania(menedzer, monkeypatch):
    """Audyt #9: GET /api/pakiety haszował ~600 MB przy KAŻDYM żądaniu (0,43 s);
    polling UI potrafił zagłodzić całe API. Stan ma być zapamiętany: liczony
    przy starcie i po zmianie, nie na żądanie."""
    menedzer.czekaj()  # pierwsze przeliczenie w tle po starcie
    menedzer.pobierz("podstawowy")
    menedzer.czekaj()  # po operacji stan świeży
    def boom(pakiet, katalog):
        raise AssertionError("stan() wywołany na żądanie (musi pochodzić z cache)")
    monkeypatch.setattr(pakiety, "stan", boom)
    wpisy = menedzer.lista()
    assert wpisy[0]["stan"] == "zainstalowany"
    assert menedzer.poziomy_dostepne() == [1, 2, 3]
    assert menedzer.brakujacy_wymagany() == []
    assert menedzer.stan_pakietu("podstawowy") == "zainstalowany"


def test_menedzer_zmiana_z_zewnatrz_odswiezana_w_tle(menedzer, katalog_testowy, tmp_path, monkeypatch):
    """IT wgrywa wagi do katalogu z zewnątrz: fingerprint obecności (stat, bez SHA)
    wykrywa zmianę, lista() zwraca zapamiętany stan, a hasze liczy wątek tła."""
    menedzer.czekaj()
    assert menedzer.lista()[0]["stan"] == "brak"
    for plik in menedzer._pakiety["podstawowy"].pliki:
        cel = tmp_path / "m" / plik.nazwa
        cel.parent.mkdir(parents=True, exist_ok=True)
        cel.write_bytes(katalog_testowy["tresci"][plik.zrodlo])
    # lista() zwraca zapamiętany stan i odpala odświeżenie w tle (tu przechwycone)
    odpalone = []
    monkeypatch.setattr(menedzer, "odswiez_w_tle", lambda: odpalone.append(1))
    assert menedzer.lista()[0]["stan"] == "brak"
    assert odpalone == [1], "zmiana obecności plików ma odpalać odświeżenie w tle"


# --- K7c pkt 10: przekierowania pod kontrolą ----------------------------------

def _transport_przekierowanie(dokad, trafione: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        trafione.append(str(request.url))
        return httpx.Response(302, headers={"location": dokad})

    return httpx.MockTransport(handler)


@pytest.fixture()
def katalog_testowy_naglowkowy(katalog_testowy):
    """Tresci serwowane po JEDNYM przekierowaniu (drugi handler zwraca pliki)."""
    return katalog_testowy


def test_przekierowanie_do_loopback_odrzucone(katalog_testowy, tmp_path):
    """Audyt #10: przejęte lustro odsyła 302 na http://127.0.0.1:12345/private;
    pobieranie nie może wykonać ślepego żądania do lokalnej usługi."""
    pakiet = katalog_testowy["lista"][0]
    trafione: list[str] = []
    klient = httpx.Client(
        transport=_transport_przekierowanie("http://127.0.0.1:12345/private", trafione)
    )
    with pytest.raises(BladPakietu):
        pakiety.pobierz(pakiet, tmp_path / "m", "https://github.com/x/", klient=klient)
    assert not any("127.0.0.1:12345" in u for u in trafione), "żądanie SSRF wykonane"


def test_przekierowanie_https_na_http_poza_lustrem_odrzucone(katalog_testowy, tmp_path):
    pakiet = katalog_testowy["lista"][0]
    trafione: list[str] = []
    klient = httpx.Client(
        transport=_transport_przekierowanie("http://zlosliwy.example/plik", trafione)
    )
    with pytest.raises(BladPakietu):
        pakiety.pobierz(pakiet, tmp_path / "m", "https://github.com/x/", klient=klient)
    assert not any("zlosliwy.example" in u for u in trafione)


def test_przekierowanie_do_sieci_prywatnej_przez_https_odrzucone(katalog_testowy, tmp_path):
    pakiet = katalog_testowy["lista"][0]
    trafione: list[str] = []
    klient = httpx.Client(
        transport=_transport_przekierowanie("https://10.1.2.3/ukryte", trafione)
    )
    with pytest.raises(BladPakietu):
        pakiety.pobierz(pakiet, tmp_path / "m", "https://github.com/x/", klient=klient)
    assert not any("10.1.2.3" in u for u in trafione)


def test_przekierowanie_wewnatrz_lustra_http_dopuszczone(katalog_testowy, tmp_path):
    """Lustro IT (NIEWIDKA_MODELE_ZRODLO, także http i loopback) może przekierowywać
    w obrębie własnego hosta — scenariusz z K7b (python -m http.server na 127.0.0.1)."""
    pakiet = katalog_testowy["lista"][0]
    tresci = katalog_testowy["tresci"]
    skoki = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal skoki
        nazwa = str(request.url).rsplit("/", 1)[-1]
        if nazwa not in tresci and skoki < 8:
            skoki += 1
            return httpx.Response(302, headers={"location": f"/pliki/{nazwa}"})
        return httpx.Response(200, content=tresci.get(nazwa, b""))

    klient = httpx.Client(transport=httpx.MockTransport(handler))
    katalog = tmp_path / "m"
    pakiety.pobierz(pakiet, katalog, "http://127.0.0.1:39950", klient=klient)
    assert pakiety.stan(pakiet, katalog) == "zainstalowany"


def test_przekierowanie_do_publicznego_https_dopuszczone(katalog_testowy, tmp_path):
    """Publiczny HTTPS poza lustrem jest dozwolony (cdn pakietów); dosłowne
    publiczne IP, by test nie zależał od DNS."""
    pakiet = katalog_testowy["lista"][0]
    tresci = katalog_testowy["tresci"]

    def handler(request: httpx.Request) -> httpx.Response:
        nazwa = str(request.url).rsplit("/", 1)[-1]
        if str(request.url).startswith("https://github.com/x/"):
            return httpx.Response(302, headers={"location": f"https://93.184.216.34/obj/{nazwa}"})
        return httpx.Response(200, content=tresci.get(nazwa, b""))

    klient = httpx.Client(transport=httpx.MockTransport(handler))
    katalog = tmp_path / "m"
    pakiety.pobierz(pakiet, katalog, "https://github.com/x/", klient=klient)
    assert pakiety.stan(pakiet, katalog) == "zainstalowany"


# --- K7c pkt 11: błąd pobierania nie blokuje ponowienia -----------------------

def test_blad_404_potem_poprawne_ponowienie(tmp_path, katalog_testowy):
    """Audyt #11: po jednym błędzie lustra UI do końca życia wyłączał przyciski
    (postep.pakiet został ustawiony). Stan operacji ma się czyścić także przy błędzie."""
    serwer_dziala = {"ok": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if not serwer_dziala["ok"]:
            return httpx.Response(404)
        nazwa = str(request.url).rsplit("/", 1)[-1]
        return httpx.Response(200, content=katalog_testowy["tresci"].get(nazwa, b""))

    menedzer = MenedzerPakietow(
        katalog_testowy["lista"],
        tmp_path / "m",
        "http://x/",
        klient=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    menedzer.pobierz("podstawowy")
    menedzer.czekaj()
    assert menedzer.postep.pakiet is None, "stan operacji ma być wyczyszczony w finally"
    assert "404" in (menedzer.postep.blad or ""), "błąd przechowywany osobno od stanu"
    assert menedzer.zakonczone()
    # lustro naprawione: ponowienie działa bez restartu
    serwer_dziala["ok"] = True
    assert menedzer.pobierz("podstawowy") is True, "ponowienie po błędzie ma być możliwe"
    menedzer.czekaj()
    wpisy = {w["id"]: w for w in menedzer.lista()}
    assert wpisy["podstawowy"]["stan"] == "zainstalowany"


def test_oserror_przez_strumien_kontrolowany_i_do_ponowienia(tmp_path, katalog_testowy):
    """OSError w trakcie (dysk pełny, urządzenie znikło) nie może zostawić stanu
    operacji ustawionego ani wyjść bez kontrolowanego komunikatu."""
    def strumien():
        yield b"pierwsze bajty"
        raise OSError("symulowany brak miejsca na dysku")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=strumien())

    menedzer = MenedzerPakietow(
        katalog_testowy["lista"],
        tmp_path / "m",
        "http://x/",
        klient=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    menedzer.pobierz("podstawowy")
    menedzer.czekaj()
    assert menedzer.postep.pakiet is None
    assert "nie powiodła się" in (menedzer.postep.blad or "")
    assert menedzer.zakonczone()
