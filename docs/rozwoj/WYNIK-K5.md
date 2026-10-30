# WYNIK K5 — interfejs web lokalny

Data: 2026-10-28 (sesja claude-glm). Zakres wg zlecenia: `niewidka/web/` (index.html +
apka.js + styl.css, bez frameworka, bez CDN, offline), serwowanie przez `api.py`
(StaticFiles na `/`, token sesji wstrzyknięty w HTML), testy `tests/test_web.py`,
E2E Playwright, zrzuty 1440/390, audyt Vercel `web-design-guidelines`.

## Co powstało

| plik | treść |
|---|---|
| `niewidka/web/index.html` | jeden ekran, po polsku: h1 „Niewidka” + pasek trybu „**Na tym urządzeniu** — dane nie opuszczają komputera”, zakładki Ukryj/Przywróć (role=tablist, strzałki, hash `#ukryj`/`#przywroc`), pole dokumentu (textarea + drag&drop + plik), suwak jakości 1–3 z żywym opisem (Szybko/Dokładniej/Najdokładniej), wynik: status kontroli, zamienione dane, szacowane ryzyko, ostrzeżenia, podgląd „kartka” z zaślepkami + Kopiuj, pobrania wyniku i mapy z notką „Zachowaj mapę”, zakładka przywracania (wynik + mapa → pobranie + rozbieżności), skip link, `aria-live` |
| `niewidka/web/apka.js` | bez zależności: token z `meta[name=niewidka-token]`, fetch z `X-Niewidka-Token`; podgląd znaczników jako **zaślepki** (czarny pasek, biały mono, `TYP numer`) budowane `textContent` (bezpiecznie, bez innerHTML); mini-czytnik ZIP (SIMPLIFICATION: stored+deflate, bez zip64 — dokładnie to, co zwraca `/api/ukryj`; rozpakowanie natywnym `DecompressionStream("deflate-raw")`); R95 jako „szacowane ryzyko pominięcia” po ludzku („co najwyżej ok. 1 na N”; poziomy bez kalibracji: jeden wiersz „dostępny na poziomie Szybko”); status `zablokowany` → czerwony STOP „tego dokumentu nie wolno wysyłać”; komunikaty 403/413/415/422/503/500 po polsku z radą; `beforeunload` przy niewysłanym tekście |
| `niewidka/web/styl.css` | świat „papier i tusz”: tło `#FBFBF9`, atrament `#23282D`, akcent akcji `--tusz #2D4A6B` (tylko akcje), kolory semantyczne w parach (tekst+tło+obramowanie tego samego hue), jeden cień (kartka, offset+blur), włosowe linie, `focus-visible` 2px, `prefers-reduced-motion`, `color-scheme: light` (świadome: brief „dużo światła” — dark mode celowo nie robiony) |
| `niewidka/web/fonty/` | Lato Regular+Bold TTF (OFL-1.1, © Łukasz Dziedzic, w repo — działa offline, bez CDN) + nota licencyjna; preload w `<head>` |
| `niewidka/api.py` | `GET /` — index.html z tokenem sesji wstrzykniętym w meta (nigdy w URL ani w zasobach; `no-store` z istniejącego middleware chroni cache); `app.mount("/", StaticFiles)` zarejestrowany PO trasach — `/api/*` mają pierwszeństwo |
| `PRODUCT.md`, `DESIGN.md` | karta produktu (odbiornik: urzędnik, twardy ogranicznik lokalności) i spisany system wizualny z zbudowanego kodu (impeccable-documenter) |
| `tests/test_web.py` | 7 testów TestClient: strona serwowana z tokenem równym `app.state.token`, token nie wycieka do URL ani do apka.js/styl.css, brak zewnętrznych zasobów (regexy na src/href/@import/url), fonty serwowane lokalnie, `no-store`, elementy funkcjonalne na stronie, priorytet `/api/*` nad statycznymi |

## Kolejność skilli (obowiązkowa — wykonana)

