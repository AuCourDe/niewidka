# Niewidka - backlog zleceń

## 2026-10-27
- [x] 21:55 (właściciel) „załóż projekt w folderze klienta” do anonimizacji danych, nazwa jednym słowem po polsku z nawiązaniem do historii - Cichociemny.
  - [x] Katalog `~/niewidka` z git, CLAUDE.md, README (lista modeli)
- [ ] (właściciel) przegląd lokalnych modeli anonimizujących, m.in. LFM 350M (obsługuje polski)
  - [x] Lista kandydatów w `README.md`
  - [x] Polskie próbki testowe + `KRYTERIA.md` (2026-10-28: korpus 62 próbek `tests/korpus/`, commit `1a3320c`; progi commit `2d173a6`)
  - [ ] Pomiar kandydatów na stacjonarce (= kamień K2; pomiar reguł K1 zrobiony, `docs/WYNIK-K1.md`)
- [~] 23:36 (właściciel) „zbuduj możliwie najprostsze narzędzie do anonimizacji tekstu”: wklejony tekst albo lokalny dokument biurowy -> lokalny model (CPU/GPU) -> ten sam format z dopiskiem ZANONIMIZOWANY; ocena jakości anonimizacji w trakcie + odwracalność (numeracja); web (serwer w organizacji), okienkowa Win/Mac/Linux, Android; polski; suwak „Jakość wykrywania danych” (1-3 przebiegi/modele); sekrety tylko z key vault/pliku; kod nienaganny; konsultacje Argon+Astra na każdym kroku; HLD -> LLD -> kamienie milowe -> plan (testy na początku) -> wytwarzanie; ultraterminal masowo; codex na końcu do przeglądu.
  - [x] Konsultacja architektoniczna Astra (ChatGPT www) + Argon (Gemini www, odpowiedział Flash-Lite) – linki `docs/konsultacje/03-odpowiedzi-www.md`. Dostęp: TYLKO przez Chrome po stronie Windows (Claude in Chrome); `czaty.py` z WSL niezalogowany. Pytanie wklejać przez schowek (`powershell Set-Clipboard`), odpowiedź czytać `javascript_tool` kawałkami po ~1400 znaków (`window.__t.slice`).
  - [x] Synteza konsultacji -> `docs/KONSULTACJE.md` (commit „Nazwa Niewidka, synteza…”)
  - [x] `docs/HLD.md`, `LLD.md`, `KAMIENIE.md`, `PLAN.md` – wykonane przez claude-glm (commit ba3cad5, 4 pliki, 574 linie). Następnie: przegląd HLD/LLD przez Astrę i Argona, potem budowa (też claude-glm, kodowanie wyłącznie tam – polecenie właściciela).
  - [x] `docs/LLD.md` (commit ba3cad5)
  - [x] `docs/KAMIENIE.md` (kamienie milowe; commit ba3cad5)
  - [x] `docs/PLAN.md` (plan wykonania, testy jako pierwsze; commit ba3cad5)
  - [x] Zestaw testowy (polskie próbki + oczekiwane encje) i `KRYTERIA.md` (2026-10-28: korpus 62 próbek + progi; `docs/WYNIK-K1.md`)
  - [~] Rdzeń: wykrywanie (reguły + model), zamiana na znaczniki numerowane, mapa przywracania, ocena jakości — reguły + scalanie + osoby + znaczniki zrobione (K1, `docs/WYNIK-K1.md`); model ONNX = K2, mapa = K4, ocena jakości = K2
  - [~] Poprawki z przeglądu Astry+Gemini (docs+kod) – claude-glm id 1028-011253-claude-glm-9d8e (/tmp/cc-glm-lld2.md)
  - [ ] K2 (bardsai ONNX, pomiar, R95) – /tmp/cc-glm-k2.md, startuje sam po 9d8e (log /tmp/cc-k2-start.log). 🔴 Dysk /mnt/projekty 100% (1,5 GB wolne): LFM2.5 (poziom 2, 1,4 GB) czeka na miejsce – decyzja właściciela
  - [ ] Formaty: txt, docx, odt, xlsx, pdf (tekst) - ten sam format na wyjściu
  - [ ] Aplikacja web (serwer lokalny) + GUI okienkowe + Android
  - [ ] Przegląd kodu codex na końcu
- [~] 23:45 (właściciel) „zmień nazwę projektu na inną, niech argon i astra zaproponują coś, bo cichociemny nie może być”: ładna polska nazwa, oddaje cel (anonimizacja), ale bez tych słów wprost, nawiązanie do historii Polski albo opowiadań.
  - [x] Propozycje: Astra TOP3 Niewidka/Skrytopis/Pseudonim; Gemini agy2 TOP3 Niewidka/Kryptonim/Płachta; Argon-www Kryptonim (zajęte: portfel krypto)
  - [~] Wybrana **Niewidka** (`docs/KONSULTACJE.md`); zmienione README/CLAUDE.md/todo. ZOSTAJE: przeniesienie katalogu `niewidka` -> `niewidka` po zakończeniu sesji (zmiana w trakcie psuje hooki/cwd); repo GitHub `niewidka` – utworzenie publicznego repo wymaga zgody właściciela

