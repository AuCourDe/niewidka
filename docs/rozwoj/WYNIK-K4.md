# WYNIK K4 — mapa, przywracanie, API

Data: 2026-10-28 (sesja claude-glm). Zakres wg zlecenia: `konfig.py`, `klucze.py`,
`mapa.py`, rdzeń `ukryj`/`przywroc`, `api.py` (FastAPI), `tests/test_api.py`, żywy serwer.
Wszystko TDD (test przed kodem, RED potwierdzony dla każdego modułu), reużyte moduły
K1–K3: `model.py`, `znaczniki.py`, `osoby.py`, `formaty/`, `kontrola.py`, `jakosc.py`.

## Co powstało

| moduł | treść |
|---|---|
| `niewidka/konfig.py` | TOML (`--konfig`, domyślnie `./niewidka.toml`) + env `NIEWIDKA_*`; **env wygrywa**; wszystkie klucze z LLD §14, wartości domyślne wg tabeli; zła liczba w env = jawny `ValueError` z nazwą zmiennej |
| `niewidka/klucze.py` | `pobierz_klucz(konfig)`: 1) plik z `NIEWIDKA_KLUCZ_PLIK` (base64, dokładnie 32 B, uprawnienia 0600 sprawdzane tylko na POSIX), 2) keyring (`NIEWIDKA_KEYRING_USLUGA`/konto `mapa`); brak obu = `BrakKlucza`, **zero fallbacku i cichego generowania**; treść klucza nie wchodzi do wyjątków (test); CLI `python -m niewidka.klucze nowy-plik <ścieżka>` (0600, O_EXCL bez nadpisania) / `do-keyringa` |
| `niewidka/mapa.py` | format LLD §8 (wersja, identyfikator, utworzono, poziom, wpisy z formami, wystąpienia z `kolejny`); `zaszyfruj`/`odszyfruj` AES-256-GCM (`cryptography`), nagłówek `NWID`+wersja(1 B)+nonce(12 B)+długość_id+id; **identyfikator jako AAD** — podmiana id w nagłówku psuje tag GCM (test); `przywroc_tekst` po parze (oznaczenie, wariant), rozbieżności: `znacznik_bez_wpisu`, `wpis_niewykorzystany` |
| `niewidka/rdzen.py` | **`ukryj(dane, format, poziom) -> (wynik, mapa, raport)`** i **`przywroc(dane, format, mapa) -> (bytes, rozbieżności)`** — jedna para dla API i przyszłego desktopu; detektor wstrzykiwany albo `zbuduj_detektor(poziom, konfig)` (poziomy 1-3 = reguły + bardsai; LFM2.5 po pomiarze K2b nie wchodzi); kontrola zapisu ZAWSZE, `kontrola_blokada` → status `zablokowany`/`ukonczony`; R95 z kalibracji w raporcie; limit rozpakowanych strumieni ZIP (zip bomb, `ArchiwumZaDuze`); nieznany format → `NieznanyFormat` |
| `niewidka/api.py` | LLD §12: `POST /api/ukryj` (ZIP: `ZANONIMIZOWANY_<id>.<ext>` + `<id>.nwidka`; nagłówki `X-Niewidka-Identyfikator/Statystyki/Ostrzezenia/R95/Status`), `POST /api/przywroc` (rozbieżności w `X-Niewidka-Rozbieznosci`), `GET /api/stan` (bez tokena, bez wycieku tokena) |

## Bezpieczeństwo API (wg LLD §12 i przeglądów)

- nasłuch **wyłącznie 127.0.0.1** z konfiguracji (`NIEWIDKA_HOST/PORT`); token sesji
  `secrets.token_urlsafe` generowany przy starcie, wymagany w nagłówku `X-Niewidka-Token`
  dla POST-ów; walidacja `Host` (host z konfiguracji albo localhost) i `Origin`
  (lista originów z konfiguracji) — naruszenie → **403**;
- limity **przed buforowaniem** (Content-Length → 413, ciało nieczytane) i **po
  dekompresji** (suma rozpakowanych strumieni ZIP → `ArchiwumZaDuze`/413); po odczycie
  ponowne sprawdzenie długości; wklejony tekst ≤ `NIEWIDKA_MAX_TEKST_MB`;
- pliki tylko w RAM: spool multipart podniesiony do limitu wejścia (`MultiPartParser.spool_max_size`),
  wyniki i ZIP składane w `BytesIO`, żadnych plików tymczasowych;
- `Cache-Control: no-store` na każdej odpowiedzi (middleware zewnętrzny);
- inferencja w puli wątków (`asyncio.to_thread`) pod `Semaphore(1)` z
  `asyncio.wait_for(NIEWIDKA_TIMEOUT_S)` (Gemini pkt 5 — pętla nie jest głodzona);
  pełna kolejka → **503 + Retry-After** (slot zajęty + `NIEWIDKA_KOLEJKA` oczekujących);
- middleware logujący wyłącznie UUID błędu przy nieobsłużonym wyjątku (Gemini pkt 15);
  `BladDetektora` celowo bez handlera → 500 z UUID, **fail-closed**, bez treści wyjątku
  w odpowiedzi (test `caplog`: brak treści dokumentu i klucza w logach);
- klucz pobierany w wątku operacji i żywy tylko na jej czas (nie w stanie aplikacji);
- sesja identyfikatorów w RAM: `przywroc` akceptuje mapę, której identyfikator powstał
  w tej sesji; obca sesja → `BladMapy`/422 (Astra pkt 3). Mapa z innego zadania tej
  samej sesji jest przyjmowana, ale rozbieżności (znacznik bez wpisu / wpis
  niewykorzystany) wracają jawnie w nagłówku — ciche podstawienie personaliów nie
  występuje (potwierdzone na żywym serwerze).

