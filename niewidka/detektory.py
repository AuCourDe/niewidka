"""Detektory (LLD §4): wspólny interfejs, okna przesuwne, adaptery modeli ONNX.

Adapter per model (przegląd Astry pkt 14): schemat etykiet (BIO/BIOES), tokeny
specjalne i normalizacja różnią się między modelami — konwersja do `Zakres`
żyje w adapterze modelu, nie we wspólnym kodzie. Błąd detektora = `BladDetektora`
(fail-closed, LLD §15).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from niewidka.konfig import PROG_OSOBA_DOMYSLNY
from niewidka.model import TypEncji, Zakres
from niewidka.osoby import rdzen_nazwiska
from niewidka.pakiety import KATALOG_PAKIETOW, BladPakietu, wczytaj_bajty_pakietu
from niewidka.reguly import REGULY
from niewidka.reguly import znajdz as znajdz_reguly
from niewidka.scalanie import scal


class BladDetektora(Exception):
    """Awaria warstwy detekcji — fail-closed: bez dokumentu „bez warstwy"."""


class Detektor(Protocol):
    nazwa: str
    typy: frozenset[TypEncji]

    def znajdz(self, tekst: str) -> list[Zakres]: ...


class RegulyDetektor:
    """Reguły + scalanie — warstwa detekcji regułowa (K1)."""

    nazwa = "reguly"
    typy = frozenset(r.typ for r in REGULY)

    def znajdz(self, tekst: str) -> list[Zakres]:
        return scal(tekst, znajdz_reguly(tekst))


@dataclass(frozen=True)
class AdapterModelu:
    """Mapowanie etykiet modelu na typy Niewidki; klasy poza mapą są pomijane."""

    nazwa: str
    mapa: dict[tuple[str, ...], TypEncji]

    @property
    def typy(self) -> frozenset[TypEncji]:
        return frozenset(self.mapa.values())

    def zwroc_typ(self, etykieta: str) -> TypEncji | None:
        if len(etykieta) > 2 and etykieta[1] == "-":  # B/I/E/S — schemat adaptera decyduje
            return self.mapa.get((etykieta[2:],))
        return None


# Bardsai (poziom 1): dostarcza WYŁĄCZNIE OSOBA — typy z sumą kontrolną i
# dokładnymi granicami mają reguły (pewność 1.0); dołączenie modelowych ADRES/
# EMAIL itd. rozmywałoby granice (unia scalania = szerszy zakres = FN+FP,
# KRYTERIA §1.3). Reszta etykiet (LOCATION, ORGANIZATION_NAME, ...) pomijana.
ADAPTER_BARDSAI = AdapterModelu(
    nazwa="onnx:bardsai",
    mapa={
        ("PERSON_NAME",): TypEncji.OSOBA,
        ("PERSON_ALIAS",): TypEncji.OSOBA,
    },
)


def _sha256(plik: Path) -> str:
    h = hashlib.sha256()
    with plik.open("rb") as f:
        for kawalek in iter(lambda: f.read(1 << 20), b""):
            h.update(kawalek)
    return h.hexdigest()


