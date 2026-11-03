"""Local web tests: page served by api.py, token in the content.

The page has the session token in meta; resources (apka.js, styl.css, fonts) are local only:
nothing reaches the network, because the tool must run on a computer without internet.
"""

from __future__ import annotations

import re

import httpx
import pytest

from niewidka.api import create_app
from niewidka.detektory import RegulyDetektor
from niewidka.konfig import Konfig

KLUCZ = bytes(range(32))


@pytest.fixture()
def konfig(tmp_path):
    plik = tmp_path / "klucz.b64"
    import base64

    plik.write_bytes(base64.b64encode(KLUCZ))
    plik.chmod(0o600)
    return Konfig(klucz_plik=str(plik))


@pytest.fixture()
def app(konfig):
    return create_app(konfig, detektor=RegulyDetektor())


@pytest.fixture()
async def klient(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{app.state.konfig.port}"
    ) as klient:
        yield klient


@pytest.mark.anyio
async def test_strona_glowna_serwuje_html_z_tokenem(klient, app):
    odpowiedz = await klient.get("/")
    assert odpowiedz.status_code == 200
    assert "text/html" in odpowiedz.headers["content-type"]
    assert 'lang="pl"' in odpowiedz.text
    meta = re.search(r'<meta name="niewidka-token" content="([^"]*)"', odpowiedz.text)
    assert meta, "strona musi mieć meta niewidka-token"
    assert meta.group(1) == app.state.token


@pytest.mark.anyio
async def test_token_nie_leci_url_i_zasobami(klient, app):
    strona = (await klient.get("/")).text
    assert "token=" not in strona.lower().replace("niewidka-token", "")
    apka = (await klient.get("/apka.js")).text
    styl = (await klient.get("/styl.css")).text
    assert app.state.token not in apka
    assert app.state.token not in styl
    # resources referenced relatively: requests go to the same server, never to the internet
    for sciezka in (strona, apka, styl):
        for wzorzec in (r'(src|href)\s*=\s*["\']https?://', r'url\(\s*["\']?https?://', r'@import\s+https?:'):
            assert not re.search(wzorzec, sciezka), f"zewnętrzny zasób w pliku web: {wzorzec}"


@pytest.mark.anyio
async def test_zasoby_statyczne_serwowane(klient):
    apka = await klient.get("/apka.js")
    styl = await klient.get("/styl.css")
    assert apka.status_code == 200
    assert "javascript" in apka.headers["content-type"] or apka.text.lstrip().startswith(("/*", "//", '"use strict"'))
    assert styl.status_code == 200
    assert "css" in styl.headers["content-type"]


@pytest.mark.anyio
async def test_strona_bez_tokenu_dostepna_i_bez_cache(klient):
    odpowiedz = await klient.get("/")
    assert odpowiedz.status_code == 200
    assert odpowiedz.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_fonty_lokalne_w_katalogu_web(klient):
    """The font is in the repo (offline, no CDN); its request hits our server."""
    fonty = re.findall(r'@font-face\s*{[^}]*url\(["\']?([^)"\']+)', styl := (await klient.get("/styl.css")).text)
    assert fonty, "styl.css ma ładować font z katalogu web"
    for sciezka in fonty:
        assert sciezka.startswith("/") or not sciezka.startswith("http")
        odpowiedz = await klient.get(sciezka if sciezka.startswith("/") else f"/{sciezka}")
        assert odpowiedz.status_code == 200, f"brak fonta: {sciezka}"
    assert "font-family" in styl


@pytest.mark.anyio
async def test_strona_mieci_elementy_funkcjonalne(klient):
    strona = (await klient.get("/")).text
    for wyraz in (
        "Ukryj dane",
        "Przywróć dane",
        "Na tym urządzeniu",
        "Jakość wykrywania",
        "Szybko",
        "Najdokładniej",
        "aria-live",
        "mapa",
    ):
        assert wyraz in strona, f"brak na stronie: {wyraz}"


@pytest.mark.anyio
async def test_api_trasy_priorytet_przed_statycznymi(klient, app):
    """/api/stan guards the token (like POSTs); the UI sends it in meta."""
    odpowiedz = await klient.get("/api/stan", headers={"X-Niewidka-Token": app.state.token})
    assert odpowiedz.status_code == 200
    assert odpowiedz.json()["wersja"]


