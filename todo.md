# Cichociemny - backlog zleceń

## 2026-10-27
- [x] 21:55 (właściciel) „załóż projekt w folderze klienta” do anonimizacji danych, nazwa jednym słowem po polsku z nawiązaniem do historii - Cichociemny.
  - [x] Katalog `~/niewidka` z git, CLAUDE.md, README (lista modeli)
- [ ] (właściciel) przegląd lokalnych modeli anonimizujących, m.in. LFM 350M (obsługuje polski)
  - [x] Lista kandydatów w `README.md`
  - [ ] Polskie próbki testowe + `KRYTERIA.md`
  - [ ] Pomiar kandydatów na stacjonarce
- [~] 23:36 (właściciel) „zbuduj możliwie najprostsze narzędzie do anonimizacji tekstu”: wklejony tekst albo lokalny dokument biurowy -> lokalny model (CPU/GPU) -> ten sam format z dopiskiem ZANONIMIZOWANY; ocena jakości anonimizacji w trakcie + odwracalność (numeracja); web (serwer w organizacji), okienkowa Win/Mac/Linux, Android; polski; suwak „Jakość wykrywania danych” (1-3 przebiegi/modele); sekrety tylko z key vault/pliku; kod nienaganny; konsultacje Argon+Astra na każdym kroku; HLD -> LLD -> kamienie milowe -> plan (testy na początku) -> wytwarzanie; ultraterminal masowo; codex na końcu do przeglądu.
  - [~] Konsultacja architektoniczna Argon + Astra -> pytanie `docs/konsultacje/01-pytanie-architektura.md`, odpowiedzi `01-astra.md`, `01-argon.md`. Argon (czaty.py argon1) NIEZALOGOWANY -> zastępczo Gemini 3.1 Pro przez `ultraterminal agy2` (id 1027-233810-agy2-fd0a). Filtr Astry blokuje słowo „R” (np. XLM-R).
  - [ ] Synteza konsultacji -> `docs/KONSULTACJE.md`
  - [ ] `docs/HLD.md`
  - [ ] `docs/LLD.md`
  - [ ] `docs/KAMIENIE.md` (kamienie milowe)
  - [ ] `docs/PLAN.md` (plan wykonania, testy jako pierwsze)
  - [ ] Zestaw testowy (polskie próbki + oczekiwane encje) i `KRYTERIA.md`
  - [ ] Rdzeń: wykrywanie (reguły + model), zamiana na znaczniki numerowane, mapa przywracania, ocena jakości
  - [ ] Formaty: txt, docx, odt, xlsx, pdf (tekst) - ten sam format na wyjściu
  - [ ] Aplikacja web (serwer lokalny) + GUI okienkowe + Android
  - [ ] Przegląd kodu codex na końcu
