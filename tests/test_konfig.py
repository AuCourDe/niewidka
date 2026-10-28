"""Testy konfiguracji (K4, LLD §14): TOML + env, env ma pierwszeństwo, nic na sztywno."""

from __future__ import annotations

from pathlib import Path

from niewidka.konfig import wczytaj_konfig


def test_domyslne_wg_lld_14():
    k = wczytaj_konfig(env={})
    assert k.host == "127.0.0.1"
    assert k.port == 8390
    assert k.poziom == 1
    assert k.modele_katalog is None
    assert k.provider == "CPUExecutionProvider"
    assert k.klucz_plik is None
    assert k.keyring_usluga == "niewidka"
    assert k.max_rozmiar_mb == 25
    assert k.max_rozpakowane_mb == 200
    assert k.max_tekst_mb == 1
    assert k.kontrola_blokada is True
    assert k.kolejka == 4
    assert k.timeout_s == 120
    assert k.wykrywaj_date is True
    assert k.prog_osoba == 0.2  # K2d wariant A; pomiar docs/WYNIK-K2d.md


def test_toml_nadaje_domyslne(tmp_path: Path):
    plik = tmp_path / "niewidka.toml"
    plik.write_text(
        """
[serwer]
host = "127.0.0.1"  # K4b pkt 14: tylko loopback przechodzi walidację
port = 9000

[detekcja]
poziom = 2
modele_katalog = "/wagi"
provider = "CUDAExecutionProvider"
wykrywaj_date = false

[klucze]
plik = "/sekrety/klucz.b64"
usluga = "niewidka-prod"

[limity]
rozmiar_mb = 10
rozpakowane_mb = 100
tekst_mb = 2
kolejka = 2
timeout_s = 30

[kontrola]
blokada = false
""",
        encoding="utf-8",
    )
    k = wczytaj_konfig(plik, env={})
    assert k.host == "127.0.0.1"  # K4b pkt 14: tylko loopback
    assert k.port == 9000
    assert k.poziom == 2
    assert k.modele_katalog == Path("/wagi")
    assert k.provider == "CUDAExecutionProvider"
    assert k.wykrywaj_date is False
    assert k.klucz_plik == "/sekrety/klucz.b64"
    assert k.keyring_usluga == "niewidka-prod"
    assert k.max_rozmiar_mb == 10
    assert k.max_rozpakowane_mb == 100
    assert k.max_tekst_mb == 2
    assert k.kolejka == 2
    assert k.timeout_s == 30
    assert k.kontrola_blokada is False


def test_env_wygra_z_toml(tmp_path: Path):
    plik = tmp_path / "niewidka.toml"
    plik.write_text("[serwer]\nport = 9000\n", encoding="utf-8")
    # K4b pkt 14: host poza loopbackiem odrzucany przy starcie, więc precedencja
    # env nad TOML dowodzi port (host dozwolony tylko z loopbacku)
    k = wczytaj_konfig(plik, env={"NIEWIDKA_PORT": "9100", "NIEWIDKA_HOST": "127.0.0.1"})
    assert k.port == 9100
    assert k.host == "127.0.0.1"


def test_env_bez_toml(tmp_path: Path):
    k = wczytaj_konfig(
        tmp_path / "brak.toml",
        env={
            "NIEWIDKA_POZIOM": "3",
            "NIEWIDKA_MODELE_KATALOG": "/wagi",
            "NIEWIDKA_KLUCZ_PLIK": "/sekrety/k.b64",
            "NIEWIDKA_KEYRING_USLUGA": "n-conv",
            "NIEWIDKA_MAX_ROZMIAR_MB": "5",
            "NIEWIDKA_MAX_ROZPAKOWANE_MB": "50",
            "NIEWIDKA_MAX_TEKST_MB": "0",
            "NIEWIDKA_KONTROLA_BLOKADA": "false",
            "NIEWIDKA_KOLEJKA": "0",
            "NIEWIDKA_TIMEOUT_S": "7",
            "NIEWIDKA_WYKRYWAJ_DATE": "false",
            "NIEWIDKA_PROVIDER": "TensorrtExecutionProvider",
        },
    )
    assert k.poziom == 3
    assert k.modele_katalog == Path("/wagi")
    assert k.klucz_plik == "/sekrety/k.b64"
    assert k.keyring_usluga == "n-conv"
    assert k.max_rozmiar_mb == 5
    assert k.max_rozpakowane_mb == 50
    assert k.max_tekst_mb == 0
    assert k.kontrola_blokada is False
    assert k.kolejka == 0
    assert k.timeout_s == 7
    assert k.wykrywaj_date is False
    assert k.provider == "TensorrtExecutionProvider"


def test_zla_liczba_w_env_jawny_blad():
    try:
        wczytaj_konfig(env={"NIEWIDKA_PORT": "abc"})
    except ValueError as e:
        assert "NIEWIDKA_PORT" in str(e)
    else:
        raise AssertionError("brak błędu dla złej liczby")


def test_prog_osoba_toml_a_env_wygra(tmp_path: Path):
    """Próg pewności OSOBA (poziomy 2/3) z konfiguracji, nie na sztywno (K2d)."""
    plik = tmp_path / "niewidka.toml"
    plik.write_text("[detekcja]\nprog_osoba = 0.35\n", encoding="utf-8")
    assert wczytaj_konfig(plik, env={}).prog_osoba == 0.35
    assert wczytaj_konfig(plik, env={"NIEWIDKA_PROG_OSOBA": "0.15"}).prog_osoba == 0.15
    assert wczytaj_konfig(env={"NIEWIDKA_PROG_OSOBA": "0.5"}).prog_osoba == 0.5


def test_zly_prog_osoba_jawny_blad():
    try:
        wczytaj_konfig(env={"NIEWIDKA_PROG_OSOBA": "mocno"})
    except ValueError as e:
        assert "NIEWIDKA_PROG_OSOBA" in str(e)
    else:
        raise AssertionError("brak błędu dla złego progu")
