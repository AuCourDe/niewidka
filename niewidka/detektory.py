"""Detectors: shared interface, sliding windows, ONNX model adapters. Differences between
models (label scheme, special tokens) live in the adapter. An error = `BladDetektora`
(fail-closed)."""

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
from niewidka.pakiety import KATALOG_PAKIETOW, BladPakietu, Pakiet, wczytaj_bajty_pakietu
from niewidka.reguly import REGULY
from niewidka.reguly import znajdz as znajdz_reguly
from niewidka.scalanie import scal


class BladDetektora(Exception):
    """Failure of the detection layer - fail-closed: no document goes through "without the layer"."""


class Detektor(Protocol):
    nazwa: str
    typy: frozenset[TypEncji]

    def znajdz(self, tekst: str) -> list[Zakres]: ...


class RegulyDetektor:
    """Rules + merging: the rule-based detection layer."""

    nazwa = "reguly"
    typy = frozenset(r.typ for r in REGULY)

    def znajdz(self, tekst: str) -> list[Zakres]:
        return scal(tekst, znajdz_reguly(tekst))


@dataclass(frozen=True)
class AdapterModelu:
    """Mapping of model labels to Niewidka types; classes outside the map are skipped."""

    nazwa: str
    mapa: dict[tuple[str, ...], TypEncji]

    @property
    def typy(self) -> frozenset[TypEncji]:
        return frozenset(self.mapa.values())

    def zwroc_typ(self, etykieta: str) -> TypEncji | None:
        if len(etykieta) > 2 and etykieta[1] == "-":  # B/I/E/S: the adapter's scheme decides
            return self.mapa.get((etykieta[2:],))
        return None


# Bardsai (level 1): supplies ONLY OSOBA; types with a checksum and exact boundaries
# come from the rules (confidence 1.0); adding the model's ADRES/EMAIL etc.
# would blur the boundaries (merge union = wider range = FN+FP).
# The other labels (LOCATION, ORGANIZATION_NAME, ...) are skipped.
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
    """ONNX token-classification detector behind the Detektor interface.

        Tokenizes the whole text (`tokenizers`, character offsets), sliding token windows,
        per-window inference and BIO decoding by the adapter. Duplicates between
        windows are removed by the global merge (above). `SIMPLIFICATION`: windows over the
        full token sequence (with special tokens), no <s>/</s> added per window -
        the overlap (window - step) compensates the boundaries; extend when measurement shows
        entities lost at window edges.
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
        watki: int = 0,
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
        # Lowered threshold: class label columns from the map (B-/I-/E-/S-) and
        # (B-label, I-label) pairs for gluing an above-threshold continuation.
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
                # tokenizer.json may cap encodings at the model length (bardsai: 512);
                # the windows below need the whole text
                tokenizer_obj.no_truncation()
                tokenizer_obj.no_padding()
            self._tokenizer = tokenizer_obj
            if sesja is None:
                import onnxruntime as ort

                dostepne = ort.get_available_providers()
                if provider not in dostepne:
                    provider = "CPUExecutionProvider"
                # session opened from bytes - the same ones that
                # passed SHA verification (no check-then-use window on disk)
                model_bajty = model if isinstance(model, bytes) else Path(model).read_bytes()
                argumenty: dict = {}
                if watki > 0:  # 0 = onnxruntime decides (inference server: [modele] watki)
                    opcje = ort.SessionOptions()
                    opcje.intra_op_num_threads = watki
                    argumenty["sess_options"] = opcje
                sesja = ort.InferenceSession(model_bajty, providers=[provider], **argumenty)
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
        except Exception as e:  # fail-closed: any model/tokenizer failure
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
        if getattr(enc, "overflowing", None):  # the cut-off rest would go unchecked
            raise BladDetektora(f"{self.nazwa}: tokenizer obciął tekst")
        tokeny = list(zip(enc.ids, enc.offsets))
        wynik: list[Zakres] = []
        # Second pass of windows shifted by half a step: an entity on a window boundary
        # has the full label chain in the shifted window - without it the first part
        # ends up as B-frAGMENT and the rest (I without B) is dropped in decoding.
        okna: list[tuple[int, int]] = []
        przesunięcia = (0, self._krok // 2) if self._pół_krok else (0,)
        for przesunięcie in przesunięcia:
            for okno in okna_tokenow(len(tokeny), self._okno, self._krok, przesunięcie):
                if okno not in okna:  # the half-step pass repeats the final window
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
                if offsets[0] == offsets[1]:  # special token / edge case
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
                            # a repeated hit of the same class is boosted by the I- continuation
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
        """The most confident class from the adapter map at token i (independent of argmax)."""
        najlepsza: tuple[tuple[str, ...], float] | None = None
        for klucz, kolumny in self._kolumny_klas.items():
            p = max((float(prawdopodobienstwa[i, k]) for k in kolumny), default=0.0)
            if najlepsza is None or p > najlepsza[1]:
                najlepsza = (klucz, p)
        return najlepsza


def rozciagnij_do_slow(zakresy: list[tuple[int, int]], tekst: str) -> list[tuple[int, int]]:
    """Model ranges extended to word boundaries (subword artifacts).

        Subword tokenizers cut words ('Kowal' -> 'Ko'+'wal'); the model may tag
        only a part or give B- on both subtokens. The range does not change when it is already
        aligned to word boundaries. Duplicates/overlaps are removed later by merging.
        """
    wynik = []
    for start, koniec in zakresy:
        # BPE tokens carry a leading space in the offset ('ĠPiot' -> (14,19)); without
        # trimming, the extension would spill onto the previous word.
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
    katalog_pakietow: Path | list[Pakiet] | None = None,
    watki: int = 0,
) -> OnnxDetektor:
    """OnnxDetektor from bardsai weights in `katalog` (NIEWIDKA_MODELE_KATALOG).

        `próg` = lowered confidence threshold for OSOBA classes (adds candidates below
        argmax) and `pół_krok` = second pass of windows by half a step (window boundaries).
        Weights are verified against the TRUSTED package catalog
        (basic), and exactly the bytes that passed hashing go to the session/tokenizer;
        the local manifest does not set the expected sums.
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
            watki=watki,
        )
    except BladPakietu as blad:
        raise BladDetektora(f"pakiet Podstawowy: {blad}") from blad


