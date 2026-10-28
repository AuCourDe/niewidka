# Przegląd adwersarialny HLD/LLD — Gemini

Data: 2026-10-28
Przegląd architektury wysokiego (HLD) i niskiego (LLD) poziomu projektu „Niewidka” w oparciu o `docs/HLD.md`, `docs/LLD.md` oraz `docs/KONSULTACJE.md`.
Zakres: sprzeczności, luki bezpieczeństwa, scenariusze awarii i nadmierna złożoność.

---

### 1. [krytyczne] Wspólny klucz symetryczny serwera i brak tożsamości użytkownika (wyciek danych między pracownikami)
* **Problem:** W trybie „Na serwerze organizacji” (HLD §3, LLD §8, §12) serwer posiada jeden globalny klucz szyfrowania map zdefiniowany w `NIEWIDKA_KLUCZ_PLIK`. Każdy użytkownik sieci LAN z dostępem do endpointu `POST /api/przywroc` może przesłać dowolny przechwycony plik `.nwidka` (np. z dysku współdzielonego lub skrzynki pocztowej), a serwer bez żadnej autoryzacji go odszyfruje i ujawni oryginalne dane osobowe. Zapewnienie, że „dane nie opuszczają sieci”, ignoruje brak separacji uprawnień wewnątrz organizacji (np. poufne dane płacowe HR vs pracownicy IT).
* **Poprawka:** Klucz szyfrowania mapy nie może być statycznym sekretem serwera współdzielonym przez wszystkich użytkowników. Szyfrowanie mapy musi bazować na haśle/kluczu podawanym przez klienta (wyprowadzanym w przeglądarce/kliencie przez Argon2id) lub na kluczu jednorazowym generowanym per dokument i zwracanym wyłącznie użytkownikowi zlecającemu anonimizację.

### 2. [krytyczne] Niewykonalność pełnego przywrócenia oryginału („round-trip failure”) przy bezpowrotnym usuwaniu metadanych i nagłówków
* **Problem:** HLD §2 i LLD §12 obiecują odtworzenie dokumentu do oryginału (`/api/przywroc` -> oryginał; PLAN T4.5: `end-to-end ukryj → przywróć = oryginał`). Jednocześnie HLD §4 (2) i LLD §9 nakazują bezpowrotne usuwanie z plików DOCX/PPTX/XLSX komentarzy, śledzonych zmian, nagłówków, stopek i metadanych. Ponieważ usunięte struktury dokumentu nie są zapisywane w formacie `Mapa` (LLD §8), dokument zwrócony przez `/api/przywroc` traci bezpowrotnie nagłówki, stopki, rewizje i układ. Zachodzi jawna sprzeczność między obietnicą odtworzenia oryginału a mechanizmem czyszczenia kanałów bocznych.
* **Poprawka:** Zmienić specyfikację w HLD/LLD: operacja przywracania odwraca jedynie zamianę znaczników w tekście (`[TYP_N]` -> `oryginał`), a usunięte elementy strukturalne są bezpowrotnie tracone. Jeśli celem ma być wierne odtworzenie 1:1, usunięte nagłówki, stopki i metadane muszą być serializowane w zaszyfrowanej mapie `.nwidka`.

### 3. [krytyczne] Uszkodzenie przywracania danych przez sekwencyjny licznik `kolejny` po przetworzeniu tekstu przez LLM
* **Problem:** LLD §8 opiera przywracanie na globalnym sekwencyjnym liczniku wystąpień znacznika (`kolejny`: 0, 1, 2...). Podstawowym celem projektu jest wysłanie zanonimizowanego tekstu do chmurowego AI, które z natury parafrazuje tekst, zmienia szyk zdań, usuwa powtórzenia lub duplikuje fragmenty. Jeśli model AI usunie choć jedno wystąpienie znacznika `[OSOBA_1]` lub zamieni kolejność akapitów, sekwencja `kolejny` ulegnie trwałej desynchronizacji, co poskutkuje wstrzyknięciem niewłaściwych odmian nazwisk w złe miejsca dokumentu.
* **Poprawka:** Każde wystąpienie znacznika musi posiadać unikalny identyfikator (np. `[OSOBA_1:0]`, `[OSOBA_1:1]`), który chmurowy model zachowuje w tekście, eliminując poleganie na podatnym na awarie sekwencyjnym dopasowywaniu pozycji.

