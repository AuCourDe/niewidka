# Niewidka — logika aplikacji (do konsultacji: poprawność podejścia i ułatwienia dla użytkownika)

Stan: 2026-10-29, commit 8e62ba5. Dokument bez danych klienta. Przykłady są fikcyjne.

## Cel i odbiorca

Ludzie, którzy nie mogą wysyłać dokumentów jawnie do chmurowego AI (urzędy, banki, kancelarie),
a chcą z niego korzystać. Niewidka na ich komputerze ukrywa dane osobowe w tekście albo dokumencie.
Wynik idzie do AI. Odpowiedź AI wraca i Niewidka przywraca w niej oryginalne dane.
Użytkownik jest nietechniczny. Nic nie wychodzi z komputera poza jednorazowym pobraniem modeli.

## Formy

- **Okienkowa (Windows, potem Linux i Mac):** EXE z oknem. W środku działa lokalny serwer na losowym
  wolnym porcie, dostępny tylko z 127.0.0.1.
- **Web:** ten sam serwer uruchomiony w organizacji, obsługiwany przez przeglądarkę.

Interfejs jest ten sam w obu formach.

## Pierwsze uruchomienie

Ekran „Przygotowanie do pracy” proponuje do wyboru:
- **pakiet Podstawowy** (wymagany, ok. 140 MB): reguły i model NER bardsai (Q4);
- **pakiet Rozszerzony** (opcjonalny, ok. 350 MB): model LFM2.5-PII (Q4). Dodaje adresy IP, numery kart, kody SWIFT i loginy na poziomie 3;
- **przycisk „Później”**.

Po pobraniu program sprawdza sumy SHA-256 każdego pliku. Ustawienia mają osobne przełączniki Pobierz/Usuń dla każdego pakietu.

Modele, rejestr wydanych map i magazyn zapisanych map leżą w katalogu danych użytkownika (Windows: `%LOCALAPPDATA%\Niewidka`), więc aktualizacja programu ich nie kasuje.

Klucz szyfrujący mapy powstaje raz. Trafia do magazynu systemowego (Windows Credential Manager)
albo do pliku sekretów wskazanego przez IT. Aplikacja nie trzyma klucza w konfiguracji.

## Ukrywanie (przycisk „Ukryj”)

Wejście to wklejony tekst albo plik TXT lub DOCX. Suwak „Jakość wykrywania” ma trzy pozycje:

| Poziom | Skład |
|---|---|
| 1 Szybko | reguły z sumami kontrolnymi (PESEL, NIP, REGON, dowód, IBAN, karta) oraz wzorce (telefon, e-mail, adres, data); do tego model NER (osoby) |
| 2 Dokładniej | to co 1 + obniżony próg pewności osób + drugi przebieg okien modelu przesuniętych o pół kroku |
| 3 Najdokładniej | to co 2 + słownik imion GUS (imię z listy + następne słowo z wielkiej litery, w każdej odmianie); z pakietem Rozszerzonym także LFM2.5 dla IP, karty, SWIFT i loginu |

