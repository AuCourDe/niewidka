# Cichociemny - reguły pracy nad projektem

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
- Kandydaci i ich stan: `README.md`. Kryteria porównania spisać w `KRYTERIA.md` PRZED pomiarem.
- Na środowisku B pobieranie z HF wyłącznie przez `httpx` (bez `huggingface_hub`).