### 4. [krytyczne] Fizyczna niemożliwość poprawnego przywrócenia dokumentów w formacie PDF (`pdf_.py`)
* **Problem:** LLD §9 zakłada w plikach PDF redakcję tekstu przez PyMuPDF (usunięcie zawartości pod prostokątem i wrysowanie znacznika `[TYP_N]`). Format PDF nie posiada mechanizmu automatycznego łamania linii i płynnego przepływu tekstu (reflow). Przywrócenie dłuższego tekstu w miejsce znacznika (np. `[OSOBA_1]` -> `Janina Przełęcka-Kowalska`) spowoduje nałożenie się tekstu na sąsiednie słowa, wyjście poza margines i zniszczenie układu graficznego. Ponadto kolejność ekstrakcji bloków w PyMuPDF bywa nieliniowa, co uniemożliwia deterministyczne mapowanie indeksu `kolejny`.
* **Poprawka:** W HLD i LLD wyłączyć format PDF z obsługi endpointu `/api/przywroc` (PDF jako format wyłącznie jednokierunkowy do bezpiecznego eksportu) i zwracać błąd HTTP 422 przy próbie przywrócenia PDF, albo ograniczyć przywracanie PDF do eksportu surowej warstwy tekstowej jako TXT.

### 5. [ważne] Zawieszanie pętli zdarzeń asyncio i zagłodzenie serwera pod obciążeniem (`Semaphore(1)`)
* **Problem:** LLD §12 i §16 definiują przetwarzanie w jednym procesie za pomocą `asyncio.Semaphore(1)`. Ciężkie parsowanie plików OOXML (do 25 MB) oraz inferencja modeli ONNX na CPU są operacjami synchronicznymi blokującymi wątek główny interpretera Pythona. Uruchomienie ich bezpośrednio w asynchronicznym handlerze FastAPI zablokuje całą pętlę zdarzeń asyncio — serwer przestanie odpowiadać na zapytania monitorujące stan (`GET /api/stan`), a oczekujący klienci nie otrzymają odpowiedzi HTTP 503 Retry-After.
* **Poprawka:** Przetwarzanie dokumentu i inferencję należy oddelegować do dedykowanej puli wątków roboczych (`asyncio.to_thread` lub `run_in_threadpool`) z asynchronicznym nadzorem czasu wykonania (`asyncio.wait_for` z limitem `NIEWIDKA_TIMEOUT_S`).

### 6. [ważne] Ryzyko ataku DoS bombą dekompresyjną (Zip Bomb) i parsowaniem XML w plikach OOXML
* **Problem:** LLD §14 ustala limit wejściowy na 25 MB. Pliki DOCX, PPTX, XLSX i ODT to skompresowane archiwa ZIP. Złośliwie spreparowane archiwum 25 MB może rozpakować się do kilkunastu gigabajtów XML. Wykorzystanie biblioteki `lxml` bez rygorystycznych ograniczeń parsera oraz brak kontroli współczynnika dekompresji (decompression ratio) doprowadzi do wyczerpania pamięci RAM (OOM) i załamania procesu serwerowego.
* **Poprawka:** Przed rozpakowaniem archiwów weryfikować łączny rozmiar rozpakowanych strumieni (limit np. 100 MB). Parsowanie XML zabezpieczyć przy użyciu biblioteki `defusedxml` lub bezpiecznej konfiguracji parsera: `lxml.etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)`.

### 7. [ważne] Naruszenie integralności struktury OpenXML w DOCX przez arbitralne cięcie runów
* **Problem:** LLD §9 zakłada dzielenie runów (`<w:r>`) na podstawie offsetów znakowych `starts` i dziedziczenie stylu lewego fragmentu. W DOCX runy tekstu leżą w strukturach specjalnych, takich jak hiperłącza (`<w:hyperlink>`), pola dynamiczne (`<w:fldSimple>` / `<w:fldChar>` dla dat i stron) czy zakładki (`<w:bookmarkStart>`). Dzielenie węzłów bez uwzględnienia hierarchii XML prowadzi do wygenerowania błędnej struktury OpenXML i błędu uszkodzonego pliku w programie Microsoft Word. Ponadto literał `[TYP_N]` w dopisku informacyjnym (LLD §7) zostanie błędnie zinterpretowany jako encja podczas kontroli wyniku (poziom 3).
* **Poprawka:** Zaimplementować parser runów respektujący granice kontenerów nadrzędnych i elementów inline; zmienić treść dopisku informacyjnego tak, aby nie zawierała składni pasującej do wzorca znacznika (użyć opisu słownego bez nawiasów kwadratowych).

