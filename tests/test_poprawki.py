"""Poprawki w podglądzie: „Ukryj wszędzie” i „To nie dane”.

Atrapa detektora liczy wywołania: poprawka NIE może uruchamiać modelu ponownie.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import zipfile
from pathlib import Path

import httpx
import pytest

from narzedzia.generator_dokumentow import zapisz_podstawowy
from niewidka.api import create_app
from niewidka.detektory import RegulyDetektor
from niewidka.konfig import Konfig
from niewidka.model import TypEncji, Zakres
from niewidka.poprawki import BladPoprawki, PamiecWykryc, sprawdz_liste, znajdz_wystapienia
from niewidka.scalanie import scal

KLUCZ = bytes(range(32))
TEKST = (
    "Jan Nowak i Maria Lis spotkali Piotra Wronę. Lis poszedł dalej, a Lisa nie było. "
    "Listopad był zimny. Zapisano: 44051401359, biuro@firma-example.pl."
)


class DetektorZLicznikiem:
    """Reguły + wskazane frazy jako OSOBA; liczy wywołania `znajdz`."""

    nazwa = "atrapa-licznik"
    typy = frozenset({TypEncji.OSOBA})

    def __init__(self, frazy: tuple[str, ...] = ("Jan Nowak", "Maria Lis", "Piotr Wron")):
        self.frazy = frazy
        self.wywolania = 0
        self._reguly = RegulyDetektor()

    def znajdz(self, tekst: str) -> list[Zakres]:
        self.wywolania += 1
        wynik = list(self._reguly.znajdz(tekst))
        for fraza in self.frazy:
            start = tekst.find(fraza)
            while start != -1:
                wynik.append(Zakres(start, start + len(fraza), TypEncji.OSOBA, 0.99, self.nazwa))
                start = tekst.find(fraza, start + len(fraza))
        return scal(tekst, wynik)


@pytest.fixture()
def konfig(tmp_path):
    klucz = tmp_path / "klucz.b64"
    klucz.write_bytes(base64.b64encode(KLUCZ))
    klucz.chmod(0o600)
    return Konfig(klucz_plik=str(klucz), max_rozmiar_mb=1, mapy_katalog=tmp_path / "mapy")


def _klient(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{app.state.konfig.port}"
    )


def _naglowki(app) -> dict:
    return {"X-Niewidka-Token": app.state.token}


def _zip(dane: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(dane)) as paczka:
        return {nazwa: paczka.read(nazwa) for nazwa in paczka.namelist()}


def _tekst_wyniku(odpowiedz) -> str:
    czesci = _zip(odpowiedz.content)
    return next(v for k, v in czesci.items() if not k.endswith(".nwidka")).decode()


async def _ukryj(klient, app, tekst: str = TEKST):
    odpowiedz = await klient.post("/api/ukryj", data={"tekst": tekst, "poziom": "1"}, headers=_naglowki(app))
    assert odpowiedz.status_code == 200, odpowiedz.text
    return odpowiedz, odpowiedz.headers["x-niewidka-zadanie"]


async def _popraw(klient, app, zadanie: str, ukryj=(), nie_dane=(), zostaw=()):
    return await klient.post(
        "/api/popraw",
        json={"zadanie": zadanie, "ukryj": list(ukryj), "nie_dane": list(nie_dane), "zostaw": list(zostaw)},
        headers=_naglowki(app),
    )


# --- dopasowanie fragmentów -----------------------------------------------------


def test_granice_slow_lis_nie_rusza_listopada():
    tekst = "Lis i Lisa, Listopad, lisowaty. Lisem."
    znalezione = [tekst[s:k] for s, k in znajdz_wystapienia(tekst, "Lis")]
    assert znalezione == ["Lis", "Lisa", "Lisem"]


def test_odmiana_brzechwy_brzechwa():
    tekst = "Wiersze Brzechwy, z Brzechwą, o Brzechwie."
    znalezione = [tekst[s:k] for s, k in znajdz_wystapienia(tekst, "Brzechwa")]
    assert znalezione == ["Brzechwy", "Brzechwą", "Brzechwie"]


def test_fragment_wielowyrazowy_i_polskie_litery():
    tekst = "Anna Żółć-Nowak mieszka. Annę Żółć-Nowak znam."
    assert len(znajdz_wystapienia(tekst, "Anna  Żółć-Nowak")) == 2


def test_fragment_bez_slow_odrzucony():
    with pytest.raises(BladPoprawki):
        znajdz_wystapienia("tekst", " ,. ")


def test_limity_listy():
    assert sprawdz_liste("ukryj", ["  a  b ", "a b", ""]) == ["a b"]
    with pytest.raises(BladPoprawki):
        sprawdz_liste("ukryj", ["x"] * 201)
    with pytest.raises(BladPoprawki):
        sprawdz_liste("ukryj", ["x" * 201])
    with pytest.raises(BladPoprawki):
        sprawdz_liste("ukryj", "nie lista")


def test_pamiec_ogranicza_liczbe_zadan_i_czas():
    teraz = [0.0]
    pamiec = PamiecWykryc(maks=2, ttl_s=10, zegar=lambda: teraz[0])
    for nazwa in ("a", "b", "c"):
        pamiec.zapamietaj(nazwa, object())
    assert pamiec.pobierz("a") is None  # najstarsze wypadło
    assert pamiec.pobierz("c") is not None
    teraz[0] = 11.0
    assert pamiec.pobierz("c") is None


# --- API ------------------------------------------------------------------------


@pytest.mark.anyio
async def test_numeracja_stabilna_nowe_dostaja_kolejne(konfig):
    app = create_app(konfig, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        pierwsza, zadanie = await _ukryj(klient, app)
        baza = _tekst_wyniku(pierwsza)
        assert "[OSOBA_3" in baza and "[OSOBA_2" in baza
        odpowiedz = await _popraw(klient, app, zadanie, ukryj=["Dalej"], nie_dane=["OSOBA_2"])
    assert odpowiedz.status_code == 200, odpowiedz.text
    tekst = _tekst_wyniku(odpowiedz)
    assert "[OSOBA_1" in tekst and "[OSOBA_3" in tekst  # numery bez przesunięć
    assert "[OSOBA_2" not in tekst and "Maria Lis" in tekst  # zdjęta cała grupa
    assert "[INNE_1]" in tekst and "dalej" not in tekst
    assert json.loads(odpowiedz.headers["x-niewidka-wlasne"]) == {"INNE_1": 0}
    assert odpowiedz.headers["x-niewidka-identyfikator"] != zadanie  # nowa mapa
    assert odpowiedz.headers["x-niewidka-zadanie"] == zadanie  # poprawki dalej od bazy


@pytest.mark.anyio
async def test_ukryj_odmiana_i_granice_slow(konfig):
    detektor = DetektorZLicznikiem(frazy=())
    app = create_app(konfig, detektor=detektor)
    async with _klient(app) as klient:
        _, zadanie = await _ukryj(klient, app, "Lis spał. Lisa nie było. Listopad minął. Wiersze Brzechwy, z Brzechwą.")
        odpowiedz = await _popraw(klient, app, zadanie, ukryj=["Lis", "Brzechwa"])
        tekst = _tekst_wyniku(odpowiedz)
        assert "Listopad" in tekst
        assert "Lis " not in tekst and "Lisa" not in tekst and "Brzechwy" not in tekst and "Brzechwą" not in tekst
        # przywrócenie zwraca oryginalne odmiany
        czesci = _zip(odpowiedz.content)
        mapa = next(v for k, v in czesci.items() if k.endswith(".nwidka"))
        przywroc = await klient.post(
            "/api/przywroc",
            data={"tekst": tekst},
            files={"mapa": ("m.nwidka", mapa)},
            headers=_naglowki(app),
        )
        assert "Brzechwy" in przywroc.text and "Brzechwą" in przywroc.text and "Lisa nie było" in przywroc.text


@pytest.mark.anyio
async def test_nie_dane_dla_typu_z_suma_to_422(konfig):
    app = create_app(konfig, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        _, zadanie = await _ukryj(klient, app)
        odpowiedz = await _popraw(klient, app, zadanie, nie_dane=["PESEL_1"])
    assert odpowiedz.status_code == 422
    assert "44051401359" not in odpowiedz.text


@pytest.mark.anyio
async def test_nieznany_znacznik_i_zle_listy_to_422(konfig):
    app = create_app(konfig, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        _, zadanie = await _ukryj(klient, app)
        assert (await _popraw(klient, app, zadanie, nie_dane=["OSOBA_99"])).status_code == 422
        assert (await _popraw(klient, app, zadanie, ukryj=["x"] * 201)).status_code == 422
        assert (await _popraw(klient, app, zadanie, ukryj=["x" * 201])).status_code == 422


@pytest.mark.anyio
async def test_ukryj_wygrywa_z_nie_dane(konfig):
    app = create_app(konfig, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        _, zadanie = await _ukryj(klient, app)
        odpowiedz = await _popraw(klient, app, zadanie, ukryj=["Nowak"], nie_dane=["OSOBA_1"])
    tekst = _tekst_wyniku(odpowiedz)
    assert "[OSOBA_1" in tekst and "Nowak" not in tekst


@pytest.mark.anyio
async def test_kontrola_nie_dokleja_zdjetego_z_powrotem(konfig):
    """E-mail zdjęty przez użytkownika zostaje jawny, a kontrola regułowa nie blokuje wyniku."""
    app = create_app(konfig, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        _, zadanie = await _ukryj(klient, app)
        odpowiedz = await _popraw(klient, app, zadanie, nie_dane=["EMAIL_1"])
    assert odpowiedz.status_code == 200, odpowiedz.text
    assert "biuro@firma-example.pl" in _tekst_wyniku(odpowiedz)
    assert odpowiedz.headers["x-niewidka-status"] == "ukonczony"


@pytest.mark.anyio
async def test_wygasniecie_pamieci_to_410(konfig):
    app = create_app(konfig, detektor=DetektorZLicznikiem())
    teraz = [1000.0]
    app.state.poprawki.zegar = lambda: teraz[0]
    async with _klient(app) as klient:
        _, zadanie = await _ukryj(klient, app)
        assert (await _popraw(klient, app, zadanie, ukryj=["Dalej"])).status_code == 200
        teraz[0] += konfig.poprawki_ttl_s + 1
        odpowiedz = await _popraw(klient, app, zadanie, ukryj=["Dalej"])
        nieznane = await _popraw(klient, app, "0" * 32, ukryj=["Dalej"])
    assert odpowiedz.status_code == 410 and "Ukryj dokument ponownie" in odpowiedz.json()["blad"]
    assert nieznane.status_code == 410


@pytest.mark.anyio
async def test_model_nie_jest_wolany_przy_poprawce(konfig):
    detektor = DetektorZLicznikiem()
    app = create_app(konfig, detektor=detektor)
    async with _klient(app) as klient:
        _, zadanie = await _ukryj(klient, app)
        po_ukryciu = detektor.wywolania
        assert po_ukryciu > 0
        for _ in range(3):
            assert (await _popraw(klient, app, zadanie, ukryj=["Dalej"], nie_dane=["OSOBA_2"])).status_code == 200
    assert detektor.wywolania == po_ukryciu


@pytest.mark.anyio
async def test_brak_tresci_w_dzienniku_i_logach(konfig, caplog):
    caplog.set_level(logging.DEBUG)
    app = create_app(konfig, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        _, zadanie = await _ukryj(klient, app)
        odpowiedz = await _popraw(klient, app, zadanie, ukryj=["Dalej"], nie_dane=["OSOBA_2"])
        zle = await _popraw(klient, app, zadanie, ukryj=["Tajne słowo"], nie_dane=["PESEL_1"])
    assert odpowiedz.status_code == 200 and zle.status_code == 422
    dziennik = (konfig.mapy_katalog / "dziennik.jsonl").read_text(encoding="utf-8")
    zdarzenia = [json.loads(w) for w in dziennik.splitlines()]
    poprawiono = [z for z in zdarzenia if z["zdarzenie"] == "poprawiono"]
    assert len(poprawiono) == 1
    assert poprawiono[0]["statystyki"] == {"ukryj": 1, "nie_dane": 1, "zostaw": 0, "na_inne": 0, "odkryj": 0}
    for tajemnica in ("Dalej", "dalej", "Tajne", "Maria", "Nowak", "44051401359", "firma-example"):
        assert tajemnica not in dziennik
        assert tajemnica not in caplog.text


# --- blokada kontroli: miejsca do decyzji ----------------------------------------


def _docx_z_nazwiskiem_w_czesci() -> bytes:
    """DOCX, w którym nazwisko z treści siedzi też w części, której adapter nie czyta."""
    zrodlo = zapisz_podstawowy(Path("/tmp") / "niewidka-popr-wzorzec.docx").read_bytes()
    wejscie = zipfile.ZipFile(io.BytesIO(zrodlo))
    czesci = {n: wejscie.read(n) for n in wejscie.namelist()}
    czesci["word/theme/proba.xml"] = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">Anna Nowak</theme>'
    )
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as paczka:
        for nazwa, tresc in czesci.items():
            paczka.writestr(nazwa, tresc)
    return bufor.getvalue()


@pytest.mark.anyio
async def test_blokada_niesie_miejsca_i_zostaw_ja_zdejmuje(konfig):
    app = create_app(konfig, detektor=DetektorZLicznikiem(frazy=("Anna Nowak",)))
    async with _klient(app) as klient:
        blokada = await klient.post(
            "/api/ukryj",
            data={"poziom": "1"},
            files={"plik": ("umowa.docx", _docx_z_nazwiskiem_w_czesci())},
            headers=_naglowki(app),
        )
        assert blokada.status_code == 422
        tresc = blokada.json()
        assert tresc["status"] == "zablokowany" and tresc["zadanie"]
        assert any(m["fragment"] == "Anna Nowak" for m in tresc["miejsca"])
        # bez decyzji nadal blokada, z decyzją „To nie dane” wynik wychodzi
        nadal = await _popraw(klient, app, tresc["zadanie"], ukryj=["Dokument"])
        assert nadal.status_code == 422
        odpowiedz = await _popraw(klient, app, tresc["zadanie"], zostaw=["Anna Nowak"])
    assert odpowiedz.status_code == 200, odpowiedz.text


class DetektorUparty(DetektorZLicznikiem):
    """Kontrola widzi „Wczoraj ... spał” na tekście z zamaskowanym znacznikiem; fragment
    zawiera spacje po znaczniku, więc nie da się go znaleźć w oryginale i blokada zostaje."""

    def znajdz(self, tekst):
        wynik = super().znajdz(tekst)
        dopasowanie = re.search(r"Wczoraj {5,}spał", tekst)
        if dopasowanie:
            wynik.append(Zakres(dopasowanie.start(), dopasowanie.end(), TypEncji.OSOBA, 0.9, self.nazwa))
        return scal(tekst, wynik)


@pytest.mark.anyio
async def test_blokada_tekstowa_zawiera_podglad_i_pozycje_potem_decyzja(konfig):
    app = create_app(konfig, detektor=DetektorUparty(frazy=("Jan Nowak",)))
    async with _klient(app) as klient:
        odpowiedz = await klient.post(
            "/api/ukryj", data={"tekst": "Wczoraj Jan Nowak spał."}, headers=_naglowki(app)
        )
        assert odpowiedz.status_code == 422, odpowiedz.text
        tresc = odpowiedz.json()
        miejsce = tresc["miejsca"][0]
        assert tresc["podglad"].startswith("ZANONIMIZOWANY.")
        # pozycja wskazuje początek fragmentu w podglądzie (tam zaczyna się „Wczoraj”)
        assert tresc["podglad"][miejsce["pozycja"] :].startswith("Wczoraj")
        # miejsce wątpliwe z modelu przeżywa poprawkę niezwiązaną z nim (decyzja nadal wymagana)
        nadal = await _popraw(klient, app, tresc["zadanie"], ukryj=["Nic"])
        assert nadal.status_code == 422
        # „To nie dane” dla tego miejsca zwalnia wynik
        gotowe = await _popraw(klient, app, tresc["zadanie"], zostaw=[miejsce["fragment"]])
    assert gotowe.status_code == 200, gotowe.text


# --- interfejs (statycznie; zachowanie sprawdza testy_e2e/gui_poprawki.py) ----------

_WEB = Path(__file__).parents[1] / "niewidka" / "web"


def test_ui_jak_to_dziala_bez_pauz_i_z_dwoma_modelami():
    html = (_WEB / "index.html").read_text(encoding="utf-8")
    opis = " ".join(html[html.index('id="jak-to-dziala"') : html.index('id="status-ukryj"')].split())
    assert "–" not in opis and "—" not in opis  # zakaz półpauz i pauz
    assert "dwa modele językowe" in opis and not re.search(r"\btrzy\b", opis.lower())
    assert "Słownik imion z danych GUS" in opis
    assert "próbkę kontrolną" in opis and "Poprzednia wersja zostaje" in opis
    assert "miejsca" in opis and "To nie dane" in opis  # punkt o ponownym sprawdzeniu


def test_ui_dostepnosc_poprawek():
    html = (_WEB / "index.html").read_text(encoding="utf-8")
    js = (_WEB / "apka.js").read_text(encoding="utf-8")
    assert 'id="komunikat-poprawek" class="komunikat-poprawek" aria-live="polite"' in html
    assert 'id="ukryj-zaznaczone"' in html and 'id="pole-ukryj-wszedzie"' in html  # klawiatura
    assert 'document.createElement("button")' in js and "zaslepka-przycisk" in js  # plakietki jako przyciski
    assert "Tekst się zmienił. Skopiuj go ponownie." in js
    assert "if (mojaKolejna !== licznikZlecen) return;" in js  # odpowiedzi starszych żądań ignorowane
    assert '"PESEL", "NIP", "REGON", "IBAN", "KARTA", "DOKUMENT"' in js  # bez „To nie dane” dla sum


@pytest.mark.anyio
async def test_na_inne_zmienia_rodzaj_bez_przenumerowania(konfig):
    app = create_app(konfig, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        _, zadanie = await _ukryj(klient, app)
        odpowiedz = await klient.post(
            "/api/popraw", json={"zadanie": zadanie, "na_inne": ["OSOBA_2"]}, headers=_naglowki(app)
        )
        assert odpowiedz.status_code == 200, odpowiedz.text
        tekst = _tekst_wyniku(odpowiedz)
        assert "[OSOBA_2" not in tekst and "[INNE_1" in tekst  # cała grupa Marii Lis, z formami
        assert "[OSOBA_1" in tekst and "[OSOBA_3" in tekst  # pozostałe numery bez zmian
        assert "Maria Lis" not in tekst
        pesel = await klient.post(
            "/api/popraw", json={"zadanie": zadanie, "na_inne": ["PESEL_1"]}, headers=_naglowki(app)
        )
        assert pesel.status_code == 422