Kroki:
1. Program dzieli dokument na segmenty: akapity i komórki.
2. Detekcja: kandydaci z reguł i modeli. Nakładające się zakresy są scalane, a maskowany obszar to ich suma.
3. Grupowanie osób po odmianach: „Jan Kowalski”, „Jana Kowalskiego” i „Janem Kowalskim” to jedna osoba z różnymi formami.
4. Zamiana na znaczniki: `[PESEL_1]`, `[OSOBA_2_F1]` (F oznacza wariant formy fleksyjnej). Ta sama wartość dostaje ten sam znacznik.
5. Na początku wyniku pojawia się dopisek: „ZANONIMIZOWANY. Dane osobowe zastąpiono znacznikami (Niewidka). Oryginalne dane przywrócisz plikiem mapy. Identyfikator mapy: …”.
6. Mapa (znacznik → oryginał we wszystkich formach) zostaje zaszyfrowana AES-256-GCM do pliku `.nwidka`.
7. **Kontrola wyniku:** program jeszcze raz przepuszcza ten sam detektor przez gotowy wynik. Znaczniki i dopisek są wyjęte ze skanu. Jeśli kontrola coś znajdzie (model po zamaskowaniu części danych widzi inny kontekst), program dokłada te fragmenty wszędzie, gdzie występują, i ukrywa od nowa. Robi to najwyżej 5 razy. Do osoby dolicza do 2 kolejnych słów z wielkiej litery w tej samej linii. Oryginały z mapy są szukane w całym pliku, także w częściach, których adapter nie czyta (metadane, style DOCX).
8. Status „ukończony” albo „zablokowany”. Na korpusie testowym (8 pism, 3 poziomy) blokad jest 0; zostaje jako zabezpieczenie. Przy blokadzie program nie wydaje pliku ani mapy, ale odpowiada 422 z podglądem tekstu (tylko TXT) i listą **miejsc wątpliwych** (typ, fragment, pozycja w podglądzie). Interfejs zaznacza je w podglądzie, wyłącza „Kopiuj” i „Pobierz” i pyta przy każdym miejscu: „Ukryj” albo „To nie dane” (patrz „Poprawki w podglądzie”). Fragmenty są wyłącznie w odpowiedzi do interfejsu na tym komputerze, nigdy w logach ani w dzienniku. Blokada bez miejsc do decyzji (np. nieparsowalna część XML) zostaje zwykłym STOP z typami i liczbami.

Ekran wyniku pokazuje:
- podgląd ze znacznikami jako plakietkami;
- przyciski „Kopiuj”, „Pobierz dokument z ukrytymi danymi” i „Pobierz mapę (.nwidka)”;
- listę „co zamieniono” (typ i liczba);
- szacunek ryzyka pominięcia dla każdego typu (górna granica 95% z kalibracji, np. „małe do umiarkowanego: co najwyżej ok. 1 na 14”);
- zdanie o zapisanej mapie: „Mapa zapisana na tym komputerze do <data>. Przywrócisz dane, wklejając odpowiedź na zakładce Przywróć.”

Wejście, które już zawiera znaczniki Niewidki, jest odrzucane. Chroni to przed cichym, błędnym przywróceniem.

## Poprawki w podglądzie („Ukryj wszędzie”, „To nie dane”)

Specyfikacja: `docs/MAPY-I-AKTUALIZACJE.md` §4, §8 (wiersze 4-6), §9 (wiersz 3).

**Pamięć wykryć.** Po każdym `/api/ukryj` serwer trzyma w RAM wykrycia ostatniego przebiegu (zakresy, typy, grupy osób, numeracja) razem z oryginałem dokumentu: najwyżej 4 zadania przez 15 minut (`[poprawki] maks_zadan`, `ttl_s`; `NIEWIDKA_POPRAWKI_MAKS_ZADAN`, `NIEWIDKA_POPRAWKI_TTL_S`). Nic na dysk, nic w logach. Kluczem jest identyfikator zadania (`x-niewidka-zadanie`, to identyfikator pierwszej mapy). Po terminie albo przy nieznanym identyfikatorze `/api/popraw` odpowiada 410: „Ukryj dokument ponownie”.

**`POST /api/popraw`** (JSON): `zadanie`, `ukryj` (fragmenty), `nie_dane` (znaczniki, np. `OSOBA_3`), `zostaw` (miejsca wątpliwe z blokady uznane za nie-dane). Za każdym razem pełne listy względem zapamiętanych wykryć, więc cofnięcie poprawki to przeliczenie bez niej. Limity: 200 pozycji po 200 znaków (422). Wynik to nowa mapa z nowym identyfikatorem, zapisana w magazynie jak przy ukryciu; stara mapa zostaje. Odpowiedź ma kształt odpowiedzi `/api/ukryj` plus nagłówek `x-niewidka-wlasne` (znacznik → numer pozycji `ukryj`, z której powstał). Model nie jest uruchamiany.