@pytest.mark.anyio
async def test_bez_polpauz_i_pauz_w_tekstach(klient):
    """Zero en/em dashes in texts
        visible to the user: the page, the script and the note in result files."""
    from niewidka.znaczniki import DOPISEK, dopisek

    for nazwa, tresc in (
        ("index.html", (await klient.get("/")).text),
        ("apka.js", (await klient.get("/apka.js")).text),
        ("dopisek", DOPISEK),
        ("dopisek z identyfikatorem", dopisek("abcdef")),
    ):
        for znak in ("–", "—"):
            assert znak not in tresc, f"zakazany znak {znak!r} w {nazwa}"


@pytest.mark.anyio
async def test_podglad_zwija_dopisek_a_ryzyko_przychodzi_z_serwera(klient):
    """The note with the map identifier collapses in the preview to
        'ZANONIMIZOWANY. ...' (the full one stays in the result file); risk labels
        (including the small-sample threshold) are supplied by the server as ready text."""
    apka = (await klient.get("/apka.js")).text
    assert "ZANONIMIZOWANY. …" in apka, "podgląd ma pokazywać skrócony dopisek"
    assert 'createElement("details")' in apka, "rozwinięcie dopisku ma być natywne"
    assert "podwyższone" not in apka, "etykieta ryzyka pochodzi z serwera (jakosc.py)"


@pytest.mark.anyio
async def test_pakiety_elementy_funkcjonalne(klient):
    """First-run screen (3 options) and Ustawienia with packages."""
    strona = (await klient.get("/")).text
    apka = (await klient.get("/apka.js")).text
    for wyraz in (
        "Przygotowanie do pracy",
        "Pobierz podstawowy (zalecane)",
        "Później",
        "Ustawienia",
        "Pakiet podstawowy wystarcza",
    ):
        assert wyraz in strona, f"brak na stronie: {wyraz}"
    # the third tab leads to the settings panel
    assert 'aria-controls="panel-ustawienia"' in strona
    assert 'id="lista-pakietow"' in strona
    # the script polls the package state and shows the screen when a required one is missing
    assert '"/api/pakiety"' in apka
    assert "ekran-pakietow" in apka and "poziomy_dostepne" in apka
    assert "Pobierz pakiet podstawowy w Ustawieniach" in apka  # slider hint


@pytest.mark.anyio
async def test_gety_pakietow_i_stanu_wysylaja_token(klient):
    """GET /api/pakiety and /api/stan require a token, so the UI
        MUST send session headers in these polls too (not only in POSTs)."""
    apka = (await klient.get("/apka.js")).text
    assert 'pobierzJson("/api/pakiety")' in apka
    assert 'pobierzJson("/api/stan")' in apka
    assert "headers: { ...NAGLOWKI, ...(opcje.headers || {}) }" in apka, "wspólne żądanie zawsze niesie token"


@pytest.mark.anyio
async def test_ui_ponawia_pobieranie_po_bledzie(klient):
    """After a download error the buttons must come back (they are driven
        by the postep.pakiet state from the API) and the error message must be visible."""
    apka = (await klient.get("/apka.js")).text
    assert "przycisk.disabled = stanPakietow.postep.pakiet !== null" in apka, (
        "przyciski pobierania mają zależeć od aktualnego stanu operacji (po błędzie: włączone)"
    )
    assert "`Nie udało się: ${blad}`" in apka, "błąd pobierania ma być pokazany użytkownikowi"


@pytest.mark.anyio
async def test_ui_instaluje_pakiet_z_folderu(klient):
    html = (await klient.get("/")).text
    apka = (await klient.get("/apka.js")).text
    assert 'id="pakiety-folder"' in html
    assert 'akcjaPakietu("instaluj", identyfikator, folder)' in apka
    assert 'akcja === "pobierz" || akcja === "instaluj"' in apka, "instalacja ma odpytywać postęp"


@pytest.mark.anyio
async def test_kontrola_jakosci_tekst_uczciwy(klient):
    """A result with an undetected SWIFT and login
        announced 'no personal data found'. Honestly: the program did not
        find data it CAN detect, and the user should review the result."""
    apka = (await klient.get("/apka.js")).text
    assert "nie znalazło żadnych danych osobowych" not in apka, (
        "stare kłamliwe sformułowanie ma zniknąć"
    )
    assert "nie znalazło danych, które program umie wykrywać" in apka


# --- map store: Przywroc tab, result screen, Ustawienia ------------------


@pytest.mark.anyio
async def test_przywroc_ma_tryb_wklejenia_i_liste_zadan(klient):
    """By default pasting the AI reply with a job choice;
        the map file is an option revealed by a button."""
    strona = (await klient.get("/")).text
    apka = (await klient.get("/apka.js")).text
    assert "Wklej odpowiedź z czatu AI" in strona, "tryb domyślny zakładki Przywróć"
    assert 'id="tekst-przywroc"' in strona, "pole na wklejoną odpowiedź"
    assert 'id="lista-zadan"' in strona, "lista wyboru Zadanie"
    assert "Mam plik mapy (.nwidka)" in strona, "opcja odsłaniająca pole pliku mapy"
    assert 'id="plik-mapa-tekst"' in strona, "pole pliku mapy w trybie wklejenia"
    assert 'pobierzJson("/api/mapy")' in apka, "lista zadań z API, za tokenem"


