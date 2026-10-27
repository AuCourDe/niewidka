# Niewidka — kamienie milowe (MVP → v1)

Każdy kamień ma mierzalne kryterium ukończenia; dowód w nawiasie. Kolejność zgodna
z `PLAN.md`. Korpus i kryteria **przed** jakimkolwiek pomiarem (polecenie właściciela).

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

## K2 — Detekcja modelowa i jakość
Zakres: `detektory.py` (bardsai ONNX INT8; LFM2.5 warunkowo), okna przesuwne, `jakosc.py`,
kalibracja R95, pomiar porównawczy „reguły" vs „reguły+model" (poziom 1/2).

**Ukończono, gdy:** poziom 1 osiąga progi `KRYTERIA.md` (recall OSOBA i precision); decyzja
o LFM2.5 udokumentowana pomiarem; `dane/r95.json` wygenerowany (dowód: WYNIK pomiaru + r95.json).

## K3 — Formaty dokumentów
Zakres: adaptery txt, docx (runy), odt, xlsx, pptx, pdf; czyszczenie metadanych/komentarzy/
śledzonych zmian/notatek; blokada elementów nieobsługiwanych.

**Ukończono, gdy:** automatyczny test round-trip na plikach wzorcowych wszystkich 6 formatów
potwierdza znacznik dokładnie na pozycji encji i poprawność mapowania przesunięć na runy;
dokument z makrem/skanem kończy się blokadą 422 z listą (dowód: `pytest tests/test_formaty.py`).

## K4 — Mapa, przywracanie, API
Zakres: `mapa.py`, `klucze.py` (AES-256-GCM, keyring/plik), `kontrola.py` (poziom 3),
`api.py` (3 endpointy, limity, kolejka).

**Ukończono, gdy:** test end-to-end przez API — ukryj → przywróć daje treść równą oryginałowi;
mapa bez klucza nie odszyfrowuje (test); pełna kolejka zwraca 503 (dowód: `pytest tests/test_api.py`).

## K5 — Web (→ **MVP**)
Zakres: `web/` — upload/wklejenie, suwak 1-3, tryb jawny, wskaźnik + R95 + ostrzeżenia,
pobranie wyniku i mapy, przełącznik przywracania.

**Ukończono, gdy:** pełny przepływ ręczny na 3 żywych dokumentach przez przeglądarkę działa
(ukryj → pobierz → przywróć); zrzuty ekranu; **ocena percepcyjna właściciela** (dowód: zrzuty + decyzja właściciela).

## K6 — Desktop i Android (→ **v1**)
Zakres: pywebview + PyInstaller (Win/Mac/Linux), PWA (manifest + service worker bez cache `/api/*`),
opcjonalny TWA.

**Ukończono, gdy:** pakiet PyInstaller startuje na Windows dwuklikiem i przechodzi pełny
przepływ lokalnie; PWA otwarta w Chrome/Androidzie pracuje jako klient serwera organizacji
(dowód: zrzut z Windows i z telefonu).

---

MVP = K0–K5 (używalne przez web w organizacji). v1 = K6 (desktop + Android jako klient).
Poza zakresem do odwołania: OCR, makra, Android offline, własne treningi (§6 `HLD.md`).
