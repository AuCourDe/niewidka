"""Tests of the model package catalog and download.

Download on httpx.MockTransport (no network); weights directory layout matches the
detector adapters (bardsai in the root directory, LFM2.5 in lfm25/q4-bl32/).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
from conftest import dowiazanie

from niewidka import pakiety
from niewidka.pakiety import BladPakietu


@pytest.fixture()
def katalog_testowy(tmp_path):
    """Temporary packages directory: files have the SHA-256 of TEST CONTENT, so
        a download can succeed without real weights."""
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
    """MockTransport serving files by the zrodlo name; Range support for resumes."""

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
    # the extended one lands in the lfm25/q4-bl32 subdirectory with its own manifest
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
    assert postepy and postepy[-1][0] == postepy[-1][1]  # progress ends at 100%
    # skipping: downloading again does not contact the server
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



# --- MenedzerPakietow (state for API/UI, one download at a time) ----------

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
    assert menedzer.poziomy_dostepne() == []  # without a package there is no level at all
    assert menedzer.brakujacy_wymagany() == ["podstawowy"]
    assert menedzer.pobierz("podstawowy") is True
    menedzer.czekaj()
    assert menedzer.poziomy_dostepne() == [1, 2, 3]
    assert menedzer.brakujacy_wymagany() == []
    wpisy = {w["id"]: w for w in menedzer.lista()}
    assert wpisy["podstawowy"]["stan"] == "zainstalowany"
    assert menedzer.postep.pakiet is None  # the download has finished


def test_menedzer_jedno_pobieranie_naraz(katalog_testowy, tmp_path):
    # download held until a signal: without it the fast stub finished it before the second
    # call and the test passed or failed depending on the thread scheduler
    import threading

    zwolnij = threading.Event()
    zwykly = _transport(katalog_testowy["tresci"])

    def wstrzymany(request: httpx.Request) -> httpx.Response:
        zwolnij.wait(10)
        return zwykly.handle_request(request)

    menedzer = MenedzerPakietow(
        katalog_testowy["lista"],
        tmp_path / "m",
        "http://x/",
        klient=httpx.Client(transport=httpx.MockTransport(wstrzymany)),
    )
    assert menedzer.pobierz("podstawowy") is True
    assert menedzer.pobierz("rozszerzony") is False  # in progress
    zwolnij.set()
    menedzer.czekaj()
    assert menedzer.pobierz("rozszerzony") is True
    menedzer.czekaj()
    wpisy = {w["id"]: w for w in menedzer.lista()}
    assert wpisy["rozszerzony"]["stan"] == "zainstalowany"


def test_menedzer_postep_w_toku(menedzer):
    # synchronize with the download thread through progress
    menedzer.pobierz("podstawowy")
    while menedzer.postep.pakiet is None and not menedzer.zakonczone():
        pass  # the thread started
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
        # file names in the mirror come from the zrodlo field
        for plik in [p for pakiet in katalog_testowy["lista"] for p in pakiet.pliki]:
            if katalog_testowy["tresci"][plik.zrodlo] == tresc:
                lustro.mkdir(parents=True, exist_ok=True)
                (lustro / plik.zrodlo).write_bytes(tresc)
    menedzer.instaluj("podstawowy", lustro)
    menedzer.czekaj()  # installation runs in the background
    wpisy = {w["id"]: w for w in menedzer.lista()}
    assert wpisy["podstawowy"]["stan"] == "zainstalowany"


# --- package state for the core + change return (cache invalidation) ---

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
    menedzer.czekaj()  # installation runs in the background
    assert zmiany == ["zmiana", "zmiana", "zmiana"]


def _lustro(katalog_testowy, tmp_path):
    lustro = tmp_path / "lustro"
    lustro.mkdir(exist_ok=True)
    for plik in [p for pakiet in katalog_testowy["lista"] for p in pakiet.pliki]:
        (lustro / plik.zrodlo).write_bytes(katalog_testowy["tresci"][plik.zrodlo])
    return lustro


# --- links do not lead outside the models directory -------------------

def test_pobierz_nie_niszczy_ofiary_przez_symlink_czesciowego(katalog_testowy, tmp_path):
    """Model.onnx.częściowy substituted as a symlink to a victim file;
        the installation must NOT open the victim for overwriting."""
    pakiet = katalog_testowy["lista"][0]
    katalog = tmp_path / "m"
    katalog.mkdir()
    ofiara = tmp_path / "ofiara.dat"
    ofiara.write_bytes(b"WAzne DANE OFIARY" * 10)
    cel = katalog / pakiet.pliki[0].nazwa
    dowiazanie(cel, ofiara)
    dowiazanie(cel.parent / (cel.name + pakiety.CZESCIOWY), ofiara)
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
        dowiazanie(katalog / (Path(plik.nazwa).name + pakiety.CZESCIOWY), ofiara)
    lustro = _lustro(katalog_testowy, tmp_path)
    pakiety.instaluj_z_katalogu(pakiet, katalog, lustro)
    assert ofiara.read_bytes() == "treść ofiary".encode()
    assert pakiety.stan(pakiet, katalog) == "zainstalowany"


def test_manifest_atomowo_nie_niszczy_ofiary(katalog_testowy, tmp_path):
    """manifest.json substituted as a symlink: the atomic write replaces the link,
        it does not write through it to the victim."""
    rozszerzony = katalog_testowy["lista"][1]  # manifest in the lfm25/q4-bl32 subdirectory
    katalog = tmp_path / "m"
    podkatalog = katalog / rozszerzony.katalog_rel
    podkatalog.mkdir(parents=True)
    ofiara = tmp_path / "ofiara.json"
    ofiara.write_bytes(b"{}")
    dowiazanie(podkatalog / "manifest.json", ofiara)
    lustro = _lustro(katalog_testowy, tmp_path)
    pakiety.instaluj_z_katalogu(rozszerzony, katalog, lustro)
    assert ofiara.read_bytes() == b"{}"
    assert pakiety.stan(rozszerzony, katalog) == "zainstalowany"


def test_pobierz_odrzucca_symlink_w_sciezce_podkatalogu(katalog_testowy, tmp_path):
    """Junction/symlink in a SUBDIRECTORY of the path (lfm25 -> anywhere) = refusal."""
    rozszerzony = katalog_testowy["lista"][1]
    katalog = tmp_path / "m"
    (katalog / "lfm25").mkdir(parents=True)
    obcy = tmp_path / "obcy"
    obcy.mkdir()
    dowiazanie(katalog / "lfm25" / "q4-bl32", obcy)
    klient = httpx.Client(transport=_transport(katalog_testowy["tresci"]))
    with pytest.raises(BladPakietu):
        pakiety.pobierz(rozszerzony, katalog, "http://x/", klient=klient)
    assert not (obcy / "model.onnx").exists()


def test_blad_pobierania_kontrolowany_bez_hasla_i_url(tmp_path, katalog_testowy):
    """A 503 from the mirror must not leak a URL with login:password into
        postep.blad (read by GET /api/pakiety)."""
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


# --- hard limits for download and background installation -------------------

def test_limit_czasu_z_env():
    assert pakiety.limit_czasu_domyslny({}) == 1800
    assert pakiety.limit_czasu_domyslny({"NIEWIDKA_PAKIETY_LIMIT_CZASU_S": "60"}) == 60
    with pytest.raises(ValueError):
        pakiety.limit_czasu_domyslny({"NIEWIDKA_PAKIETY_LIMIT_CZASU_S": "duzo"})


def test_pobierz_twardy_limit_bajtow(katalog_testowy, tmp_path):
    """The server declares 1 B but sends megabytes; the write must enforce
        the catalog size BEFORE every write."""
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
    """The limit also applies with Range: start + newly downloaded <= catalog size."""
    pakiet = katalog_testowy["lista"][0]
    plik = pakiet.pliki[0]
    calosc = katalog_testowy["tresci"][plik.zrodlo]
    katalog = tmp_path / "m"
    cel = katalog / plik.nazwa
    cel.parent.mkdir(parents=True)
    czesciowy = cel.with_name(cel.name + pakiety.CZESCIOWY)
    czesciowy.write_bytes(calosc[:-1])  # the last byte is missing

    def handler_dopisuje(request: httpx.Request) -> httpx.Response:
        # ignores Range, sends the last byte + 5 bytes too many
        return httpx.Response(206, content=calosc[-1:] + b"X" * 5,
                              headers={"content-range": f"bytes {len(calosc)-1}-/x"})

    klient = httpx.Client(transport=httpx.MockTransport(handler_dopisuje))
    with pytest.raises(BladPakietu, match="rozmiar"):
        pakiety.pobierz(pakiet, katalog, "http://x/", klient=klient)


def test_pobierz_calkowity_limit_czasu(katalog_testowy, tmp_path):
    """The read timeout applies to a chunk, not the whole transfer:
        a stream sending chunks more often than the timeout must still be cut off."""
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
    """Byte limit for offline installation: a source file larger than the weights
        catalog = refusal before copying (filling the disk via the IT mirror)."""
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
    """Offline installation goes to a background thread (does not block the API loop)
        with the same byte limit; cancelling ends the operation."""
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
    assert menedzer.postep.pakiet is None  # can be retried


# --- remembered state, background verification ---------------------------

def test_menedzer_lista_z_cache_bez_haszowania(menedzer, monkeypatch):
    """GET /api/pakiety hashed ~600 MB on EVERY request (0.43 s);
        UI polling could starve the whole API. The state must be remembered: computed
        at start and after a change, not on demand."""
    menedzer.czekaj()  # first recomputation in the background after start
    menedzer.pobierz("podstawowy")
    menedzer.czekaj()  # after an operation the state is fresh
    def boom(pakiet, katalog):
        raise AssertionError("stan() wywołany na żądanie (musi pochodzić z cache)")
    monkeypatch.setattr(pakiety, "stan", boom)
    wpisy = menedzer.lista()
    assert wpisy[0]["stan"] == "zainstalowany"
    assert menedzer.poziomy_dostepne() == [1, 2, 3]
    assert menedzer.brakujacy_wymagany() == []
    assert menedzer.stan_pakietu("podstawowy") == "zainstalowany"


def test_menedzer_zmiana_z_zewnatrz_odswiezana_w_tle(menedzer, katalog_testowy, tmp_path, monkeypatch):
    """IT drops weights into the directory from outside: a presence fingerprint (stat, no SHA)
        detects the change, lista() returns the remembered state, and a background thread computes hashes."""
    menedzer.czekaj()
    assert menedzer.lista()[0]["stan"] == "brak"
    for plik in menedzer._pakiety["podstawowy"].pliki:
        cel = tmp_path / "m" / plik.nazwa
        cel.parent.mkdir(parents=True, exist_ok=True)
        cel.write_bytes(katalog_testowy["tresci"][plik.zrodlo])
    # lista() returns the remembered state and triggers a background refresh (captured here)
    odpalone = []
    monkeypatch.setattr(menedzer, "odswiez_w_tle", lambda: odpalone.append(1))
    assert menedzer.lista()[0]["stan"] == "brak"
    assert odpalone == [1], "zmiana obecności plików ma odpalać odświeżenie w tle"


# --- redirects under control ----------------------------------

def _transport_przekierowanie(dokad, trafione: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        trafione.append(str(request.url))
        return httpx.Response(302, headers={"location": dokad})

    return httpx.MockTransport(handler)


@pytest.fixture()
def katalog_testowy_naglowkowy(katalog_testowy):
    """Content served after ONE redirect (the second handler returns the files)."""
    return katalog_testowy


def test_przekierowanie_do_loopback_odrzucone(katalog_testowy, tmp_path):
    """A hijacked mirror replies 302 to http://127.0.0.1:12345/private;
        the download must not make a blind request to a local service."""
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
    """The IT mirror (NIEWIDKA_MODELE_ZRODLO, also http and loopback) may redirect
        within its own host (e.g. python -m http.server on 127.0.0.1)."""
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
    """Public HTTPS outside the mirror is allowed (package CDN); a literal
        public IP, so the test does not depend on DNS."""
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


# --- a download error does not block a retry -----------------------

def test_blad_404_potem_poprawne_ponowienie(tmp_path, katalog_testowy):
    """After one mirror error the UI disabled the buttons for good
        (postep.pakiet stayed set). The operation state must be cleared on error too."""
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
    # mirror fixed: the retry works without a restart
    serwer_dziala["ok"] = True
    assert menedzer.pobierz("podstawowy") is True, "ponowienie po błędzie ma być możliwe"
    menedzer.czekaj()
    wpisy = {w["id"]: w for w in menedzer.lista()}
    assert wpisy["podstawowy"]["stan"] == "zainstalowany"


def test_oserror_przez_strumien_kontrolowany_i_do_ponowienia(tmp_path, katalog_testowy):
    """An OSError midway (disk full, device gone) must not leave the operation
        state set nor exit without a controlled message."""
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


def test_koniec_operacji_widoczny_dopiero_gdy_mozna_zaczac_nastepna():
    # postep.pakiet=None before releasing _w_toku ->
    # the UI started a second package ('Pobierz wszystko') and got 409
    import inspect

    from niewidka.pakiety import MenedzerPakietow

    zrodlo = inspect.getsource(MenedzerPakietow._uruchom_w_tle)
    assert zrodlo.index("self._w_toku = False") < zrodlo.index("self.postep.pakiet = None")


def test_katalog_podaje_pochodzenie_i_licencje_modeli():
    """Before downloading, the user sees the model address on Hugging Face and the licence type."""
    for pakiet in pakiety.wczytaj_pakiety():
        assert pakiet.model_hf and pakiet.model_hf.startswith("https://huggingface.co/")
        assert pakiet.licencja and pakiet.licencja_url and pakiet.licencja_uwagi
