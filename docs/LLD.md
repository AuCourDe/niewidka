# Niewidka — LLD (projekt niskiego poziomu)

Stan: 2026-10-28 (wersja 1 z 2026-10-27 po przeglądach). Nadrzędne: `HLD.md`, decyzje
`KONSULTACJE.md` (wiążące). Odpowiedzi na przeglądy Astry i Gemini: §17.
Python 3.11+, rdzeń bez HTTP/GUI, testy `tests/` (pytest), web bez frameworka.
Zakresy i offsety liczone **w znakach segmentu** (akapit/komórka/linia), nie całego dokumentu.
MVP po zawężeniu: wklejony tekst + TXT + DOCX + web lokalny (`HLD.md` nagłówek).

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
    pewnosc: float             # 0..1; reguły z sumą kontrolną = 1.0, podejrzane = 0.5
    zrodlo: str                # "regula", "onnx:bardsai", "onnx:lfm25"
    suma_kontrolna: bool = False
    podejrzana: bool = False   # wzorzec pasuje, suma kontrolna błędna (Astra pkt 14)

@dataclass
class Encja:
    zakres: Zakres
    tekst: str                 # tekst powierzchniowy znaleziska
    oznaczenie: str | None = None   # "OSOBA_1" po grupowaniu i numeracji
    klucz_grupy: str | None = None  # klucz grupowania osób
    wariant: str | None = None      # "F2" — stabilny numer formy powierzchniowej osoby

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
- **Błędna suma kontrolna ≠ odrzucenie** (Astra pkt 14): dopasowanie do wzorca z nieprzechodzącą
  sumą daje encję z `podejrzana=True`, `suma_kontrolna=False`, pewność 0.5 — wchodzi do
  maskowania jak każda inna (nadmaskowanie z flagą jest bezpieczniejsze niż ciche pominięcie
  literówki w prawdziwym numerze). Miara: takie nadmaskowanie liczone osobno jako PN
  (`KRYTERIA.md` §1.3), nie jako FP.
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
- **Adapter per model** (przegląd Astry pkt 14): schemat etykiet (BIO/BIOES), tokeny
  specjalne i normalizacja różnią się między modelami — konwersja do `Zakres` żyje
  w adapterze modelu, nie we wspólnym kodzie; testy zgodności zakresów per adapter.
- Wagi z `NIEWIDKA_MODELE_KATALOG`, `manifest.json` z SHA-256 modelu, tokenizera i pliku
  etykiet, sprawdzany przy ładowaniu, brak pobierania w runtime.
- Błąd detektora = `BladDetektora` (fail-closed): nie zwracamy dokumentu przetworzonego
  bez pełnej ustalonej warstwy detekcji.

## 5. Scalanie (`scalanie.py`)

```python
def scal(tekst_segmentu: str, kandydaci: list[Zakres]) -> list[Zakres]:
    """Nakładające się zakresy tworzą grupę; maskowany obszar grupy to UNIA jej
    zakresów — wybór jednego zwycięzcy zostawiałby dziury (przegląd Astry pkt 1:
    [0,12)+[8,20) muszą dać [0,20)). Wybierana jest wyłącznie ETYKIETA grupy wg:
    suma_kontrolna > wewnętrzny przy pełnym pokryciu > długość > pewność >
    źródło (reguła > model); flaga `podejrzana` przechodzi z etykiety zwycięskiej.
    Deterministyczne niezależnie od kolejności wejścia; własność unii sprawdzona
    testem losowym w `tests/test_scalanie.py`."""
```

## 6. Grupowanie osób (`osoby.py`)

