"""Testy grupowania osób po odmianach (LLD §6, przegląd Gemini pkt 13)."""

from niewidka.model import Encja, TypEncji, Zakres
from niewidka.osoby import pogrupuj, rdzen_nazwiska


def _osoba(tekst: str) -> Encja:
    return Encja(zakres=Zakres(0, len(tekst), TypEncji.OSOBA, 0.9, "regula"), tekst=tekst)


def test_rdzen_odmian_rownym_stemem():
    assert rdzen_nazwiska("Kowalski") == rdzen_nazwiska("Kowalska")
    assert rdzen_nazwiska("Kowalskiego") == rdzen_nazwiska("Kowalski")
    assert rdzen_nazwiska("Kowalską") == rdzen_nazwiska("Kowalski")
    assert rdzen_nazwiska("Nowaka") == rdzen_nazwiska("Nowak")
    assert rdzen_nazwiska("Nowakowi") == rdzen_nazwiska("Nowak")
    assert rdzen_nazwiska("Kowal") == rdzen_nazwiska("Kowala")
    assert rdzen_nazwiska("Przełęcka-Kowalska") == rdzen_nazwiska("Przełęcka-Kowalski")


def test_odmiany_tejsamej_osoby_maja_wspolny_klucz():
    encje = [_osoba(t) for t in ("Jan Kowalski", "Jana Kowalskiego", "Janowi Kowalskiemu")]
    pogrupuj(encje)
    assert len({e.klucz_grupy for e in encje}) == 1


def test_rozne_imiona_to_rozne_osoby():
    encje = [_osoba("Jan Kowalski"), _osoba("Piotr Kowalski"), _osoba("Anna Kowalska")]
    pogrupuj(encje)
    assert len({e.klucz_grupy for e in encje}) == 3


def test_inicjaly_nie_lacza_sie_z_imieniem():
    # Przegląd Astry pkt 10: niejednoznacznych domyślnie nie łączymy.
    encje = [_osoba("Jan Kowalski"), _osoba("J. Kowalski")]
    pogrupuj(encje)
    assert encje[0].klucz_grupy != encje[1].klucz_grupy


def test_odwrocony_szyk_przymiotnikowe_nazwisko():
    encje = [_osoba("Jan Kowalski"), _osoba("Kowalski Jan"), _osoba("Jana Kowalskiego")]
    pogrupuj(encje)
    klucze = {e.klucz_grupy for e in encje}
    assert len(klucze) == 1


def test_janina_to_inna_osoba_niz_jan():
    encje = [_osoba("Jan Kowalski"), _osoba("Janina Kowalska")]
    pogrupuj(encje)
    assert encje[0].klucz_grupy != encje[1].klucz_grupy


def test_samo_nazwisko_dolacza_do_jedynej_osoby():
    # Przegląd Gemini pkt 13: „wniosek Kowalskiego" przy jednej osobie o tym rdzeniu.
    encje = [_osoba("Jan Kowalski"), _osoba("wniosek Kowalskiego")]
    pogrupuj(encje)
    assert encje[0].klucz_grupy == encje[1].klucz_grupy


def test_samo_nazwisko_przy_dwoch_osobach_rozdzielone():
    encje = [_osoba("Jan Kowalski"), _osoba("Piotr Kowalski"), _osoba("najemca Kowalski")]
    pogrupuj(encje)
    klucze = [e.klucz_grupy for e in encje]
    assert klucze[0] != klucze[2] and klucze[1] != klucze[2]


def test_tytuly_nie_sa_imieniem():
    encje = [_osoba("Jan Kowalski"), _osoba("pan Kowalski"), _osoba("mgr Kowalska")]
    pogrupuj(encje)
    assert encje[0].klucz_grupy == encje[1].klucz_grupy == encje[2].klucz_grupy


def test_encje_bez_osoby_niezmienione():
    pesel = Encja(zakres=Zakres(0, 11, TypEncji.PESEL, 1.0, "regula", True), tekst="44051401359")
    pogrupuj([pesel])
    assert pesel.klucz_grupy is None
