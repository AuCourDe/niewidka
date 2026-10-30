# Przegląd Codex/astra #2 (2026-10-28, K7b: pakiety modeli i wydanie)

Audyt stanu `f3fdb6b`, bez zmian plików i commitów. Poniżej 11 znalezisk; próby wykonywałem w pamięci, a rzeczywiste modele sprawdziłem względem sum z `pakiety.json`.

1. **Ważne — zainstalowany pakiet Rozszerzony nie uczestniczy w anonimizacji.**  
   Lokalizacja: [rdzen.py:77](~/niewidka/niewidka/rdzen.py:77), [detektory.py:443](~/niewidka/niewidka/detektory.py:443), [rdzen.py:167](~/niewidka/niewidka/rdzen.py:167).  
   **Scenariusz:** oba pakiety są zainstalowane → nadawca dostarcza dokument z loginem → użytkownik wybiera „Najdokładniej” → rdzeń nie przekazuje `pakiet_rozszerzony=True`, więc zarówno ukrywanie, jak i kontrola pomijają LFM2.5. Potwierdziłem na rzeczywistych wagach: `Kontakt na czacie: stefan_wodorost.` pozostaje z loginem i statusem `ukonczony`; jawnie dołączony model wykrywa LOGIN. Test w [test_detektory.py:852](~/niewidka/tests/test_detektory.py:852) podaje flagę ręcznie, omijając wadliwą integrację.  
   **Minimalna poprawka:** przekazywać zweryfikowany stan rozszerzenia do budowy detektora i unieważniać cache detektorów po zmianach pakietów.

2. **Ważne — loader ufa manifestowi dostarczonemu razem z podmienionymi wagami.**  
   Lokalizacja: [detektory.py:173](~/niewidka/niewidka/detektory.py:173), [api.py:295](~/niewidka/niewidka/api.py:295).  
   **Scenariusz:** napastnik mający zapis do współdzielonego katalogu modeli, bez prawa zmiany aplikacji, czeka na poprawne odświeżenie UI → podmienia `model.onnx` i zapisuje `manifest.json` jako `{}` → pierwsze użycie jeszcze niewczytanego poziomu ładuje podmieniony model. Manifest bez `pliki` przechodzi bez sprawdzenia choćby jednego hasha, co potwierdziłem. API sprawdza stan pakietów dopiero po wyjątku podczas budowy, więc poprawny technicznie model pomijający osoby zostanie zaakceptowany.  
   **Minimalna poprawka:** weryfikować komplet wymaganych plików względem zaufanego `pakiety.json`; lokalny manifest nie może określać oczekiwanych sum.

3. **Ważne — wyścig sprawdź–użyj obejmuje konfigurację i wagi.**  
   Lokalizacja: [detektory.py:295](~/niewidka/niewidka/detektory.py:295), [detektory.py:390](~/niewidka/niewidka/detektory.py:390), [detektory.py:142](~/niewidka/niewidka/detektory.py:142), [pakiety.py:128](~/niewidka/niewidka/pakiety.py:128).  
   **Scenariusz:** napastnik z zapisem do katalogu podkłada `config.json` mapujący wszystkie etykiety na `O` → loader odczytuje konfigurację **przed** weryfikacją → napastnik przywraca oryginał podczas haszowania modelu → wszystkie sumy pasują, lecz używana jest wcześniejsza konfiguracja. Symulacja tych odczytów w pamięci dała HTTP 200, `ukonczony` i nieukryte `Jan Kowalski`, mimo sprawdzenia wszystkich trzech plików. Analogiczne okna istnieją między haszowaniem a otwarciem ONNX oraz między haszowaniem `.częściowy` a `os.replace`.  
   **Minimalna poprawka:** haszować i przetwarzać te same bajty; dla instalacji używać prywatnego katalogu roboczego i blokady obejmującej weryfikację oraz publikację.