```python
def pogrupuj(encje: list[Encja]) -> None:
    """Ustawia klucz_grupy: (rdzeń_nazwiska, imię/inicjały). Rdzeń nazwiska = lower()
    + obcięcie końcówek odmiany (-ski/-ska, -cki/-cka, -dzki/-dzka, -ny/-na, …).
    Różne imię + to samo nazwisko = różne osoby (nie łączymy Jana i Piotra).
    Niejednoznaczne domyślnie NIE są łączone (przegląd Astry pkt 10): inicjały
    („J. Kowalski") to osobna grupa od „Jan Kowalski", nawet gdy są jedynym
    kandydatem; samo nazwisko przy dwóch osobach o tym rdzeniu zostaje osobne.
    Jedyna dozwolona asocjacja wsteczna (Gemini pkt 13): samo nazwisko dołącza do
    grupy, gdy o danym rdzeniu istnieje DOKŁADNIE jedna osoba z imieniem.
    Kontrprzykłady zamknięte testami w `tests/test_osoby.py`."""
```

`SIMPLIFICATION: heurystyka końcówek zamiast lematyzacji (Morfeusz 2) — rozbudować, gdy
pomiar pokaże błędne łączenia/rozdzielenia.` (decyzja z `KONSULTACJE.md`)

## 7. Znaczniki (`znaczniki.py`)

Format: `[TYP_N]` — `N` licznik per typ w kolejności wystąpienia w dokumencie.
Dla osób: `[OSOBA_N_Fk]` — `N` numer grupy osoby (odmiany dzielą numer), `Fk` **stabilny
numer wariantu formy powierzchniowej** tej osoby (nadawany wg kolejności pierwszych
wystąpień danej formy; ta sama forma w całym dokumencie = to samo `Fk`). Znacznik
identyfikuje parę (osoba, forma), więc przywracanie nie zależy od pozycji ani kolejności
wystąpień — parafraza, przestawienie zdań albo usunięcie fragmentu przez chmurowe AI nie
psuje dopasowania (przegląd Astry pkt 2, Gemini pkt 3). Zamiana od końca segmentu
(offsety nie uciekają).

```python
def nadaj_oznaczenia(encje: list[Encja]) -> None
    # ustawia oznaczenie i wariant ("F1", "F2", …) dla encji z klucz_grupy;
    # encje bez klucza (pozostałe typy) dostają wariant=None
def zamien_w_segment(segment_tekst: str, encje: list[Encja]) -> tuple[str, list[int]]
    # tekst ze znacznikami + "kolejny" (globalny numer wystąpienia znacznika) dla mapy
```

Dopisek na początku (akapit/arkusz/strona): „ZANONIMIZOWANO w Niewidka. Dokument zawiera
znaczniki anonimizacji; zastąpione dane odtworzysz plikiem mapy i kluczem." — obietnica
przywrócenia dotyczy **wyłącznie danych zastąpionych znacznikami**; elementy usunięte przy
czyszczeniu (komentarze, metadane, nagłówki/stopki) nie wracają (przegląd Astry pkt 2,
Gemini pkt 2). Dopisek celowo bez nawiasów kwadratowych — kontrola wyniku szuka wzorca
znacznika (Gemini pkt 7).

## 8. Mapa i klucze (`mapa.py`, `klucze.py`)

Mapa jawna (przed szyfrowaniem):

```json
{
  "wersja": 1,
  "identyfikator": "a3f9c2",
  "utworzono": "2026-10-27T23:36:00+02:00",
  "poziom": 2,
  "wpisy": [
    {"typ": "OSOBA", "oznaczenie": "OSOBA_1", "formy": {
      "F1": "Jan Kowalski", "F2": "Jana Kowalskiego"}},
    {"typ": "PESEL", "oznaczenie": "PESEL_1", "formy": {
      "F1": "44051401359"}}
  ],
  "wystapienia": [
    {"kolejny": 0, "oznaczenie": "OSOBA_1", "wariant": "F1", "oryginal": "Jan Kowalski"},
    {"kolejny": 2, "oznaczenie": "PESEL_1", "wariant": "F1", "oryginal": "44051401359"},
    {"kolejny": 5, "oznaczenie": "OSOBA_1", "wariant": "F2", "oryginal": "Jana Kowalskiego"}
  ]
}
```

