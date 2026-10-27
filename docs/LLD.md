# Niewidka — LLD (projekt niskiego poziomu)

Stan: 2026-10-27, wersja 1. Nadrzędne: `HLD.md`, decyzje `KONSULTACJE.md` (wiążące).
Python 3.11+, rdzeń bez HTTP/GUI, testy `tests/` (pytest), web bez frameworka.
Zakresy i offsety liczone **w znakach segmentu** (akapit/komórka/linia), nie całego dokumentu.

## 1. Struktura pakietu

```
niewidka/
├── __init__.py        # wersja
├── model.py           # TypEncji, Zakres, Encja, RunInfo, Segment, Dokument
├── konfig.py          # konfiguracja: plik TOML + env (env ma pierwszeństwo)
├── reguly.py          # regexy + walidatory sum kontrolnych
├── detektory.py       # interfejs Detektor + ONNX (bardsai, LFM2.5), okna przesuwne
├── scalanie.py        # unia zakresów z priorytetami
├── osoby.py           # grupowanie osób po odmianach
├── znaczniki.py       # nadanie [TYP_N], zamiana w segmentach
├── mapa.py            # Mapa, serializacja JSON, AES-256-GCM
├── klucze.py          # klucz: keyring albo plik z env; CLI
├── kontrola.py        # kontrola wyniku (poziom 3)
├── jakosc.py          # R95 z kalibracji + wskaźnik dokumentu
├── api.py             # FastAPI: 3 endpointy, kolejka, limity
├── dane/r95.json      # progi R95 policzone offline (dane kalibracji, nie konfiguracja)
├── web/               # index.html, apka.js, styl.css
└── formaty/
    ├── __init__.py    # rejestr: rozszerzenie → AdapterFormatu
    ├── tekst.py  docx_.py  odt_.py  xlsx_.py  pptx_.py  pdf_.py
narzedzia/             # poza pakietem: kalibracja R95, pomiar, generator plików wzorcowych
tests/
```

## 2. Model danych (`model.py`)

```python
class TypEncji(enum.StrEnum):
    OSOBA, PESEL, NIP, REGON, ADRES, TELEFON, EMAIL, IBAN, DOKUMENT, DATA, INNE

@dataclass
class Zakres:
    start: int                 # znak w segment.tekst, włącznie
    koniec: int                # wyłącznie
    typ: TypEncji
    pewnosc: float             # 0..1; reguły z sumą kontrolną = 1.0
    zrodlo: str                # "regula", "onnx:bardsai", "onnx:lfm25"
    suma_kontrolna: bool = False

@dataclass
class Encja:
    zakres: Zakres
    tekst: str                 # tekst powierzchniowy znaleziska
    oznaczenie: str | None = None   # "OSOBA_1" po grupowaniu i numeracji
    klucz_grupy: str | None = None  # klucz grupowania osób

@dataclass
class RunInfo:
    tekst: str
    element: Any               # uchwyt węzła (lxml/run python-docx/cella arkusza)

@dataclass
class Segment:
    tekst: str                 # tekst złączony z runów
    runs: list[RunInfo]
    starts: list[int]          # starts[i] = offset runs[i].tekst w segment.tekst

@dataclass
class Dokument:
    format: str                # "docx", "odt", ...
    segmenty: list[Segment]
```

## 3. Reguły (`reguly.py`) — regex + sumy kontrolne

```python
@dataclass(frozen=True)
class Regula:
    typ: TypEncji
    wzorzec: re.Pattern[str]
    walidator: Callable[[str], bool] | None   # suma kontrolna na znormalizowanym tekście
    suma_kontrolna: bool                      # True → najwyższy priorytet przy scalaniu

REGULY: tuple[Regula, ...]   # PESEL, NIP, REGON, IBAN, dowód, e-mail, telefon PL, adres, data
```

- Walidatory z **python-stdnum**: `stdnum.pl.pesel`, `stdnum.pl.nip`, `stdnum.pl.regon`,
  `stdnum.iban`. Dowód osobisty: sprawdzić pokrycie stdnum; brak → własny walidator wag
  (7,3,1,7,3,…) ~10 linii.
- Wzorce dopuszczają spacje/myślniki wewnątrz numerów; walidator dostaje tekst znormalizowany
  (bez spacji i myślników).
- Adres: heurystyka (`ul.`/`al.`/`ulica` + numer), `suma_kontrolna=False`.
- DATA: pełne daty, typ włączany konfiguracją (`wykrywaj_date`, domyślnie tak) — data to
  quasi-identyfikator często legalny.