@pytest.mark.anyio
async def test_wynik_ukrywania_mowi_o_zapisanej_mapie(klient):
    """The user does not have to download a file; the program saves the map on this computer."""
    apka = (await klient.get("/apka.js")).text
    strona = (await klient.get("/")).text
    assert 'id="mapa-zapisana"' in strona
    assert "Mapa zapisana na tym komputerze do" in apka
    assert "Bez mapy nie przywrócisz danych." in apka
    assert 'get("x-niewidka-mapa-zapisana")' in apka, "zdanie tylko gdy mapa faktycznie zapisana"


@pytest.mark.anyio
async def test_ustawienia_zapisane_mapy_z_usuwaniem(klient):
    """List of saved maps in Ustawienia, Usun on each, Usun wszystkie
        with confirmation, a sentence about the retention period."""
    strona = (await klient.get("/")).text
    apka = (await klient.get("/apka.js")).text
    assert "Zapisane mapy" in strona
    assert 'id="lista-map-zapisanych"' in strona
    assert 'id="usun-wszystkie-mapy"' in strona
    assert "Mapy są usuwane automatycznie po" in apka
    assert "Okres ustawia administrator." in apka
    assert "Mapy nie są zapisywane automatycznie. Pobierz mapę po każdym ukryciu." in apka
    # deletion: single and all, both through the API and behind the token
    assert "/api/mapy/${" in apka, "Usuń pojedynczej mapy przez API"
    assert '"DELETE"' in apka and '"/api/mapy"' in apka, "Usuń wszystkie przez API"
    assert "confirm(" in apka, "Usuń wszystkie ma potwierdzenie"


@pytest.mark.anyio
async def test_wybierz_mape_prowadzi_do_listy_zadan(klient):
    """A 422 with the wybierz_mape code does not become a generic error; the interface
        shows the message, selects the best-matching job and leads to the job list."""
    apka = (await klient.get("/apka.js")).text
    assert 'wybierz_mape' in apka
    assert "Zaznaczyłem zadanie, które najlepiej pasuje do znaczników. " in apka
    assert "kandydaci" in apka and 'lista-zadan' in apka, "po komunikacie fokus/akcja na liście zadań"
    # a suggested job never silently applies to another reply, and the list resets after a restore
    assert "lista.dataset.propozycja = \"1\";" in apka and 'listaPo.value = "";' in apka


@pytest.mark.anyio
async def test_przywrocony_tekst_w_podgladzie_z_kopiowaniem(klient):
    """The result of restoring pasted text is visible in the preview with Kopiuj;
        for a file the download remains."""
    strona = (await klient.get("/")).text
    apka = (await klient.get("/apka.js")).text
    assert 'id="blok-podglad-przywroc"' in strona
    assert 'id="kopiuj-przywrocony"' in strona
    assert 'id="podglad-przywroconego"' in strona
    assert "tekstPrzywroconego" in apka, "surowy tekst pod podglądem do kopiowania"
    assert 'id="pobierz-przywrocony"' in strona, "pobranie zostaje (plik i tekst)"


@pytest.mark.anyio
async def test_mapa_niezapisana_i_licznik_zlecen(klient):
    """A map save error = result issued with the header 'blad' and
        the message 'Pobierz mape'; responses to older requests are discarded."""
    apka = (await klient.get("/apka.js")).text
    assert "Pobierz mapę, bo nie została zapisana." in apka
    assert '"blad"' in apka or "'blad'" in apka
    assert "licznikZlecen" not in apka, "wspólny licznik unieważniał niezależne formularze"
    assert "mojaKolejna !== licznikWyniku" in apka, "spóźniona odpowiedź nie renderuje się"
    assert "mojaKolejna !== licznikPrzywracania" in apka
    assert "if (mojaKolejna === licznikWyniku) ustawTrwa" not in apka, "przycisk odblokowuje się zawsze"
    assert "if (mojaKolejna === licznikPrzywracania) ustawTrwa" not in apka


@pytest.mark.anyio
async def test_ui_nie_koduje_json_dwa_razy(klient):
    apka = (await klient.get("/apka.js")).text
    assert not re.search(r"wyslij\([^)]*JSON\.stringify", apka), "wyslij() sam zamienia obiekt na JSON"
