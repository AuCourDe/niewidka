# Przegląd Codex, 2026-10-30 (przed publikacją)

Kategorie: 1 błąd, 2 duplikacja, 3 martwy kod, 4 nadmiarowość, 5 teksty dla użytkownika. Wynik werbatim, ścieżki skrócone.

1. **(1)** [niewidka/poprawki.py:230](niewidka/poprawki.py:230) — Poprawka częściowo nachodząca na istniejące wykrycie usuwa całe wcześniejsze ukrycie: dla „Jan Kowalski oraz Anna” dodanie „Kowalski oraz” daje `Jan [INNE_1] Anna`, ze statusem `ukonczony`. Scalaj nachodzące zakresy przez ich unię, zachowując ochronę całego wcześniejszego wykrycia.

2. **(1)** [niewidka/poprawki.py:308](niewidka/poprawki.py:308) — Pusty fragment ostrzeżenia pasuje do każdego wyjątku, więc dowolny wpis `zostaw` usuwa blokadę `XML_NIEPRAWIDLOWY`; potwierdzone na DOCX z uszkodzonym plikiem motywu. Ostrzeżenia strukturalne muszą być nieodwoływalne przez wyjątki tekstowe, a dopasowanie wyjątków powinno wymagać niepustego fragmentu.

3. **(1)** [niewidka/formaty/docx_.py:463](niewidka/formaty/docx_.py:463) — Czyszczenie adresów odnośników usuwa tylko query i fragment: `https://example.org/Jan%20Kowalski` pozostaje w wydanym DOCX i przechodzi kontrolę. Usuwaj zewnętrzne cele relacji albo sprawdzaj również ich zdekodowaną zawartość przed wydaniem dokumentu.

4. **(1)** [niewidka/api.py:950](niewidka/api.py:950) — Nagłówek `x-niewidka-z-listy` zawiera jawne fragmenty z listy „Zawsze ukrywaj”, np. `{"INNE_1":"Kowalski"}`. Przekazuj w nagłówku wyłącznie identyfikatory pozycji; potrzebną treść pobieraj chronionym API lub umieść w treści odpowiedzi.

5. **(1)** [niewidka/aktualizacje.py:459](niewidka/aktualizacje.py:459) — Logowanie całego wyjątku HTTP ujawnia adres lustra wraz z loginem, hasłem i parametrami URL; podobnie `str(blad)` trafia do stanu aktualizacji i logu instalacji. Zastosuj sanitację już obecną w menedżerze pakietów: typ błędu i kod HTTP, bez pełnego URL.

6. **(1)** [niewidka/api.py:923](niewidka/api.py:923) — Po błędzie magazynu program wydaje wynik i poleca pobrać mapę, ale usuwa jej identyfikator z rejestru pamięci; pobrana mapa następnie dostaje błąd „mapa z innego zadania albo sesji”. Zachowuj rejestr wydania niezależnie od powodzenia automatycznego zapisu mapy.

7. **(1)** [niewidka/detektory.py:509](niewidka/detektory.py:509) — Budowanie detektora produktu nie przekazuje aktywnego, podpisanego katalogu aktualizacji do loaderów, które domyślnie sprawdzają stare, wbudowane sumy SHA-256. Przekaż zaufany katalog przez `zbuduj_detektor()` i `zbuduj_poziom()` do obu loaderów, inaczej poprawnie zaktualizowane modele zostaną odrzucone.

8. **(1)** [niewidka/aktualizacje.py:514](niewidka/aktualizacje.py:514) — Samo sprawdzenie aktualizacji podmienia katalog używany do oceny zainstalowanych plików na katalog nowych wersji, przez co dotychczasowy poprawny pakiet staje się „uszkodzony”. Rozdziel katalog wersji dostępnych od zaufanych metadanych wersji faktycznie zainstalowanej.

9. **(1)** [niewidka/aktualizacje.py:646](niewidka/aktualizacje.py:646) — Próbkę aktualizacji pakietu Rozszerzonego sprawdza wyłącznie detektor IP/KARTA/SWIFT/LOGIN, natomiast wspólna próbka wymaga osób, PESEL-u, telefonu i adresów. Przygotuj próbki właściwe dla każdego pakietu albo oceniaj pełny zestaw detektorów z podmienianą warstwą.

10. **(1)** [niewidka/listy.py:88](niewidka/listy.py:88) — Uszkodzona lub nieczytelna lista użytkownika jest bez komunikatu zastępowana pustą, więc „Zawsze ukrywaj” przestaje chronić wskazane dane. Rozróżnij brak pliku od błędu odczytu i blokuj wydanie wyniku do wyjaśnienia błędu listy.

11. **(1)** [niewidka/api.py:251](niewidka/api.py:251) — Timeout zmniejsza licznik oczekujących, mimo że utworzone zadanie nadal czeka na semafor; kolejne żądania mogą bez końca dopisywać prace przechowujące dokumenty. Anuluj zadania, które nie rozpoczęły pracy, albo licz ich miejsce aż do rzeczywistego zakończenia.

12. **(1)** [niewidka/web/apka.js:529](niewidka/web/apka.js:529) — Podczas przeliczania poprawki przyciski kopiowania i pobierania nadal wydają poprzedni wynik, również gdy poprawka właśnie ukrywa przeoczone dane osobowe. Zablokuj eksport na czas przeliczania i odblokuj go dopiero dla aktualnego, zaakceptowanego wyniku.

