# Wydanie pakietów modeli: podpisywanie i publikacja

Instrukcja osoby wydającej Niewidkę. Podstawa: `docs/rozwoj/MAPY-I-AKTUALIZACJE.md` §5,
§8 wiersze 7-8, §9 wiersz 6. Narzędzie: `narzedzia/podpisz_katalog.py`.

## Co publikuje wydanie aktualizacji

1. `katalog-pakietow.json` — wykaz wersji: `wersja_katalogu`, lista pakietów
   (`wersja`, `min_wersja`, pliki z `zrodlo`, `rozmiar`, `sha256`).
2. `katalog-pakietow.json.sig` — podpis Ed25519 katalogu (surowe 64 B).
3. Pliki pakietów pod nazwami źródłowymi z pola `zrodlo` (załączniki wydania
   GitHub albo lustro IT). Program pobiera je względem `NIEWIDKA_MODELE_ZRODLO`.

Katalog i podpis muszą powstać z dokładnie tych samych bajtów: podpisuje się
plik PO ostatniej zmianie, nie przed.

## Klucze (jednorazowo, przed pierwszym podpisanym wydaniem)

```bash
# para testowa/produkcyjna; klucz prywatny LEŻY poza repo (magazyn sekretów wydawcy)
python narzedzia/podpisz_katalog.py --generuj-pare /sciezka/do/klucza/wydawcy.key
# wypisuje klucz publiczny (base64 surowych 32 bajtów) — ten trafia do repo
```

Klucz publiczny wpisujemy do `niewidka/dane/klucz-katalogu.pub`: po jednym w linii,
linie z `#` to komentarze. Klucz prywatny czytany jest WYŁĄCZNIE ze zmiennej
`NIEWIDKA_KLUCZ_PODPISU` (nigdy z argumentu, nigdy z repo, nigdy w logach):

```bash
NIEWIDKA_KLUCZ_PODPISU=/sciezka/do/klucza/wydawcy.key \
  python narzedzia/podpisz_katalog.py katalog-pakietow.json   # powstaje katalog-pakietow.json.sig
```

W repo (`niewidka/dane/klucz-katalogu.pub`) do czasu pierwszego wydania leży
placeholder. Program bez ważnego klucza działa normalnie na katalogu wbudowanym,
ale aktualizacje (zdalne i z folderu) są niedostępne z czytelnym komunikatem.

### Rotacja klucza (§9 w. 6)

1. Nowy klucz publiczny DOPISUJEMY do `klucz-katalogu.pub` i wydajemy program.
2. Od tego wydania podpisujemy katalogi nowym kluczem; stary w pliku zostaje,
   bo instalacje starszych wersji programu weryfikują nim dalej.
3. Stary klucz usuwamy z pliku dopiero, gdy przestajemy wspierać wersje programu,
   które go znają.

## Zasady numerowania

- `wersja_katalogu`: +1 przy KAŻDYM przyjęciu do publikacji. Program przyjmuje
  wyłącznie wersje WYŻSZE od ostatniej przyjętej (ochrona przed cofnięciem),
  a najwyższą przyjętą zapisuje osobno w `ustawienia.json`, więc jej nie obniży
  uszkodzony ani podmieniony plik katalogu.
- `wersja` pakietu: +1 przy nowych plikach tego pakietu; nowe SHA-256 i rozmiary
  obowiązkowe. Wersję mniejszą lub równą zainstalowanej program nie zaoferuje.
- `min_wersja`: podnosi się, gdy starsza wersja pakietu jest wadliwa i powrót
  do niej ma być zablokowany (przycisk „Wróć do poprzedniej wersji" odmówi).
- `probka-kontrolna.json`: przy zmianie zachowania wykrywania dopisujemy zdania
  z `musi_wykryc` (nowe możliwości) i `nie_moze_wykryc` (np. dawne fałszywe
  alarmy). Nowa wersja musi zaliczyć CAŁĄ próbkę, inaczej instalacja zostanie
  odrzucona, a poprzednia wersja zostanie na miejscu.

## Instalacja offline (sieć bez internetu)

Folder na pendrive od IT zawiera: `katalog-pakietow.json`, `katalog-pakietow.json.sig`
i pliki pakietów pod nazwami `zrodlo`. Użytkownik wkleja ścieżkę w Ustawieniach
(„Zainstaluj z folderu"). Program stosuje TĘ SAMĄ weryfikację co przy pobieraniu:
podpis, próg wersji, SHA-256 każdego pliku, próbka kontrolna, dopiero potem
atomowa zamiana z kopią poprzedniej wersji w `modele/.poprzednie/`.

Uwaga na rozróżnienie: „Zainstaluj z folderu” przy pakiecie w Ustawieniach
(`POST /api/pakiety`, akcja `instaluj`) to INNA droga — służy do wgrania wersji przypiętych w katalogu
wbudowanym danego programu (sha256 pilnuje katalog wbudowany, folder ma same
pliki). Nowości wersjonowane idą wyłącznie przez katalog podpisany.

## Checklista wydania

- [ ] `wersja_katalogu` o 1 wyższa niż ostatnio opublikowana.
- [ ] Zmienione pakiety mają podbite `wersja` i świeże `sha256` + `rozmiar`.
- [ ] `probka-kontrolna.json` odzwierciedla oczekiwane zachowanie nowej wersji.
- [ ] Podpis zrobiony PO ostatecznej treści katalogu kluczem ze zmiennej
      `NIEWIDKA_KLUCZ_PODPISU`; `.sig` pasuje do opublikowanego pliku.
- [ ] Weryfikacja przed publikacją: program testowy przyjmuje katalog i zalicza
      próbkę (pytest `tests/test_aktualizacje.py` przechodzi na tym katalogu).
- [ ] Załączniki wydania: katalog, podpis i wszystkie pliki z pól `zrodlo`.
- [ ] Licencje modeli obok paczek: `podstawowy-LICENSE.txt` (Apache 2.0 z repozytorium
      bardsai), `rozszerzony-LICENSE.txt` (LFM Open License v1.0 z repozytorium LiquidAI)
      i `NOTICE.txt` z informacją, że pliki ONNX powstały z tych modeli przez eksport
      i kwantyzację Q4 (oba pakiety). Wzór: załącznik `NOTICE.txt` wydania 0.1.0. Wymagają tego obie licencje.
- [ ] Klucz prywatny nie opuścił magazynu sekretów (nigdy: repo, CI cache, log).
