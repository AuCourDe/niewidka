# Argon: redakcja README, instrukcji obsługi i konfiguracji (2026-10-30)

Zapytanie: redakcja trzech plików (README.md, docs/INSTRUKCJA.md, docs/KONFIGURACJA.md),
zasady: ludzki język, zero półpauz i pauz, bez uzasadniania każdego zdania, fakty bez zmian.

Przyjęte z redakcji: krótsze zdania, tryb rozkazujący, uproszczenia w „Poprawianiu wyniku”,
„Gdy kontrola zatrzyma wynik”, „Ustawieniach” i tabeli kłopotów.

Odrzucone z redakcji: „wyślesz bezpiecznie” (obietnica bez pokrycia), „instalator programu”
(myli się z plikiem instalatora), „program odmówi startu” przy złych uprawnieniach klucza
(program odrzuca klucz, nie start), linki Markdown wstawione przez Gemini do bloków kodu.

Uwagi Argona i co z nimi zrobiono:
1. Dopisek ZANONIMIZOWANY a numer mapy: to ta sama pierwsza linia. Dopisane w INSTRUKCJI.
2. Instalacja modeli bez internetu: interfejs nie ma przycisku instalacji pakietów z folderu
   (jest tylko w API). Opisano lustro HTTP przez NIEWIDKA_MODELE_ZRODLO. Brak przycisku zgłoszony właścicielowi.
3. Poziomy 1/2/3 a nazwy z suwaka: dopisane. Przy okazji: opcja `poziom` dotyczy tylko zapytań API bez poziomu.
4. Wartości `provider`: dopisane.
5. Zmienne bez klucza TOML: przeniesione do tabeli „Tylko zmienne środowiskowe”.
6. Python 3.13 do budowy a 3.11 do uruchomienia: celowe, bez zmian.
7. `nowy-plik` nie nadpisuje pliku: dopisane.