13. **(1)** [niewidka/reguly.py:63](niewidka/reguly.py:63), [narzedzia/numery.py:88](narzedzia/numery.py:88) — Walidator błędnie porównuje sumę obejmującą wagę `9` cyfry kontrolnej z samą cyfrą: odrzuca `ABC123458`, a akceptuje `ABC212345`; generator powiela błąd, więc testy go utrwalają. Przy tych wagach sprawdzaj resztę równą `0`, popraw generator i dodaj niezależne przykłady ([algorytm](https://wybryki-informatyki.pl/narzedzia/generator-numeru-dowodu-osobistego/)).

14. **(1)** [niewidka/web/apka.js:975](niewidka/web/apka.js:975) — Ukrywanie i przywracanie współdzielą `licznikZlecen`: uruchomienie drugiej operacji unieważnia pierwszą i pomija jej `finally`, pozostawiając jej przycisk wyłączony. Stosuj osobne liczniki i stan zajętości dla obu formularzy, a sprzątanie stanu wykonuj niezależnie od aktualności odpowiedzi.

15. **(1)** [niewidka/web/apka.js:680](niewidka/web/apka.js:680) — Po zmianie `OSOBA_1` na `INNE_1` akcja „To nie dane osobowe” wysyła `INNE_1`, chociaż backend waliduje znaczniki względem bazowych wykryć i zna tylko `OSOBA_1`. Zwracaj mapowanie nowych znaczników na bazowe i używaj bazowego identyfikatora w kolejnych poprawkach.

16. **(1)** [niewidka/formaty/docx_.py:303](niewidka/formaty/docx_.py:303) — Klonowanie całego runu powiela jego elementy nietekstowe: `PESEL: 44051401359\tKwota: 100` po ukryciu ma trzy tabulatory zamiast jednego. Uwzględnij tabulatory i podziały w modelu segmentu oraz przypisuj każdy element do jednego fragmentu.

17. **(1)** [niewidka/api.py:530](niewidka/api.py:530) — Konfiguracja dopuszcza `::1`, ale dzielenie nagłówka Host po `:` odrzuca poprawny `[::1]:port`; launcher dodatkowo buduje URL bez nawiasów IPv6. Parsuj Host jako adres URL i generuj adresy IPv6 w nawiasach kwadratowych.

18. **(1)** [niewidka/aktualizacje.py:292](niewidka/aktualizacje.py:292) — Limit katalogu sprawdzany jest po `klient.get()`, gdy cała odpowiedź została już pobrana i zbuforowana, więc deklarowane 1 MB nie ogranicza zużycia pamięci. Pobieraj strumieniowo i przerywaj odczyt natychmiast po przekroczeniu limitu.

19. **(1)** [niewidka/web/apka.js:1236](niewidka/web/apka.js:1236) — Każde odświeżenie map zeruje wybór użytkownika i zaznacza pierwsze zadanie; dla odpowiedzi AI bez dopisku może to podstawić dane z innej mapy. Zachowuj wybraną wartość, a domyślnie udostępnij pustą opcję automatycznego dopasowania lub jawnego wyboru.

20. **(1)** [niewidka/web/apka.js:428](niewidka/web/apka.js:428) — Backend akceptuje rozszerzenie `.TXT`, ale zachowuje jego wielkość w nazwie wyniku, przez co frontend wyłącza podgląd i kopiowanie dla poprawnie przetworzonego tekstu. Normalizuj rozszerzenie przed sprawdzeniem albo zwracaj format jako osobne metadane.

21. **(1)** [narzedzia/pobierz_model.py:149](narzedzia/pobierz_model.py:149) — `Path("")` daje prawdziwe logicznie `Path(".")`, więc bez `--katalog` i zmiennej środowiskowej narzędzie pobiera duże pliki do bieżącego katalogu zamiast zgłosić wymagany parametr. Zamieniaj wartość środowiskową na `Path` dopiero po sprawdzeniu, czy jest niepusta.

22. **(2)** [niewidka/web/apka.js:1144](niewidka/web/apka.js:1144) — Odczyty list, map, pakietów i aktualizacji powielają blok `fetch`/`ok`/`json`/`catch`, a zapis list ma kolejną implementację obsługi błędów HTTP. Wydziel wspólne żądanie JSON zachowujące kod odpowiedzi i komunikat, pozostawiając renderowanie w poszczególnych funkcjach.

23. **(3)** [niewidka/znaczniki.py:76](niewidka/znaczniki.py:76), [niewidka/mapa.py:174](niewidka/mapa.py:174) — `zamien_w_segment()` i `przywroc_tekst()` są używane wyłącznie przez własne testy, podczas gdy produkt wykonuje te operacje innymi ścieżkami. Usuń nieużywane implementacje i przenieś przypadki testowe na funkcje faktycznie wywoływane przez rdzeń.

24. **(3)** [niewidka/web/styl.css:412](niewidka/web/styl.css:412) — Selektory `.podglad-naglowek`, `.pobieracz` i `.wazne` nie mają użyć w HTML ani JS, również w wariantach responsywnych. Usuń te reguły wraz z późniejszymi nadpisaniami.

25. **(4)** [tests/test_web.py:282](tests/test_web.py:282) — Test deklaruje sprawdzanie odrzucania spóźnionych odpowiedzi, lecz weryfikuje tylko obecność napisów w źródle JS, dlatego przepuszcza błąd wspólnego licznika formularzy. Zastąp te asercje testem zachowania z kontrolowaną kolejnością odpowiedzi i sprawdzeniem odblokowania przycisków.

26. **(5)** [niewidka/web/apka.js:328](niewidka/web/apka.js:328) — Techniczne typy kontroli, np. `XML_NIEPRAWIDLOWY`, `ORYGINAL` i `NAZWA_CZESCI`, wpadają do ogólnego formatowania etykiet i są pokazywane użytkownikowi jako niezrozumiałe kody. Dodaj osobny słownik komunikatów kontroli z opisem problemu i możliwym działaniem użytkownika.