# Niewidka: instrukcja obsługi

Instrukcja dotyczy obu wersji programu. Wersja okienkowa i wersja w przeglądarce mają
te same przyciski i działają tak samo.

## Pierwsze uruchomienie

**Klucz mapy.** W wersji okienkowej program poprosi o utworzenie klucza. Kliknij
„Utwórz klucz”. Klucz zapisze się na stałe w Menedżerze poświadczeń Windows. Szyfruje on
mapy, czyli spisy danych ukrytych pod znacznikami. Nie usuwaj klucza. Bez niego nie
odczytasz starych map.

W wersji w przeglądarce klucz tworzy osoba, która instaluje program (`docs/KONFIGURACJA.md`).

**Modele.** Na ekranie „Przygotowanie do pracy” wybierz jedną z opcji:

- „Pobierz podstawowy (zalecane)”: około 190 MB. Wystarcza do pracy na każdym poziomie.
- „Pobierz wszystko”: dochodzi pakiet rozszerzony (około 230 MB). Na poziomie
  Najdokładniej wykrywa też adresy IP, kody SWIFT i loginy.
- „Później”: modele pobierzesz w Ustawieniach.

Przy każdym pakiecie znajdziesz adres modelu w serwisie Hugging Face i jego licencję.
Przeczytaj licencję przed pobraniem. Modele pobierasz raz. Potem program działa bez internetu.

Jeśli administrator ustawił wspólny serwer modeli, ten ekran się nie pojawi. W nagłówku
zobaczysz wtedy napis, że dane nie opuszczają sieci urzędu.

## Ukrywanie danych

1. Na zakładce **Ukryj** wklej tekst albo kliknij „Wybierz plik”. Plik możesz też
   przeciągnąć na pole. Program przyjmuje pliki `.txt` i `.docx` do 25 MB.
2. Ustaw suwak **Jakość wykrywania danych**:
   - **Szybko**: najkrótszy czas, do prostych tekstów.
   - **Dokładniej**: ustawienie domyślne, do zwykłych pism.
   - **Najdokładniej**: działa najwolniej, do najważniejszych pism.
3. Kliknij **Ukryj dane**.

Po prawej stronie zobaczysz podgląd. Ukryte dane mają postać czarnych plakietek, na przykład
`[OSOBA_1]`. Ta sama osoba albo ten sam numer ma w całym tekście ten sam znacznik.

Pierwsza linia wyniku zaczyna się od słowa „ZANONIMIZOWANY” i kończy identyfikatorem mapy.
Kopiuj tekst razem z tą linią. Jeśli czat AI ją zostawi, przy przywracaniu program sam
znajdzie właściwą mapę.

Pasek nad podglądem pokazuje wynik kontroli jakości. Gdy widzisz „sprawdź wynik”,
przejrzyj miejsca z ramki „Uwaga: sprawdź te miejsca”.

Gotowy wynik możesz:

- skopiować przyciskiem **Kopiuj tekst**,
- zapisać przyciskiem **Pobierz dokument** (w formacie pliku wejściowego),
- zapisać mapę do akt przyciskiem **Pobierz mapę (.nwidka)**. Nie musisz tego robić,
  program sam zapamiętuje mapę.

Po zmianie tekstu albo przesunięciu suwaka kliknij **Ukryj ponownie**.

## Poprawianie wyniku

Program może coś pominąć albo ukryć za dużo. Błędy poprawisz od razu w podglądzie.

**Program ukrył zwykłe słowo.** Kliknij plakietkę w podglądzie i wybierz
„To nie dane osobowe”. Słowo wróci do tekstu w każdym miejscu. Dla słów ze stałej listy
użyj przycisku „Odkryj tylko w tym dokumencie”.

Numerów PESEL, NIP, REGON, IBAN, numerów kart i dowodów nie odkryjesz. Mają poprawną
sumę kontrolną, więc na pewno są danymi osobowymi.

**Program pominął daną.** Zaznacz ją myszą w podglądzie i kliknij „Ukryj wszędzie”.
Możesz też wpisać ją w pole „Ukryj wszędzie” pod podglądem. Fragment dostanie znacznik
`[INNE_1]` i zniknie z całego tekstu.