- **Wiązanie mapy z dokumentem** (przegląd Astry pkt 3): mapa i wynik niosą wspólny
  `identyfikator` zadania; `/api/przywroc` przyjmuje listę dozwolonych identyfikatorów
  (sesja), niezgodny albo nieznany = `BladMapy` (422) — bez cichego podstawienia cudzych
  personaliów.
- Przywracanie kluczem jest **para (oznaczenie, wariant) → oryginal** — niezależne od
  pozycji; `kolejny` zostaje jako numer porządkowy do weryfikacji kompletności wystąpień,
  nie jako mechanizm dopasowania (Astra pkt 2, Gemini pkt 3).
- Pole `forma` (fallback „forma podstawowa") **wykreślone** — bez lematyzatora byłoby
  zgadywaniem mianownika (Gemini pkt 12); powrót odbywa się na zarejestrowaną formę
  powierzchniową `oryginal` z `formy`/wystąpienia.

```python
def zaszyfruj(mapa: Mapa, klucz: bytes) -> bytes
    # b"NWID" + wersja(1B) + nonce(12B) + AESGCM.encrypt(nonce, json, None)   [cryptography]
def odszyfruj(dane: bytes, klucz: bytes) -> Mapa    # zły tag/wersja → BladMapy

def pobierz_klucz(konfig: Konfig) -> bytes
    # 1) plik z NIEWIDKA_KLUCZ_PLIK (base64, 32 B; uprawnienia 0600 sprawdzane
    #    tylko na POSIX — na Windows weryfikacja dostępu przez win32security
    #    albo wymóg katalogu profilu [Gemini pkt 10]),
    # 2) keyring[NIEWIDKA_KEYRING_USLUGA / konto "mapa"],
    # brak obu → BrakKlucza; brak fallbacku i cichego generowania.
```

CLI: `python -m niewidka.klucze nowy-plik <ścieżka>` / `do-keyringa`. Klucz nigdy w logach,
wyjątkach ani repo. Przywracanie: `/api/przywroc` podmienia znaczniki wg pary
(oznaczenie, wariant) na `oryginal`; w formatach bogatych znacznik wraca do miejsca
znacznika (styl otoczenia). Przywrócenie odtwarza **dane zastąpione znacznikami**, nie
elementy usunięte przy czyszczeniu.

## 9. Adaptery formatów (`formaty/`)

```python
class AdapterFormatu(Protocol):
    rozszerzenia: frozenset[str]
    def wczytaj(self, dane: bytes) -> Dokument: ...
    def zapisz(self, dok: Dokument) -> bytes: ...      # czyści metadane, dodaje dopisek
    def elementy_nieobslugiwane(self, dok: Dokument) -> list[str]: ...
```

- **MVP: txt i docx** (zawężenie 2026-10-28); odt/xlsx/pptx/pdf — v1 (decyzje niżej
  zostają wiążące dla v1).
- **Allowlist struktury per format** (przegląd Astry pkt 5): dozwolone części archiwum
  (OOXML/ODF) spisane w adapterze; każda inna część zostaje przetworzona, usunięta albo
  blokuje eksport — nigdy nie przechodzi cicho. Dotyczy też: hiperłączy, pól dynamicznych,
  tekstów alternatywnych, custom XML, miniatur, nieużywanych części archiwum (Gemini pkt 7,
  Astra pkt 5).
- **Mapowanie przesunięć na runy**: encje wykryte w `segment.tekst`; wstawienie znacznika
  dzieli runy na granicach start/koniec (`starts`), nowy run dziedziczy styl lewego
  fragmentu. Cięcie respektuje kontenery nadrzędne (hiperłącza `<w:hyperlink>`, pola
  `<w:fldSimple>`/`<w:fldChar>`, zakładki) — bez tego plik się uszkadza (Gemini pkt 7).
- **txt**: jeden segment; trywialne.
- **docx** (python-docx + lxml): segment = akapit; scalenie tekstów runów + `starts`;
  czyszczone: komentarze, śledzone zmiany, nagłówki/stopki, właściwości dokumentu.
  Najtrudniejszy adapter — większość pracy. Parsowanie XML przez `defusedxml` albo
  `lxml.etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)`
  (Gemini pkt 6).
- **odt** (odfpy/lxml; v1): jak docx, segment = węzeł tekstowy akapitu.
- **xlsx** (openpyxl; v1): segment = komórka; dopisek = arkusz „ZANONIMIZOWANO". Skan
  obejmuje **liczby** (renderowane zgodnie z formatem arkusza), **formuły** i **cache
  wartości** — nie tylko tekstowe komórki (przegląd Astry pkt 6). Ukryte arkusze →
  blokada albo odsłonięcie (konfiguracja), nigdy cicho.
- **pptx** (python-pptx; v1): segment = kształt tekstowy; notatki prelegenta czyszczone.
- **pdf** (PyMuPDF; v1): segment = blok tekstu; redakcja przez `apply_redactions` + pełny
  zapis z `garbage`, **nie** same adnotacje; dokumenty **mieszane** (część tekstu, część
  skan) blokowane — kontrola „ma warstwę tekstową" przepuszcza skany (przegląd Astry
  pkt 7). `/api/przywroc` dla PDF: 422 albo eksport surowej warstwy tekstowej jako TXT —
  PDF jednokierunkowy (Gemini pkt 4). Uwaga licencyjna: PyMuPDF to AGPL-3.0 — decyzja
  przed dystrybucją poza organizacją (alternatywa: pypdfium2).