Zasady:
- `ukryj`: tylko całe słowa (granice słów z polskimi literami, więc „Lis” nie rusza „Listopad”), wszystkie wystąpienia, w każdej odmianie. Dopasowanie używa rdzenia końcówkowego z `osoby.py` („Brzechwy” i „Brzechwą” to „Brzechwa”). Typ z reguł, jeśli reguła obejmuje cały fragment, inaczej `INNE`. Różne formy tego samego fragmentu dostają warianty `_F2`, `_F3`, więc przywrócenie zwraca właściwą odmianę. Fragment już zakryty znacznikiem nic nie zmienia.
- `nie_dane`: zdejmuje kliknięty znacznik w całości (wszystkie wystąpienia tej osoby albo wartości w tym wyniku), nie przyszłe wystąpienia. Kontrola nie dokłada zdjętego z powrotem. „Ukryj” wygrywa: grupa, której wystąpienie nachodzi na zaznaczenie z `ukryj`, zostaje. Typy z sumą kontrolną (PESEL, NIP, REGON, IBAN, KARTA, DOKUMENT) są odrzucane (422).
- Numeracja: numery istniejących znaczników się nie zmieniają; nowe dostają kolejne numery danego typu (liczone od najwyższego numeru z wykryć bazowych, także zdjętych).
- Kontrola po poprawce to reguły i oryginały z mapy (bez modelu) oraz znaleziska modelu z wyniku bazowego, które nadal są w tekście. Fragmenty dodane przez użytkownika są w kontroli surowej szukane jako całe słowa.
- Dziennik magazynu: zdarzenie `poprawiono` z liczbami pozycji `ukryj`, `nie_dane` i `zostaw`, bez treści.

**Interfejs.** Zaznaczenie tekstu w podglądzie pokazuje przycisk „Ukryj wszędzie” (to samo robi pole tekstowe pod podglądem, dla klawiatury). Plakietka znacznika jest przyciskiem: „To nie dane osobowe” (dla typów z sumą wyłączone, z wyjaśnieniem) albo „Cofnij tę poprawkę”, gdy znacznik powstał z „Ukryj wszędzie”. Lista „Twoje poprawki” ma cofnięcie każdej pozycji. Po poprawce komunikat „Tekst się zmienił. Skopiuj go ponownie.” (aria-live). Interfejs ignoruje odpowiedzi starszych żądań.

**Znane ograniczenia.** Krótkie słowa (do 3 liter) nie łączą odmian. Poprawka liczy się od zapamiętanych wykryć, więc nie widzi tego, czego model nie znalazł w pierwszym przebiegu, dopóki użytkownik tego nie zaznaczy. Miejsca wątpliwe z modelu, które obejmowały zamaskowany znacznik, tracą pozycję w podglądzie po poprawce.

## Magazyn map z retencją (docs/MAPY-I-AKTUALIZACJE.md §2)

Program sam zapisuje zaszyfrowaną mapę każdego ukrycia w `<katalog danych>/mapy`:
`<id>.nwidka` (szyfrogram AES-256-GCM, jak przy pobieraniu) i `<id>.json` (metadane bez danych
osobowych: utworzono, wygasa, poziom, liczby per typ). Kradzież katalogu bez klucza z magazynu
systemowego nic nie daje. Dziennik `dziennik.jsonl` zapisuje czas, zdarzenie (`utworzono`,
`przywrocono`, `usunieto`, `wygasla`), 12-znakowy skrót identyfikatora, poziom i liczby per typ,
nigdy treści ani nazw plików.

