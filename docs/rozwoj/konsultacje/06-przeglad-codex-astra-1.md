# Przegląd bezpieczeństwa Codex (model astra), 2026-10-28, kod po K4+K3b


1. **Ważne — „zablokowany” wynik nadal można pobrać.** [api.py:220](~/niewidka/niewidka/api.py:220), [apka.js:258](~/niewidka/niewidka/web/apka.js:258).
   
   **Atak:** (1) Dostarczyć DOCX z PESEL-em w dodatkowej części XML. (2) Kontrola wykrywa pozostawione dane i ustawia `zablokowany`. (3) API mimo tego zwraca **200 i kompletny dokument z PESEL-em**, a interfejs udostępnia pobieranie. Odtworzone przy domyślnym `kontrola_blokada=True`.
   
   **Minimalna poprawka:** Przy blokadzie zakończyć żądanie przed pakowaniem wyniku, bez zwracania dokumentu; wyłączyć również pobieranie i kopiowanie w UI.

2. **Ważne — obrazy z danymi przechodzą bez ostrzeżenia.** [rdzen.py:111](~/niewidka/niewidka/rdzen.py:111), [docx_.py:317](~/niewidka/niewidka/formaty/docx_.py:317), [kontrola.py:80](~/niewidka/niewidka/kontrola.py:80).
   
   **Atak:** (1) Umieścić PESEL wyłącznie na obrazie w DOCX. (2) Użytkownik anonimizuje dokument. (3) Obraz pozostaje identyczny, raport ma `ukonczony` i zero ostrzeżeń. Potwierdziłem to PNG zawierającym numer; metoda adaptera wykrywająca obrazy istnieje, ale rdzeń jej nie wywołuje. Także nowe dane w `word/media/*.bin` przechodzą, jeżeli nie występują już w mapie.
   
   **Minimalna poprawka:** Włączyć sprawdzanie nieobsługiwanej zawartości do rdzenia; bez OCR domyślnie blokować lub usuwać obrazy i niezweryfikowane części binarne.

3. **Ważne — pomijanie `tail` pozwala ominąć kontrolę XML.** [kontrola.py:86](~/niewidka/niewidka/kontrola.py:86).
   
   **Atak:** (1) Dodać `word/theme/proba.xml` z `<root><node/>44051401359</root>`. (2) PESEL nie występuje w głównej treści, więc nie trafia do mapy. (3) Skan bada `e.text` i atrybuty, pomijając `e.tail`: wynik zachowuje numer, dostaje `ukonczony` i `[]` ostrzeżeń.
   
   **Minimalna poprawka:** Skanować również `tail`, np. przez odpowiednio użyte `itertext()`, zachowując kontrolę atrybutów.

4. **Ważne — błąd parsowania dodatkowej części XML powoduje fail-open.** [kontrola.py:82](~/niewidka/niewidka/kontrola.py:82).
   
   **Atak:** (1) Do poprawnego DOCX dodać dozwoloną ścieżką część `word/theme/proba.xml` zawierającą niedomknięte `<root>44051401359`. (2) Parser zgłasza `XMLSyntaxError`. (3) `continue` pomija kontrolę, a część zostaje w wyniku z `ukonczony`. Odtworzone.
   
   **Minimalna poprawka:** Błąd parsowania zachowywanej części XML musi blokować eksport; wyszukiwanie wyłącznie oryginałów już znanych z mapy nie zastępuje kontroli.

5. **Ważne — dane osobowe pozostają w nazwach części DOCX.** [kontrola.py:75](~/niewidka/niewidka/kontrola.py:75), [docx_.py:314](~/niewidka/niewidka/formaty/docx_.py:314).
   
   **Atak:** (1) Dodać część `word/media/44051401359.bin` z nieszkodliwą zawartością. (2) Kontrola skanuje zawartość, pomijając nazwę. (3) Odbiorca „zanonimizowanego” dokumentu odczytuje PESEL z katalogu ZIP. Próba zakończyła się `ukonczony`, bez ostrzeżeń.
   
   **Minimalna poprawka:** Kontrolować również nazwy części i blokować wykryte PII; przy neutralizacji nazw aktualizować powiązane relacje.

6. **Ważne — podmiana mapy między zadaniami tej samej sesji.** [api.py:251](~/niewidka/niewidka/api.py:251), [mapa.py:157](~/niewidka/niewidka/mapa.py:157).
   
   **Atak:** (1) Powstają dokumenty A i B, oba zawierające `[EMAIL_1]`. (2) Atakujący podsuwa mapę B podczas przywracania A. (3) Oba identyfikatory należą do sesji, więc kontrola przechodzi. W próbie wynik A został przywrócony jako `b@example.net`, z **200 i pustą listą rozbieżności**. AAD uwierzytelnia identyfikator mapy, ale nie wiąże jej z przesłanym dokumentem.
   
   **Minimalna poprawka:** Weryfikować oczekiwany identyfikator konkretnego zadania i powiązać z nim znaczniki; sama obecność ID w zbiorze sesji jest niewystarczająca.

