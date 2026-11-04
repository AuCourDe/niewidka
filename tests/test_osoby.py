"""Tests of grouping people by inflected forms."""

from niewidka.model import Encja, TypEncji, Zakres
from niewidka.odmiana import rdzen as rdzen_nazwiska
from niewidka.osoby import _rozbij, pogrupuj


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
    # ambiguous ones are not merged by default.
    encje = [_osoba("Jan Kowalski"), _osoba("J. Kowalski")]
    pogrupuj(encje)
    assert encje[0].klucz_grupy != encje[1].klucz_grupy


def test_inicjaly_przy_dwoch_imionach_osobne_od_obu():
    # Counterexample: an initial does not attach to either of the two
    # candidates with the same stem; it stays a separate group.
    encje = [_osoba("Jan Kowalski"), _osoba("Piotr Kowalski"), _osoba("J. Kowalski")]
    pogrupuj(encje)
    assert len({e.klucz_grupy for e in encje}) == 3


def test_same_nazwiska_bez_imion_to_jedna_osoba():
    # "Sprawę prowadzi Kowalski. Kowalskiego poinformowano." is one person, not one per occurrence
    encje = [_osoba("Kowalskiego"), _osoba("Kowalski"), _osoba("Kowalski")]
    pogrupuj(encje)
    assert len({e.klucz_grupy for e in encje}) == 1


def test_samo_nazwisko_łączy_sie_z_jedynym_inicjałem():
    # Rule boundary: back-association works
    # with EXACTLY one candidate with the stem; the initial is that one.
    encje = [_osoba("J. Kowalski"), _osoba("najemca Kowalskiego")]
    pogrupuj(encje)
    assert encje[0].klucz_grupy == encje[1].klucz_grupy


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
    # 'wniosek Kowalskiego' with a single person with that stem.
    encje = [_osoba("Jan Kowalski"), _osoba("wniosek Kowalskiego")]
    pogrupuj(encje)
    assert encje[0].klucz_grupy == encje[1].klucz_grupy


def test_samo_nazwisko_przy_dwoch_osobach_rozdzielone():
    encje = [
        _osoba("Jan Kowalski"), _osoba("Piotr Kowalski"), _osoba("najemca Kowalski"), _osoba("Kowalskiego")
    ]
    pogrupuj(encje)
    klucze = [e.klucz_grupy for e in encje]
    assert klucze[0] != klucze[2] and klucze[1] != klucze[2]
    assert klucze[2] == klucze[3]  # bare occurrences share one ambiguous group


def test_tytuly_nie_sa_imieniem():
    encje = [_osoba("Jan Kowalski"), _osoba("pan Kowalski"), _osoba("mgr Kowalska")]
    pogrupuj(encje)
    assert encje[0].klucz_grupy == encje[1].klucz_grupy == encje[2].klucz_grupy


def test_encje_bez_osoby_niezmienione():
    pesel = Encja(zakres=Zakres(0, 11, TypEncji.PESEL, 1.0, "regula", True), tekst="44051401359")
    pogrupuj([pesel])
    assert pesel.klucz_grupy is None


def test_odmiany_z_naprawy_2026_11_to_jedna_osoba():
    pary = [
        ("Anna Kowalska", "Anny Kowalskiej"), ("Anna Kowalska", "Annie Kowalskiej"),
        ("Jan Nowak", "Janem Nowakiem"), ("Marek Zawadzki", "Marka Zawadzkiego"),
        ("Paweł Kot", "Pawła Kota"), ("Agnieszka Lis", "Agnieszce Lis"),
        ("Jan Kowalski-Nowak", "Janowi Kowalskiemu-Nowakowi"), ("Maria Nowicka", "Marii Nowickiej"),
        ("Krzysztof Dąb", "Krzysztofem Dębem"), ("Beata Krupa-Dąbrowska", "Beacie Krupie-Dąbrowskiej"),
        ("Andrzej Nowicki", "Panem Andrzejem Nowickim"), ("Anna Kowalska", "Panią Annę Kowalską"),
    ]
    for a, b in pary:
        encje = [_osoba(a), _osoba(b)]
        pogrupuj(encje)
        assert encje[0].klucz_grupy == encje[1].klucz_grupy, (a, b)


def test_imie_na_ska_nie_jest_odwracane():
    assert _rozbij("Agnieszka Lis") == (rdzen_nazwiska("Agnieszka"), "lis")
    assert _rozbij("Nowicka Anna") == (rdzen_nazwiska("Anna"), rdzen_nazwiska("Nowicka"))


def test_tytul_malą_literą_nie_kasuje_imienia():
    assert _rozbij("ks. Jan Kowalski") == ("jan", rdzen_nazwiska("Kowalski"))
    assert _rozbij("Panią Annę Kowalską") == (rdzen_nazwiska("Anna"), rdzen_nazwiska("Kowalska"))


def test_samo_imie_dolacza_do_jedynej_osoby_z_tym_imieniem():
    encje = [_osoba("Jan Piotr Zawadzki"), _osoba("Panie Janie"), _osoba("Katarzyna Lis"), _osoba("Katarzyno")]
    pogrupuj(encje)
    assert encje[0].klucz_grupy == encje[1].klucz_grupy
    assert encje[2].klucz_grupy == encje[3].klucz_grupy


def test_zdrobnienie_dolacza_do_jedynej_osoby_o_pelnym_imieniu():
    encje = [_osoba("Katarzyna Mazur"), _osoba("Kasia"), _osoba("Kasi"), _osoba("Janusz Mazur")]
    pogrupuj(encje)
    assert encje[0].klucz_grupy == encje[1].klucz_grupy == encje[2].klucz_grupy
    assert encje[3].klucz_grupy != encje[0].klucz_grupy


def test_zdrobnienie_z_nazwiskiem_to_ta_sama_osoba():
    encje = [_osoba("Bartosz Wróbel"), _osoba("Bartek Wróbel"), _osoba("Bartka")]
    pogrupuj(encje)
    assert len({e.klucz_grupy for e in encje}) == 1


def test_zdrobnienie_przy_dwoch_kandydatach_osobno():
    encje = [_osoba("Tomasz Lis"), _osoba("Tomasz Mazur"), _osoba("Tomek")]
    pogrupuj(encje)
    assert len({e.klucz_grupy for e in encje}) == 3


def test_patron_tylko_po_skrocie_im():
    from niewidka.osoby import nie_jest_osoba

    tekst = "Szkoła im. Marii Konopnickiej; wniosek o zmianę imienia Anna Kowalska."
    start = tekst.index("Marii")
    assert nie_jest_osoba(tekst, start, start + len("Marii Konopnickiej"))
    start = tekst.index("Anna")
    assert not nie_jest_osoba(tekst, start, start + len("Anna Kowalska"))
    naglowek = "SZPITAL IM. MIKOŁAJA KOPERNIKA W GDAŃSKU"
    start = naglowek.index("KOPERNIKA")
    assert nie_jest_osoba(naglowek, start, len(naglowek))
    zdanie = "Szkoła im. Konopnickiej. Uczeń Jan Nowak zdał."
    start = zdanie.index("Jan")
    assert not nie_jest_osoba(zdanie, start, start + len("Jan Nowak"))