- **Retencja**: `[mapy] retencja_dni` albo `NIEWIDKA_MAPY_RETENCJA_DNI`, domyślnie 30 (wartość
  domyślna, nie wymóg RODO - okres ustawia organizacja); `0` wyłącza automatyczny zapis (zostaje
  pobranie pliku, jak dawniej); ujemna wartość odrzucana przy starcie. Dla administratora:
  sprzątanie po terminie działa przy starcie programu i przy każdym ukryj/przywróć/liście;
  program wyłączony nie sprząta, ale sprząta przy następnym uruchomieniu, zanim cokolwiek
  przywrócimy.
- **Pobrane kopie**: retencja i ręczne „Usuń” dotyczą magazynu programu; pobrany plik `.nwidka`
  działa dalej i podlega przechowywaniu organizacji. Dopiero opcja `[mapy] uniewaznij_pobrane`
  skreśla mapę z rejestru wydanych map: ten program odmówi jej przywrócenia (to wykreślenie
  z rejestru, nie unieważnienie kryptograficzne - kopia razem z kluczem pozostaje
  odszyfrowywalna narzędziami mającymi klucz).
- **Blokada**: jedna blokada procesu obejmuje magazyn, dziennik i rejestr wydanych map.
- **Dziennik podpisany łańcuchem**: każdy wpis ma skrót SHA-256 poprzedniej linii, więc edycja
  albo usunięcie wpisu jest wykrywalne (`zweryfikuj_lancuch` w `niewidka/magazyn.py`).

## Przywracanie przez wklejenie (zakładka „Przywróć”)

Domyślny tryb: użytkownik wkleja odpowiedź AI, bez wskazywania plików. Program bierze mapę:
1. z pliku `.nwidka`, jeśli użytkownik go podał (dawny sposób);
2. z dopisku w treści (identyfikator mapy); dopisek wygrywa z wyborem z listy, więc stare
   ustawienie listy nie psuje nowego tekstu;
3. z wyboru na liście „Zadanie” (etykieta „dziś 7:41 · 3 osoby, 1 numer PESEL”, domyślnie najnowsze).

Bez dopisku kandydatem jest tylko mapa zawierająca WSZYSTKIE znaczniki z tekstu. Dokładnie jeden
kandydat: przywracane z jawnym komunikatem „Przywrócono z mapy zadania: …”. Więcej kandydatów albo
zero: komunikat „Wskaż mapę” prowadzi do listy. Wklejony tekst wraca w podglądzie z „Kopiuj”;
plik odpowiedzi wraca jak dawniej, do pobrania.

Zapisane mapy widać w Ustawieniach („Zapisane mapy”): lista z liczbami per typ i terminem
usunięcia, „Usuń” przy każdej, „Usuń wszystkie” z potwierdzeniem i zdanie o okresie
przechowywania.

## Przywracanie (zakładka „Przywróć”)

Program sprawdza trzy rzeczy:
1. mapa została wydana przez ten program (rejestr skrótów SHA-256 w pliku, bez danych; mapa
   pobrana z magazynu programu jest z definicji wydana, bo zapisano ją przy ukrywaniu);
2. identyfikator w dopisku zgadza się z identyfikatorem mapy;
3. mapa daje się odszyfrować kluczem.

Gdy w tekście nie ma dopisku (zwykła odpowiedź czatu AI go nie powtarza), program przywraca dane i ostrzega, że zgodności mapy nie sprawdził. Dopisek z identyfikatorem innej mapy oznacza odmowę.

Potem program zamienia znaczniki na oryginały, z właściwą formą fleksyjną dla wariantu F. Raport rozbieżności obejmuje znacznik bez wpisu w mapie i wpis niewykorzystany.

## Aktualizacje modeli (Ustawienia, docs/MAPY-I-AKTUALIZACJE.md §5)

Wydawca publikuje wykaz wersji (`katalog-pakietow.json`) z podpisem Ed25519; klucz publiczny
jest w programie. Program przyjmuje wyłącznie wykaz z poprawnym podpisem i wersją wyższą
od ostatnio przyjętej (cofanie wykazu jest wykrywane), przyjęty zapisuje u użytkownika
i sprawdza podpis przy każdym starcie. Zły podpis przyjętego wykazu nie zatrzymuje programu:
wraca wbudowany wykaz, ale Ustawienia pokazują „błąd integralności", a aktualizacje stają
się zablokowane.