7. **Ważne — 24-bitowe identyfikatory umożliwiają przyjęcie mapy z wcześniejszej sesji.** [rdzen.py:140](~/niewidka/niewidka/rdzen.py:140), [api.py:221](~/niewidka/niewidka/api.py:221).
   
   **Atak:** (1) Napastnik posiada archiwalne zaszyfrowane mapy tego samego klucza; ich ID są jawne. (2) Generuje nowe zadania przez API, szukając kolizji ID. (3) Stara mapa z trafionym ID przechodzi kontrolę sesji i daje się odszyfrować. Dla 5000 starych map i 5000 nowych ID prawdopodobieństwo trafienia wynosi około **77,5%**. W próbie identyfikatory generował rzeczywisty rdzeń; kolizja wystąpiła po 7510 nowych zadaniach, a odtworzona kontrola API zaakceptowała starą mapę.
   
   **Minimalna poprawka:** Użyć co najmniej 128-bitowego ID i rejestrować w sesji skróty konkretnych wydanych szyfrogramów, sprawdzane przed odszyfrowaniem.

8. **Ważne — pełne PII trafiają do `X-Niewidka-Ostrzezenia`.** [api.py:90](~/niewidka/niewidka/api.py:90), [api.py:230](~/niewidka/niewidka/api.py:230).
   
   **Atak:** (1) Dokument pozostawia wykrywalny PESEL w dodatkowej części XML. (2) Kontrola tworzy ostrzeżenie. (3) Pełny numer zostaje wysłany jawnym nagłówkiem HTTP, niezależnie od szyfrowania mapy; przechwycenie lub zapis diagnostyki nagłówków ujawnia dane. Odtworzone — skracanie fragmentu w UI nie skraca nagłówka.
   
   **Minimalna poprawka:** W nagłówkach zwracać typy, liczniki i bezpieczne lokalizacje, bez oryginalnych fragmentów oraz potencjalnie osobowych nazw części.