4. **Ważne — dowiązania pozwalają nadpisywać pliki poza katalogiem modeli.**  
   Lokalizacja: [pakiety.py:267](~/niewidka/niewidka/pakiety.py:267), [pakiety.py:193](~/niewidka/niewidka/pakiety.py:193).  
   **Scenariusz:** napastnik mogący tworzyć wpisy w katalogu modeli podstawia `model.onnx.częściowy` jako symlink do pliku ofiary → użytkownik uruchamia instalację offline → `shutil.copyfile` otwiera wskazany plik do nadpisania. Sprawdzenie SHA następuje już po zniszczeniu jego zawartości; usunięcie symlinku nie odwraca szkody. `manifest.json` również jest zapisywany z podążaniem za dowiązaniem, a junction w katalogu nadrzędnym przekierowuje operacje poza katalog modeli.  
   **Minimalna poprawka:** bezpiecznie tworzyć nowe pliki tymczasowe, odrzucać dowiązania i reparse points także w rodzicach ścieżki, używać prywatnego katalogu oraz atomowo publikować manifest.

5. **Ważne — hasło do lustra wycieka przez niechroniony status pakietów.**  
   Lokalizacja: [pakiety.py:364](~/niewidka/niewidka/pakiety.py:364), [api.py:425](~/niewidka/niewidka/api.py:425).  
   **Scenariusz:** IT ustawia źródło jako `https://login:haslo@lustro/...` → serwer zwraca np. 503 → pełny tekst wyjątku HTTPX, zawierający URL z hasłem, trafia do `postep.blad` → inny lokalny użytkownik odczytuje `GET /api/pakiety` bez tokena. Potwierdziłem ujawnienie syntetycznego hasła również przy obcym Host i Origin.  
   **Minimalna poprawka:** zwracać kontrolowany komunikat i kod błędu; usuwać dane logowania oraz sekretne parametry URL przed umieszczeniem informacji w statusie lub logach.