Tryby do wyboru w Ustawieniach: ręcznie (tylko „Sprawdź teraz"), sam raz na dobę
(domyślny: pokazuje „Dostępna aktualizacja"), sam pobierz i zainstaluj. Administrator może
tryb narzucić konfiguracją (`[aktualizacje] tryb`, `NIEWIDKA_AKTUALIZACJE`, także
`wylaczone`); wtedy wybór jest zablokowany z dopiskiem „Tryb ustawiony przez administratora".

Instalacja: pobranie do katalogu przejściowego, sumy SHA-256, próba na próbce kontrolnej
(fikcyjne zdania: nowa wersja musi wykryć to, co ma, i nie może dawać znanych fałszywych
alarmów). Bez zaliczonej próby zamiany nie ma. Po zaliczeniu nowa wersja zastępuje starą,
a poprzednia zostaje w `modele/.poprzednie/` z przyciskiem powrotu (zablokowanym, gdy
wydawca zabronił wracania poniżej `min_wersja`). W sieci bez internetu osoba opiekująca
się programem wkleja ścieżkę do folderu od IT (wykaz z podpisem i pliki); obowiązuje ta
sama weryfikacja. Program bez klucza publicznego wydawcy (np. przed wydaniem) działa na
wykazie wbudowanym, a aktualizacje są niedostępne z czytelnym komunikatem.

## Bezpieczeństwo

- Token sesji w stronie, wymagany w każdym żądaniu API.
- Kontrola nagłówków Host i Origin (ochrona przed DNS rebinding i CSRF).
- Nasłuch tylko na loopbacku.
- Limity rozmiaru, rozpakowania (zip bomb) i kolejki.
- DOCX: komentarze, usunięte zmiany (`w:del`), autorzy rewizji, miniatura i właściwości dokumentu są usuwane przed analizą.
- DOCX z makrami jest odrzucany. Obrazy są domyślnie usuwane, bo bez OCR nie da się ich sprawdzić.
- Logi i odpowiedzi błędów nie zawierają treści dokumentów ani nazw plików.

## Znane ograniczenia (dziś)

- Brak typów: tablica rejestracyjna, VIN, numer KRS (KRS bywa oznaczany jako NIP).
- Nazwy instytucji i patroni szkół („im. Jana Brzechwy”) bywają maskowane jako osoby, a bywają zostawiane.
- Formaty: tylko TXT i DOCX. Brak PDF, ODT, XLSX i OCR obrazów.
- Model działa na CPU. Poziom 3 trwa na piśmie A4 ok. 10 s.

## Pytania do konsultantów

1. Czy to podejście (reguły i NER lokalnie, znaczniki z wariantem formy, zaszyfrowana mapa, kontrola wyniku z dokładaniem znalezisk, blokada jako ostateczność) jest prawidłowe dla tej grupy odbiorców? Co byś zmienił w pierwszej kolejności?
2. Jakie ułatwienia dla nietechnicznego użytkownika widzisz? Interesują nas konkretne zmiany ekranu, kolejności kroków albo domyślnych ustawień, np.:
   - jeden przycisk „Ukryj i skopiuj”;
   - automatyczne zapamiętanie mapy zamiast jej pobierania;
   - podświetlenie w podglądzie, co zostało ukryte;
   - ręczne dopisanie „ukryj też to słowo”;
   - przywracanie przez wklejenie odpowiedzi AI bez wskazywania pliku mapy.
3. Czy przy blokadzie należy pokazać użytkownikowi wynik z zaznaczonym miejscem wątpliwym i pozwolić mu świadomie zdecydować? A może blokada bez wyniku jest właściwa?
4. Czego brakuje w liście wykrywanych danych dla polskich pism urzędowych, bankowych i kadrowych?
