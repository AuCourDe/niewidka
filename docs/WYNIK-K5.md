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

Playwright headless, pełny przepływ: wklejenie wniosku (osoba, adres, PESEL, telefon,
e-mail, dowód) → „Ukryj dane” (poziom 2) → wynik: 6 zaślepek widocznych (OSOBA/ADRES/
PESEL/TELEFON/EMAIL/DOKUMENT), status „Kontrola jakości: zaliczona”, pobrania klikalne →
zakładka Przywróć → upload pary wynik+mapa (z tego samego zadania) → „Przywrócono”,
lista rozbieżności pusta. Zrzuty po recapture: `docs/zrzuty/k5-desktop-start.png`,
`k5-desktop-wynik.png` (1440), `k5-mobile-start.png`, `k5-mobile-wynik.png` (390).

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
  `Desktop/C/`, decyzja tak/nie należy do właściciela.
