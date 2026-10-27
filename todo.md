# Niewidka - backlog zleceń

## 2026-10-27
- [x] 21:55 (właściciel) „załóż projekt w folderze klienta” do anonimizacji danych, nazwa jednym słowem po polsku z nawiązaniem do historii - Cichociemny.
  - [x] Katalog `~/niewidka` z git, CLAUDE.md, README (lista modeli)
- [ ] (właściciel) przegląd lokalnych modeli anonimizujących, m.in. LFM 350M (obsługuje polski)
  - [x] Lista kandydatów w `README.md`
  - [ ] Polskie próbki testowe + `KRYTERIA.md`
  - [ ] Pomiar kandydatów na stacjonarce
- [~] 23:36 (właściciel) „zbuduj możliwie najprostsze narzędzie do anonimizacji tekstu”: wklejony tekst albo lokalny dokument biurowy -> lokalny model (CPU/GPU) -> ten sam format z dopiskiem ZANONIMIZOWANY; ocena jakości anonimizacji w trakcie + odwracalność (numeracja); web (serwer w organizacji), okienkowa Win/Mac/Linux, Android; polski; suwak „Jakość wykrywania danych” (1-3 przebiegi/modele); sekrety tylko z key vault/pliku; kod nienaganny; konsultacje Argon+Astra na każdym kroku; HLD -> LLD -> kamienie milowe -> plan (testy na początku) -> wytwarzanie; ultraterminal masowo; codex na końcu do przeglądu.
  - [x] Konsultacja architektoniczna Astra (ChatGPT www) + Argon (Gemini www, odpowiedział Flash-Lite) – linki `docs/konsultacje/03-odpowiedzi-www.md`. Dostęp: TYLKO przez Chrome po stronie Windows (Claude in Chrome); `czaty.py` z WSL niezalogowany. Pytanie wklejać przez schowek (`powershell Set-Clipboard`), odpowiedź czytać `javascript_tool` kawałkami po ~1400 znaków (`window.__t.slice`).
  - [x] Synteza konsultacji -> `docs/KONSULTACJE.md` (commit „Nazwa Niewidka, synteza…”)
  - [x] `docs/HLD.md`, `LLD.md`, `KAMIENIE.md`, `PLAN.md` – wykonane przez claude-glm (commit ba3cad5, 4 pliki, 574 linie). Następnie: przegląd HLD/LLD przez Astrę i Argona, potem budowa (też claude-glm, kodowanie wyłącznie tam – polecenie właściciela).
  - [x] `docs/LLD.md` (commit ba3cad5)
  - [x] `docs/KAMIENIE.md` (kamienie milowe; commit ba3cad5)
  - [x] `docs/PLAN.md` (plan wykonania, testy jako pierwsze; commit ba3cad5)
  - [ ] Zestaw testowy (polskie próbki + oczekiwane encje) i `KRYTERIA.md`
  - [ ] Rdzeń: wykrywanie (reguły + model), zamiana na znaczniki numerowane, mapa przywracania, ocena jakości
  - [ ] Formaty: txt, docx, odt, xlsx, pdf (tekst) - ten sam format na wyjściu
  - [ ] Aplikacja web (serwer lokalny) + GUI okienkowe + Android
  - [ ] Przegląd kodu codex na końcu
- [~] 23:45 (właściciel) „zmień nazwę projektu na inną, niech argon i astra zaproponują coś, bo cichociemny nie może być”: ładna polska nazwa, oddaje cel (anonimizacja), ale bez tych słów wprost, nawiązanie do historii Polski albo opowiadań.
  - [x] Propozycje: Astra TOP3 Niewidka/Skrytopis/Pseudonim; Gemini agy2 TOP3 Niewidka/Kryptonim/Płachta; Argon-www Kryptonim (zajęte: portfel krypto)
  - [~] Wybrana **Niewidka** (`docs/KONSULTACJE.md`); zmienione README/CLAUDE.md/todo. ZOSTAJE: przeniesienie katalogu `niewidka` -> `niewidka` po zakończeniu sesji (zmiana w trakcie psuje hooki/cwd); repo GitHub `niewidka` – utworzenie publicznego repo wymaga zgody właściciela

## 2026-10-28
- [~] (właściciel) „zrealizuj kamienie K0 i K1 dokładnie wg PLAN.md/LLD.md”: K0 = korpus ≥40 próbek JSONL (polskie, fikcyjne, poprawne i błędne sumy kontrolne) + `KRYTERIA.md` (osobny commit PRZED pierwszym pomiarem) + `narzedzia/pomiar.py` (recall/precision per typ); K1 TDD = `model.py`, `reguly.py` (python-stdnum), `scalanie.py`, `osoby.py` (grupowanie odmian nazwisk), `znaczniki.py`; bez modeli ONNX (to K2). Venv `.venv`, pyproject, pytest lokalnie, ruff czysty, bez Dockera. Commity po każdym zielonym kroku (Co-Authored-By: GLM via claude-glm), bez pusha. Wynik: `docs/WYNIK-K1.md` (per typ vs progi, bez przesuwania progów) + statusy w todo.md.
  - [ ] K0: `KRYTERIA.md` z progami recall/precision (osobny commit przed pierwszym pomiarem)
  - [ ] K0: korpus ≥40 próbek JSONL (autor inny niż autor detektorów) + `tests/test_korpus.py` (walidacja formatu)
  - [ ] K0: `narzedzia/pomiar.py` — recall/precision per typ, działa na detektorze pustym
  - [ ] K1 TDD: `model.py` (TypEncji, Zakres, Encja, RunInfo, Segment, Dokument wg LLD §2)
  - [ ] K1 TDD: `reguly.py` (PESEL, NIP, REGON, IBAN, dowód, e-mail, telefon PL, adres, data; sumy kontrolne python-stdnum)
  - [ ] K1 TDD: `scalanie.py` (unia, priorytet sumy kontrolnej, wg LLD §5)
  - [ ] K1 TDD: `osoby.py` (grupowanie odmian nazwisk po rdzeniu, wg LLD §6)
  - [ ] K1 TDD: `znaczniki.py` ([TYP_N], zamiana od końca, wg LLD §7)
  - [ ] Pomiar K1 na korpusie → `docs/WYNIK-K1.md` (liczby per typ vs progi, co nie spełnia i dlaczego)
  - [ ] Aktualizacja statusów w todo.md + commit