6. **Ważne — ruchome tagi akcji wykonują kod z uprawnieniami zapisu do repozytorium.**  
   Lokalizacja: [wydanie.yml:26](~/niewidka/.github/workflows/wydanie.yml:26), [wydanie.yml:34](~/niewidka/.github/workflows/wydanie.yml:34), [wydanie.yml:78](~/niewidka/.github/workflows/wydanie.yml:78).  
   **Scenariusz:** napastnik przejmuje repozytorium jednej z używanych akcji → przestawia tag, np. `softprops/action-gh-release@v2` → następne wydanie wykonuje jego kod z `contents: write` → kod podmienia artefakt i jego sumę albo zmienia wydanie bez respektowania `draft: true`. Ruchomość tagów jest udokumentowanym zagrożeniem. [Dokumentacja GitHub](https://docs.github.com/en/actions/reference/security/secure-use#using-third-party-actions).  
   **Minimalna poprawka:** przypiąć wszystkie akcje do sprawdzonych pełnych SHA; budowę wykonywać z `contents: read`, a zapis przyznać osobnemu zadaniu publikacji. Wyłączyć utrwalanie poświadczeń checkoutu.

7. **Ważne — wydanie pobiera nieprzypięte zależności, pomijając istniejący lockfile.**  
   Lokalizacja: [wydanie.yml:45](~/niewidka/.github/workflows/wydanie.yml:45), [zbuduj_windows.ps1:49](~/niewidka/narzedzia/zbuduj_windows.ps1:49).  
   **Scenariusz:** napastnik przejmuje jedną zależność lub jej zależność przechodnią i publikuje nową wersję → następna budowa pobiera ją bez zmiany commitu Niewidki → złośliwy kod wykonuje się podczas importu/budowy lub trafia do EXE. Późniejsze `SHA256SUMS` poświadcza już zatruty wynik. Dodatkowo checkout domyślnie pozostawia token w konfiguracji Git dostępnej dla kolejnych kroków. [Definicja checkout v4](https://raw.githubusercontent.com/actions/checkout/v4/action.yml).  
   **Minimalna poprawka:** objąć lockfile także zależności desktopowe i narzędzia budowy; oba procesy budowania mają instalować zatwierdzone wersje z kontrolą hashów.

8. **Ważne — źródło pakietów może zapełnić dysk albo bezterminowo zajmować pobieranie.**  
   Lokalizacja: [pakiety.py:177](~/niewidka/niewidka/pakiety.py:177), [pakiety.py:207](~/niewidka/niewidka/pakiety.py:207), [pakiety.py:268](~/niewidka/niewidka/pakiety.py:268), [api.py:465](~/niewidka/niewidka/api.py:465).  
   **Scenariusz:** przejęte lustro lub napastnik na trasie HTTP wysyła strumień przekraczający rozmiar z katalogu → aplikacja zapisuje go bez limitu → SHA jest sprawdzany dopiero na końcu. Próba w RAM przy deklarowanym 1 B przyjęła 8 MiB przed odrzuceniem. Wysyłanie kolejnych fragmentów przed upływem 600 s pozwala utrzymywać operację: timeout odczytu HTTPX dotyczy oczekiwania na fragment, nie całego transferu. [Dokumentacja HTTPX](https://www.python-httpx.org/advanced/timeouts/). Ogromny plik w katalogu IT działa podobnie, dodatkowo kopiowanie blokuje pętlę API.  
   **Minimalna poprawka:** egzekwować rozmiar przed każdym zapisem, uwzględniając wznowienie; dodać całkowity limit czasu i anulowanie. Instalację offline wykonywać w tle z takim samym limitem bajtów.

9. **Ważne — nieautoryzowane GET-y mogą zagłodzić całe API haszowaniem wag.**  
   Lokalizacja: [api.py:425](~/niewidka/niewidka/api.py:425), [api.py:590](~/niewidka/niewidka/api.py:590), [pakiety.py:318](~/niewidka/niewidka/pakiety.py:318), [apka.js:685](~/niewidka/niewidka/web/apka.js:685).  
   **Scenariusz:** lokalny klient bez tokena wysyła serię `GET /api/pakiety` → każde żądanie synchronicznie haszuje wszystkie pliki oraz ponownie pakiet podstawowy → pętla obsługująca API przestaje terminowo obsługiwać pozostałe żądania. Dla obu pakietów to **608 936 431 B na żądanie**, około **0,43–0,45 s** w pomiarze; obcy Host/Origin nadal dawał 200. Sam polling UI co 300 ms może generować kolejkę takich operacji.  
   **Minimalna poprawka:** GET powinien zwracać zapamiętany status, a kosztowna kontrola działać w ograniczonym zadaniu tła; dodać ograniczenie częstotliwości i równoległości kontroli.

10. **Drobne — przekierowanie lustra umożliwia ślepe SSRF i obniżenie HTTPS do HTTP.**  
    Lokalizacja: [pakiety.py:166](~/niewidka/niewidka/pakiety.py:166), [pakiety.py:207](~/niewidka/niewidka/pakiety.py:207).  
    **Scenariusz:** użytkownik rozpoczyna pobieranie z zatwierdzonego lustra → przejęte lustro albo napastnik przechwytujący HTTP zwraca `302 Location: http://127.0.0.1:12345/private` → downloader wykonuje GET do wskazanej usługi lokalnej. Dokładnie taki przebieg potwierdził MockTransport; późniejszy błąd SHA nie cofa żądania. Warunkiem jest kontrola odpowiedzi źródła, a możliwość ogranicza się tutaj do ślepych żądań GET.  
    **Minimalna poprawka:** walidować każdy etap przekierowania, dopuszczać zatwierdzone hosty/adresy i HTTPS, z osobnym jawnym wyjątkiem dla skonfigurowanego lustra IT.

11. **Drobne — pojedynczy błąd pobierania blokuje ponowienie w GUI do restartu.**  
    Lokalizacja: [pakiety.py:360](~/niewidka/niewidka/pakiety.py:360), [apka.js:625](~/niewidka/niewidka/web/apka.js:625), [apka.js:669](~/niewidka/niewidka/web/apka.js:669).  
    **Scenariusz:** lustro raz zwraca 404 lub niepoprawny plik → wątek kończy pracę, ale `postep.pakiet` pozostaje ustawiony → UI nadal wyłącza przyciski pobierania i ukrywa wybór pierwszego uruchomienia → przywrócenie poprawnego lustra nie umożliwia ponowienia. Potwierdziłem stan `zakonczone=True` przy nadal ustawionym identyfikatorze pakietu.  
    **Minimalna poprawka:** kończyć stan operacji w `finally`, także dla `OSError`; komunikat błędu przechowywać niezależnie i udostępnić ponowienie.

Pełny SHA-256 jest liczony również po wznowieniu przez Range, a wykryta niezgodność usuwa plik częściowy. POST-y pakietów poprawnie egzekwują token, Host i Origin, a API nie pozwala podmienić adresu lustra ani nazw plików z wbudowanego katalogu. Brak podstawowego modelu blokuje wynik; runtime nie używa pickle, a oba zweryfikowane modele ONNX nie zawierają `external_data`.