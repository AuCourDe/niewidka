# Niewidka — logika aplikacji (do konsultacji: poprawność podejścia i ułatwienia dla użytkownika)

Stan: 2026-10-29, commit 56029d1. Dokument bez danych klienta. Przykłady są fikcyjne.

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
8. Status „ukończony” albo „zablokowany”. Przy blokadzie wynik nie jest wydawany: brak podglądu, kopiowania i pobrania. Komunikat podaje tylko typy i liczby, nigdy fragmenty danych.

Ekran wyniku pokazuje:
- podgląd ze znacznikami jako plakietkami;
- przyciski „Kopiuj”, „Pobierz dokument z ukrytymi danymi” i „Pobierz mapę (.nwidka)”;
- listę „co zamieniono” (typ i liczba);
- szacunek ryzyka pominięcia dla każdego typu (górna granica 95% z kalibracji, np. „małe do umiarkowanego: co najwyżej ok. 1 na 14”).

Wejście, które już zawiera znaczniki Niewidki, jest odrzucane. Chroni to przed cichym, błędnym przywróceniem.

## Przywracanie (zakładka „Przywróć”)

Użytkownik podaje tekst albo plik z odpowiedzią AI (ze znacznikami) i plik mapy. Program sprawdza trzy rzeczy:
1. mapa została wydana przez ten program (rejestr skrótów SHA-256 w pliku, bez danych);
2. identyfikator w dopisku zgadza się z identyfikatorem mapy;
3. mapa daje się odszyfrować kluczem.

Potem program zamienia znaczniki na oryginały, z właściwą formą fleksyjną dla wariantu F. Raport rozbieżności obejmuje znacznik bez wpisu w mapie i wpis niewykorzystany.

## Bezpieczeństwo

- Token sesji w stronie, wymagany w każdym żądaniu API.
- Kontrola nagłówków Host i Origin (ochrona przed DNS rebinding i CSRF).
- Nasłuch tylko na loopbacku.
- Limity rozmiaru, rozpakowania (zip bomb) i kolejki.
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