9. **Ważne — upload bez `Content-Length` omija limit przed buforowaniem i uruchamia zapis na dysk.** [api.py:104](~/niewidka/niewidka/api.py:104), [api.py:133](~/niewidka/niewidka/api.py:133), [api.py:244](~/niewidka/niewidka/api.py:244).
   
   **Atak:** (1) Klient z tokenem wysyła multipart strumieniowo, bez `Content-Length`. (2) Parser przyjmuje całość i przekracza `spool_max_size`. (3) Jawny dokument trafia do pliku tymczasowego przed późnym 413; `/przywroc` nie ma nawet analogicznego sprawdzenia długości. Przy limicie 1 MiB odtworzyłem wywołanie `rollover()` dla 1,1 MB, zastępując rzeczywisty zapis atrapą w RAM. [Starlette potwierdza mechanizm buforowania plików](https://starlette.dev/requests/).
   
   **Minimalna poprawka:** Liczyć rzeczywiste bajty w middleware ASGI przed parserem formularza i przerywać odczyt po przekroczeniu limitu, także dla transferu chunked.

10. **Ważne — limit ZIP ufa fałszywemu rozmiarowi z nagłówka.** [rdzen.py:84](~/niewidka/niewidka/rdzen.py:84), [docx_.py:102](~/niewidka/niewidka/formaty/docx_.py:102), [kontrola.py:108](~/niewidka/niewidka/kontrola.py:108).
    
    **Atak:** (1) Przygotować silnie skompresowany wpis, deklarując rozmiar 1 B i CRC zgodne z zachowanym prefiksem. (2) Suma `file_size` przechodzi kontrolę. (3) `paczka.read()` dekompresuje dane przed przycięciem do deklarowanej długości. Archiwum 8296 B z rzeczywistym strumieniem 8 MiB przeszło limit 1 MiB, osiągając ponad **21 MiB szczytowej alokacji**.
    
    **Minimalna poprawka:** Zastąpić nieograniczone `read()` odczytem małych porcji, ograniczyć metody kompresji i egzekwować budżet dekompresji oraz zgodność długości.

11. **Ważne — po timeoucie wątek pracuje dalej, ale semafor jest zwolniony.** [api.py:74](~/niewidka/niewidka/api.py:74).
    
    **Atak:** (1) Zlecić pracę przekraczającą timeout. (2) `wait_for()` kończy oczekiwanie, a wyjście z `async with` zwalnia slot. (3) Następne zadanie zaczyna działać równolegle z poprzednim, mimo `Semaphore(1)` i nawet `kolejka=0`. Odtworzone. W ukrywaniu poprzedni wątek nadal może przechowywać dokument i lokalną zmienną `klucz`; anulowanie oczekiwania nie zatrzymuje uruchomionej pracy executora. [Dokumentacja Pythona](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Future.cancel).
    
    **Minimalna poprawka:** Zwalniać slot dopiero po rzeczywistym zakończeniu pracy; twardy timeout realizować procesem, który można zakończyć.

12. **Ważne — kolejka nie ogranicza liczby buforowanych uploadów.** [api.py:190](~/niewidka/niewidka/api.py:190), [api.py:204](~/niewidka/niewidka/api.py:204), [api.py:220](~/niewidka/niewidka/api.py:220).
    
    **Atak:** (1) Otworzyć wiele poprawnie uwierzytelnionych uploadów, każdy poniżej limitu rozmiaru. (2) Wysłać prawie całe pliki i wstrzymać zakończenie multipart. (3) Wszystkie zajmują pamięć przed wejściem do kolejki. Przy `kolejka=0` osiem prób utrzymywało łącznie 2 MiB, podczas gdy kolejka i slot inferencji pozostawały wolne.
    
    **Minimalna poprawka:** Ograniczać liczbę przyjętych żądań przed parsowaniem body, odrzucać nadmiar przez 503 i ograniczyć czas uploadu.

13. **Ważne — kwadratowy regex blokuje również obsługę timeoutu.** [reguly.py:155](~/niewidka/niewidka/reguly.py:155), [api.py:80](~/niewidka/niewidka/api.py:80).
    
    **Atak:** (1) Wysłać dozwolony rozmiarem tekst zawierający długi ciąg `a`, bez `@`. (2) Regex e-maila ponawia długie, nieudane dopasowanie od kolejnych pozycji. (3) CPU zostaje zajęte, a wykonanie regexu blokuje GIL. Dla 4/8/16 tys. znaków zmierzyłem około 0,012/0,056/0,242 s; timeout 20 ms został obsłużony dopiero po około 247 ms.
    
    **Minimalna poprawka:** Dodać właściwą granicę początku dopasowania lub użyć skanowania liniowego; ciężką pracę izolować procesem zamiast polegać na timeoutach wątków.

14. **Ważne — ustawienie nasłuchu LAN udostępnia odszyfrowanie bez uwierzytelnienia użytkownika.** [konfig.py:70](~/niewidka/niewidka/konfig.py:70), [api.py:123](~/niewidka/niewidka/api.py:123), [api.py:294](~/niewidka/niewidka/api.py:294).
    
    **Warunek:** Uruchomienie z `NIEWIDKA_HOST=0.0.0.0` lub adresem LAN. **Atak:** (1) Zdalny klient pobiera token przez `GET /`. (2) Wysyła żądanie poza przeglądarką z `Host: localhost`, bez `Origin`. (3) Przesyła przechwyconą mapę aktywnej sesji i otrzymuje jawne dane. Odtworzone na poziomie ASGI z adresem klienta spoza loopbacku; nie wymaga poznania klucza.
    
    **Minimalna poprawka:** W lokalnym MVP odrzucać konfigurację nasłuchu poza loopbackiem. Udostępnienie LAN wymaga osobnego uwierzytelnienia i autoryzacji odszyfrowania.

15. **Drobne — obsługiwane błędy odbijają dane wejściowe w HTTP.** [api.py:152](~/niewidka/niewidka/api.py:152), [api.py:185](~/niewidka/niewidka/api.py:185), [api.py:192](~/niewidka/niewidka/api.py:192).
    
    **Scenariusz:** (1) Plik ma osobową nazwę bez rozszerzenia albo zawiera niedozwoloną część z PESEL-em w nazwie. (2) Handler zwraca tę nazwę w 415/422. (3) Zapis lub przekazanie odpowiedzi błędu do diagnostyki utrwala PII. Potwierdziłem również odbicie wartości `poziom=44051401359-test` przez domyślny handler walidacji w polu `input`.
    
    **Minimalna poprawka:** Zwracać bezpieczne kody błędów zamiast surowych nazw; dodać handler `RequestValidationError` usuwający wartości wejściowe.

AES-256-GCM używa losowego 96-bitowego nonce i AAD, a próby modyfikacji nonce, identyfikatora, wersji i szyfrogramu były odrzucane. Nowy plik klucza otrzymuje uprawnienia 0600 bez nadpisywania istniejącego pliku, a nieobsłużone wyjątki detektora i kontroli kończą się 500 z UUID bez ujawnienia treści. Interfejs wstawia wynik przez węzły tekstowe, a sprawdzanie tokenu oraz Host/Origin blokowało testowane niedozwolone POST-y.
