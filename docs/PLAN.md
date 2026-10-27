# Niewidka — plan wykonania

Zasady: zadania po 1–4 h; **najpierw korpus testowy i `KRYTERIA.md`** (polecenie właściciela,
progi recall/precision przed pierwszym pomiarem); TDD w rdzeniu; gotowe biblioteki zamiast
własnego kodu; kodowanie w claude-glm (polecenie właściciela), dyrygent planuje, odbiera
i weryfikuje; konsultacje Astra/Argon na przejściach etapów; przegląd końcowy codex.

## 0. Przegląd bibliotek (Library survey)

Gotowe biblioteki zamiast własnego kodu — decyzja domyślna dla każdej potrzeby:

| Potrzeba | Biblioteka | Własny kod tylko gdy |
|---|---|---|
| sumy kontrolne PESEL/NIP/REGON/IBAN | `python-stdnum` (`stdnum.pl.*`, `stdnum.iban`) | dowód osobisty, jeśli brak w stdnum (~10 linii) |
| szyfrowanie mapy | `cryptography` (AESGCM) | — |
| magazyn klucza | `keyring` | — |
| docx | `python-docx` + `lxml` | — |
| odt | `odfpy` | — |
| xlsx | `openpyxl` | — |
| pptx | `python-pptx` | — |
| pdf (tekst + redakcja) | `pymupdf` (AGPL-3.0 — decyzja licencyjna przed dystrybucją; zapas: `pypdfium2`) | — |
| inferencja NER | `onnxruntime` | — |
| tokenizacja + offsety | `tokenizers` | — |
| API | `fastapi` + `uvicorn` | — |
| desktop | `pywebview`, `pyinstaller` | — |
| kalibracja R95 (tylko narzędzia) | `scipy` | — |
| ~~spaCy/Morfeusz 2, GLiNER, torch~~ | odrzucone na MVP | po pomiarze, jeśli pokaże zysk |

## Etap 0 — Fundament pomiaru (PIERWSZE, ~7–9 h)

- [ ] T0.1 (1–2 h) `KRYTERIA.md`: progi recall/precision per typ i łącznie, progi poziomów
      1-3, zasady pomiaru. **Przed jakimkolwiek pomiarem.** Startowo do zatwierdzenia:
      reguły z sumą kontrolną — precision 1.00 na poprawnych numerach, 0 trafficień na błędnych;
      OSOBA (poziom 1) — recall ≥ 0.90, precision ≥ 0.95.