# LFM2.5 (level 2): like bardsai it supplies ONLY OSOBA (identity.person_name,
# BIOES scheme) - types with a checksum and exact boundaries come from the rules;
# the other 39 model classes are skipped.
ADAPTER_LFM25 = AdapterModelu(
    nazwa="onnx:lfm25",
    mapa={
        ("identity.person_name",): TypEncji.OSOBA,
    },
)


# Extended package: LFM2.5 Q4 works ONLY as a detector of types that the rules and
# bardsai do not cover - IP, payment card, SWIFT and logins - and only where the range
# does not overlap other detections. It does not touch OSOBA or rule-based types
# (measured: it hurts there).
ADAPTER_LFM25_ROZSZERZONY = AdapterModelu(
    nazwa="onnx:lfm25-rozszerzony",
    mapa={
        ("contact.ip_address",): TypEncji.IP,
        ("financial.credit_card",): TypEncji.KARTA,
        ("financial.swift_bic",): TypEncji.SWIFT,
        ("online.username",): TypEncji.LOGIN,
    },
)


# Mapping of LFM2.5 classes -> Niewidka types (full 27-type schema in
# ~/models/niewidka/lfm25/label_schema.json). Classes outside the map are not
# detected today - the measurement reports them under their own LFM2.5 names.
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
    """LFM2.5 class -> Niewidka type; a class outside the map falls out under its raw name.

        national_id is decided by the shape of the number (the model does not tell Polish numbers apart):
        10 digits = NIP, 9/14 = REGON, 11 = PESEL; with letters = DOKUMENT (ID card/passport
        in the same class), otherwise PESEL by default.
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
    katalog_pakietow: Path | list[Pakiet] | None = None,
    watki: int = 0,
) -> OnnxDetektor:
    """OnnxDetektor from the exported LFM2.5 ONNX (`lfm25/{fp32,int8}/`).

        The variant is chosen by the quantization directory; both have an SHA-256 manifest from the export.
        `rozszerzony=True` = Extended package adapter (only IP/KARTA/
        SWIFT/LOGIN); in measurement these types are the only real gain from this model.
        The package variant `q4-bl32` is verified against the
        TRUSTED package catalog and loaded from the verified bytes; the measurement
        variants (fp32/int8) keep the manifest from the export.
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
                watki=watki,
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
        watki=watki,
    )


