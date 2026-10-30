# Niewidka: przewodnik

Co program umie, jak działa w środku i jak go wdrożyć. Instrukcja klikania jest
w `docs/INSTRUKCJA.md`, wszystkie ustawienia w `docs/KONFIGURACJA.md`.

## Do czego służy

Chcesz, żeby czat AI streścił pismo, poprawił odpowiedź na skargę albo przygotował
notatkę. Pismo zawiera dane osobowe, więc nie możesz go wysłać. Niewidka zamienia te dane
na znaczniki, a po odpowiedzi czatu wstawia je z powrotem.

```
Jan Kowalski, PESEL 44051401359, ul. Lipowa 5, Gdańsk
          ↓ Ukryj
[OSOBA_1], PESEL [PESEL_1], [ADRES_1]
          ↓ czat AI pracuje na tekście ze znacznikami
          ↓ Przywróć
Jan Kowalski, PESEL 44051401359, ul. Lipowa 5, Gdańsk
```

## Co wykrywa

| Znacznik | Co to jest | Jak wykrywa |
|---|---|---|
| `OSOBA` | imiona i nazwiska, także w odmianie | model językowy, na poziomie 3 także słownik imion GUS |
| `PESEL`, `NIP`, `REGON`, `IBAN`, `KARTA` | numery z sumą kontrolną | reguły i suma kontrolna |
| `DOKUMENT` | numery dowodów osobistych | reguły i suma kontrolna |
| `ADRES`, `TELEFON`, `EMAIL`, `DATA` | adresy, telefony, e-maile, daty | reguły i model |
| `IP`, `SWIFT`, `LOGIN` | adresy IP, kody banków, loginy | reguły; pakiet rozszerzony na poziomie 3 |
| `INNE` | wszystko, co dodasz sam | Twoje poprawki i stałe listy |

Ta sama osoba ma ten sam znacznik w całym tekście, także w innej formie
(„Jana Kowalskiego” to nadal `[OSOBA_1]`). Daty można wyłączyć w ustawieniach.

## Trzy poziomy jakości

| Poziom | Co robi | Kiedy |
|---|---|---|
| Szybko | reguły i model, jeden przebieg | krótkie, proste teksty |
| Dokładniej | niższy próg pewności dla osób i drugi przebieg przesunięty o pół okna | zwykłe pisma, ustawienie domyślne |
| Najdokładniej | jak wyżej oraz słownik imion GUS, z pakietem rozszerzonym także IP, SWIFT i loginy | pisma, w których pomyłka kosztuje najwięcej |

Wyniki pomiarów każdego poziomu są w `docs/MODELE.md`.

## Kontrola jakości

Po ukryciu program wczytuje wynik jak obcy dokument i jeszcze raz szuka w nim danych
osobowych. Wszystko, co znajdzie, a co nie jest znacznikiem, trafia na listę do przejrzenia.
Plik `.docx` przegląda dodatkowo na surowo, część po części.

- **zaliczona**: nic podejrzanego nie zostało;
- **sprawdź wynik**: są miejsca do przejrzenia, lista pokazuje każde z nich;
- **STOP**: kopiowanie i pobieranie czekają, aż zdecydujesz o każdym miejscu.

Kontrola zmniejsza ryzyko, ale go nie usuwa. Wynik zawsze przegląda człowiek.

## Mapa

Mapa to spis: który znacznik zastąpił jaką daną. Bez niej nie da się przywrócić tekstu.

- Program zapisuje mapę każdego dokumentu na Twoim komputerze, zaszyfrowaną kluczem
  AES-256. Klucz leży w magazynie haseł systemu albo w pliku wskazanym przez IT.
  Program go nie zapisuje u siebie.
- Mapa wygasa po 30 dniach. Okres ustala administrator.
- Pierwsza linia wyniku zawiera identyfikator mapy. Jeśli czat ją zostawi, program
  sam dobierze mapę przy przywracaniu.
- Mapę możesz też pobrać jako plik `.nwidka` i dołączyć do akt sprawy.

## Gdy program się pomyli

Poprawiasz wynik w podglądzie, bez ponownego ukrywania:

- słowo ukryte niepotrzebnie: kliknij plakietkę, „To nie dane osobowe”;
- dana pominięta: zaznacz ją i kliknij „Ukryj wszędzie”;
- powtarzający się kłopot: dodaj słowo do stałej listy „Zawsze ukrywaj” albo
  „Nigdy nie ukrywaj”. Administrator może ustawić listy dla wszystkich.

Numerów z poprawną sumą kontrolną nie da się odkryć. Program uznaje je za dane osobowe zawsze.

## Pliki

Program przyjmuje `.txt` i `.docx` do 25 MB. Wynik ma ten sam format co plik wejściowy,
a dokument `.docx` zachowuje układ i style treści. Z `.docx` program usuwa komentarze,
przypisy, nagłówki, stopki, miniaturę i dodatkowe właściwości pliku, bo tam często zostają
nazwiska i e-maile. Obrazy domyślnie też usuwa, bo nie czyta z nich tekstu. Dokument
z nieznaną częścią wewnętrzną odrzuca. Skanów i PDF nie obsługuje.

## Sposoby wdrożenia

**Jeden komputer.** Wersja okienkowa z ZIP, modele pobrane przy pierwszym uruchomieniu.
Nic więcej nie trzeba.

**Wiele komputerów bez internetu.** IT pobiera pliki pakietów raz i kładzie je w folderze
sieciowym. Użytkownik wkleja ścieżkę w Ustawieniach i klika „Zainstaluj z folderu”. Można też
wystawić folder na serwerze HTTP i ustawić `NIEWIDKA_MODELE_ZRODLO`. Program sprawdza
sumę SHA-256 każdego pliku.

**Wspólny serwer modeli.** Modele działają na jednym serwerze w sieci urzędu, na procesorze
albo karcie graficznej. Na komputery użytkowników trafia sam program. Do serwera idzie
tylko tekst do sprawdzenia, przez TLS i z tokenem. Mapy i klucze zostają u użytkowników.
Opis: `docs/SERWER-INFERENCJI.md`.

## Bezpieczeństwo w skrócie

- Program nasłuchuje tylko na `127.0.0.1`. Każde zapytanie wymaga tokenu sesji ze strony.
- Treść dokumentów nie trafia do dziennika. W razie błędu dziennik dostaje sam identyfikator.
- Przy błędzie modelu program niczego nie zwraca. Nie poda tekstu, którego nie sprawdził.
- Aktualizacje modeli są podpisane. Program instaluje nową wersję dopiero po teście
  na przykładowych zdaniach i zostawia poprzednią do cofnięcia.

## Czego program nie robi

- Nie gwarantuje wykrycia wszystkich danych. Rzadkie nazwiska, pseudonimy i opisy
  pozwalające rozpoznać osobę („sąsiad z trzeciego piętra”) mogą przejść.
- Nie czyta obrazów, skanów ani PDF.
- Wersja w przeglądarce nie ma kont użytkowników, więc każdy uruchamia ją u siebie.