- [ ] T0.2 (3–4 h) Korpus: `tests/korpus/*.jsonl`, ≥ 40 próbek — odmiany imion i nazwisk,
      PESEL/NIP/REGON/IBAN poprawne **i z błędną sumą**, adresy, telefony, e-maile, dowody,
      daty, homonimy („Róża", „Wiśniewski" vs „wiśnie"), nazwiska-rzeczowniki („Kowal", „Nowak").
      **Autor korpusu ≠ autor detektorów** (reguła wariantów).
- [ ] T0.3 (2 h) `narzedzia/pomiar.py` + `tests/test_korpus.py`: walidacja formatu próbek,
      raport recall/precision per typ; działa na detektorze pustym.
- [ ] T0.4 (1–2 h) `narzedzia/wzorce.py`: generator plików wzorcowych docx/odt/xlsx/pptx/pdf/txt
      (w tym warianty z komentarzami, śledzonymi zmianami, makrem — do testów blokad).

## Etap 1 — Rdzeń regułowy, TDD (~10–12 h)

- [ ] T1.1 (2 h) `model.py` + `reguly.py`: PESEL (test → kod).
- [ ] T1.2 (2 h) NIP, REGON, IBAN (python-stdnum); normalizacja spacji/myślników.
- [ ] T1.3 (2–3 h) e-mail, telefon PL, dowód, adres (heurystyka), data.
- [ ] T1.4 (2 h) `scalanie.py` (unia, priorytet sumy kontrolnej) + testy nakładań.
- [ ] T1.5 (2 h) `osoby.py` (grupowanie po rdzeniu nazwiska) + `znaczniki.py` + testy.
- [ ] T1.6 (1 h) Pomiar reguł na korpusie, wynik do `WYNIK-pomiar.md`.

**Brama G1:** wynik K1 ≥ progi `KRYTERIA.md`; poniżej → naprawa reguł przed modelami.

## Etap 2 — Modele ONNX i jakość (~11–14 h)

- [ ] T2.1 (2–3 h) Pobranie bardsai (ONNX INT8) — HF przez `httpx`, wagi do magazynu
      poza repo, `manifest.json` z SHA-256; `OnnxDetektor` ładuje i liczy na CPU.
- [ ] T2.2 (2–3 h) Tokenizacja + `offset_mapping` + okna przesuwne → `list[Zakres]`.
- [ ] T2.3 (2 h) Pomiar: reguły vs reguły+bardsai na korpusie; decyzja o LFM2.5 **tylko
      przy wykazanym zysku** (KONSULTACJE). Wynik zapisany.
- [ ] T2.4 (3–4 h, warunkowe) LFM2.5 jako drugi detektor (uwaga: `trust_remote_code`;
      jeśli eksport do ONNX wymaga torch w runtime — odpuszczamy, odnotowujemy).
- [ ] T2.5 (2 h) `narzedzia/kalibracja.py` → `dane/r95.json`; `jakosc.py` (R95 + wskaźnik).

## Etap 3 — Formaty (~13–15 h)

- [ ] T3.1 (1 h) `formaty/tekst.py` + rejestr formatów.
- [ ] T3.2 (3–4 h) `docx_.py`: scalanie runów, `starts`, wstawianie ze stylem, czyszczenie
      (komentarze, śledzone zmiany, metadane).
- [ ] T3.3 (2 h) `odt_.py`.
- [ ] T3.4 (2 h) `xlsx_.py` (komórki, arkusz dopisku, ukryte arkusze).
- [ ] T3.5 (3 h) `pdf_.py` (PyMuPDF: ekstrakcja bloków, redakcja + znacznik; skan → blokada).
- [ ] T3.6 (2 h) `pptx_.py` (+ notatki prelegenta).
- [ ] T3.7 (1–2 h) Blokady nieobsługiwanych elementów + `tests/test_formaty.py` (round-trip 6 formatów).

## Etap 4 — Mapa, przywracanie, API (~8–10 h)

- [ ] T4.1 (2 h) `mapa.py` + `klucze.py`: AES-256-GCM, keyring/plik, CLI.
- [ ] T4.2 (2 h) Przywracanie wg `kolejny` + rozbieżności form + testy.
- [ ] T4.3 (2 h) `kontrola.py` (poziom 3: ponowny odczyt, okna przesunięte).
- [ ] T4.4 (2–3 h) `api.py`: 3 endpointy, kolejka, limity, błędy wg LLD §15.
- [ ] T4.5 (1 h) `tests/test_api.py`: end-to-end ukryj → przywróć = oryginał; 413/422/503.

## Etap 5 — Web, MVP (~4–6 h)

- [ ] T5.1 (3–4 h) `web/`: upload/wklejenie, wynik + mapa do pobrania, wskaźnik, R95,
      ostrzeżenia, przywracanie.
- [ ] T5.2 (1–2 h) Suwak poziomów 1-3 + jawny tryb („Na tym urządzeniu" / „Na serwerze organizacji").

**Brama G2 = MVP (K5):** pokazanie właścicielowi — ocena percepcyjna należy do właściciela.

## Etap 6 — Desktop i Android, v1 (~5–8 h)

- [ ] T6.1 (1–2 h) pywebview ładujące `web/`.
- [ ] T6.2 (2–3 h) PyInstaller (onedir) + test uruchomienia na Windows.
- [ ] T6.3 (2 h) PWA: manifest + service worker (cache tylko powłoki, `no-store` na `/api/*`).
- [ ] T6.4 (2 h, opcja) TWA (Bubblewrap).

## Zamknięcie (poza etapami)

- Przegląd HLD/LLD przez Astrę i Argona — **przed Etapem 1** (zlecone w backlogu).
- Konsultacje Astra/Argon na przejściach etapów; przegląd końcowy kodu **codex** (polecenie właściciela).
- Każdy pomiar porównawczy: kryteria spisane wcześniej, wynik i słabości zwycięzcy zapisane.

## Zależności i ryzyka

- Kolejność twarda: Etap 0 → 1 → (2 ∥ 3) → 4 → 5 → 6; formaty (E3) można równoleglić z E2.
- LFM2.5: `trust_remote_code` i eksport ONNX — brama T2.3, odpuszczamy bez kosztu jakości MVP.
- PyMuPDF AGPL-3.0: dla użycia wewnątrz organizacji OK; decyzja przed dystrybucją zewnętrzną.
- Pobieranie z HF: wyłącznie `httpx` (środowisko B); wagi nigdy do repo.
- Szacunek łączny: ~58–74 h (bez opcjonalnego T6.4).