def wczytaj_poziom2(
    katalog: Path,
    provider: str = "CPUExecutionProvider",
) -> DetektorKompozyt:
    """Level 2: rules + bardsai + LFM2.5; duplicates are removed by merging."""
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
    """The LFM2.5 supplementary variant adds OSOBA only where it does not overlap
        ranges from the rules or bardsai. Bardsai/rules take precedence.
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
    watki: int = 0,
    katalog_pakietow: Path | list[Pakiet] | None = None,
) -> Detektor:
    """Product levels (quality slider) - the ONLY function that composes a level;
        used by the core (`rdzen.zbuduj_detektor`) and the measurement (`narzedzia.pomiar`), so
        the measurement measures exactly what the product computes.

        1 = rules + bardsai (no threshold, no half step); 2 = variant A (bardsai with the OSOBA confidence threshold `próg_osoba` + second window pass shifted by half a step);
        3 = variant B (2 + GUS first-name dictionary, CC0). `reguly` = replacement of the rule layer
        (the core inserts the `_BezDaty` filter when `wykrywaj_date=False`).
        `pakiet_rozszerzony=True` adds LFM2.5 Q4 from the Extended package to level 3
        (only IP/KARTA/SWIFT/LOGIN, no overlap); the `lfm25/q4-bl32` subdirectory
        is the condition - without the package level 3 works as before.
        """
    if poziom not in (1, 2, 3):
        raise ValueError(f"poziom poza 1-3: {poziom}")
    warstwa_regul = RegulyDetektor() if reguly is None else reguly
    model = wczytaj_bardsai(
        katalog,
        provider=provider,
        próg=None if poziom == 1 else próg_osoba,
        pół_krok=poziom > 1,
        katalog_pakietow=katalog_pakietow,
        watki=watki,
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
        uzup=BezSwiftWNaglowku(
            wczytaj_lfm25(
                katalog,
                wariant="q4-bl32",
                provider=provider,
                rozszerzony=True,
                katalog_pakietow=katalog_pakietow,
                watki=watki,
            )
        ),
        typy_uzup=frozenset(
            {TypEncji.IP, TypEncji.KARTA, TypEncji.SWIFT, TypEncji.LOGIN}
        ),
    )


class BezSwiftWNaglowku:
    """Rejects a SWIFT from LFM2.5 whose direct neighbour (only a space between them)
        is another all-capitals word: a heading ("STOŁECZNEGO WARSZAWY"),
        not a bank code. SWIFT/BIC labels do not count.
        """

    def __init__(self, wewnetrzny):
        self._wewnetrzny = wewnetrzny
        self.nazwa = wewnetrzny.nazwa
        self.typy = wewnetrzny.typy

    def znajdz(self, tekst: str) -> list[Zakres]:
        return [
            z
            for z in self._wewnetrzny.znajdz(tekst)
            if z.typ is not TypEncji.SWIFT or not _sasiad_wielkimi(tekst, z.start, z.koniec)
        ]


_SASIAD_PRZED = re.compile(r"([^\W\d_]{3,})[ \t]+$")
_SASIAD_ZA = re.compile(r"[ \t]+([^\W\d_]{3,})")


def _sasiad_wielkimi(tekst: str, start: int, koniec: int) -> bool:
    poczatek_linii = tekst.rfind("\n", 0, start) + 1
    if re.search(r"\b(?:SWIFT|BIC)\b", tekst[poczatek_linii:start]):
        return False  # explicit label before the code
    przed = _SASIAD_PRZED.search(tekst, max(0, start - 40), start)
    za = _SASIAD_ZA.match(tekst, koniec)
    return any(
        m and m.group(1).isupper() and m.group(1) not in ("SWIFT", "BIC") for m in (przed, za)
    )


class SlownikImionDetektor:
    """Dictionary-based OSOBA detector: a first name from the list + the next
        capitalized word, in any inflected form - matched by the
        first-name stem (`osoby.rdzen_nazwiska`, the same ending heuristic).

        SIMPLIFICATION: stem = dropping one inflectional ending instead of
        lemmatization (Jan/Jana/Janem, Anna/Anny/Annie work); extend when
        measurement shows FN on non-trivial inflections.
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
                continue  # only punctuation
            if not tekst[s1].isupper() or not tekst[s2].isupper():
                continue  # both words capitalized ("marki Skoda" is not Marek)
            if not tekst[e1 : s2].isspace():
                continue  # only whitespace between the words
            if rdzen_nazwiska(tekst[s1:e1]) in self._stemy:
                wynik.append(Zakres(s1, e2, TypEncji.OSOBA, 1.0, self.nazwa))
        return wynik


