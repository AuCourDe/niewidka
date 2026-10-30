# Niewidka (dawniej Cichociemny) - reguły pracy nad projektem

**Target: CLIENT_B** (katalog klienta). Profil: `~/.claude/environments/CLIENT_B.md`.
Na dziś w repo nie ma danych klienta; zasady B dotyczą środowiska docelowego.
Komunikacja i dokumentacja po polsku.

## Cel

Lokalna anonimizacja danych osobowych w tekście polskim: wykrycie (imiona i nazwiska
w odmianie, PESEL, NIP, REGON, adresy, telefony, e-maile, IBAN, numery dokumentów)
i zastąpienie ich znacznikami albo pseudonimami. Wyłącznie modele uruchamiane lokalnie,
bez wysyłania danych na zewnątrz.

## Zasady

- Wagi modeli tylko w magazynie z pliku maszyny (stacjonarka: `~/models`), nie w repo.
- Kandydaci i ich stan: `README.md`. Kryteria porównania spisać w `docs/rozwoj/KRYTERIA.md` PRZED pomiarem.
- Na środowisku B pobieranie z HF wyłącznie przez `httpx` (bez `huggingface_hub`).

## Nazwa i architektura (2026-10-27)
- Nazwa: **Niewidka** (czapka niewidka). Katalog nadal `Cichociemny` do czasu przeniesienia (zmiana katalogu w trakcie sesji psuje hooki).
- Decyzje architektoniczne: `docs/rozwoj/KONSULTACJE.md`. Projekt dokumentów: `docs/rozwoj/HLD.md`, `docs/rozwoj/LLD.md`, plan `docs/rozwoj/PLAN.md`.
- Kod: Python w `niewidka/` (rdzeń bez HTTP/GUI), testy `tests/` (pytest), interfejs web `niewidka/web/` (bez frameworka).
- Sekrety (klucz mapy) wyłącznie z magazynu systemowego (`keyring`) albo pliku sekretów wskazanego zmienną środowiskową; nigdy w repo, konfiguracji ani logach.
