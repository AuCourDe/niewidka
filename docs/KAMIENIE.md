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

Status (2026-10-28, `docs/WYNIK-K2.md`): pomiar wykonany; progi K1 i „łącznie" poziomu 1
spełnione, OSOBA recall 0.957 spełnia, **precision 0.917 nie spełnia progu 0.95** — brama
niezaliczona, opcje dalsze w WYNIK-K2. R95 wygenerowane (`niewidka/dane/r95.json`).
Poziom 2 (LFM2.5, 1.4 GB): **czeka na miejsce na dysku** (`~/models` — 887 MB wolne).

## K3 — Formaty dokumentów (MVP: txt, docx)
Zakres: adaptery txt i docx (runy, czyszczenie metadanych/komentarzy/śledzonych zmian,
allowlist struktury); blokada elementów nieobsługiwanych. odt/xlsx/pptx/pdf — v1 (K6),
z decyzjami z `LLD.md` §9 (skan liczb/formuł w XLSX, redakcja PDF, polityka obrazów).

**Ukończono, gdy:** automatyczny test round-trip na plikach wzorcowych TXT i DOCX
potwierdza znacznik dokładnie na pozycji encji i poprawność mapowania przesunięć na runy;
dokument z makrem kończy się blokadą 422 z listą (dowód: `pytest tests/test_formaty.py`).

## K4 — Mapa, przywracanie, API
Zakres: `mapa.py` (identyfikator zadania, warianty form), `klucze.py` (AES-256-GCM,
keyring/plik; uprawnienia 0600 tylko POSIX), `kontrola.py` (weryfikacja zapisu — zawsze,
blokada statusu), `api.py` (3 endpointy na 127.0.0.1, limity przed buforowaniem i po
dekompresji, kolejka, pula wątków, odpowiedź ZIP, middleware logów bez treści).

**Ukończono, gdy:** test end-to-end przez API — ukryj → przywróć odtwarza dane zastąpione
znacznikami (forma powierzchniowa każdej pozycji, także po przestawieniu zdań w wyniku);
mapa bez klucza nie odszyfrowuje; mapa z niezgodnym identyfikatorem → 422; pełna kolejka
zwraca 503 (dowód: `pytest tests/test_api.py`).

## K5 — Web lokalny (→ **MVP**)
Zakres: `web/` — upload/wklejenie, suwak 1-3, jawny tryb („Na tym urządzeniu"), R95 +
ostrzeżenia (bez procentowego wskaźnika), pobranie wyniku i mapy, przełącznik przywracania.

**Ukończono, gdy:** pełny przepływ ręczny na 3 żywych dokumentach przez przeglądarkę działa
(ukryj → pobierz → przywróć); zrzuty ekranu; **ocena percepcyjna właściciela** (dowód: zrzuty + decyzja właściciela).

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