**Znacznik ma zły typ.** Kliknij plakietkę i wybierz „Oznacz jako inne dane”.

Wszystkie zmiany znajdziesz w sekcji **Twoje poprawki**. Każdą możesz cofnąć. Kliknij
„Ukrywaj zawsze”, a słowo trafi na stałą listę. Program ukryje je w każdym kolejnym dokumencie.

## Gdy kontrola zatrzyma wynik

Czasem kontrola jakości znajdzie w tekście podejrzane fragmenty. Zobaczysz wtedy napis
„STOP: kontrola ma wątpliwości” i listę miejsc. Przy każdym kliknij „Ukryj” albo
„To nie dane”. Gdy zdecydujesz o wszystkich, kopiowanie i pobieranie się odblokują.

## Przywracanie danych

1. Wyślij ukryty tekst do czatu AI i skopiuj odpowiedź.
2. Na zakładce **Przywróć** wybierz „Wklej odpowiedź z czatu AI” i wklej skopiowany tekst.
3. Z listy **Zadanie** wybierz dokument, z którego pochodzi tekst. Domyślnie jest najnowszy.
   Jeśli odpowiedź zawiera identyfikator mapy, program sam wybierze właściwą mapę.
4. Kliknij **Przywróć dane**.

Prawdziwe dane zastąpią znaczniki. Jeśli czat zmienił albo usunął znacznik, zobaczysz to
w ramce „Nie wszystko wróciło idealnie”.

Masz plik dokumentu i plik mapy? Wybierz „Mam plik dokumentu i mapę (.nwidka)”, wskaż
oba pliki i kliknij **Przywróć dane**. Dostaniesz dokument w tym samym formacie.

## Ustawienia

**Pakiety modeli.** Pobieranie i usuwanie modeli, licencje.

**Aktualizacje modeli.** Domyślnie program raz na dobę sprawdza, czy są nowe wersje.
Pobiera tylko wykaz wersji i nigdy nie wysyła Twoich dokumentów. Nowa wersja zainstaluje
się dopiero po udanej próbie na przykładowych zdaniach. Aby cofnąć aktualizację, kliknij
„Wróć do poprzedniej wersji”. W sieci bez internetu osoba z IT wkleja ścieżkę do folderu
z aktualizacją i klika „Zainstaluj z folderu”.

**Stałe listy.** Wpisz jedno słowo albo wyrażenie w każdym wierszu:

- **Zawsze ukrywaj**: na przykład nazwa referatu albo rzadki pseudonim.
- **Nigdy nie ukrywaj**: na przykład nazwa Twojego urzędu.

Program rozpoznaje odmiany. Wpis „Urząd Miasta” zadziała też dla „Urzędu Miasta”.
Kliknij „Zapisz listy”. Listy ustawione przez administratora możesz tylko oglądać.

**Zapisane mapy.** Program sam zapisuje zaszyfrowaną mapę każdego dokumentu. Mapy znikają
po czasie ustawionym przez administratora, domyślnie po 30 dniach. Tu je przejrzysz
i usuniesz wcześniej.

## Ważne

Niewidka ułatwia pracę, ale nie gwarantuje wykrycia wszystkich danych. Zawsze przejrzyj
podgląd przed wysłaniem tekstu. Decyzja o przekazaniu dokumentu należy do Ciebie.

Program nie czyta tekstu ze zdjęć i skanów. Obrazy z plików `.docx` usuwa.

## Kłopoty

| Co widzisz | Co zrobić |
|---|---|
| „Nie można wystartować” | Brakuje modeli. Pobierz je w Ustawieniach albo zgłoś się do IT. |
| „Serwer modeli nie odpowiada” | Wspólny serwer modeli nie działa. Zgłoś to administratorowi. |
| Przywracanie nie zna mapy | Mapa wygasła albo ktoś ją usunął. Wczytaj plik `.nwidka`, jeśli go masz. |
| Plik się nie wczytuje | Program przyjmuje pliki `.txt` i `.docx` mniejsze niż 25 MB. |
