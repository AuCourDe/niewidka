"""Znaczniki [TYP_N] / [OSOBA_N_Fk] — nadawanie numerów i zamiana (LLD §7).

„N" liczy się per typ w kolejności wystąpienia w dokumencie; [OSOBA_1] wspólne
dla wszystkich form tej osoby (klucz_grupy z osoby.py). Osoby dostają dodatkowo
stabilny wariant formy powierzchniowej — [OSOBA_1_F2] — dzięki czemu przywracanie
kluczem (oznaczenie, wariant) nie zależy od pozycji ani kolejności wystąpień
i przetrwa parafrazę tekstu przez chmurowe AI (przegląd Astry pkt 2, Gemini
pkt 3). Dopisek celowo nie zawiera nawiasów kwadratowych — kontrola wyniku
szuka wzorca znacznika (przegląd Gemini pkt 7) — i obiecuje odtworzenie tylko
danych zastąpionych znacznikami (Astra pkt 2).
"""

from niewidka.model import Encja, TypEncji

DOPISEK = (
    "ZANONIMIZOWANY. Dane osobowe zastąpiono znacznikami (Niewidka). "
    "Oryginalne dane przywrócisz plikiem mapy."
)


_ALFABET_ID = "abcdefghijklmnop"


def zakoduj_identyfikator(identyfikator: str) -> str:
    """Identyfikator jako same litery (nibble → a..p). Surowy hex w dopisku tworzył
    losowe 9-11-znakowe okna cyfr, które tripały reguły PESEL/REGON w kontroli
    wyniku i losowo blokowały dokumenty (K4b pkt 6+7)."""
    return "".join(_ALFABET_ID[int(znak, 16)] for znak in identyfikator)


def odkoduj_identyfikator(litery: str) -> str | None:
    """Odwrotność `zakoduj_identyfikator`; None dla tekstu niebędącego identyfikatorem."""
    try:
        return "".join(f"{_ALFABET_ID.index(znak):x}" for znak in litery)
    except ValueError:
        return None


def dopisek(identyfikator: str) -> str:
    """Dopisek wyniku z identyfikatorem mapy (K4b pkt 6): wiąże mapę z KONKRETNYM
    dokumentem — przywracanie sprawdza, że identyfikator mapy równa się temu
    zapisanemu w treści; podsunięcie mapy innego zadania kończy się 422."""
    return f"{DOPISEK} Identyfikator mapy: {zakoduj_identyfikator(identyfikator)}."


def nadaj_oznaczenia(encje: list[Encja]) -> None:
    """Ustawia encja.oznaczenie i encja.wariant; encje muszą być w kolejności dokumentu.

    OSOBY o tym samym klucz_grupy dzielą numer; bez klucza każda dostaje
    własny. Każda unikalna forma powierzchniowa osoby ma stabilny numer
    wariantu Fk (nadawany wg pierwszego wystąpienia; ta sama forma = to samo
    Fk). Pozostałe typy bez wariantu.
    """
    liczniki: dict[str, int] = {}
    numery: dict[str, str] = {}
    formy: dict[str, dict[str, str]] = {}  # identyfikator grupy -> forma -> "Fk"
    for pozycja, encja in enumerate(encje):
        typ = encja.zakres.typ.value
        identyfikator = f"{typ}\x00{encja.klucz_grupy or f'#{pozycja}'}"
        if identyfikator not in numery:
            liczniki[typ] = liczniki.get(typ, 0) + 1
            numery[identyfikator] = f"{typ}_{liczniki[typ]}"
        encja.oznaczenie = numery[identyfikator]
        if encja.zakres.typ is TypEncji.OSOBA:
            formy_grupy = formy.setdefault(identyfikator, {})
            if encja.tekst not in formy_grupy:
                formy_grupy[encja.tekst] = f"F{len(formy_grupy) + 1}"
            encja.wariant = formy_grupy[encja.tekst]


def znacznik_encji(encja: Encja) -> str:
    """Tekst znacznika encji: [TYP_N] albo [OSOBA_N_Fk]."""
    if encja.oznaczenie is None:
        raise ValueError("encja bez oznaczenia — najpierw nadaj_oznaczenia")
    return f"[{encja.oznaczenie}]" if encja.wariant is None else f"[{encja.oznaczenie}_{encja.wariant}]"


def zamien_w_segment(
    segment_tekst: str, encje: list[Encja], poczatek_kolejnego: int = 0
) -> tuple[str, list[int]]:
    """Tekst ze znacznikami + numery „kolejny" wystąpień dla mapy (LLD §8).

    Zamiana od końca segmentu, żeby offsety nie uciekały. `poczatek_kolejnego`
    kontynuuje globalną numerację między segmentami.
    """
    wynik = segment_tekst
    kolejne: list[int] = []
    posortowane = sorted(encje, key=lambda e: e.zakres.start)
    for numer, encja in enumerate(posortowane):
        kolejne.append(poczatek_kolejnego + numer)
    for encja in reversed(posortowane):
        wynik = wynik[: encja.zakres.start] + znacznik_encji(encja) + wynik[encja.zakres.koniec :]
    return wynik, kolejne