- **Obrazy**: brak OCR w MVP → polityka jawna: usuwanie obrazów z wyniku ALBO pozostawienie
  z obowiązkowym ostrzeżeniem o niesprawdzonej zawartości graficznej; kryterium „obraz
  z tekstem" odpada, bo bez OCR jest nieweryfikowalne (Gemini pkt 8).
- **Blokada**: makra VBA, osadzone obiekty → eksport przerwany z listą
  (`ElementNieobslugiwany` → HTTP 422), zgodnie z `KONSULTACJE.md`.

## 10. Kontrola zapisu (`kontrola.py`)

```python
def kontroluj(dane: bytes, format: str, detektory: list[Detektor]) -> list[Ostrzezenie]
    # zapisany plik wczytany jak obcy dokument → detekcja
    # → znaleziska niebędące znacznikami = Ostrzezenie{typ, fragment, segment}
```

- Weryfikacja zapisu działa **ZAWSZE, na każdym poziomie suwaka**; poziom 3 dodaje
  rozszerzone wykrywanie (okna przesunięte) (przegląd Astry pkt 8).
- Nowe znaleziska w zapisanym pliku **blokują status „ukończony"** — ostrzeżenie nie może
  towarzyszyć deklaracji gotowości; użytkownik dostaje plik oznaczony jako niesprawdzony
  albo blokadę eksportu (decyzja konfiguracja: `kontrola.blokada`, domyślnie blokada).

## 11. Ocena jakości (`jakosc.py`)

```python
def r95_z_kalibracji(poziom: int, typ: TypEncji) -> float | None   # z dane/r95.json
```

- **R95** (ryzyko resztkowe poziomu): `beta.ppf(0.95, k+1, n−k)` (Clopper–Pearson) liczony
  offline `narzedzia/kalibracja.py` (scipy tylko tam) na korpusie walidacyjnym; wynik
  w `dane/r95.json` — runtime nie wymaga scipy.