1. `moje-human-frontend` (router): krok 0a — brak `PRODUCT.md` (utworzony w trakcie; sesja
   nieinteraktywna, brief = zlecenie właściciela), 0b — seed **3570690072** (z niego strategia
   koloru „zero koloru poza jednym elementem ogniskowym”; layout/typografia/ruch nadpisane
   briefem właściciela: stonowane, dużo światła, bez efekciarstwa), 0c — dobór KatalogUI
   (`pnpm katalog dobierz --powierzchnia aplikacja`): L-0075/L-0002/L-0078, wynik 0.36/0.23/0.20
   — rozpoznanie nietrafione (dashboard/master-detail zamiast narzędzia transakcyjnego); strona
   propozycji: `Desktop/C/Niewidka - propozycje layoutow.html`; brak pasującego layoutu do
   dopisania w `KatalogUI/todo.md` (w toku sesji równoległej).
2. `impeccable` (prowadzi): `context` → `shape` (surface brief + direction contract w
   `.impeccable/surfaces/niewidka-web-index-html.md`, code-led, brief przypięty) → craft-floor
   przed edycją → budowa → `detect --json` (4× warning „overused-font” Lato — zaakceptowane:
   jedyny OFL z polskimi znakami dostępny offline; reszta to klony albo AGPL) → recenzja
   końcowa → polish (batch poprawek) → recapture → **disposition: ship**.