class OnnxDetektor:
    """Detektor token-klasyfikacyjny ONNX za interfejsem Detektor (LLD §4).

    Tokenizacja całości (`tokenizers`, offsety znakowe), okna przesuwne
    tokenów, per okno inferencja i dekodowanie BIO adapterem. Duplikaty między
    oknami zdejmuje globalne scalanie (wyżej). `SIMPLIFICATION`: okna na
    pełnym ciągu tokenów (ze specjalnymi), bez doklejania <s>/</s> per okno —
    zakładka (okno-krok) kompensuje granice; rozbudować, gdy pomiar pokaże
    gubienie encji przy krawędziach okien.
    """

    def __init__(
        self,
        nazwa: str,
        model: Path | bytes,
        tokenizer: Path | bytes,
        etykiety: dict[tuple[str, ...], TypEncji],
        id2etykieta: dict[str, str],
        okno: int = 510,
        krok: int = 448,
        sesja: object | None = None,
        tokenizer_obj: object | None = None,
        laduj_manifest: bool = True,
        provider: str = "CPUExecutionProvider",
        próg: float | None = None,
        pół_krok: bool = False,
    ):
        self.nazwa = nazwa
        self.etykiety = etykiety
        self.typy = frozenset(etykiety.values())
        self._id2etykieta = {str(k): v for k, v in id2etykieta.items()}
        self._okno = okno
        self._krok = krok
        if próg is not None and not 0.0 <= próg <= 1.0:
            raise BladDetektora(f"{nazwa}: próg pewności klas poza [0, 1]: {próg}")
        self._próg = próg
        self._pół_krok = pół_krok
        # Obniżony próg (K2d): kolumny etykiet klas z mapy (B-/I-/E-/S-) oraz
        # pary (B-etykieta, I-etykieta) do sklejenia ponadprogowej kontynuacji.
        self._kolumny_klas: dict[tuple[str, ...], list[int]] = {}
        self._etykiety_klas: dict[tuple[str, ...], tuple[str, str]] = {}
        for klucz in self.etykiety:
            klasa = klucz[0]
            kol = [
                int(id_tekstu)
                for id_tekstu, et in self._id2etykieta.items()
                if len(et) > 2 and et[1] == "-" and et[2:] == klasa
            ]
            self._kolumny_klas[klucz] = kol
            litery = {
                et[:1]: et
                for et in self._id2etykieta.values()
                if len(et) > 2 and et[1] == "-" and et[2:] == klasa and et[:1] in ("B", "I")
            }
            if "B" in litery and "I" in litery:
                self._etykiety_klas[klucz] = (litery["B"], litery["I"])
        if laduj_manifest and not isinstance(model, bytes):
            self._sprawdz_manifest(model.parent)
        try:
            import numpy as np

            self._np = np
            if tokenizer_obj is None:
                from tokenizers import Tokenizer

                if isinstance(tokenizer, bytes):
                    tokenizer_obj = Tokenizer.from_str(tokenizer.decode("utf-8"))
                else:
                    tokenizer_obj = Tokenizer.from_file(str(tokenizer))
            self._tokenizer = tokenizer_obj
            if sesja is None:
                import onnxruntime as ort

                dostepne = ort.get_available_providers()
                if provider not in dostepne:
                    provider = "CPUExecutionProvider"
                # K7c pkt 3 (audyt): sesja otwierana z bajtów — te same, które
                # przeszły weryfikację SHA (brak okna sprawdź-użyj na dysku)
                model_bajty = model if isinstance(model, bytes) else Path(model).read_bytes()
                sesja = ort.InferenceSession(model_bajty, providers=[provider])
            wejscia = (
                [i.name for i in sesja.get_inputs()]
                if hasattr(sesja, "get_inputs")
                else list(sesja.wejscia)
            )
            if wejscia[:2] != ["input_ids", "attention_mask"]:
                raise BladDetektora(f"{nazwa}: nieobsługiwane wejścia ONNX: {wejscia}")
            self._sesja = sesja
        except BladDetektora:
            raise
        except Exception as e:  # fail-closed: każdy pad modelu/toklenizera
            raise BladDetektora(f"{nazwa}: ładowanie nie powiodło się: {e}") from e

    @staticmethod
    def _sprawdz_manifest(katalog: Path) -> None:
        manifest_plik = katalog / "manifest.json"
        if not manifest_plik.is_file():
            raise BladDetektora(f"brak manifest.json w {katalog}")
        manifest = json.loads(manifest_plik.read_text(encoding="utf-8"))
        for nazwa, sumka in manifest.get("pliki", {}).items():
            plik = katalog / nazwa
            if not plik.is_file() or _sha256(plik) != sumka:
                raise BladDetektora(f"manifest: rozbieżny SHA-256 dla {nazwa}")

    def znajdz(self, tekst: str) -> list[Zakres]:
        try:
            return self._znajdz(tekst)
        except BladDetektora:
            raise
        except Exception as e:
            raise BladDetektora(f"{self.nazwa}: inferencja nie powiodła się: {e}") from e

    def _znajdz(self, tekst: str) -> list[Zakres]:
        np = self._np
        enc = self._tokenizer.encode(tekst, add_special_tokens=True)
        tokeny = list(zip(enc.ids, enc.offsets))
        wynik: list[Zakres] = []
        # Drugi przebieg okien przesuniętych o pół kroku (K2d): encja na granicy
        # okien ma pełny łańcuch etykiet w przesuniętym oknie — bez tego pierwsza
        # część pada jako B-frAGMENT, a reszta (I bez B) jest odpadana w dekodowaniu.
        okna: list[tuple[int, int]] = []
        przesunięcia = (0, self._krok // 2) if self._pół_krok else (0,)
        for przesunięcie in przesunięcia:
            for okno in okna_tokenow(len(tokeny), self._okno, self._krok, przesunięcie):
                if okno not in okna:  # przebieg półkrokowy powtarza okno końcowe
                    okna.append(okno)
        for start, koniec in okna:
            ids = tokeny[start:koniec]
            feed = {
                "input_ids": np.asarray([ids_w for ids_w, _ in ids], dtype=np.int64)[None],
                "attention_mask": np.ones((1, len(ids)), dtype=np.int64),
            }
            logits = np.asarray(self._sesja.run(None, feed)[0][0])
            prawdopodobienstwa = _softmax(np, logits)
            najlepsze = prawdopodobienstwa.argmax(axis=-1)
            etykiety_tokenow = []
            poprz_klasa: tuple[str, ...] | None = None
            for i, (_, offsets) in enumerate(ids):
                if offsets[0] == offsets[1]:  # token specjalny/wypadek
                    etykiety_tokenow.append(
                        (self._id2etykieta[str(int(najlepsze[i]))], offsets, float(prawdopodobienstwa[i, najlepsze[i]]))
                    )
                    poprz_klasa = None
                    continue
                et = self._id2etykieta[str(int(najlepsze[i]))]
                klasa = (et[2:],) if len(et) > 2 and et[1] == "-" else None
                etykieta, pewnosc = et, float(prawdopodobienstwa[i, najlepsze[i]])
                if self._próg is not None and (klasa is None or klasa not in self.etykiety):
                    kandydat = self._najlepsza_klasa_mapy(prawdopodobienstwa, i)
                    if kandydat is not None and kandydat[1] >= self._próg:
                        litery = self._etykiety_klas.get(kandydat[0])
                        if litery is not None:
                            # ponowne trafienie tej samej klasy podbija się kontynuacją I-
                            etykieta = litery[1] if poprz_klasa == kandydat[0] else litery[0]
                            pewnosc, klasa = kandydat[1], kandydat[0]
                etykiety_tokenow.append((etykieta, offsets, pewnosc))
                poprz_klasa = klasa
            for zn_start, zn_koniec, typ, pewnosc in zdekoduj_bio(etykiety_tokenow, self.etykiety):
                ((zn_start, zn_koniec),) = rozciagnij_do_slow([(zn_start, zn_koniec)], tekst)
                wynik.append(Zakres(zn_start, zn_koniec, typ, pewnosc, self.nazwa))
        return wynik

    def _najlepsza_klasa_mapy(
        self, prawdopodobienstwa, i: int  # type: ignore[no-untyped-def]
    ) -> tuple[tuple[str, ...], float] | None:
        """Najpewniejsza klasa z mapy adaptera w tokenie i (niezależnie od argmax)."""
        najlepsza: tuple[tuple[str, ...], float] | None = None
        for klucz, kolumny in self._kolumny_klas.items():
            p = max((float(prawdopodobienstwa[i, k]) for k in kolumny), default=0.0)
            if najlepsza is None or p > najlepsza[1]:
                najlepsza = (klucz, p)
        return najlepsza


def rozciagnij_do_slow(zakresy: list[tuple[int, int]], tekst: str) -> list[tuple[int, int]]:
    """Zakresy modelu rozciągnięte do granic słowa (artefakty subword).

    Tokenizery subword tną słowa ('Kowal' -> 'Ko'+'wal'); model potrafi oznaczyć
    tylko część albo dać B- na obu subtokenach. Zakres nie zmienia się, gdy już
    jest wyrównany do granic słowa. Duplikaty/pokrycia zdejmuje potem scalanie.
    """
    wynik = []
    for start, koniec in zakresy:
        # Tokeny BPE niosą wiodącą spację w offsecie ('ĠPiot' -> (14,19)); bez
        # przycięcia rozciąganie uciekłoby na poprzednie słowo (K2b).
        while start < koniec and tekst[start].isspace():
            start += 1
        while koniec > start and tekst[koniec - 1].isspace():
            koniec -= 1
        while start > 0 and tekst[start - 1].isalnum():
            start -= 1
        while koniec < len(tekst) and tekst[koniec].isalnum():
            koniec += 1
        wynik.append((start, koniec))
    return wynik


def _softmax(np, logits):  # type: ignore[no-untyped-def]
    z = logits - logits.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def wczytaj_bardsai(
    katalog: Path,
    provider: str = "CPUExecutionProvider",
    okno: int = 510,
    krok: int = 448,
    próg: float | None = None,
    pół_krok: bool = False,
    katalog_pakietow: Path | None = None,
) -> OnnxDetektor:
    """OnnxDetektor z wag bardsai w `katalog` (NIEWIDKA_MODELE_KATALOG, LLD §14).

    K2d: `próg` = obniżony próg pewności klas OSOBA (dodaje kandydatów poniżej
    argmaxu) i `pół_krok` = drugi przebieg okien o pół kroku (granice okien).
    K7c pkt 2/3 (audyt): wagi weryfikowane względem ZAUFANEGO katalogu pakietów
    (podstawowy), a do sesji/tokenizera idą dokładnie te bajty, które przeszły
    haszowanie; lokalny manifest nie wyznacza oczekiwanych sum.
    """
    try:
        bajty = wczytaj_bajty_pakietu(
            "podstawowy", katalog, katalog_pakietow=katalog_pakietow or KATALOG_PAKIETOW
        )
        config = json.loads(bajty["config.json"])
        return OnnxDetektor(
            nazwa=ADAPTER_BARDSAI.nazwa,
            model=bajty["model.onnx"],
            tokenizer=bajty["tokenizer.json"],
            etykiety=ADAPTER_BARDSAI.mapa,
            id2etykieta=config.get("id2label", {}),
            okno=okno,
            krok=krok,
            provider=provider,
            próg=próg,
            pół_krok=pół_krok,
            laduj_manifest=False,
        )
    except BladPakietu as blad:
        raise BladDetektora(f"pakiet Podstawowy: {blad}") from blad


# LFM2.5 (poziom 2, K2b): jak bardsai dostarcza WYŁĄCZNIE OSOBA (identity.person_name,
# schemat BIOES) — typy z sumą kontrolną i dokładnymi granicami mają reguły (KRYTERIA
# §1.3); 39 pozostałych klas modelu pomijanych.
ADAPTER_LFM25 = AdapterModelu(
    nazwa="onnx:lfm25",
    mapa={
        ("identity.person_name",): TypEncji.OSOBA,
    },
)


# K7b pakiet Rozszerzony (decyzja orkiestratora po K2e/K7a): LFM2.5 Q4 działa
# WYŁĄCZNIE jako detektor typów, których reguły i bardsai nie obsługują —
# IP, karta płatnicza, SWIFT i loginy — i tylko tam, gdzie zakres nie nachodzi
# na inne wykrycia. Nie dotyka OSOBA ani typów regułowych (pomiar K2b/K2c/K2e:
# tam szkodzi).
ADAPTER_LFM25_ROZSZERZONY = AdapterModelu(
    nazwa="onnx:lfm25-rozszerzony",
    mapa={
        ("contact.ip_address",): TypEncji.IP,
        ("financial.credit_card",): TypEncji.KARTA,
        ("financial.swift_bic",): TypEncji.SWIFT,
        ("online.username",): TypEncji.LOGIN,
    },
)


# Mapowanie klas LFM2.5 -> typy Niewidki (K2e; pełny schemat 27 typów w
# ~/models/niewidka/lfm25/label_schema.json). Klasy poza mapą Niewidka
# dziś nie wykrywa — pomiar K2e raportuje je pod własnymi nazwami LFM2.5.
_MAPA_LFM25: dict[str, TypEncji] = {
    "identity.person_name": TypEncji.OSOBA,
    "identity.passport": TypEncji.DOKUMENT,
    "identity.drivers_license": TypEncji.DOKUMENT,
    "contact.address": TypEncji.ADRES,
    "contact.postal_code": TypEncji.ADRES,
    "contact.phone": TypEncji.TELEFON,
    "contact.email": TypEncji.EMAIL,
    "financial.iban": TypEncji.IBAN,
    "financial.bank_account": TypEncji.IBAN,
    "identity.date_of_birth": TypEncji.DATA,
}


def mapuj_typ_lfm25(klasa: str, tekst: str = "") -> TypEncji | str:
    """Klasa LFM2.5 -> typ Niewidki (K2e); klasa poza mapą wypada surową nazwą.

    national_id rozstrzyga kształt zapisu (model nie odróżnia polskich numerów):
    10 cyfr = NIP, 9/14 = REGON, 11 = PESEL; z literami = DOKUMENT (dowód/paszport
    w tej samej klasie), inaczej PESEL domyślnie.
    """
    if klasa == "identity.national_id":
        if any(znak.isalpha() for znak in tekst):
            return TypEncji.DOKUMENT
        cyfry = sum(1 for znak in tekst if znak.isdigit())
        if cyfry == 10:
            return TypEncji.NIP
        if cyfry in (9, 14):
            return TypEncji.REGON
        return TypEncji.PESEL
    wynik = _MAPA_LFM25.get(klasa)
    return wynik if wynik is not None else klasa


def wczytaj_lfm25(
    katalog: Path,
    wariant: str = "int8",
    provider: str = "CPUExecutionProvider",
    okno: int = 510,
    krok: int = 448,
    rozszerzony: bool = False,
    katalog_pakietow: Path | None = None,
) -> OnnxDetektor:
    """OnnxDetektor z wyeksportowanego ONNX LFM2.5 (`lfm25/{fp32,int8}/`, K2b).

    Wariant wybiera katalog kwantyzacji; oba mają manifest SHA-256 z eksportu.
    K7b: `rozszerzony=True` = adapter pakietu Rozszerzonego (tylko IP/KARTA/
    SWIFT/LOGIN); pomiar K2e: te typy to jedyny realny zysk z tego modelu.
    K7c pkt 2/3 (audyt): wariant pakietowy `q4-bl32` weryfikowany względem
    ZAUFANEGO katalogu pakietów i ładowany z zweryfikowanych bajtów; warianty
    pomiarowe (fp32/int8) zachowują manifest z eksportu.
    """
    podkatalog = katalog / "lfm25" / wariant
    adapter = ADAPTER_LFM25_ROZSZERZONY if rozszerzony else ADAPTER_LFM25
    if wariant == "q4-bl32":
        try:
            bajty = wczytaj_bajty_pakietu(
                "rozszerzony", katalog, katalog_pakietow=katalog_pakietow or KATALOG_PAKIETOW
            )
            config = json.loads(bajty["lfm25/q4-bl32/config.json"])
            return OnnxDetektor(
                nazwa=adapter.nazwa,
                model=bajty["lfm25/q4-bl32/model.onnx"],
                tokenizer=bajty["lfm25/q4-bl32/tokenizer.json"],
                etykiety=adapter.mapa,
                id2etykieta=config.get("id2label", {}),
                okno=okno,
                krok=krok,
                provider=provider,
                laduj_manifest=False,
            )
        except BladPakietu as blad:
            raise BladDetektora(f"pakiet Rozszerzony: {blad}") from blad
    config = json.loads((podkatalog / "config.json").read_text(encoding="utf-8"))
    return OnnxDetektor(
        nazwa=adapter.nazwa,
        model=podkatalog / "model.onnx",
        tokenizer=podkatalog / "tokenizer.json",
        etykiety=adapter.mapa,
        id2etykieta=config.get("id2label", {}),
        okno=okno,
        krok=krok,
        provider=provider,
    )


def wczytaj_poziom2(
    katalog: Path,
    provider: str = "CPUExecutionProvider",
) -> DetektorKompozyt:
    """Poziom 2 (KRYTERIA §4): reguły + bardsai + LFM2.5; duplikaty zdejmuje scalanie."""
    return DetektorKompozyt(
        "poziom2",
        [
            RegulyDetektor(),
            wczytaj_bardsai(katalog, provider=provider),
            wczytaj_lfm25(katalog, provider=provider),
        ],
    )


def wczytaj_poziom2_uzupelniajacy(
    katalog: Path,
    provider: str = "CPUExecutionProvider",
    wariant_b: bool = False,
    wariant_lfm25: str = "fp32",
) -> DetektorUzupełniający:
    """Wariant uzupełniający K2c: LFM2.5 dodaje OSOBA tylko tam, gdzie nie nachodzi
    na zakresy z reguł ani bardsai. Bardsai/reguły mają pierwszeństwo.
    """
    nazwa = "poziom2-uzup-b" if wariant_b else "poziom2-uzup"
    return DetektorUzupełniający(
        nazwa,
        podstawa=[RegulyDetektor(), wczytaj_bardsai(katalog, provider=provider)],
        uzup=wczytaj_lfm25(katalog, wariant=wariant_lfm25, provider=provider),
        wariant_b=wariant_b,
    )


def zbuduj_poziom(
    poziom: int,
    katalog: Path,
    *,
    provider: str = "CPUExecutionProvider",
    próg_osoba: float = PROG_OSOBA_DOMYSLNY,
    reguly: Detektor | None = None,
    pakiet_rozszerzony: bool = False,
) -> Detektor:
    """Poziomy produktu (suwak jakości, K2d) — JEDYNA funkcja składająca poziom;
    używa jej rdzeń (`rdzen.zbuduj_detektor`) i pomiar (`narzedzia.pomiar`), więc
    pomiar mierzy dokładnie to, co liczy produkt.

    1 = reguły + bardsai (bez progu, bez półkroku); 2 = wariant A (`docs/WYNIK-K2d.md`:
    bardsai z progiem pewności OSOBA `próg_osoba` + drugi przebieg okien o pół kroku);
    3 = wariant B (2 + słownik imion GUS, CC0). `reguly` = podmiana warstwy reguł
    (rdzeń wstawia filtr `_BezDaty` przy `wykrywaj_date=False`). K7b:
    `pakiet_rozszerzony=True` oblewa poziom 3 LFM2.5 Q4 z pakietu Rozszerzonego
    (tylko IP/KARTA/SWIFT/LOGIN, bez nachodzenia); podkatalog `lfm25/q4-bl32`
    jest warunkiem — bez pakietu poziom 3 działa jak dotąd.
    """
    if poziom not in (1, 2, 3):
        raise ValueError(f"poziom poza 1-3: {poziom}")
    warstwa_regul = RegulyDetektor() if reguly is None else reguly
    model = wczytaj_bardsai(
        katalog,
        provider=provider,
        próg=None if poziom == 1 else próg_osoba,
        pół_krok=poziom > 1,
    )
    if poziom == 1:
        return DetektorKompozyt("poziom1", [warstwa_regul, model])
    if poziom == 2:
        return DetektorKompozyt("poziom2", [warstwa_regul, model])
    poziom3 = DetektorUzupełniający(
        "poziom3",
        podstawa=[warstwa_regul, model],
        uzup=SlownikImionDetektor(),
    )
    if not pakiet_rozszerzony:
        return poziom3
    return DetektorUzupełniający(
        "poziom3+rozszerzony",
        podstawa=[poziom3],
        uzup=wczytaj_lfm25(katalog, wariant="q4-bl32", provider=provider, rozszerzony=True),
        typy_uzup=frozenset(
            {TypEncji.IP, TypEncji.KARTA, TypEncji.SWIFT, TypEncji.LOGIN}
        ),
    )


class SlownikImionDetektor:
    """Wykrywacz słownikowy OSOBA (K2d, wariant B): imię z listy + następne
    słowo z wielkiej litery, w dowolnej formie fleksyjnej — dopasowanie po
    rdzeniu imienia (`osoby.rdzen_nazwiska`, ta sama heurystyka końcówek).

    SIMPLIFICATION: rdzeń = zrzucenie jednej końcówki fleksyjnej zamiast
    lematyzacji (Jan/Jana/Janem, Anna/Anny/Annie działają); rozbudować, gdy
    pomiar pokaże FN na nietrywialnych odmianach.
    """

    nazwa = "slownik-imion"
    typy = frozenset({TypEncji.OSOBA})
    DANY_PLIK = Path(__file__).resolve().parent / "dane" / "imiona_gus.txt"

    def __init__(self, plik: Path | None = None):
        self._stemy = wczytaj_imiona(plik or self.DANY_PLIK)

    def znajdz(self, tekst: str) -> list[Zakres]:
        fragmenty = [(m.start(), m.end(), m.group()) for m in _SLOWO.finditer(tekst)]
        wynik: list[Zakres] = []
        for i in range(len(fragmenty) - 1):
            (s1, e1, _), (s2, e2, _) = fragmenty[i], fragmenty[i + 1]
            s1, e1 = _zadość_liter(tekst, s1, e1)
            s2, e2 = _zadość_liter(tekst, s2, e2)
            if s1 >= e1 or s2 >= e2:
                continue  # sam_interpunkcja
            if not tekst[s2].isupper():
                continue  # wymagane: następne słowo z wielkiej litery
            if not tekst[e1 : s2].isspace():
                continue  # pomiędzy słowami tylko biały znak
            if rdzen_nazwiska(tekst[s1:e1]) in self._stemy:
                wynik.append(Zakres(s1, e2, TypEncji.OSOBA, 1.0, self.nazwa))
        return wynik


_SLOWO = re.compile(r"\S+")


def _zadość_liter(tekst: str, start: int, koniec: int) -> tuple[int, int]:
    """Obcięcie interpunkcji na brzegach fragmentu („Jan,” -> „Jan")."""
    while start < koniec and not tekst[start].isalpha():
        start += 1
    while koniec > start and not tekst[koniec - 1].isalpha():
        koniec -= 1
    return start, koniec


def wczytaj_imiona(plik: Path) -> dict[str, str]:
    """Słownik imion -> rdzeń -> forma bazowa; `#` nagłówki pominięte.

    Plik `niewidka/dane/imiona_gus.txt` (K2d): rejestrowane kolumny `Imię<TAB>liczba`,
    wygenerowany przez `narzedzia/pobierz_imiona.py` (GUS/dane.gov.pl, CC0 1.0).
    """
    if not plik.is_file():
        raise BladDetektora(f"brak słownika imion: {plik}")
    stemy: dict[str, str] = {}
    for linia in plik.read_text(encoding="utf-8").splitlines():
        linia = linia.strip()
        if not linia or linia.startswith("#"):
            continue
        imię = linia.split("\t", 1)[0].strip()
        if imię and imię.isalpha():
            stemy[rdzen_nazwiska(imię)] = imię
    if not stemy:
        raise BladDetektora(f"pusty słownik imion: {plik}")
    return stemy


class DetektorKompozyt:
    """Kilka detektorów za jednym interfejsem; duplikaty zdejmuje scalanie (LLD §4)."""

    def __init__(self, nazwa: str, czesci: list[Detektor]):
        self.nazwa = nazwa
        self.czesci = czesci
        self.typy: frozenset[TypEncji] = frozenset().union(*(c.typy for c in czesci))
    def znajdz(self, tekst: str) -> list[Zakres]:
        kandydaci = [z for czesc in self.czesci for z in czesc.znajdz(tekst)]
        return scal(tekst, kandydaci)


class DetektorUzupełniający:
    """Poziom 2 wariant uzupełniający (K2c): reguły + bardsai jako podstawa,
    LFM2.5 dodaje zakresy WYŁĄCZNIE wybranych typów (`typy_uzup`, domyślnie
    OSOBA) tam, gdzie nie nachodzą na żaden zakres z podstawy (podstawa ma
    pierwszeństwo granic). K7b: pakiet Rozszerzony podaje 4 typy poza regułami.
    """

    def __init__(
        self,
        nazwa: str,
        podstawa: list[Detektor],
        uzup: Detektor,
        wariant_b: bool = False,
        typy_uzup: frozenset[TypEncji] | None = None,
    ):
        self.nazwa = nazwa
        self.podstawa = podstawa
        self.uzup = uzup
        self.wariant_b = wariant_b
        self.typy_uzup = typy_uzup or frozenset({TypEncji.OSOBA})
        self.typy: frozenset[TypEncji] = frozenset().union(
            *(c.typy for c in podstawa)
        ) | (frozenset(uzup.typy) & self.typy_uzup)

    def znajdz(self, tekst: str) -> list[Zakres]:
        kandydaci_podstawa = [z for czesc in self.podstawa for z in czesc.znajdz(tekst)]
        kandydaci_uzup = self.uzup.znajdz(tekst)
        # Dodaj tylko wybrane typy i tylko tam, gdzie nie nachodzą na podstawę
        dodatkowe: list[Zakres] = []
        for z in kandydaci_uzup:
            if z.typ not in self.typy_uzup:
                continue
            # sprawdź czy nachodzi na cokolwiek z podstawy
            nachodzi = False
            for p in kandydaci_podstawa:
                # nachodzenie - standardowe nakładanie się przedziałów
                if not (z.koniec <= p.start or p.koniec <= z.start):  # mają część wspólną
                    nachodzi = True
                    break
            if nachodzi:
                continue
            if self.wariant_b:
                # przyjmowany tylko, gdy zaczyna się wielką literą i ma ≥ 2 znaki
                if z.koniec - z.start < 2:
                    continue
                if z.start >= len(tekst) or not tekst[z.start].isupper():
                    continue
            dodatkowe.append(z)
        wszystkie = list(kandydaci_podstawa) + dodatkowe
        return scal(tekst, wszystkie)


def okna_tokenow(n: int, okno: int, krok: int, offset: int = 0) -> list[tuple[int, int]]:
    """Przesuwne okna tokenów (zakładka = okno - krok); ostatnie dociągnięte do końca.

    `offset` = start pierwszego okna (przebieg półkrokowy K2d: offset = krok // 2);
    puste okno wyjście dla offsetu != 0 przy tekstach krótszych niż okno (duplikat).
    """
    if n <= 0:
        return []
    if n <= okno:
        return [(0, n)] if offset == 0 else []
    wynik = [(start, start + okno) for start in range(offset, n - okno + 1, krok)]
    if not wynik:
        return [(n - okno, n)]
    if wynik[-1][1] < n:
        wynik.append((n - okno, n))
    return wynik


def zdekoduj_bio(
    tokeny: list[tuple[str, tuple[int, int], float]],
    mapa: dict[tuple[str, ...], TypEncji],
) -> list[tuple[int, int, TypEncji, float]]:
    """BIO/BIOES -> zakresy znakowe (start, koniec, typ, pewność = min. tokenów).

    `tokeny` to (etykieta, offsety znakowe, pewność); etykiety nieobecne w `mapa`
    są pomijane (adapter modelu decyduje, które typy model dostarcza). I- po
    B/I tego samego typu kontynuuje encję; I innego typu albo bez B kończy bieżącą.
    BIOES (LFM2.5): E- kończy encję (dokleja swój token), S- to encja jedno-tokenowa;
    E/S poza mapą albo bez rozpoczętej encji swojego typu są pomijane.
    """
    wynik: list[tuple[int, int, TypEncji, float]] = []
    biezaca: tuple[int, int, TypEncji, float] | None = None
    biezaca_klasa: tuple[str, ...] | None = None
    for etykieta, (start, koniec), pewnosc in tokeny:
        if start == koniec:  # token specjalny/wypadek
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            continue
        if not (len(etykieta) > 2 and etykieta[1] == "-"):
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            continue
        schemat, klasa = etykieta[:1], etykieta[2:]
        klucz = (klasa,)
        if klucz not in mapa:
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            continue
        if schemat == "S":  # encja jedno-tokenowa: zamknij bieżącą, dodaj swoją
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            wynik.append((start, koniec, mapa[klucz], pewnosc))
            continue
        if schemat == "E":  # ostatni token encji: doklej i zamknij
            if biezaca is not None and biezaca_klasa == klucz:
                wynik.append((biezaca[0], koniec, biezaca[2], min(biezaca[3], pewnosc)))
            else:
                _zamknij(biezaca, wynik)  # E bez swojego B/I — pomijane
            biezaca, biezaca_klasa = None, None
            continue
        if schemat == "B" or klucz != biezaca_klasa:
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            if schemat == "I":
                continue  # I bez swojego B — fragment niepełny, pomijany
            typ = mapa[klucz]
            biezaca, biezaca_klasa = (start, koniec, typ, pewnosc), klucz
        else:  # I kontynuuje bieżącą encję
            assert biezaca is not None
            biezaca = (biezaca[0], koniec, biezaca[2], min(biezaca[3], pewnosc))
    _zamknij(biezaca, wynik)
    return wynik


def _zamknij(
    biezaca: tuple[int, int, TypEncji, float] | None,
    wynik: list[tuple[int, int, TypEncji, float]],
) -> None:
    if biezaca is not None:
        wynik.append(biezaca)