_SLOWO = re.compile(r"\S+")


def _zadość_liter(tekst: str, start: int, koniec: int) -> tuple[int, int]:
    """Trim punctuation at the fragment edges ("Jan," -> "Jan")."""
    while start < koniec and not tekst[start].isalpha():
        start += 1
    while koniec > start and not tekst[koniec - 1].isalpha():
        koniec -= 1
    return start, koniec


def wczytaj_imiona(plik: Path) -> dict[str, str]:
    """First-name dictionary -> stem -> base form; `#` headers skipped.

        File `niewidka/dane/imiona_gus.txt`: columns `Imię<TAB>count`,
        generated by `narzedzia/pobierz_imiona.py` (GUS/dane.gov.pl, CC0 1.0).
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
    """Several detectors behind one interface; duplicates are removed by merging."""

    def __init__(self, nazwa: str, czesci: list[Detektor]):
        self.nazwa = nazwa
        self.czesci = czesci
        self.typy: frozenset[TypEncji] = frozenset().union(*(c.typy for c in czesci))
    def znajdz(self, tekst: str) -> list[Zakres]:
        kandydaci = [z for czesc in self.czesci for z in czesc.znajdz(tekst)]
        return scal(tekst, kandydaci)


class DetektorUzupełniający:
    """Level 2 supplementary variant: rules + bardsai as the base,
        LFM2.5 adds ranges ONLY of the chosen types (`typy_uzup`, OSOBA by default)
        where they do not overlap any range from the base (the base wins
        on boundaries). The Extended package provides 4 types outside the rules.
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
        # Add only the chosen types and only where they do not overlap the base
        dodatkowe: list[Zakres] = []
        for z in kandydaci_uzup:
            if z.typ not in self.typy_uzup:
                continue
            # check whether it overlaps anything from the base
            nachodzi = False
            for p in kandydaci_podstawa:
                # overlap - the standard interval intersection
                if not (z.koniec <= p.start or p.koniec <= z.start):  # have a common part
                    nachodzi = True
                    break
            if nachodzi:
                continue
            if self.wariant_b:
                # accepted only when it starts with a capital letter and has >= 2 characters
                if z.koniec - z.start < 2:
                    continue
                if z.start >= len(tekst) or not tekst[z.start].isupper():
                    continue
            dodatkowe.append(z)
        wszystkie = list(kandydaci_podstawa) + dodatkowe
        return scal(tekst, wszystkie)


def okna_tokenow(n: int, okno: int, krok: int, offset: int = 0) -> list[tuple[int, int]]:
    """Sliding token windows (overlap = window - step); the last one is stretched to the end.

        `offset` = start of the first window (half-step pass: offset = step // 2);
        for offset != 0 and texts shorter than the window the empty window is skipped (duplicate).
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
    """BIO/BIOES -> character ranges (start, end, type, confidence = min. over tokens).

        `tokeny` are (label, character offsets, confidence); labels absent from `mapa`
        are skipped (the model adapter decides which types the model supplies). I- after
        B/I of the same type continues the entity; I of another type or without B ends the current one.
        BIOES (LFM2.5): E- ends the entity (appends its token), S- is a single-token entity;
        E/S outside the map or without a started entity of their type are skipped.
        """
    wynik: list[tuple[int, int, TypEncji, float]] = []
    biezaca: tuple[int, int, TypEncji, float] | None = None
    biezaca_klasa: tuple[str, ...] | None = None
    for etykieta, (start, koniec), pewnosc in tokeny:
        if start == koniec:  # special token / edge case
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
        if schemat == "S":  # single-token entity: close the current one, add its own
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            wynik.append((start, koniec, mapa[klucz], pewnosc))
            continue
        if schemat == "E":  # last token of the entity: append and close
            if biezaca is not None and biezaca_klasa == klucz:
                wynik.append((biezaca[0], koniec, biezaca[2], min(biezaca[3], pewnosc)))
            else:
                _zamknij(biezaca, wynik)  # E without its own B/I - skipped
            biezaca, biezaca_klasa = None, None
            continue
        if schemat == "B" or klucz != biezaca_klasa:
            biezaca, biezaca_klasa = _zamknij(biezaca, wynik), None
            if schemat == "I":
                continue  # I without its own B - incomplete fragment, skipped
            typ = mapa[klucz]
            biezaca, biezaca_klasa = (start, koniec, typ, pewnosc), klucz
        else:  # I continues the current entity
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