- **Procentowy „wskaźnik dokumentu" usunięty** (przegląd Astry pkt 9, Gemini pkt 11):
  premiował ślepotę (dokument bez wykryć = 100) i karzał typy naturalnie bez sumy
  kontrolnej. UI pokazuje: R95 z etykietą „dokładność na korpusie wzorcowym" (liczba
  stała dla poziomu, nie ocena bieżącego pliku) oraz **listę ostrzeżeń** kontroli zapisu
  jako ocenę bieżącego dokumentu.

## 12. API (`api.py`, FastAPI)

| Endpoint | Wejście | Wyjście |
|---|---|---|
| `POST /api/ukryj` | multipart: `plik` (albo pole `tekst`), `poziom` 1-3 | **ZIP binarny** (`application/zip`: wynik + `.nwidka`; Gemini pkt 14), metadane (`r95`, `ostrzezenia[]`, `statystyki{typ: liczba}`, `identyfikator`) w nagłówkach `X-Niewidka-*`; błędy 413/415/422/500/503 |
| `POST /api/przywroc` | multipart: `wynik`, `mapa` | plik/tekst odtworzony (dane zastąpione znacznikami) + lista rozbieżności; 422 zła/niezgodna mapa (weryfikacja `identyfikator`), 500 brak klucza |
| `GET /api/stan` | — | wersja, załadowane modele, poziom domyślny, limity, stan kolejki |

