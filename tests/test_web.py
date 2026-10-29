"""Testy webu lokalnego (K5, LLD §13): strona serwowana przez api.py, token w treści.

Strona z tokenem sesji w meta, zasoby (apka.js, styl.css, fonty) wyłącznie lokalne —
nic nie sięga po sieć, bo narzędzie ma działać na komputerze bez internetu.
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
    # zasoby referowane względnie — żądania idą na ten sam serwer, nigdy do internetu
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
    """Font wchodzi w repo (offline, bez CDN); żądanie o niego trafia w nasz serwer."""
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
    """K7c pkt 5: /api/stan pilnuje tokenu (jak POST-y); UI wysyła go w meta."""
    odpowiedz = await klient.get("/api/stan", headers={"X-Niewidka-Token": app.state.token})
    assert odpowiedz.status_code == 200
    assert odpowiedz.json()["wersja"]


@pytest.mark.anyio
async def test_bez_polpauz_i_pauz_w_tekstach(klient):
    """Zlecenie właściciela (12:55 / K5b): zero półpauz i pauz (– —) w tekstach
    widocznych dla użytkownika: strona, skrypt i dopisek w plikach wynikowych."""
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
    """K5c: dopisek z identyfikatorem mapy zwija się w podglądzie do
    „ZANONIMIZOWANY. …" (pełny zostaje w pliku wynikowym); etykiety ryzyka
    (w tym próg małej próby) podaje serwer w gotowym tekście."""
    apka = (await klient.get("/apka.js")).text
    assert "ZANONIMIZOWANY. …" in apka, "podgląd ma pokazywać skrócony dopisek"
    assert 'createElement("details")' in apka, "rozwinięcie dopisku ma być natywne"
    assert "podwyższone" not in apka, "etykieta ryzyka pochodzi z serwera (jakosc.py)"


@pytest.mark.anyio
async def test_pakiety_elementy_funkcjonalne(klient):
    """K7b: ekran pierwszego uruchomienia (3 opcje) i Ustawienia z pakietami."""
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
    # trzecia zakładka prowadzi do panelu ustawień
    assert 'aria-controls="panel-ustawienia"' in strona
    assert 'id="lista-pakietow"' in strona
    # skrypt odpytuje stan pakietów i pokaże ekran przy braku wymaganego
    assert '"/api/pakiety"' in apka
    assert "ekran-pakietow" in apka and "poziomy_dostepne" in apka
    assert "Pobierz pakiet podstawowy w Ustawieniach" in apka  # podpowiedź suwaka


@pytest.mark.anyio
async def test_gety_pakietow_i_stanu_wysylaja_token(klient):
    """K7c pkt 5 (audyt): GET /api/pakiety i /api/stan wymagają tokenu, więc UI
    MUSI wysyłać nagłówki sesji też w tych odpytaniach (nie tylko w POST-ach)."""
    apka = (await klient.get("/apka.js")).text
    assert 'fetch("/api/pakiety", { headers: NAGLOWKI })' in apka
    assert 'fetch("/api/stan", { headers: NAGLOWKI })' in apka


@pytest.mark.anyio
async def test_ui_ponawia_pobieranie_po_bledzie(klient):
    """K7c pkt 11 (audyt): po błędzie pobierania przyciski mają wracać (sterują
    nimi stan postep.pakiet z API) i komunikat błędu ma być widoczny."""
    apka = (await klient.get("/apka.js")).text
    assert "przycisk.disabled = stanPakietow.postep.pakiet !== null" in apka, (
        "przyciski pobierania mają zależeć od aktualnego stanu operacji (po błędzie: włączone)"
    )
    assert "Nie udało się pobrać pakietu" in apka, "błąd pobierania ma być pokazany użytkownikowi"


@pytest.mark.anyio
async def test_kontrola_jakosci_tekst_uczciwy(klient):
    """K7c pkt 12 (obserwacja orkiestratora): wynik z niewykrytym SWIFT i loginem
    ogłaszał «nie znalazło żadnych danych osobowych». Uczciwie: program nie
    znalazł danych, które UMIE wykrywać, a użytkownik ma przejrzeć wynik."""
    apka = (await klient.get("/apka.js")).text
    assert "nie znalazło żadnych danych osobowych" not in apka, (
        "stare kłamliwe sformułowanie ma zniknąć"
    )
    assert "nie znalazło danych, które program umie wykrywać" in apka


# --- magazyn map: zakładka Przywróć, ekran wyniku, Ustawienia ------------------


@pytest.mark.anyio
async def test_przywroc_ma_tryb_wklejenia_i_liste_zadan(klient):
    """docs/MAPY-I-AKTUALIZACJE.md §1: domyślnie wklejanie odpowiedzi AI z wyborem
    zadania; plik mapy to opcja odsłaniana przyciskiem."""
    strona = (await klient.get("/")).text
    apka = (await klient.get("/apka.js")).text
    assert "Wklej odpowiedź z czatu AI" in strona, "tryb domyślny zakładki Przywróć"
    assert 'id="tekst-przywroc"' in strona, "pole na wklejoną odpowiedź"
    assert 'id="lista-zadan"' in strona, "lista wyboru Zadanie"
    assert "Mam plik mapy (.nwidka)" in strona, "opcja odsłaniająca pole pliku mapy"
    assert 'id="plik-mapa-tekst"' in strona, "pole pliku mapy w trybie wklejenia"
    assert 'fetch("/api/mapy", { headers: NAGLOWKI })' in apka, "lista zadań z API, za tokenem"


@pytest.mark.anyio
async def test_wynik_ukrywania_mowi_o_zapisanej_mapie(klient):
    """§1: użytkownik nie musi pobierać pliku; mapę zapisze program na tym komputerze."""
    apka = (await klient.get("/apka.js")).text
    strona = (await klient.get("/")).text
    assert 'id="mapa-zapisana"' in strona
    assert "Mapa zapisana na tym komputerze do" in apka
    assert "Bez mapy nie przywrócisz danych." in apka
    assert 'get("x-niewidka-mapa-zapisana")' in apka, "zdanie tylko gdy mapa faktycznie zapisana"


@pytest.mark.anyio
async def test_ustawienia_zapisane_mapy_z_usuwaniem(klient):
    """§2: lista zapisanych map w Ustawieniach, Usuń przy każdej, Usuń wszystkie
    z potwierdzeniem, zdanie o okresie przechowywania."""
    strona = (await klient.get("/")).text
    apka = (await klient.get("/apka.js")).text
    assert "Zapisane mapy" in strona
    assert 'id="lista-map-zapisanych"' in strona
    assert 'id="usun-wszystkie-mapy"' in strona
    assert "Mapy są usuwane automatycznie po" in apka
    assert "Okres ustawia administrator." in apka
    assert "Mapy nie są zapisywane automatycznie. Pobierz mapę po każdym ukryciu." in apka
    # usuwanie: pojedyncze i wszystkie, oba przez API i za tokenem
    assert "/api/mapy/${" in apka, "Usuń pojedynczej mapy przez API"
    assert '"DELETE"' in apka and '"/api/mapy"' in apka, "Usuń wszystkie przez API"
    assert "confirm(" in apka, "Usuń wszystkie ma potwierdzenie"


@pytest.mark.anyio
async def test_wybierz_mape_prowadzi_do_listy_zadan(klient):
    """§3: 422 z kodem wybierz_mape nie zostaje błędem ogólnym; interfejs pokazuje
    komunikat i prowadzi do listy zadań."""
    apka = (await klient.get("/apka.js")).text
    assert 'wybierz_mape' in apka
    assert "Wybierz zadanie z listy" in apka
    assert 'lista-zadan' in apka, "po komunikacie fokus/akcja na liście zadań"


@pytest.mark.anyio
async def test_przywrocony_tekst_w_podgladzie_z_kopiowaniem(klient):
    """§1: wynik przywrócenia z wklejonego tekstu widać w podglądzie z Kopiuj;
    dla pliku pozostaje pobranie."""
    strona = (await klient.get("/")).text
    apka = (await klient.get("/apka.js")).text
    assert 'id="blok-podglad-przywroc"' in strona
    assert 'id="kopiuj-przywrocony"' in strona
    assert 'id="podglad-przywroconego"' in strona
    assert "tekstPrzywroconego" in apka, "surowy tekst pod podglądem do kopiowania"
    assert 'id="pobierz-przywrocony"' in strona, "pobranie zostaje (plik i tekst)"


@pytest.mark.anyio
async def test_mapa_niezapisana_i_licznik_zlecen(klient):
    """sekcja 9 pkt 5: błąd zapisu mapy = wynik wydany z nagłówkiem „blad” i
    komunikatem „Pobierz mapę”; odpowiedzi starszych żądań są odrzucane."""
    apka = (await klient.get("/apka.js")).text
    assert "Pobierz mapę, bo nie została zapisana." in apka
    assert '"blad"' in apka or "'blad'" in apka
    assert "licznikZlecen" in apka
    assert "mojaKolejna !== licznikZlecen" in apka, "spóźniona odpowiedź nie renderuje się"
