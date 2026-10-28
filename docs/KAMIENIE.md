# Niewidka — kamienie milowe (MVP → v1)

Każdy kamień ma mierzalne kryterium ukończenia; dowód w nawiasie. Kolejność zgodna
z `PLAN.md`. Korpus i kryteria **przed** jakimkolwiek pomiarem (polecenie właściciela).

**MVP zawężone 2026-10-28 po przeglądach** (Astra pkt 15): wejście wklejony tekst + TXT
+ DOCX, kanał web lokalny. Pozostałe formaty (odt/xlsx/pptx/pdf), tryb serwera organizacji,
desktop i Android → **v1**. Odpowiedzi na przeglądy: `LLD.md` §17.

## K0 — Korpus testowy i kryteria pomiaru
Zakres: ≥ 40 polskich próbek JSONL (odmiany imion i nazwisk, PESEL/NIP/REGON/IBAN poprawne
i z błędną sumą, adresy, telefony, e-maile, dowody, daty, homonimy „Róża", „Wiśniewski"
vs „wiśnie", nazwiska-rzeczowniki „Kowal", „Nowak"), pliki wzorcowe biurowe, `KRYTERIA.md`
z progami recall/precision spisanymi przed pierwszym pomiarem.

**Ukończono, gdy:** `pytest tests/test_korpus.py` waliduje format próbek; `narzedzia/pomiar.py`
wypisuje recall/precision per typ; `KRYTERIA.md` commitnięty (dowód: commit + wynik pomiaru).

## K1 — Rdzeń regułowy (TDD)
Zakres: `model.py`, `reguly.py` (PESEL, NIP, REGON, IBAN, dowód, e-mail, telefon, adres,
data), `scalanie.py`, `osoby.py`, `znaczniki.py` — test przed kodem.

**Ukończono, gdy:** na korpusie 100% numerów z poprawną sumą kontrolną wykrytych i 0 fałszywych
trafficień na numerach z błędną sumą; recall/precision pozostałych typów ≥ progów z `KRYTERIA.md`;
wynik pomiaru zapisany (dowód: raport pomiaru w commicie).

Uwaga (2026-10-28): „0 fałszywych trafficień na numerach z błędną sumą" liczone jest po
doprecyzowaniu definicji z `KRYTERIA.md` §1.3 — nadmaskowanie z flagą `podejrzana` (wzorzec
pasuje, suma błędna; przegląd Astry pkt 14) to zamierzona kategoria PN, nie FP. Progi bez
zmian; wynik pomiaru po zmianie: dopisek w `docs/WYNIK-K1.md`.

## K2 — Detekcja modelowa i jakość
Zakres: `detektory.py` (bardsai ONNX INT8; LFM2.5 warunkowo), okna przesuwne, `jakosc.py`,
kalibracja R95, pomiar porównawczy „reguły" vs „reguły+model" (poziom 1/2).

**Ukończono, gdy:** poziom 1 osiąga progi `KRYTERIA.md` (recall OSOBA i precision); decyzja
o LFM2.5 udokumentowana pomiarem; `dane/r95.json` wygenerowany (dowód: WYNIK pomiaru + r95.json).

Status (2026-10-28, `docs/WYNIK-K2b.md`): korpus rozszerzony do 182 próbek (autor
zewnętrzny), pomiar poziomu 1 powtórzony po naprawie reguł (TELEFON/DATA) — wszystkie
progi K1 i „łącznie" **spełnione** (1.000/1.000); OSOBA recall 0.971 ✓, precision 0.943
✗ (próg 0.95). **Decyzja właściciela: FN groźniejszy niż FP — brama nie blokuje dalszych
kamieni**, próg zostaje. Poziom 2 (LFM2.5): pomiar wykonany (eksport ONNX fp32/int8,
adapter, kompozyt) — **zysku brak** (unia z rozmytymi granicami LFM2.5 obniża recall
i precision poziomu 1); LFM2.5 nie wchodzi, ślad mierzalny w repo. R95 odświeżone
(`niewidka/dane/r95.json`, OSOBA 0.0736).

## K3 — Formaty dokumentów (MVP: txt, docx)
Zakres: adaptery txt i docx (runy, czyszczenie metadanych/komentarzy/śledzonych zmian,
allowlist struktury); blokada elementów nieobsługiwanych. odt/xlsx/pptx/pdf — v1 (K6),
z decyzjami z `LLD.md` §9 (skan liczb/formuł w XLSX, redakcja PDF, polityka obrazów).

**Ukończono, gdy:** automatyczny test round-trip na plikach wzorcowych TXT i DOCX
potwierdza znacznik dokładnie na pozycji encji i poprawność mapowania przesunięć na runy;
dokument z makrem kończy się blokadą 422 z listą (dowód: `pytest tests/test_formaty.py`).

Status (2026-10-28, `docs/WYNIK-K2b.md`): **zrealizowany** — TXT (segment pojedynczy,
BOM tolerowany) i DOCX (akapity + komórki tabel + pola tekstowe; czyszczone: komentarze,
przypisy, nagłówki/stopki, właściwości app/core, miniatura, customXml; w:del usunięte,
w:ins jako treść; hiperłącza http zostają, mailto/file rozpakowane; allowlista — makra
i osadzone obiekty = blokada z listą); dopisek „ZANONIMIZOWANO w Niewidka…" na początku;
nazwa wyniku `ZANONIMIZOWANY_<krótki-id>.<ext>`; weryfikacja zapisu ZAWSZE (round-trip:
ponowne wczytanie i skan = 0 nowych znalezisk). Pliki wzorcowe: `narzedzia/generator_
dokumentow.py` (python-docx). Dowód: `pytest tests/test_formaty.py` — 27 zielonych.

Status K3b (2026-10-28, `docs/WYNIK-K3b.md`): **zrealizowany** — 15/15 punktów przeglądu
DOCX (Gemini) potwierdzonych testami (każdy padał na wzorcu pułapek) i naprawionych:
pola (instrText/fldSimple — instrukcja znika, wynik zostaje), osierocone w:t opakowane
w w:r, akceptacja śledzonych zmian bez author/date/initials i bez pustych w:tc, relacje
części dziedziczą los części, settings.xml czyszczone, zakładki/kotwice → _Bm1.., SDT
alias/tag, query string w URL, docPr/VML, people/custom/glossary usuwane, smartTag
rozpakowany. Kontrola zapisu ma drugą siatkę NIEZALEŻNĄ od adaptera: surowy skan każdej
części ZIP (XML wartość po wartości, binarne bajt po bajcie) + oryginały z mapy =
ostrzeżenie ORYGINAL blokujące. Poprawność wyników: python-docx otwiera, każda w:tc
ma w:p. Dowód: **314 passed, 1 xfailed**, ruff czysty.

## K4 — Mapa, przywracanie, API
Zakres: `mapa.py` (identyfikator zadania, warianty form), `klucze.py` (AES-256-GCM,
keyring/plik; uprawnienia 0600 tylko POSIX), `kontrola.py` (weryfikacja zapisu — zawsze,
blokada statusu), `api.py` (3 endpointy na 127.0.0.1, limity przed buforowaniem i po
dekompresji, kolejka, pula wątków, odpowiedź ZIP, middleware logów bez treści).

**Ukończono, gdy:** test end-to-end przez API — ukryj → przywróć odtwarza dane zastąpione
znacznikami (forma powierzchniowa każdej pozycji, także po przestawieniu zdań w wyniku);
mapa bez klucza nie odszyfrowuje; mapa z niezgodnym identyfikatorem → 422; pełna kolejka
zwraca 503 (dowód: `pytest tests/test_api.py`).

Status (2026-10-28, `docs/WYNIK-K4.md`): **zrealizowany** — konfig.py (TOML+env, LLD §14),
klucze.py (plik 0600/keyring, `BrakKlucza` bez fallbacku, CLI), mapa.py (AES-256-GCM,
identyfikator jako AAD, przywracanie po (oznaczenie, wariant) z rozbieżnościami), rdzeń
`ukryj`/`przywroc` (jedna para dla API i desktopu, kontrola zapisu zawsze, zip-bomb),
api.py (3 endpointy, token sesji, Host/Origin 403, limity 413 przed buforowaniem i po
dekompresji, 415/422/500 wg LLD §15, Semaphore(1)+timeout, kolejka 503+Retry-After,
middleware UUID bez treści). Żywy serwer: TXT round-trip identyczny (diff), DOCX wraca
w całości; negatywy 403/415 potwierdzone curl. Dowód: `NIEWIDKA_MODELE_KATALOG=…
pytest tests/ -q` → **256 passed, 1 xfailed**, ruff czysty (`tests/test_api.py` 16
zielonych).

## K5 — Web lokalny (→ **MVP**)
Zakres: `web/` — upload/wklejenie, suwak 1-3, jawny tryb („Na tym urządzeniu"), R95 +
ostrzeżenia (bez procentowego wskaźnika), pobranie wyniku i mapy, przełącznik przywracania.

**Ukończono, gdy:** pełny przepływ ręczny na 3 żywych dokumentach przez przeglądarkę działa
(ukryj → pobierz → przywróć); zrzuty ekranu; **ocena percepcyjna właściciela** (dowód: zrzuty + decyzja właściciela).

Status (2026-10-28, `docs/WYNIK-K5.md`): zrealizowany technicznie — `niewidka/web/` (3 pliki,
bez frameworka/CDN, font Lato OFL w repo), serwowane przez `api.py` z tokenem wstrzykniętym
w HTML; pełny E2E przez przeglądarkę (wklej → ukryj → zaślepki → przywróć) na żywym serwerze;
zrzuty 1440/390 w `docs/zrzuty/` i w `Desktop/C/` (ocena percepcyjna właściciela — **czeka na
decyzję**); kolejność skilli zachowana; recenzja końcowa impeccable: **ship**; 314 passed /
1 xfailed, ruff czysty. Po decyzji właściciela: teksty GUI idą przez Argona (zlecenie 12:55),
logo czapki i „jak to działa" — sesja równoległa.

## K6 — v1: pozostałe formaty, serwer organizacji, desktop, Android
Zakres: adaptery odt, xlsx (liczby/formuły/cache), pptx, pdf (redakcja, blokada mieszanych,
jednokierunkowy); tryb „Na serwerze organizacji" — uwierzytelnianie, HTTPS, klucz per
dokument/hasło klienta, autoryzacja odszyfrowania; pywebview + PyInstaller (Win/Mac/Linux);
PWA (manifest + service worker bez cache `/api/*`), opcjonalny TWA.

**Ukończono, gdy:** round-trip na plikach wzorcowych wszystkich 6 formatów potwierdza
znaczniki na pozycjach encji i blokady nieobsługiwanych elementów; serwer w LAN wymaga
logowania i odszyfrowuje wyłącznie mapy właściciela (test autoryzacji); pakiet PyInstaller
startuje na Windows dwuklikiem i przechodzi pełny przepływ lokalnie; PWA w Chrome/Androidzie
pracuje jako klient serwera organizacji (dowód: `pytest tests/test_formaty.py` + zrzuty).

---

MVP = K0–K5 (wklejony tekst + TXT + DOCX przez web lokalny). v1 = K6 (pozostałe formaty,
serwer organizacji, desktop + Android jako klient).
Poza zakresem do odwołania: OCR, makra, Android offline, własne treningi (§6 `HLD.md`).