## Błędy wg LLD §15 (zweryfikowane testami)

| sytuacja | odpowiedź |
|---|---|
| plik/tekst ponad limit (przed buforowaniem i po odczycie) | 413 |
| rozpakowane archiwum ponad limit (zip bomb) | 413 |
| nieznany format | 415 + lista obsługiwanych |
| zły klucz / zmieniony bajt mapy / zły tag GCM | 422 |
| mapa z obcej sesji (niezgodny identyfikator) | 422 |
| makra / elementy nieobsługiwane (`ElementNieobslugiwany`) | 422 + lista |
| brak klucza (`BrakKlucza`) | 500 (jawny komunikat bez treści klucza) |
| błąd detektora (`BladDetektora`) | 500 fail-closed, tylko UUID |
| kolejka pełna | 503 + `Retry-After` |

## Żywy serwer (uvicorn 127.0.0.1:8390, wagi z `~/models/niewidka`)

Klucz wygenerowany CLI: `python -m niewidka.klucze nowy-plik` → `0600`. Start
`NIEWIDKA_KLUCZ_PLIK=… NIEWIDKA_MODELE_KATALOG=… uvicorn` (port wolny sprawdzony
`ss -tlnp`); token sesji odczytany przez operatora procesu.

**TXT (ukryj → przywróć):**

```
GET /api/stan → {"wersja":"0.1.0","modele":["reguly","onnx:bardsai"],"poziom":1,
                 "limity":{rozmiar_mb:25,rozpakowane_mb:200,tekst_mb:1,kolejka:4,timeout_s:120},
                 "kolejka":{"czekajacy":0,"maks":4}}
POST /api/ukryj -F "tekst=…" -F "poziom=1"
  → x-niewidka-identyfikator: 69b9af
    x-niewidka-statystyki: {"OSOBA": 1, "PESEL": 1, "TELEFON": 1, "EMAIL": 1}   (OSOBA od bardsai)
    x-niewidka-ostrzezenia: []   x-niewidka-r95: {"OSOBA": 0.0736, "PESEL": 0.3482, …}
    x-niewidka-status: ukonczony
  ZIP: ZANONIMIZOWANY_69b9af.txt + 69b9af.nwidka
  treść: "[OSOBA_1_F1], PESEL [PESEL_1]. Telefon [TELEFON_1], e-mail [EMAIL_1]. Mieszka w Krakowie."
POST /api/przywroc (wynik + mapa)
  → x-niewidka-rozbieznosci: []
  diff oryginal.txt przywrocony.txt  →  IDENTYCZNE z oryginałem
```

**DOCX (wzorzec generatora K3):** ukryj → `{"OSOBA": 2, "PESEL": 2, "TELEFON": 2, "EMAIL": 1, "NIP": 1}`,
status `ukonczony`, ostrzeżenia puste; przywróć → rozbieżności `[]`, treść dokumentu
wraca w całości (Jan Kowalski, PESEL 44051401359, telefon, NIP 1234563218 z tabeli,
Anna Nowak, pułapka 12345678901), bez dopisku i znaczników.

**Negatywy na żywym serwerze:** bez tokena → `403`; zły `Origin` → `403`;
`plik=coś.pptx` → `415` `{"blad":"nieznany format: 'pptx'; obsługiwane: docx, txt"}`;
mapa z innego zadania tej samej sesji na wynik DOCX → przyjęta, ale z jawną listą
rozbieżności (osobna sesja → 422, dowód w `tests/test_api.py::test_niezgodny_identyfikator_422`).

## Weryfikacja całości

```
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m pytest tests/ -q
→ 256 passed, 1 xfailed in 19.39s        (przed K4: 195 passed / 9 skipped — modele doładowane w tym biegu)
.venv/bin/python -m ruff check niewidka/ tests/ narzedzia/  → All checks passed!
```

Nowe testy: `test_konfig.py` (5), `test_klucze.py` (10), `test_mapa.py` (13),
`test_rdzen.py` (16 + 1 modelowy), `test_api.py` (16). `ruff format` celowo
nieobowiązywany (konwencja projektu z K1–K3: `ruff check`).

## Nowe zależności (ryzyko JFrog dla B — raport obowiązkowy)

| pakiet | wersja | rola | ryzyko |
|---|---|---|---|
| fastapi | 0.162.0 | API | popularny,enterprise; pośrednio pydantic 2.14.1, starlette 1.10.0 |
| uvicorn | 0.54.0 | serwer ASGI | popularny |
| cryptography | 50.0.2 | AES-256-GCM | standard branżowy (zamiast własnej kryptografii — zasada drabiny) |
| keyring | 25.7.0 | magazyn klucza | używa SecretStorage/dbus na Linux; na B VM do weryfikacji backend |
| python-multipart | 0.0.32 | multipart FastAPI | wymagany przez UploadFile |

## Ograniczenia (świadome, do v1/K5)

- token sesji dziś tylko w logu procesu operacyjnego; K5 (web) osadzi go w stronie
  serwowanej lokalnie przez ten sam proces;
- zbiór identyfikatorów sesji rośnie bez limitu przez żywotność procesu (MVP lokalne);
- poziomy 1-3 budują ten sam kompozyt (reguły + bardsai) — wyróżnik poziomu 2/3 wróci
  z pracą K2c (LFM2.5 „uzupełniający") i rozszerzonymi oknami poziomu 3;
- przywrócenie odtwarza wyłącznie dane zastąpione znacznikami (usunięte przy czyszczeniu
  metadane/komentarze/nagłówki nie wracają — granica z dopisku, LLD §7).