## 4. Detektory (`detektory.py`) — ONNX za jednym interfejsem

```python
class Detektor(Protocol):
    nazwa: str
    typy: frozenset[TypEncji]
    def znajdz(self, tekst: str) -> list[Zakres]: ...

class RegulyDetektor:                    # opakowuje REGULY
class OnnxDetektor:
    def __init__(self, nazwa: str, model: Path, tokenizer: Path,
                 etykiety: dict[str, TypEncji], okno: int = 510, krok: int = 448): ...
```

- `OnnxDetektor`: `onnxruntime.InferenceSession` (CPU `INT8`; provider z konfiguracji,
  GPU opcjonalnie). Długie segmenty → przesuwne okna tokenów (nakładanie = okno − krok),
  zakresy tokenów → znaki przez `offset_mapping` z biblioteki `tokenizers`; duplikaty
  między oknami zdejmuje potem globalne scalanie.
- Wagi z `NIEWIDKA_MODELE_KATALOG`, `manifest.json` z SHA-256 sprawdzany przy ładowaniu,
  brak pobierania w runtime.
- Błąd detektora = `BladDetektora` (fail-closed): nie zwracamy dokumentu przetworzonego
  bez pełnej ustalonej warstwy detekcji.

## 5. Scalanie (`scalanie.py`)

```python
def scal(tekst_segmentu: str, kandydaci: list[Zakres]) -> list[Zakres]:
    """Grupy nakładających się zakresów → zwycięzca grupy wg: suma_kontrolna >
    długość > pewność > źródło (reguła > model). Nakładające się encje różnych
    typów o pełnym pokryciu (np. nazwisko w środku adresu) — wygrywa bardziej
    specyficzny typ. Deterministyczne."""
```

## 6. Grupowanie osób (`osoby.py`)

```python
def pogrupuj(encje: list[Encja]) -> None:
    """Ustawia klucz_grupy: (rdzeń_nazwiska, imię/inicjały). Rdzeń nazwiska = lower()
    + obcięcie końcówek odmiany (-ski/-ska, -cki/-cka, -dzki/-dzka, -ny/-na, …).
    Różne imię + to samo nazwisko = różne osoby (nie łączymy Jana i Piotra)."""
```

`SIMPLIFICATION: heurystyka końcówek zamiast lematyzacji (Morfeusz 2) — rozbudować, gdy
pomiar pokaże błędne łączenia/rozdzielenia.` (decyzja z `KONSULTACJE.md`)

## 7. Znaczniki (`znaczniki.py`)

Format: `[TYP_N]` — `N` licznik per typ w kolejności wystąpienia w dokumencie;
`[OSOBA_1]` wspólne dla wszystkich form tej osoby (odmiany). Czytelny, bez formy w treści
znacznika. Zamiana od końca segmentu (offsety nie uciekają).

```python
def nadaj_oznaczenia(encje: list[Encja]) -> None
def zamien_w_segment(segment_tekst: str, encje: list[Encja]) -> tuple[str, list[int]]
    # tekst ze znacznikami + "kolejny" (globalny numer wystąpienia znacznika) dla mapy
```

Dopisek na początku (akapit/arkusz/strona): „ZANONIMIZOWANO w Niewidka. Dokument zawiera
znaczniki [TYP_N]; oryginał odtworzysz plikiem mapy i kluczem."

## 8. Mapa i klucze (`mapa.py`, `klucze.py`)

Mapa jawna (przed szyfrowaniem):

```json
{
  "wersja": 1,
  "utworzono": "2026-10-27T23:36:00+02:00",
  "poziom": 2,
  "wpisy": [
    {"typ": "OSOBA", "oznaczenie": "OSOBA_1", "wystapienia": [
      {"kolejny": 0, "oryginal": "Jan Kowalski", "forma": "Jan Kowalski"},
      {"kolejny": 5, "oryginal": "Jana Kowalskiego", "forma": "Jan Kowalski"}]},
    {"typ": "PESEL", "oznaczenie": "PESEL_1", "wystapienia": [
      {"kolejny": 2, "oryginal": "44051401359", "forma": "44051401359"}]}
  ]
}
```

- `kolejny` = globalny numer wystąpienia znacznika (przywracanie 1:1);
  `oryginal` = tekst powierzchniowy tego wystąpienia (zachowuje odmianę);
  `forma` = forma podstawowa (fallback, gdy pozycja się rozjedzie).