- **MVP: nasłuch wyłącznie 127.0.0.1** (tryb „Na tym urządzeniu"); token sesji generowany
  przy starcie i walidacja `Host`/`Origin` zamiast uwierzytelniania kont (Astra pkt 4).
  Tryb serwerowy (LAN) — **v1**: uwierzytelnianie, HTTPS (wymaga go też service worker
  PWA), właściciel mapy, autoryzacja odszyfrowania, klucz per dokument albo wywodzony
  z hasła klienta (Gemini pkt 1).
- Modele ładowane raz przy starcie; ciężkie parsowanie i inferencja **w puli wątków**
  (`asyncio.to_thread`/`run_in_threadpool`) z nadzorem `asyncio.wait_for(NIEWIDKA_TIMEOUT_S)`
  — blokowanie pętli asyncio zagłodziłoby `/api/stan` i 503 (Gemini pkt 5); jednym
  procesowi inferencji odpowiada `Semaphore(1)` wewnątrz puli wątków, kolejka
  `maxsize=NIEWIDKA_KOLEJKA`, pełna → `503 + Retry-After`.
- Limity sprawdzane **przed buforowaniem treści** (Content-Length, limit po dekompresji
  archiwów ZIP — ratio i łączny rozmiar rozpakowanych strumieni; Gemini pkt 6, Astra
  pkt 13).
- Pliki wyłącznie w RAM (kontrola buforowania multipart i plików tymczasowych — Astra
  pkt 12); odpowiedzi `Cache-Control: no-store`; logi bez treści: globalny middleware
  przechwytuje nieobsłużone wyjątki i loguje wyłącznie UUID błędu (Gemini pkt 15).

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
| `NIEWIDKA_MAX_ROZMIAR_MB` | `limity.rozmiar_mb` | `25` | maks. rozmiar wejścia (przed buforowaniem) |
| `NIEWIDKA_MAX_ROZPAKOWANE_MB` | `limity.rozpakowane_mb` | `200` | suma rozpakowanych strumieni ZIP (zip bomb) |
| `NIEWIDKA_MAX_TEKST_MB` | `limity.tekst_mb` | `1` | maks. wklejony tekst |
| `NIEWIDKA_KONTROLA_BLOKADA` | `kontrola.blokada` | `true` | nowe znaleziska kontroli blokują status „ukończony" |
| `NIEWIDKA_KOLEJKA` | `limity.kolejka` | `4` | oczekujące w kolejce |
| `NIEWIDKA_TIMEOUT_S` | `limity.timeout_s` | `120` | timeout przetwarzania |
| `NIEWIDKA_WYKRYWAJ_DATE` | `detekcja.wykrywaj_date` | `true` | typ DATA |

## 15. Obsługa błędów

| Sytuacja | Sygnał | Zachowanie |
|---|---|---|
| element nieobsługiwany (makra, skan, osadzony obiekt, niedozwolona część archiwum) | `ElementNieobslugiwany` / 422 | eksport blokowany + lista elementów |
| obraz w dokumencie (brak OCR) | Ostrzeżenie albo usunięcie | polityka jawna (§9), nigdy cicho (Gemini pkt 8) |
| nowe znaleziska w kontroli zapisu | `Ostrzezenie` | blokują status „ukończony" (§10, Astra pkt 8) |
| brak klucza | `BrakKlucza` / 500 | jawny błąd, bez fallbacku |
| zła/uszkodzona mapa, zły tag GCM, wersja, niezgodny identyfikator | `BladMapy` / 422 | odrzucenie, brak prób naprawy |
| nieznany format | / 415 | lista obsługiwanych w treści |
| plik za duży (przed buforowaniem albo po dekompresji) | / 413 | limit z konfiguracji |
| kolejka pełna | / 503 + `Retry-After` | klient czeka albo rezygnuje |
| błąd detektora/modelu | `BladDetektora` / 500 | **fail-closed** — nie zwracamy wyniku bez ustalonej warstwy detekcji |

## 16. Limity (domyślne, wszystkie w konfiguracji)

plik ≤ 25 MB; rozpakowana treść archiwów ZIP ≤ 200 MB (ratio — zip bomb, Gemini pkt 6);
wklejony tekst ≤ 1 MB; liczba elementów dokumentu ograniczona (nagłówek `MAX_ELEMENTS`);
kolejka 4 oczekujące + 1 w toku; timeout 120 s; okno detektora 510 tokenów (krok 448);
jeden proces inferencji; parsery XML bez sieci, bez encji zewnętrznych, prerywalne.

## 17. Odpowiedzi na przeglądy (2026-10-28)

Źródła: `konsultacje/04-przeglad-astra.md`, `konsultacje/04-przeglad-gemini.md`.
Każda uwaga krytyczna ma odpowiedź: **zmiana** (z miejscem) albo **świadome odrzucenie**
(z powodem). Zawężenie MVP (Astra 15): wklejony tekst + TXT + DOCX + web lokalny;
reszta formatów i kanałów w v1 po K-kamieniach (`HLD.md` nagłówek, `KAMIENIE.md`, `PLAN.md`).

### Astra — KRYTYCZNE

| pkt | Uwaga | Decyzja |
|---|---|---|
| 1 | „unia" (HLD) vs „zwycięzca" (LLD); [0,12)+[8,20) zostawiłoby 12–20 jawne | **Zmiana**: maskowany obszar = suma (unia) zaakceptowanych zakresów, wybierana tylko etykieta. Kod `scalanie.py` + test własności z przypadkiem [0,12)+[8,20) (`tests/test_scalanie.py`); §5. |
| 2 | przywracanie po kolejności nie przetrwa parafrazy AI; obietnica „odtworzysz oryginał" za szeroka | **Zmiana**: znacznik `[OSOBA_N_Fk]` — stabilny wariant formy; przywracanie kluczem (oznaczenie, wariant), nie pozycją; dopisek obiecuje tylko odtworzenie danych zastąpionych. §7, §8; kod `znaczniki.py`. |
| 3 | mapa może pasować do innego dokumentu (ciche podstawienie cudzych personaliów) | **Zmiana**: mapa i wynik niosą `identyfikator` zadania; `/api/przywroc` weryfikuje zgodność z listą dozwolonych; niezgodny = `BladMapy` 422. §8, §15 (implementacja w K4). |
| 4 | LAN bez uwierzytelniania; wspólny klucz = każda osoba odszyfruje cudzą mapę | **Zmiana**: MVP tylko localhost (token sesji + walidacja Host/Origin); tryb serwerowy w v1 z uwierzytelnianiem, HTTPS, kluczem per dokument/hasło klienta i autoryzacją odszyfrowania. §12; HLD §3. |
| 5 | czyszczenie nie obejmuje całego pliku (hiperłącza, pola, custom XML, miniatury, nazwa pliku) | **Zmiana**: allowlist dozwolonej struktury per format (inna część → przetworzona/usunięta/blokada); nazwa wyniku `ZANONIMIZOWANY_<krótki-id>.<ext>`. §9; HLD §4.10. |
| 6 | XLSX: PESEL/telefon jako liczby, formuły, cache poza zakresem | **Zmiana** (w v1): skan liczb renderowanych wg formatu arkusza, formuł i cache wartości. §9. |
| 7 | PDF mieszany (tekst+skan) przejdzie kontrolę „ma warstwę tekstową"; adnotacje zamiast redakcji | **Zmiana** (w v1): dokumenty mieszane blokowane; redakcja `apply_redactions` + pełny zapis z `garbage`; PDF jednokierunkowy (bez przywracania). §9. |
| 8 | kontrola eksportu tylko na poziomie 3; wyciek = tylko ostrzeżenie | **Zmiana**: weryfikacja zapisu ZAWSZE (każdy poziom), poziom 3 = okna rozszerzone; nowe znaleziska blokują status „ukończony". §10; HLD §2/§3. |

### Astra — WAŻNE

| pkt | Uwaga | Decyzja |
|---|---|---|
| 9 | wskaźnik dokumentu premiuje ślepotę (0 encji → 100); R95 per typ ≠ ryzyko dokumentu | **Zmiana**: procentowy wskaźnik usunięty; UI pokazuje R95 z kalibracji + listę ostrzeżeń. §11. |
| 10 | nie łączyć niejednoznacznych osób domyślnie; heurystyka na kontrprzykładach | **Zmiana**: inicjały i samo nazwisko przy wielu kandydatach = osobne grupy; asocjacja wsteczna tylko przy dokładnie jednej osobie z imieniem; kontrprzykłady w `tests/test_osoby.py`. §6; kod `osoby.py`. |
| 11 | segmenty odcinają kontekst (etykieta w jednej komórce, wartość w drugiej) | **Przyjęte do LLD**: jednostka zapisu (segment) rozdzielona od okna detekcji; kontekst z sąsiednich elementów + `segment_id` przy detekcji. Doprecyzowanie w K2 przy `detektory.py` (etap z modelem); zapisane, nie teraz — rdzeń K1 działa per segment. |
| 12 | „tylko RAM" nieuzasadnione (multipart, tmp, DOM) | **Zmiana**: limity przed buforowaniem, kontrola multipart/plików tymczasowych, czyszczenie sesji w UI; obietnice tylko po zmierzeniu. §12. |
| 13 | limity przed buforowaniem, rozmiar po dekompresji, parser prerywalny | **Zmiana**: limit rozpakowanej treści 200 MB, licznik elementów, parsery bez sieci/encji. §16. |
| 14 | błędna suma kontrolna nie może wykluczać danych (literówka w prawdziwym PESEL) | **Zmiana**: encja z flagą `podejrzana=True` (pewność 0.5) wchodzi do maskowania; w pomiarze liczone osobno jako PN — definicja w `KRYTERIA.md` §1.3 (próg bez zmian, powód tam zapisany). §3; kod `reguly.py`, `model.py`, `scalanie.py`, `narzedzia/pomiar.py`. |
| 15 | za szerokie MVP bez kryteriów odbioru | **Zmiana**: MVP zawężone do tekstu/TXT/DOCX/web lokalny; kryteria odbioru kamieni w `KAMIENIE.md`. |

### Gemini — punkty przyjęte ponad Astrę

| pkt | Uwaga | Decyzja |
|---|---|---|
| 2 | „round-trip failure": usunięte nagłówki/metadane nie wracają, a dokumentacja obiecywała odtworzenie oryginału | **Zmiana**: specyfikacja mówi wprost — przywracanie odwraca tylko zamianę znaczników; usunięte elementy strukturalne przepadają. §7, §8. |
| 4 | PDF nie da się przywrócić (brak reflow) | **Zmiana** (w v1): PDF jednokierunkowy; `/api/przywroc` → 422 albo TXT. §9. |
| 5 | `Semaphore(1)` w pętli asyncio zagłodzi serwer | **Zmiana**: pula wątków (`to_thread`/`run_in_threadpool`) + `wait_for`. §12 (implementacja w K4). |
| 6 | zip bomb / parser XML | **Zmiana**: limit po dekompresji, `defusedxml`/bezpieczny parser. §9, §16. |
| 7 | cięcie runów psuje OpenXML; dopisek z literałem `[TYP_N]` fałszywie trafia kontrolę | **Zmiana**: cięcie respektujące kontenery; dopisek bez nawiasów kwadratowych (już w kodzie `znaczniki.py`). §9. |
| 8 | „obraz z tekstem" nieweryfikowalne bez OCR, a OCR poza MVP | **Zmiana**: polityka jawna — usuń obrazy albo zostaw z obowiązkowym ostrzeżeniem. §9, §15. |
| 10 | `0600` zawiedzie na Windows | **Zmiana**: sprawdzanie tylko na POSIX; Windows przez `win32security`/katalog profilu. §8 (implementacja w K4). |
| 11 | R95 statyczny myli; wskaźnik karze OSOBA/ADRES bez sum | **Zmiana**: etykieta „dokładność na korpusie wzorcowym"; kary za brak sum usunięte razem ze wskaźnikiem. §11. |
| 12 | `forma` w mapie bez lematyzatora = fikcja | **Zmiana**: pole `forma` wykreślone; powrót na zarejestrowaną formę powierzchniową (oznaczenie, wariant). §8. |
| 13 | samo nazwisko rozbija grupę osoby | **Zmiana**: asocjacja wsteczna przy dokładnie jednej osobie o rdzeniu; kod `osoby.py`. §6. |
| 14 | base64 JSON dla 25 MB | **Zmiana**: odpowiedź ZIP + nagłówki `X-Niewidka-*`. §12 (implementacja w K4). |
| 15 | traceback z PII w logach | **Zmiana**: middleware logujący UUID błędu bez treści. §12, §15 (implementacja w K4). |
| 1 | wspólny klucz serwera bez tożsamości użytkownika | **Zmiana**: jak Astra pkt 4 — MVP lokalne bez klucza serwera; v1 klucz per dokument/hasło klienta. §12. |
| 3 | sekwencyjny licznik `kolejny` pada po parafrazie | **Zmiana**: jak Astra pkt 2 — (oznaczenie, wariant); `kolejny` tylko do weryfikacji kompletności. §7, §8; kod `znaczniki.py`. |

### Świadome odrzucenia

- **Pełne odtworzenie 1:1 dokumentu** (serializacja usuniętych nagłówków/metadata w mapie,
  Gemini pkt 2 alternatywa): odrzucone w MVP — mapa z pełnym stanem dokumentu to drugi
  format kopii zapasowej wrażliwych danych do chronienia; cel Niewidki to bezpieczne
  wysłanie, nie backup. Jawna granica w dopisku i dokumentacji.
- **Rozszerzanie MVP o kolejne formaty/kanały** (Astra pkt 15 w drugą stronę): odrzucone
  do v1 — web lokalny + TXT/DOCX pokrywa zlecenie „wklejony tekst albo lokalny dokument
  biurowy"; reszta po kamieniach K0–K5.
- **Heurystyka wskaźnika 0-100**: odrzucona (pkt 9/11 wyżej) zamiast kalibrowania wag.
