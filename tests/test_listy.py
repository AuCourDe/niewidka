"""Listy stałe „Zawsze ukrywaj” / „Nigdy nie ukrywaj” (niewidka/listy.py, decyzja 1a 2026-10-29)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from niewidka.api import create_app
from niewidka.listy import ListyStale
from niewidka.poprawki import BladPoprawki
from tests.test_poprawki import (
    TEKST,
    DetektorZLicznikiem,
    _klient,
    _naglowki,
    _popraw,
    _tekst_wyniku,
    _ukryj,
    konfig,  # noqa: F401 — fixture
)


@pytest.fixture()
def konfig_list(konfig, tmp_path):  # noqa: F811
    return replace(konfig, listy_plik=tmp_path / "listy.json")


def test_walidacja_list(tmp_path):
    listy = ListyStale(tmp_path / "l.json")
    with pytest.raises(BladPoprawki):
        listy.zapisz(["Lis"], ["Lis"])  # ta sama pozycja na obu
    with pytest.raises(BladPoprawki):
        listy.zapisz([], ["44051401359"])  # PESEL nie może być „nigdy”
    assert listy.zapisz([" Zielony  Dąb "], ["Listopad"]).zawsze == ["Zielony Dąb"]
    assert listy.uzytkownika().nigdy == ["Listopad"]


def test_administrator_wygrywa_i_blokuje_edycje(tmp_path):
    plik = tmp_path / "l.json"
    plik.write_text(json.dumps({"zawsze": ["Lis"], "nigdy": ["Kowal"]}), encoding="utf-8")
    listy = ListyStale(plik, admin_nigdy=("Lis",), tylko_administrator=True)
    razem = listy.razem()
    assert razem.nigdy == ["Lis", "Kowal"] and razem.zawsze == []
    with pytest.raises(PermissionError):
        listy.zapisz([], [])


def test_uszkodzony_plik_nie_blokuje(tmp_path):
    plik = tmp_path / "l.json"
    plik.write_text("{to nie json", encoding="utf-8")
    assert ListyStale(plik, admin_zawsze=("Lis",)).razem().zawsze == ["Lis"]


@pytest.mark.anyio
async def test_listy_dzialaja_przy_ukryciu_i_poprawce(konfig_list):
    app = create_app(konfig_list, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        zapis = await klient.put(
            "/api/listy", json={"zawsze": ["zimny"], "nigdy": ["Maria Lis"]}, headers=_naglowki(app)
        )
        assert zapis.status_code == 200, zapis.text
        odpowiedz, zadanie = await _ukryj(klient, app)
        tekst = _tekst_wyniku(odpowiedz)
        assert "zimny" not in tekst and "[INNE_1]" in tekst  # zawsze ukrywaj, typ INNE
        assert "Maria Lis" in tekst  # nigdy nie ukrywaj zdejmuje osobę
        assert "44051401359" not in tekst
        assert json.loads(odpowiedz.headers["x-niewidka-z-listy"]) == {"INNE_1": "zimny"}
        # poprawka użytkownika: listy dalej obowiązują, a numery własnych liczą się od zera
        poprawka = await _popraw(klient, app, zadanie, ukryj=["dalej"])
        tekst = _tekst_wyniku(poprawka)
        assert "zimny" not in tekst and "Maria Lis" in tekst and "dalej" not in tekst
        assert json.loads(poprawka.headers["x-niewidka-wlasne"]) == {"INNE_2": 0}
        # jawne „Ukryj wszędzie” wygrywa z listą „Nigdy”
        poprawka = await _popraw(klient, app, zadanie, ukryj=["Maria Lis"])
        assert "Maria Lis" not in _tekst_wyniku(poprawka)


@pytest.mark.anyio
async def test_put_listy_wymaga_tokenu_i_waliduje(konfig_list):
    app = create_app(konfig_list, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        bez_tokenu = await klient.put("/api/listy", json={"zawsze": [], "nigdy": []})
        assert bez_tokenu.status_code == 403
        pesel = await klient.put(
            "/api/listy", json={"zawsze": [], "nigdy": ["44051401359"]}, headers=_naglowki(app)
        )
        assert pesel.status_code == 422 and "44051401359" not in pesel.text
        odczyt = await klient.get("/api/listy", headers=_naglowki(app))
        assert odczyt.json()["zawsze"] == [] and odczyt.json()["tylko_administrator"] is False


@pytest.mark.anyio
async def test_lista_administratora_tylko_do_odczytu(konfig_list):
    admin = replace(konfig_list, listy_zawsze=("zimny",), listy_tylko_administrator=True)
    app = create_app(admin, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        zapis = await klient.put(
            "/api/listy", json={"zawsze": [], "nigdy": []}, headers=_naglowki(app)
        )
        assert zapis.status_code == 403
        odpowiedz, _ = await _ukryj(klient, app, TEKST)
        assert "zimny" not in _tekst_wyniku(odpowiedz)


@pytest.mark.anyio
async def test_odkryj_pozycje_listy_tylko_w_tym_dokumencie(konfig_list):
    app = create_app(konfig_list, detektor=DetektorZLicznikiem())
    async with _klient(app) as klient:
        await klient.put("/api/listy", json={"zawsze": ["zimny"], "nigdy": []}, headers=_naglowki(app))
        _, zadanie = await _ukryj(klient, app)
        odpowiedz = await klient.post(
            "/api/popraw", json={"zadanie": zadanie, "odkryj": ["zimny"]}, headers=_naglowki(app)
        )
        assert "zimny" in _tekst_wyniku(odpowiedz)
        assert "x-niewidka-z-listy" not in odpowiedz.headers
        # lista stała bez zmian: kolejne ukrycie dalej ukrywa
        ponownie, _ = await _ukryj(klient, app)
        assert "zimny" not in _tekst_wyniku(ponownie)