```python
def zaszyfruj(mapa: Mapa, klucz: bytes) -> bytes
    # b"NWID" + wersja(1B) + nonce(12B) + AESGCM.encrypt(nonce, json, None)   [cryptography]
def odszyfruj(dane: bytes, klucz: bytes) -> Mapa    # zły tag/wersja → BladMapy

def pobierz_klucz(konfig: Konfig) -> bytes
    # 1) plik z NIEWIDKA_KLUCZ_PLIK (base64, 32 B, uprawnienia 0600),
    # 2) keyring[NIEWIDKA_KEYRING_USLUGA / konto "mapa"],
    # brak obu → BrakKlucza; brak fallbacku i cichego generowania.
```

CLI: `python -m niewidka.klucze nowy-plik <ścieżka>` / `do-keyringa`. Klucz nigdy w logach,
wyjątkach ani repo. Przywracanie: `/api/przywroc` podmienia znaczniki wg `kolejny` na
`oryginal`; w formatach bogatych znacznik wraca do miejsca znacznika (styl otoczenia).

## 9. Adaptery formatów (`formaty/`)

```python
class AdapterFormatu(Protocol):
    rozszerzenia: frozenset[str]
    def wczytaj(self, dane: bytes) -> Dokument: ...
    def zapisz(self, dok: Dokument) -> bytes: ...      # czyści metadane, dodaje dopisek
    def elementy_nieobslugiwane(self, dok: Dokument) -> list[str]: ...
```

- **Mapowanie przesunięć na runy**: encje wykryte w `segment.tekst`; wstawienie znacznika
  dzieli runy na granicach start/koniec (`starts`), nowy run dziedziczy styl lewego fragmentu.
- **txt**: jeden segment; trywialne.
- **docx** (python-docx + lxml): segment = akapit; scalenie tekstów runów + `starts`;
  czyszczone: komentarze, śledzone zmiany, nagłówki/stopki, właściwości dokumentu.
  Najtrudniejszy adapter — większość pracy.
- **odt** (odfpy/lxml): jak docx, segment = węzeł tekstowy akapitu.
- **xlsx** (openpyxl): segment = komórka tekstowa; dopisek = arkusz „ZANONIMIZOWANO";
  ukryte arkusze → blokada albo odsłonięcie (konfiguracja), nigdy cicho.
- **pptx** (python-pptx): segment = kształt tekstowy; notatki prelegenta czyszczone.
- **pdf** (PyMuPDF): segment = blok tekstu; zamiana = adnotacja redakcyjna (usuń treść)
  + wstaw znacznik; układ może się zmienić (jawne ostrzeżenie). PDF bez warstwy tekstu
  (skan) → `ElementNieobslugiwany` (OCR poza MVP). Uwaga licencyjna: PyMuPDF to AGPL-3.0 —
  decyzja przed dystrybucją poza organizacją (alternatywa: pypdfium2).
- **Blokada**: makra VBA, osadzone obiekty, obrazy z tekstem → eksport przerwany
  z listą (`ElementNieobslugiwany` → HTTP 422), zgodnie z `KONSULTACJE.md`.

## 10. Kontrola wyniku (`kontrola.py`, poziom 3)

```python
def kontroluj(dane: bytes, format: str, detektory: list[Detektor]) -> list[Ostrzezenie]
    # zapisany plik wczytany jak obcy dokument → pełna detekcja przesuniętymi oknami
    # → znaleziska niebędące znacznikami = Ostrzezenie{typ, fragment, segment}
```

## 11. Ocena jakości (`jakosc.py`)

```python
def r95_z_kalibracji(poziom: int, typ: TypEncji) -> float | None   # z dane/r95.json
def wskaznik_dokumentu(encje: list[Encja], ostrzezenia: list[Ostrzezenie]) -> int   # 0-100
```

- **R95** (ryzyko resztkowe poziomu): `beta.ppf(0.95, k+1, n−k)` (Clopper–Pearson) liczony
  offline `narzedzia/kalibracja.py` (scipy tylko tam) na korpusie walidacyjnym; wynik
  w `dane/r95.json` — runtime nie wymaga scipy. To liczba dla poziomu, pokazywana w UI.
- **Wskaźnik dokumentu**: heurystyka bieżąca — 100 minus kary: encje niepotwierdzone
  (bez sumy kontrolnej i bez drugiego źródła), każde ostrzeżenie kontroli. Wagi w konfiguracji.
  Ostrzeżenia pokazywane obok, wskaźnik ich nie zastępuje.