### 8. [ważne] Sprzeczność: blokowanie „obrazów z tekstem” przy jednoczesnym braku modułu OCR w MVP
* **Problem:** LLD §9 i §15 nakazują blokowanie eksportu (`ElementNieobslugiwany -> 422`) w przypadku wystąpienia „obrazów z tekstem”. Jednocześnie HLD §6 jednoznacznie wyklucza OCR z zakresu MVP („OCR poza MVP”). Bez silnika OCR adapter nie ma technicznej możliwości ustalenia, czy dany obraz rastrowy zawiera dane osobowe (np. skan dowodu osobistego), czy jest neutralnym logotypem lub wykresem. W efekcie system albo przepuści obrazy z PII, albo zablokuje każdy dokument zawierający grafikę.
* **Poprawka:** Usunąć kryterium „obraz z tekstem” z warunku błędu `ElementNieobslugiwany`. Wprowadzić jednoznaczną politykę dla grafik w MVP: domyślne usuwanie obrazów z pliku wynikowego albo pozostawianie ich z obowiązkowym ostrzeżeniem w raporcie weryfikacji o obecności niesprawdzonej zawartości graficznej.

### 9. [ważne] Pozostawianie danych osobowych w nazwie pliku wyjściowego
* **Problem:** HLD §4 (10) i LLD §7 określają nazwę pliku wynikowego jako `ZANONIMIZOWANY_*` (gdzie `*` to nazwa pliku wejściowego). W praktyce nazwy plików biznesowych często zawierają dane osobowe (np. `Umowa_Jan_Kowalski_PESEL_85010112345.docx`). Samo dodanie prefiksu nie usuwa danych osobowych z nazwy pliku, która trafia do czatu AI lub zewnętrznego systemu.
* **Poprawka:** Nazwa pliku wynikowego musi być neutralizowana w całości, np. `ZANONIMIZOWANY_<hash_lub_uuid>.<ext>` lub oryginalna nazwa pliku musi być obowiązkowo przepuszczana przez ten sam potok anonimizacji regex/NER przed zapisem.

### 10. [ważne] Niezgodność platformowa weryfikacji uprawnień pliku klucza (0600) na systemach Windows
* **Problem:** LLD §8 i §14 wymagają uprawnień `0600` dla pliku wskazanego przez `NIEWIDKA_KLUCZ_PLIK`. Projekt ma działać jako desktop na Windows, macOS i Linux (HLD §5). W systemie Windows (NTFS) uprawnienia POSIX nie są odwzorowywane przez `os.stat().st_mode`. Sprawdzanie `st_mode & 0o777 == 0o600` spowoduje błąd `BrakKlucza` i uniemożliwi uruchomienie aplikacji na stacjach Windows.
* **Poprawka:** Ograniczyć sprawdzanie bitów `0600` do systemów POSIX (`os.name != 'nt'`); na platformie Windows weryfikować brak dostępu dla innych użytkowników za pośrednictwem modułu `win32security` lub wymusić przechowywanie klucza w katalogu profilu użytkownika (`%APPDATA%`).

### 11. [ważne] Złudny charakter wskaźnika R95 i karanie poprawnych dokumentów we wskaźniku jakości
* **Problem:** LLD §11 zakłada wyświetlanie w UI statycznego wskaźnika R95 z pliku `dane/r95.json`, wyliczonego offline na korpusie testowym (zaledwie 40 próbek w PLAN §Etap 0). Wartość ta jest stała dla danego poziomu suwaka i nie zależy od treści przesłanego dokumentu, wprowadzając użytkownika w błąd co do jakości przetworzenia konkretnego pliku. Jednocześnie `wskaznik_dokumentu` automatycznie odejmuje punkty za encje bez sumy kontrolnej, co na poziomie 1 zaniża ocenę każdego dokumentu z nazwiskami, nawet przy 100% poprawnej detekcji.
* **Poprawka:** Wyraźnie rozdzielić w UI etykietę statyczną („Dokładność modelu na korpusie wzorcowym”) od oceny pliku („Ocena bieżącego dokumentu”). Ze wzoru `wskaznik_dokumentu` wykluczyć odejmowanie punktów za brak sum kontrolnych dla typów OSOBA i ADRES, które takich sum naturalnie nie posiadają.