## 2026-10-28
- [x] (właściciel) „zrealizuj kamienie K0 i K1 dokładnie wg PLAN.md/LLD.md”: K0 = korpus ≥40 próbek JSONL (polskie, fikcyjne, poprawne i błędne sumy kontrolne) + `KRYTERIA.md` (osobny commit PRZED pierwszym pomiarem) + `narzedzia/pomiar.py` (recall/precision per typ); K1 TDD = `model.py`, `reguly.py` (python-stdnum), `scalanie.py`, `osoby.py` (grupowanie odmian nazwisk), `znaczniki.py`; bez modeli ONNX (to K2). Venv `.venv`, pyproject, pytest lokalnie, ruff czysty, bez Dockera. Commity po każdym zielonym kroku (Co-Authored-By: GLM via claude-glm), bez pusha. Wynik: `docs/WYNIK-K1.md` (per typ vs progi, bez przesuwania progów) + statusy w todo.md.
  - [x] K0: `KRYTERIA.md` z progami recall/precision (osobny commit `2d173a6` PRZED pierwszym pomiarem)
  - [x] K0: korpus 62 próbki JSONL (autor zewnętrzny opencode/deepseek, commit `1a3320c`) + `tests/test_korpus.py` zielone (walidacja formatu, sum przez stdnum, pułapki, pokrycie)
  - [x] K0: `narzedzia/pomiar.py` (commit `e7ed6fa`) — sanity na detektorze pustym: recall 0,0
  - [x] K1 TDD: `model.py` (commit `2d8f8a9`)
  - [x] K1 TDD: `reguly.py` — cykle A/B/C (`ec057a2`, `64bef30`, `66f5e48`); sumy kontrolne: python-stdnum (PESEL/NIP/REGON/IBAN) + własny walidator dowodu (stdnum nie obejmuje; algorytm z algorytm.org)
  - [x] K1 TDD: `scalanie.py` (commit `3b0abc4`) — maskowanie UNIĄ grup nakładań (przegląd Astry pkt 1), etykieta wg priorytetów LLD §5
  - [x] K1 TDD: `osoby.py` (commit `6c7e103`) — rdzenie odmian nazwiska i imienia, asocjacja wsteczna (Gemini #13), niejednoznaczne rozdzielone (Astra #10)
  - [x] K1 TDD: `znaczniki.py` (commity `70a3fec`, `788db17`) — `[TYP_N]`, zamiana od końca, dopisek bez nawiasów (Gemini #7)
  - [x] Pomiar K1 → `docs/WYNIK-K1.md`: recall 1.000 / precision 1.000 na WSZYSTKICH typach K1 (40/40 TP, 0 FP na pułapkach); OSOBA 0/23 poza zakresem reguł (K2); progi nieprzesunięte, nic nie wymagało przesunięcia
  - [x] Aktualizacja statusów w todo.md + commit (pełny zestaw: 71 testów zielonych, ruff czysty, bez pusha)
- [~] 01:22 (właściciel) „wprowadź uwagi z przeglądów do dokumentacji i do kodu, który już istnieje (K0/K1)”: każda uwaga krytyczna z 04-przeglad-astra.md ma odpowiedź w nowej sekcji LLD „Odpowiedzi na przegląd” (zmiana albo świadome odrzucenie z powodem); zawężenie MVP: wklejony tekst + TXT + DOCX + web lokalny, reszta formatów i kanałów w v1 po K-kamieniach; kod TDD: scalanie (test własności unii z [0,12)+[8,20)), znaczniki ze stabilnym wariantem formy ([OSOBA_1_F2] albo równoważne + opis w LLD), osoby domyślnie nie łączą niejednoznacznych (test kontrprzykładów), błędna suma kontrolna = encja „podejrzana”, nie odrzucona (KRYTERIA: tylko definicja, nie próg, z powodem). Testy zielone, ruff czysty, commit po każdym kroku (Co-Authored-By: GLM via claude-glm), bez pusha.
  - [ ] Dokumenty: HLD/LLD/KAMIENIE/PLAN — zawężone MVP + LLD „Odpowiedzi na przegląd” (Astra, Gemini) + definicja podejrzanych w KRYTERIA
  - [ ] Scalanie: test własności — maskowany obszar = suma zaakceptowanych zakresów (przypadek [0,12)+[8,20))
  - [ ] Znaczniki: stabilny wariant formy [OSOBA_N_Fk] + opis w LLD
  - [ ] Osoby: kontrprzykłady — niejednoznaczne domyślnie niełączone
  - [ ] Podejrzane: błędna suma = encja z flagą (model/reguly/scalanie/pomiar); ponowny pomiar + dopisek w WYNIK-K1
  - [ ] Statusy w todo.md na koniec
