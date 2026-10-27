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