### 12. [ważne] Fikcja generowania formy podstawowej (`forma`) w mapie przy braku lematyzatora
* **Problem:** LLD §8 wymaga zapisywania w mapie pola `"forma": "Jan Kowalski"` jako fallbacku przy rozjechaniu się pozycji znacznika. Jednocześnie w LLD §6 i KONSULTACJE jednoznacznie zrezygnowano z lematyzatora (brak Morfeusza 2 / spaCy) na rzecz prostej heurystyki ucinania końcówek fleksyjnych (`-ski/-ska`). Heurystyka odcinania końcówek nie generuje poprawnego mianownika (np. dla „Piotra”, „Michała”, „Kowalskim”), a model Bardsai zwraca jedynie surowe tokeny bez lematów.
* **Poprawka:** W fazie MVP wykreślić pole `forma` ze specyfikacji mapy i opierać odtwarzanie wyłącznie na unikalnym identyfikatorze znacznika i wartości `oryginal` (zgodnie z punktem 3), eliminując potrzebę zawodnego generowania mianownika bez dedykowanego słownika fleksyjnego.

### 13. [drobne] Fragmentacja tożsamości osoby przy wystąpieniu samego nazwiska bez imienia
* **Problem:** LLD §6 definiuje klucz grupy osób jako parę `(rdzeń_nazwiska, imię/inicjały)`. W pismach urzędowych i biznesowych po jednokrotnym przedstawieniu osoby z imienia i nazwiska w dalszym tekście powszechnie występuje samo nazwisko („wniosek Kowalskiego”, „Pan Kowalski oświadczył”). Klucz dla samego nazwiska otrzyma `imię = None`, przez co system zakwalifikuje je jako odrębną osobę (np. `[OSOBA_2]`), rozbijając spójność logiczną tekstu dla modelu LLM.
* **Poprawka:** Wprowadzić regułę asocjacji wstecznej: jeśli w dokumencie występuje dokładnie jedna osoba o danym rdzeniu nazwiska, późniejsze wystąpienia samego nazwiska bez sprzecznego imienia powinny być dołączane do istniejącej grupy `[OSOBA_1]`.

### 14. [drobne] Nieoptymalne przesyłanie plików binarnych do 25 MB w formacie JSON Base64
* **Problem:** LLD §12 specyfikuje odpowiedź `POST /api/ukryj` jako JSON zawierający pola `wynik_base64` i `mapa_base64`. Kodowanie pliku 25 MB do base64 zwiększa payload do ~33 MB i wymusza wielokrotną alokację w pamięci RAM serwera i przeglądarki podczas serializacji i parsowania stringa JSON, co na maszynach klienckich grozi zawieszeniem karty webowej lub awarią OOM.
* **Poprawka:** Zwracać odpowiedź jako strumień binarny (`application/octet-stream`) lub archiwum ZIP zawierające zanonimizowany plik oraz zaszyfrowaną mapę `.nwidka`, a metadane jakości przekazywać w nagłówkach odpowiedzi HTTP.

### 15. [drobne] Ryzyko ujawnienia PII w logach serwera przy nieobsłużonych wyjątkach aplikacji
* **Problem:** HLD §4 (7) deklaruje całkowity brak logowania treści. Domyślna konfiguracja loggera Uvicorn i frameworka FastAPI w razie nieprzechwyconego wyjątku (np. błąd parsowania uszkodzonego pliku przez bibliotekę formatu lub błąd sesji ONNX) wypisuje na standardowe wyjście pełny traceback Pythona wraz z argumentami wywołań, które mogą zawierać surowy tekst dokumentu z PII.
* **Poprawka:** Zaimplementować globalny middleware przechwytujący błędy w `api.py`, który usuwa dane kontekstowe przed wysłaniem błędu do logów systemowych (stdout/journald) i rejestruje wyłącznie unikalny identyfikator błędu (UUID) bez wartości zmiennych lokalnych.