## 12. API (`api.py`, FastAPI)

| Endpoint | Wejście | Wyjście |
|---|---|---|
| `POST /api/ukryj` | multipart: `plik` (albo pole `tekst`), `poziom` 1-3 | JSON: `wynik_base64`, `mapa_base64` (`.nwidka`), `wskaznik`, `r95`, `ostrzezenia[]`, `statystyki{typ: liczba}`; błędy 413/415/422/500/503 |
| `POST /api/przywroc` | multipart: `wynik`, `mapa` | plik/tekst odtworzony + lista rozbieżności form; 422 zła mapa, 500 brak klucza |
| `GET /api/stan` | — | wersja, załadowane modele, poziom domyślny, limity, stan kolejki |

- Modele ładowane raz przy starcie; inferencja przez `Semaphore(1)` (jeden proces),
  kolejka `maxsize=NIEWIDKA_KOLEJKA`, pełna → `503 + Retry-After`.
- Pliki wyłącznie w RAM; odpowiedzi `Cache-Control: no-store`; logi bez treści.

## 13. Web (`web/`, bez frameworka)

`index.html` + `apka.js` + `styl.css`: strefa upuszczania / textarea, suwak poziomów 1-3,
jawny wybór trybu („Na tym urządzeniu" / „Na serwerze organizacji"), `fetch()` + `FormData`,
wynik do pobrania + plik `.nwidka` do pobrania, wskaźnik, R95, lista ostrzeżeń, przełącznik
Ukryj/Przywróć (z plikiem mapy).

## 14. Konfiguracja (`konfig.py`) — nic na sztywno

Plik TOML (`--konfig <ścieżka>`, domyślnie `./niewidka.toml`) + env; **env ma pierwszeństwo**.

| Env | Klucz TOML | Domyślnie | Znaczenie |
|---|---|---|---|
| `NIEWIDKA_HOST` | `serwer.host` | `127.0.0.1` | nasłuch API |
| `NIEWIDKA_PORT` | `serwer.port` | `8390` | port API |
| `NIEWIDKA_POZIOM` | `detekcja.poziom` | `1` | domyślny poziom 1-3 |
| `NIEWIDKA_MODELE_KATALOG` | `detekcja.modele_katalog` | (wymagany od poziomu 1) | katalog wag + `manifest.json` |
| `NIEWIDKA_PROVIDER` | `detekcja.provider` | `CPUExecutionProvider` | provider onnxruntime |
| `NIEWIDKA_KLUCZ_PLIK` | `klucze.plik` | — | plik sekretów z kluczem (base64) |
| `NIEWIDKA_KEYRING_USLUGA` | `klucze.usluga` | `niewidka` | nazwa wpisu keyring |
| `NIEWIDKA_MAX_ROZMIAR_MB` | `limity.rozmiar_mb` | `25` | maks. rozmiar wejścia |
| `NIEWIDKA_MAX_TEKST_MB` | `limity.tekst_mb` | `1` | maks. wklejony tekst |
| `NIEWIDKA_KOLEJKA` | `limity.kolejka` | `4` | oczekujące w kolejce |
| `NIEWIDKA_TIMEOUT_S` | `limity.timeout_s` | `120` | timeout przetwarzania |
| `NIEWIDKA_WYKRYWAJ_DATE` | `detekcja.wykrywaj_date` | `true` | typ DATA |

## 15. Obsługa błędów

| Sytuacja | Sygnał | Zachowanie |
|---|---|---|
| element nieobsługiwany (makra, skan, osadzony obiekt) | `ElementNieobslugiwany` / 422 | eksport blokowany + lista elementów |
| brak klucza | `BrakKlucza` / 500 | jawny błąd, bez fallbacku |
| zła/uszkodzona mapa, zły tag GCM, wersja | `BladMapy` / 422 | odrzucenie, brak prób naprawy |
| nieznany format | / 415 | lista obsługiwanych w treści |
| plik za duży | / 413 | limit z konfiguracji |
| kolejka pełna | / 503 + `Retry-After` | klient czeka albo rezygnuje |
| błąd detektora/modelu | `BladDetektora` / 500 | **fail-closed** — nie zwracamy wyniku bez ustalonej warstwy detekcji |

## 16. Limity (domyślne, wszystkie w konfiguracji)

plik ≤ 25 MB; wklejony tekst ≤ 1 MB; kolejka 4 oczekujące + 1 w toku; timeout 120 s;
okno detektora 510 tokenów (krok 448); jeden proces inferencji.