3. `frontend-design` (kalibracja): plan tokenów sprawdzony przeciw kliszom AI (krem+terakota+serif,
   near-black+acid, SaaS-card kit, ALL-CAPS eyebrow, mono-etikiety, „→" w CTA) — żadna nie
   występuje; sygnatura produktowa (zaślepki) pochodzi z tematu, nie z katalogu efektów.
4. `web-design-guidelines` (audyt końcowy, reguły pobrane na żywo od Vercela) — wynik niżej.

## Audyt web-design-guidelines (Vercel) — znaleziska i naprawy (commit `4ec3c74`)

| gdzie | problem | naprawa |
|---|---|---|
| `niewidka/web/index.html:11` | brak h1 (nazwa jako `p`) | h1 + poprawna hierarchia |
| `index.html` | brak skip linku | `.przeskok` do `#glowna` |
| `index.html` | brak `theme-color` | `<meta name="theme-color" content="#FBFBF9">` |
| `index.html` | brak preload fontów | `<link rel="preload" as="font">` ×2 |
| `index.html` | formularze bez `autocomplete` | `autocomplete="off"` (pola nie-auth, wg reguły Vercel) |
| `index.html` | placeholder bez wielokropka | „…dane osobowe…” |
| `niewidka/web/apka.js` | błędy inline bez fokusu | walidacja „Pusto”/„Brakuje pliku” ustawia focus na brakujące pole |
| `apka.js` | stany ładowania bez „…” | „Sprawdzam dokument…”, „Przywracam dane…” |
| `apka.js` | suwak nie ogłasza nazwy poziomu AT | `aria-valuetext` („Szybko/Dokładniej/Najdokładniej”) |
| `apka.js` | zakładki bez deep-link | hash `#ukryj`/`#przywroc` (odczyt przy starcie + `replaceState`) |
| `apka.js` | utrata wklejonego tekstu bez ostrzeżenia | `beforeunload` gdy textarea niepusta |
| `niewidka/web/styl.css` | liczby bez `tabular-nums` | `.lista-danych`, `.zaslepka` |
| `styl.css` | nagłówki bez `text-wrap` | `h1,h2,h3 { text-wrap: balance }` |
| `styl.css` | brak `touch-action` | `body { touch-action: manipulation }` + `overflow-x: hidden` |
| `styl.css` | `.linkowy` bez hover | `:hover` ciemniejszy tusz |

Po naprawach czyste wg reguł: icon-only (brak), paste (nieblokowany), transition:all (brak),
outline-none (brak), user-scalable (nietknięty), autoFocus (brak), Intl dla liczb/dat
(nie dotyczy — brak dat/liczb walutowych w UI).

## Recenzja końcowa impeccable (subagent-finish-reviewer, 2 biegi)

Pierwszy bieg: **disposition: fix** — 4 materialne poprawki:
1. blok ryzyka renderował 6× „nie oszacowano” przy poziomie bez kalibracji → filtrowanie
   nulli + jeden wiersz zastępczy („Szacunek ryzyka — dostępny na poziomie Szybko”);
2. wizualnie ukryty `input[type=file]` bez widocznego fokusu →
   `#plik:focus-visible + .przycisk-wtorny { outline … }` (WCAG 2.4.7);
3. brak wpisu 415 w komunikatach → „Nieobsługiwany format pliku — przyjmuję .txt i .docx.”;
4. brak `PRODUCT.md` → utworzony.
Drugi bieg (po recapture zrzutów): wszystkie 4 **resolved**, brak regresji,
**disposition: ship**. Zastrzeżenie utrzymane: sygnatura (zaślepki) nie może zostać
rozcieńczona. Obserwacja sufitu (niewykorzystany ruch jako jedyny autorski moment —
świat „biurka drukarza” mógłby udźwignąć np. osadzanie kartki) — celowo nierobiona:
brief „bez efekciarstwa”, ruch ograniczony do `:active` + reduced-motion.

## E2E (żywy serwer: uvicorn 127.0.0.1:8393, wagi z `~/models/niewidka`, klucz CLI)

Playwright headless, pełne przepływy przez UI:
- **wklejony tekst** (osoba, adres, PESEL, telefon, e-mail, dowód; poziom 2) → 6 zaślepek
  widocznych (OSOBA/ADRES/PESEL/TELEFON/EMAIL/DOKUMENT), „Kontrola jakości: zaliczona”,
  pobrania klikalne → zakładka Przywróć → upload pary → „Przywrócono”, rozbieżności puste;
- **plik TXT** przez UI (upload → ukryj → zaślepki w podglądzie → przywróć) — ✓;
- **plik DOCX** przez UI — ✗, **defekt spoza K5**: `POST /api/ukryj` przekracza
  `NIEWIDKA_TIMEOUT_S=120` i kończy 500 (fail-closed). Faulthandler wskazuje
  `kontrola.py:_skan_surowy` (K3b): detektor ONNX odpalany na surowych częściach XML
  archiwum — na DOCX to setki okien na CPU. TXT przechodzi w 0,18 s. Regresja
  wydajnościowa kontroli zapisu (K3b), nie interfejsu; do naprawy w sesji rdzenia
  (zmiany `kontrola.py` są dla K5 zakazane). Na żywym serwerze K4 DOCX przechodził,
  bo surowy skan wtedy nie istniał.

Zrzuty po recapture: `docs/zrzuty/k5-desktop-start.png`, `k5-desktop-wynik.png` (1440),
`k5-mobile-start.png`, `k5-mobile-wynik.png` (390); kopie w `Desktop/C/Niewidka - k5-*.png`.

Błędy startowe sesji (odnotowane): klucz wygenerowany ręcznie (44 znaki base64 = 33 B)
dawał 500 — naprawiony przez projektowy CLI `python -m niewidka.klucze nowy-plik`;
`runpod-qwen` w UltraAPI nie istnieje (rotacja katalogu), a trasa wizyjna `nim-llama-3.2-11b`
jest cięta przez strażnika PII — **ocena wizyjna LLM zrzutów była niemożliwa wiarygodnie**;
zgodnie z regułą właściciela ocena percepcyjna idzie do właściciela (zrzuty, pytanie tak/nie).

## Weryfikacja całości

```
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m pytest tests/ -q
→ 314 passed, 1 xfailed in 33.63s   (przed K5: 256 passed / 1 xfailed)
.venv/bin/python -m ruff check niewidka/ tests/ narzedzia/  → All checks passed!
```

## Ograniczenia (świadome)

- podgląd i Kopiuj tylko dla tekstu (wklejony tekst albo .txt); DOCX tylko do pobrania
  (podgląd DOCX w przeglądarce = rozplątywanie runów — poza MVP);
- poziomy 2–3 mają wspólny kompozyt z poziomem 1 (WYNIK-K4) — suwak już działa, sens
  poziomów wróci z pracą K2d; szacowanie ryzyka jest skalibrowane tylko dla poziomu 1;
- czytnik ZIP w przeglądarce: stored+deflate, bez zip64 — sufit opisany komentarzem
  SIMPLIFICATION w `apka.js`;
- teksty GUI mają jeszcze półpauzy i pauzy — przebieg poprawek przez Argona jest osobnym
  zleceniem właściciela (12:55) i zostawione niezmienione, żeby nie kolidować z pracą
  równoległą (logo, „Jak to działa” — ta sama sesja).
- ocena percepcyjna właściciela (kamień K5 w KAMIENIE.md) — **czeka**: zrzuty poszły do
  `Desktop/C/`, decyzja tak/nie należy do właściciela;
- 🔴 do zgłoszenia sesji rdzenia (K3b/K4): surowa kontrola zapisu spowalnia DOCX ponad
  timeout 120 s (500 fail-closed) — znalezione E2E K5, szczegóły wyżej.

---

# K5b — 2026-10-28 (naprawa timeoutu DOCX, teksty Argona, „Jak to działa”, logo)

Zlecenie 15:19. Punkty 0-5 zlecenia; TDD tam, gdzie kod rdzenia; bez Dockera, bez codex.

## 0. DOCX przekraczał timeout 120 s — NAPRAWIONE

Przyczyna (potwierdzona pomiarem): `kontrola.py:_skan_surowy` puszczał detektor
z modelem ONNX na każdą część XML archiwum — setki inferencji na surowym DOCX.

| pomiar (wzorzec generatora, poziom 3) | czas | status |
|---|---|---|
| PRZED (model na surowym XML) | **219,25 s** | zablokowany, 11 ostrzeżeń (fałszywe, z metadanych XML) |
| PO (skan surowy: wyłącznie reguły + oryginały z mapy) | **1,72 s** | ukonczony, 0 ostrzeżeń |
| PO przez API `/api/ukryj` (DOCX, poziomy 1/2/3) | 0,52 / 0,68 / 2,38 s | 200, round-trip przywrócenia 200 |

TDD: `tests/test_kontrola.py::TestWydajnoscKontroli` (ukrycie wzorcowego DOCX na
poziomie 3 trwa < 10 s, marker `model`; RED: 224,73 s, status zablokowany) oraz
`TestSkanSurowyReguly` (skan surowy stosuje reguły nawet z detektorem bez reguł).
Model uruchamia się odtąd wyłącznie na treści czytanej adapterem; siatka kontroli
bez zmian (reguły na surowych częściach + oryginały z mapy; testy K3b/K4b zielone).

## Znalezione przy okazji (E2E): model odpalał OSOBA na tekście znacznika

Po naprawie timeoutu DOCX przeszedł, ale zwykły tekst (wniosek z Janem Kowalskim)
był blokowany na każdym poziomie: bardsai klasyfikował `[OSOBA_1_F1]`, `[PESEL_1]`
(nawet fragmenty typu `PESEL_1]`) jako osobę w wyniku, a kontrola nie wykluczała
znaczników — obietnica „znaleziska niebędące znacznikami” z LLD §10 nigdy nie była
w kodzie (reguły na znacznikach nie odpalały, więc błąd spał do czasu modelu
w kontroli). Naprawa (TDD, `TestKontrolaZnaczniki`): kontrola wyjmuje znaczniki
`WZORZEC_ZNACZNIKA` ze skanowanej treści (spacja za znak, offsety bez zmian) —
w znaczniku nie ma oryginału, prawdziwe wycieki blokują dalej (test z wyciekiem
`79020853217` obok znaczników). Stabilność: 4 biegi × poziomy 1/2/3, zawsze
`ukonczony`, 0 ostrzeżeń. Bezpieczeństwo kontroli bez osłabienia: surowy skan
regułowy, oryginały z mapy i fail-closed bez zmian.

## 1-3. Teksty Argona (Część 1), sekcja „Jak to działa” (Część 2), zakaz półpauz

- Tabela „Część 1” wdrożona w `apka.js` i `index.html` (m.in. „Gotowe: dokument
  z ukrytymi danymi”, „Ukryte dane”, STOP: „Wynik zatrzymany przez kontrolę
  jakości…”, ryzyka „małe do umiarkowanego: …”); nowy dopisek w `znaczniki.DOPISEK`
  („ZANONIMIZOWANY. Dane osobowe zastąpiono znacznikami (Niewidka). Oryginalne dane
  przywrócisz plikiem mapy.”) z podniesionymi asercjami testów (test_rdzen/test_api:
  „ZANONIMIZOWANY not in” zamiast „ZANONIMIZOWANO not in”, które nowemu dopiskowi
  nie patrzało na ręce).
- Sekcja „Jak to działa”: `<details>` pod formularzem zakładki Ukryj; W skrócie,
  wyróżniona lista wykrywanych danych (nazwy typów z `ETYKIETY` w `apka.js` — jedno
  źródło z wynikiem, opisy i przykłady w `TYPY_WYKRYWANE`), „Ważne zastrzeżenie”
  w wyróżnionym bloku, „Szczegóły techniczne” jako zagnieżdżony `<details>`; styl:
  granat `#2C4560`, tło `#F8F7F4`, reszta palety projektu bez zmian.
- Zakaz – —: `tests/test_web.py::test_bez_polpauz_i_pauz_w_tekstach` pada przy
  choć jednym znaku w index.html, apka.js albo dopisku (RED potwierdzony, potem
  sprzątnięte wszystkie wystąpienia, także w komentarzach apka.js).

## 4. Zrzuty E2E odświeżone (żywy serwer 127.0.0.1:8393, wagi z magazynu, klucz z CLI)

Przepływy Playwright: tekst wklejony poziom 2 (zaślepki, kontrola zaliczona),
DOCX wzorcowy przez UI (poprzednio defekt K5 — teraz przechodzi), mobilne 390.
Pliki: `docs/zrzuty/k5-desktop-start.png`, `k5-desktop-wynik.png`,
`k5-jak-to-dziala.png` (nowy), `k5-mobile-start.png`, `k5-mobile-wynik.png`;
kopie w `Desktop/C/Niewidka - k5-*.png`. Ocena percepcyjna → właściciel (tak/nie).

## 5. Logo (wariant B właściciela)

- `web/logo.svg` = wybrany `docs/logo/logo-agy4-2.svg` bez tła (`rect`), wpięty
  w `<h1>` (alt „Niewidka”, 134x42); favicon: `favicon.svg` (kopia
  `logo-agy4-2-favicon.svg`) + `favicon-32.png` (czytelność 32 px sprawdzona na
  rastrze) + `apple-touch-icon.png` 180 px (rasteryzacja `rsvg-convert`).
- `web/ikona.ico` (16/32/48/256, wpisy PNG) — ten sam znak z **pełnym konturem**
  (bez zanikającego gradientu: w 16-32 px wychodził zbyt blado); używa jej
  `zbuduj_windows.ps1` (fallback na `narzedzia/ikona.py`, gdyby pliku zabrakło).
- `docs/logo/`: usunięte szkice odrzucone i skrypty agentów; zostały
  `logo-agy4-2*.svg/png` + `README.md` (wybór B, data, autor Gemini agy4, mapa
  plików i przepis przebudowy ikony).

## Weryfikacja całości

```
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m pytest tests/ -q
→ 420 passed, 1 xfailed in 73.21s   (przed K5b: 408 passed / 1 xfailed)
.venv/bin/python -m ruff check niewidka/ tests/ narzedzia/  → All checks passed!
```

Procesy po teście ubite (serwer E2E zatrzymany, przeglądarka zamknięta).
