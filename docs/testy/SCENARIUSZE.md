# Niewidka: scenariusze testowe (web i okienkowa)

Stan: 2026-10-29. Zlecenie właściciela 23:55 z 2026-10-28 (`todo.md`): scenariusze per rozwiązanie,
najpierw przebieg po API, potem przez GUI. Scenariusze wynikają z dokumentacji
(`README.md`, `docs/HLD.md`, `LLD.md`, `PLAN.md`, `KAMIENIE.md`, `KONSULTACJE.md`) i z listy ekranów
`niewidka/web/index.html`, nie z kodu aplikacji.

## Konwencje

- **WEB** = serwer w organizacji, przeglądarka (adres z `NIEWIDKA_HOST`/`NIEWIDKA_PORT`, domyślnie `127.0.0.1:8390`).
  **OKNO** = `Niewidka.exe`, okno WebView2, serwer w środku na wolnym porcie `127.0.0.1`. **WSP** = wspólne.
- Warstwa **API**: `/api/stan`, `/api/ukryj`, `/api/przywroc`, `/api/pakiety` (z tokenem sesji, Host i Origin walidowane).
  Warstwa **GUI**: ekrany z `index.html` (zakładki *Ukryj dane*, *Przywróć dane*, *Ustawienia*, ekran *Przygotowanie do pracy*).
- Poziomy: 1 *Szybko*, 2 *Dokładniej* (domyślny suwak), 3 *Najdokładniej*.
- Wszystkie dane testowe są fikcyjne. Przykłady z poprawną sumą kontrolną: PESEL `44051401359`, NIP `526-025-02-74`,
  dowód `ABA300000`, IBAN `PL61 1090 1014 0000 0712 1981 2874`. Z błędną sumą: PESEL `44051401358`, NIP `526-025-02-75`.
- „Wynik bez oryginału” = ani w treści wyniku, ani w nazwie pliku, ani w nagłówkach HTTP, ani w surowych częściach ZIP
  pliku DOCX nie ma żadnego z oryginalnych ciągów (sprawdzenie `grep`/bajtowe na każdym ciągu z tekstu wzorcowego).
- `NIEJASNE:` = dokumentacja nie rozstrzyga; scenariusz zostaje do uzupełnienia po decyzji.

## Teksty wzorcowe

**T-PISMO** (pismo urzędowe, wiele typów danych):

```
Warszawa, 12.03.2024 r.
Szanowny Pan Jan Kowalski
ul. Długa 5/12, 00-950 Warszawa

Dotyczy: wniosku Pana Jana Kowalskiego (PESEL 44051401359, NIP 526-025-02-74).
Dowód osobisty ABA300000, telefon +48 601 234 567, e-mail jan.kowalski@przyklad.example.
Pani Anna Nowak przekazała Janowi Kowalskiemu dokumenty. Przelew na rachunek
PL61 1090 1014 0000 0712 1981 2874. Z poważaniem, Anna Nowak.
```

**T-ODMIANY**: `Jan Kowalski zadzwonił do Marii Wiśniewskiej. Wiśniewska odpisała Kowalskiemu. Dla Jana Kowalskiego i Marii Wiśniewskiej przygotowano umowę z Piotrem Kowalskim.`
(Piotr Kowalski to inna osoba niż Jan Kowalski.)

**T-ROZSZERZONY**: `Serwer 192.168.10.15, login: stefan_wodorost, SWIFT: BREXPLPW, karta 4111 1111 1111 1111.`

**T-CZYSTY**: `Dziś jest ładna pogoda, a wiśnie w sadzie dojrzały wcześniej niż zwykle.` (brak danych osobowych)

---

## 1. Pierwsze uruchomienie i pakiety modeli

### S-WSP-01: ekran „Przygotowanie do pracy” przy braku pakietów
Warstwa: oba
Źródło: KAMIENIE K7b: „ekran pierwszego uruchomienia (Pobierz podstawowy zalecane / Pobierz wszystko / Później)”
Warunki wstępne: katalog modeli pusty (`NIEWIDKA_MODELE_KATALOG` wskazuje pusty katalog, w OKNO czysty `%LOCALAPPDATA%\Niewidka\modele`).
Kroki: 1. Uruchom aplikację. 2. API: `GET /api/stan` z tokenem. 3. GUI: otwórz stronę główną.
Oczekiwany stan końcowy: serwer startuje bez wag (łagodny start, bez 500). `/api/stan` zwraca 200 i pustą/niepełną listę
`poziomy_dostepne`. Na ekranie widoczna sekcja „Przygotowanie do pracy” z trzema akcjami: „Pobierz podstawowy (zalecane)”,
„Pobierz wszystko (podstawowy i rozszerzony)”, „Później” i podpowiedzią o pakiecie rozszerzonym (adresy IP, kody SWIFT, loginy).
Suwak jakości jest wyłączony.
Rodzaj: pozytywny

### S-WSP-02: pobranie pakietu podstawowego
Warstwa: oba
Źródło: README: „Pobierz podstawowy (zalecane): to ok. 190 MB, pobiera się raz.”
Warunki wstępne: S-WSP-01; dostęp do źródła pakietów (internet albo `NIEWIDKA_MODELE_ZRODLO` wskazujące lustro).
Kroki: 1. GUI: kliknij „Pobierz podstawowy (zalecane)”. 2. Obserwuj `#ekran-pakietow-status` i pasek. 3. API: `GET /api/pakiety` w trakcie i po.
Oczekiwany stan końcowy: widoczny pasek postępu i komunikat statusu (aria-live). `POST /api/pakiety` zwraca 202 (pobieranie w tle).
Po zakończeniu: pakiet Podstawowy ma stan „zainstalowany” (rozmiar ok. 191 MB, suma SHA-256 zgodna), ekran „Przygotowanie do pracy”
znika sam, suwak jakości jest aktywny, `/api/stan.poziomy_dostepne` zawiera co najmniej poziomy 1 i 2.
Rodzaj: pozytywny

### S-WSP-03: pobranie wszystkiego (podstawowy i rozszerzony)
Warstwa: oba
Źródło: README: „Pobierz wszystko (podstawowy i rozszerzony)”; pakiet Rozszerzony ok. 227 MB
Warunki wstępne: S-WSP-01.
Kroki: 1. Kliknij „Pobierz wszystko”. 2. Poczekaj na koniec. 3. Otwórz zakładkę *Ustawienia*.
Oczekiwany stan końcowy: pobieranie obu pakietów jedno po drugim (kolejka), bez dwóch równoległych pobrań tego samego pakietu.
W *Ustawieniach* oba pakiety w stanie „zainstalowany”. `/api/stan.poziomy_dostepne` zawiera 1, 2 i 3.
Rodzaj: pozytywny

### S-WSP-04: „Później” i praca bez pakietów
Warstwa: oba
Źródło: KAMIENIE K7b: „409 z brak_pakietu”; „suwak wyłączony bez pakietu”
Warunki wstępne: S-WSP-01.
Kroki: 1. Kliknij „Później”. 2. Wklej T-PISMO. 3. Kliknij „Ukryj dane”. 4. API: `POST /api/ukryj` (pole `tekst`, `poziom=1`).
Oczekiwany stan końcowy: API zwraca **409** z treścią `brak_pakietu` i nazwą wyświetlaną brakującego pakietu (Podstawowy).
GUI nie pokazuje wyniku, wyświetla czytelny komunikat i prowadzi do zakładki *Ustawienia*. W wyniku nie pojawia się żaden
częściowo zanonimizowany tekst.
Rodzaj: negatywny

### S-WSP-05: błąd sieci podczas pobierania i ponowna próba
Warstwa: oba
Źródło: HLD §4.8 / pakiety: „zły hash = usunięcie”; README: źródło `NIEWIDKA_MODELE_ZRODLO`
Warunki wstępne: S-WSP-01; źródło pakietów ustawione na adres, który zostanie odcięty w trakcie (np. lustro HTTP zatrzymane po kilku MB).
Kroki: 1. Rozpocznij pobieranie podstawowego. 2. Przerwij sieć/zatrzymaj lustro w połowie. 3. Obserwuj ekran. 4. Przywróć sieć. 5. Ponów pobranie.
Oczekiwany stan końcowy: po przerwaniu ekran pokazuje **widoczny** komunikat o błędzie pobierania (nie cisza, nie wieczny pasek), pakiet
nie jest oznaczony jako zainstalowany, w katalogu nie zostaje niepełny plik uznany za gotowy. Po ponownej próbie pobieranie kończy się
sukcesem (wznowienie Range albo od nowa), suma SHA-256 zgodna, stan „zainstalowany”.
Rodzaj: negatywny

### S-WSP-06: uszkodzona suma kontrolna pakietu
Warstwa: API
Źródło: HLD §4.8: „manifest z SHA-256 sprawdzany przy ładowaniu”
Warunki wstępne: lustro serwujące plik pakietu z jednym zmienionym bajtem.
Kroki: 1. `POST /api/pakiety` (instalacja Podstawowego). 2. Odczekaj do zakończenia. 3. `GET /api/pakiety`.
Oczekiwany stan końcowy: pobrany plik z błędnym hashem zostaje usunięty, błąd pakietu zgłoszony (komunikat widoczny w `GET /api/pakiety`
lub odpowiedzi 422), pakiet **nie** jest „zainstalowany”, `poziomy_dostepne` bez nowych poziomów.
Rodzaj: negatywny

### S-OKNO-07: błąd 403 przy pakietach widoczny w oknie (regresja Origin)
Warstwa: oba
Źródło: todo 23:36 2026-10-28: „w okienkowej kliknąłem »pobierz podstawowy« i nic się nie dzieje”
Warunki wstępne: EXE uruchomione na wolnym porcie innym niż 8390; brak pakietów.
Kroki: 1. Kliknij „Pobierz podstawowy (zalecane)”. 2. API: `POST /api/pakiety` z Originem `http://127.0.0.1:<faktyczny port okna>` i tokenem.
Oczekiwany stan końcowy: Origin własnego okna (faktyczny port) jest **akceptowany** (nie 403), pobieranie startuje (202) albo 409/200 zgodnie
ze stanem. Gdyby serwer odrzucił żądanie, na ekranie pojawia się widoczny komunikat błędu, a nie brak reakcji.
Rodzaj: negatywny

### S-WSP-08: instalacja pakietów offline z katalogu
Warstwa: oba
Źródło: README: „Instalacja offline… akcja instalowania z katalogu” i Ustawienia: „wgrać pakiety z dowolnego katalogu”
Warunki wstępne: maszyna bez internetu; katalog z plikami pakietów o nazwach z pola `zrodlo` w `pakiety.json`.
Kroki: 1. W *Ustawieniach* użyj akcji instalowania z katalogu (albo `NIEWIDKA_MODELE_ZRODLO` na lokalny katalog/serwer). 2. Wskaż katalog.
Oczekiwany stan końcowy: pakiet instaluje się bez ruchu sieciowego na zewnątrz, SHA-256 sprawdzone, stan „zainstalowany”.
NIEJASNE: czy akcja instalowania z katalogu ma osobny przycisk w *Ustawieniach*, czy tylko zmienną środowiskową? Dokumentacja wspomina o „akcji”,
a `index.html` jej nie nazywa.
Rodzaj: pozytywny

### S-WSP-09: restart zachowuje zainstalowane pakiety
Warstwa: oba
Źródło: README: „Pobrane modele zostają na komputerze (Windows: %LOCALAPPDATA%\Niewidka\modele)”
Warunki wstępne: zainstalowany Podstawowy.
Kroki: 1. Zamknij aplikację. 2. Uruchom ponownie. 3. Otwórz stronę główną.
Oczekiwany stan końcowy: ekran „Przygotowanie do pracy” **nie** pojawia się, suwak aktywny, `/api/stan` pokazuje te same poziomy.
Brak jakiegokolwiek żądania sieciowego poza `127.0.0.1` w trakcie pracy.
Rodzaj: pozytywny

---

## 2. Ukrywanie danych: poziomy 1-3

### S-WSP-10: poziom 1 (Szybko), tekst z wieloma typami danych
Warstwa: oba
Źródło: README, tabela poziomów: „1: reguły + bardsai”
Warunki wstępne: zainstalowany Podstawowy.
Kroki: 1. Wklej T-PISMO. 2. Ustaw suwak na 1. 3. Kliknij „Ukryj dane”. 4. API: `POST /api/ukryj` (`tekst`, `poziom=1`).
Oczekiwany stan końcowy: HTTP 200. W wyniku znaczniki `[OSOBA_N...]`, `[PESEL_1]`, `[NIP_1]`, `[DOKUMENT_1]`, `[TELEFON_1]`, `[EMAIL_1]`,
`[IBAN_1]`, `[ADRES_1]`, `[DATA_1]` (zgodnie z listą typów w sekcji „Jakie dane wykrywamy”). Wynik zaczyna się dopiskiem
„ZANONIMIZOWANO w Niewidka…” (bez nawiasów kwadratowych). **W wyniku nie ma:** „Kowalski”, „Kowalskiego”, „Jana”, „Nowak”, `44051401359`,
`526-025-02-74`, `ABA300000`, `601 234 567`, `jan.kowalski@przyklad.example`, `PL61 1090…`, „Długa 5/12”, „00-950”, „12.03.2024”.
Status: „Gotowe: dokument z ukrytymi danymi”, blok „Ukryte dane” z liczbami per typ.
Rodzaj: pozytywny

### S-WSP-11: poziom 2 (Dokładniej)
Warstwa: oba
Źródło: README: „2: 1 + próg pewności OSOBA 0.2 + okna półkrokowe”
Warunki wstępne: zainstalowany Podstawowy.
Kroki: jak S-WSP-10 z `poziom=2` oraz osobno na T-ODMIANY.
Oczekiwany stan końcowy: wszystkie ciągi z S-WSP-10 nieobecne. W T-ODMIANY „Jan Kowalski”, „Jana Kowalskiego”, „Kowalskiemu” mają ten sam numer osoby
`[OSOBA_1_Fk]` (różne `Fk` dla różnych form), „Maria Wiśniewska/Marii Wiśniewskiej/Wiśniewska” wspólny numer `[OSOBA_2_...]`,
„Piotr Kowalski” **inny** numer niż Jan Kowalski. Wynik nie zawiera żadnego fragmentu nazwiska w postaci jawnej.
Rodzaj: pozytywny

### S-WSP-12: poziom 3 (Najdokładniej) z samym pakietem Podstawowym
Warstwa: oba
Źródło: README: Podstawowy „pełne działanie na wszystkich poziomach”; Rozszerzony „na poziomie Najdokładniej rozpoznaje dodatkowo IP, SWIFT i loginy”
Warunki wstępne: zainstalowany tylko Podstawowy.
Kroki: 1. Ustaw suwak na 3. 2. Ukryj T-PISMO. 3. Ukryj T-ROZSZERZONY.
Oczekiwany stan końcowy: poziom 3 jest **dostępny** (suwak pozwala go wybrać, `poziomy_dostepne` zawiera 3). T-PISMO ukryty jak na poziomie 2.
W T-ROZSZERZONY adres IP `192.168.10.15` i karta `4111 1111 1111 1111` ukryte (wykrywa je już Podstawowy: `[IP_1]`, `[KARTA_1]`),
natomiast `stefan_wodorost` (LOGIN) i `BREXPLPW` (SWIFT) **mogą** zostać jawne, bo to typy Rozszerzonego.
NIEJASNE: czy GUI w tej sytuacji ostrzega, że login i SWIFT nie będą wykrywane bez pakietu Rozszerzonego? Dokumentacja tego nie mówi.
Rodzaj: brzegowy

### S-WSP-13: poziom 3 z pakietem Rozszerzonym
Warstwa: oba
Źródło: KAMIENIE K7b: „Rozszerzony… poziom 3: dodatkowo IP, kody SWIFT i loginy”
Warunki wstępne: zainstalowane oba pakiety.
Kroki: ukryj T-ROZSZERZONY i T-PISMO na poziomie 3.
Oczekiwany stan końcowy: w wyniku `[LOGIN_1]`, `[SWIFT_1]`, `[IP_1]`, `[KARTA_1]`; nie ma `stefan_wodorost`, `BREXPLPW`, `192.168.10.15`, `4111…`.
OSOBA i typy regułowe w T-PISMO takie same jak bez Rozszerzonego (warunek identyczności z `WYNIK-K7.md`): te same liczby w bloku „Ukryte dane”.
Rodzaj: pozytywny

### S-WSP-14: poziom poza zakresem w API
Warstwa: API
Źródło: LLD §12: „`poziom` 1-3”
Warunki wstępne: zainstalowany Podstawowy.
Kroki: `POST /api/ukryj` z `poziom=0`, `poziom=4`, `poziom=abc`.
Oczekiwany stan końcowy: odpowiedź 4xx (nie 500, nie wynik „domyślnym poziomem”) z czytelnym komunikatem o dozwolonym zakresie.
NIEJASNE: dokładny kod (400 czy 422) nie jest podany w dokumentacji; sprawdzamy tylko, że jest 4xx i żaden tekst nie został przetworzony.
Rodzaj: negatywny

### S-WSP-15: tekst bez danych osobowych
Warstwa: oba
Źródło: HLD §4.1: „UI pokazuje R95 z kalibracji (nie średnią pewność)”; LLD §11: wskaźnik procentowy usunięty
Warunki wstępne: zainstalowany Podstawowy.
Kroki: ukryj T-CZYSTY na poziomach 1, 2 i 3.
Oczekiwany stan końcowy: HTTP 200, treść wyniku = dopisek + niezmieniony tekst (słowo „wiśnie” **niezasłonięte**). Brak błędnego komunikatu „STOP”.
Blok „Ukryte dane” pokazuje brak wykryć (bez fałszywego komunikatu o 100% bezpieczeństwa; widoczne zastrzeżenie, że narzędzie nie gwarantuje
wykrycia wszystkiego).
Rodzaj: brzegowy

### S-WSP-16: homonimy i nazwiska-rzeczowniki
Warstwa: API
Źródło: PLAN T0.2: homonimy „Róża”, „Wiśniewski” vs „wiśnie”, „Kowal”, „Nowak”
Warunki wstępne: zainstalowany Podstawowy.
Kroki: ukryj `Róża rośnie w ogrodzie. Pani Róża Wiśniewska kupiła wiśnie od kowala. Pan Kowal odebrał paczkę.` na poziomie 2.
Oczekiwany stan końcowy: „Róża Wiśniewska” zasłonięte jako osoba. „wiśnie”, „kowala” (rzeczownik) i „Róża rośnie” (kwiat) nie zasłonięte jako osoba.
„Pan Kowal” zasłonięty jako osoba.
NIEJASNE: dokumentacja nie rozstrzyga zachowania na pojedynczym „Róża” bez nazwiska; sprawdzamy, że wynik jest deterministyczny (dwa przebiegi identyczne).
Rodzaj: brzegowy

### S-WSP-17: pismo urzędowe nie kończy się blokadą kontroli (zgłoszenie właściciela)
Warstwa: oba
Źródło: todo 23:55: „STOP: tego dokumentu nie wolno wysyłać… Ponowne sprawdzenie znalazło: 1 osoba”, „nie zmienia się zupełnie nic”
Warunki wstępne: zainstalowane oba pakiety; wersja EXE, na której zgłoszono błąd, oraz wersja web.
Kroki: 1. Wklej T-PISMO. 2. Poziom 2, potem 3. 3. „Ukryj dane”. 4. Powtórz z własnym pismem urzędowym z imionami, nazwiskami w odmianie i adresem (fikcyjnym).
Oczekiwany stan końcowy: wynik **zawiera** znaczniki zamiast danych (nie „zupełnie nic nie zmienione”). Komunikat „STOP” nie pojawia się dla poprawnie
zanonimizowanego dokumentu. Jeśli kontrola jednak coś znajdzie, GUI wskazuje **które** miejsce (fragment lub numer akapitu), a nie samo „1 osoba”,
i nie wynik pozostaje jawny tylko dlatego, że blokada zasłoniła podgląd.
Rodzaj: pozytywny (regresja)

### S-WSP-18: dwukrotne ukrycie tego samego tekstu daje ten sam wynik
Warstwa: API
Źródło: LLD §5: „Deterministyczne niezależnie od kolejności wejścia”
Warunki wstępne: zainstalowany Podstawowy.
Kroki: 1. `POST /api/ukryj` T-PISMO poziom 2 dwa razy. 2. Porównaj treść wyniku (bez dopisku i `identyfikatora`).
Oczekiwany stan końcowy: identyczny układ znaczników i te same numery; `identyfikator` zadania różny między wywołaniami.
Rodzaj: brzegowy

### S-WSP-19: pusty tekst i same białe znaki
Warstwa: oba
Źródło: LLD §12: pole `tekst` albo `plik`
Warunki wstępne: zainstalowany Podstawowy.
Kroki: 1. GUI: kliknij „Ukryj dane” z pustym polem i bez pliku. 2. API: `POST /api/ukryj` z `tekst=""`, z `tekst="   "`, bez pól `tekst` i `plik`.
Oczekiwany stan końcowy: brak 500; GUI wyświetla komunikat o potrzebie wklejenia tekstu albo wyboru pliku (komunikat w `aria-live`), API zwraca 4xx.
NIEJASNE: czy tekst złożony z samych spacji ma dać wynik (z samym dopiskiem), czy odmowę 4xx? Dokumentacja milczy.
Rodzaj: negatywny

### S-WSP-20: tekst z polskimi znakami, formatowaniem i znakami specjalnymi
Warstwa: API
Źródło: LLD §2: zakresy liczone w znakach segmentu
Warunki wstępne: zainstalowany Podstawowy.
Kroki: ukryj `Łukasz Żółć-Ćwikła (ur. 01.02.1990) mieszka przy al. Niepodległości 10 m. 3, 02-626 Warszawa. 📞 +48 601 234 567` poziom 2 i wynik przywróć.
Oczekiwany stan końcowy: dane ukryte, znaczniki na właściwych pozycjach (nie przesunięte o emotikon/polskie znaki), przywrócenie bajt w bajt (zob. S-WSP-31).
Rodzaj: brzegowy

---

## 3. Wynik, kopiowanie, pobieranie

### S-WSP-21: wynik nie zawiera żadnego oryginału (kontrola niezależna)
Warstwa: API
Źródło: HLD §2.6: „kontrola zapisu ZAWSZE”; KAMIENIE K3b: „surowy skan każdej części ZIP”
Warunki wstępne: zainstalowany Podstawowy.
Kroki: 1. `POST /api/ukryj` z T-PISMO, poziomy 1/2/3. 2. Rozpakuj odpowiedź ZIP. 3. Sprawdź `grep -a` na każdym oryginalnym ciągu w pliku wyniku, w pliku `.nwidka`, w nagłówkach `X-Niewidka-*`.
Oczekiwany stan końcowy: odpowiedź `application/zip` z dokładnie dwoma plikami: wynik oraz `.nwidka`. Żaden oryginalny ciąg nie występuje w wyniku **ani w nagłówkach**
(nagłówki zawierają tylko `r95`, `ostrzezenia`, `statystyki`, `identyfikator`). Plik `.nwidka` nie zawiera oryginałów w postaci jawnej (grep -a pusty; szyfrowany AES-256-GCM). Nagłówek `Cache-Control: no-store`.
Rodzaj: pozytywny

### S-WSP-22: nazwa pliku wyniku nie zdradza oryginalnej nazwy
Warstwa: oba
Źródło: HLD §4.10: „ZANONIMIZOWANY_<krótki-id>.<ext>”
Warunki wstępne: zainstalowany Podstawowy.
Kroki: wgraj plik `Pismo_Jan_Kowalski_44051401359.txt` (treść T-PISMO), ukryj.
Oczekiwany stan końcowy: pobrany wynik ma nazwę `ZANONIMIZOWANY_<krótki-id>.txt` i nie zawiera „Kowalski”, „Jan” ani numeru PESEL.
`<krótki-id>` równa się `identyfikator` zadania (spójność z mapą).
Rodzaj: pozytywny

### S-WSP-23: kopiowanie wyniku
Warstwa: GUI
Źródło: index.html: przycisk „Kopiuj” w bloku „Podgląd tekstu”
Warunki wstępne: wykonane ukrycie tekstu wklejonego (S-WSP-10).
Kroki: 1. Kliknij „Kopiuj”. 2. Wklej do pustego pola (np. nowej karty/Notatnika). 3. Porównaj ze „Podglądem tekstu”.
Oczekiwany stan końcowy: schowek zawiera dokładnie tekst z podglądu (z dopiskiem i znacznikami), bez oryginałów. Użytkownik dostaje potwierdzenie (komunikat/zmiana
etykiety w `aria-live`).
NIEJASNE: czy „Kopiuj” kopiuje także dopisek „ZANONIMIZOWANO…” (jest w wyniku) czy tylko sam tekst? Zakładamy cały wynik.
Rodzaj: pozytywny

### S-WSP-24: kopiowanie odmówione przez przeglądarkę
Warstwa: GUI
Źródło: dostępność i brak ciszy (HLD §4.1: nic nie „cicho”)
Warunki wstępne: wynik widoczny; uprawnienie schowka zablokowane w przeglądarce (OKNO: brak dostępu do schowka).
Kroki: kliknij „Kopiuj”.
Oczekiwany stan końcowy: widoczny komunikat o niepowodzeniu kopiowania i wskazówka (zaznacz i skopiuj ręcznie); przycisk nie sygnalizuje sukcesu.
Rodzaj: negatywny

### S-WSP-25: pobranie wyniku (TXT) i mapy
Warstwa: oba
Źródło: index.html: „Pobierz dokument z ukrytymi danymi”, „Pobierz mapę (.nwidka)”, „Zachowaj mapę”
Warunki wstępne: wykonane ukrycie wklejonego tekstu.
Kroki: 1. Kliknij „Pobierz dokument z ukrytymi danymi”. 2. Kliknij „Pobierz mapę (.nwidka)”. 3. Otwórz pobrany tekst.
Oczekiwany stan końcowy: pobrane dwa pliki: `ZANONIMIZOWANY_<id>.txt` (treść zgodna z podglądem) i `<id>.nwidka` (niepusty, zaczyna się bajtami `NWID`). Widoczny tekst „Zachowaj mapę… To jedyny klucz do oryginału”.
W OKNO pobranie zapisuje pliki lokalnie (okno zapisu albo katalog Pobrane), bez błędu.
NIEJASNE: gdzie dokładnie WebView2 zapisuje pobrane pliki (dialog zapisu czy folder domyślny)? Dokumentacja tego nie opisuje.
Rodzaj: pozytywny

### S-WSP-26: pliki wyniku i mapy nie są dostępne bez wcześniejszego ukrycia
Warstwa: GUI
Źródło: index.html: bloki `hidden` do czasu wyniku
Warunki wstępne: świeżo załadowana strona.
Kroki: 1. Otwórz stronę. 2. Sprawdź widoczność sekcji „Gotowe…”, „Pobierz pliki”, „Podgląd tekstu”.
Oczekiwany stan końcowy: sekcja wyniku, przyciski pobrania i „Kopiuj” są ukryte (`hidden`) i nieosiągalne klawiaturą do momentu wykonania ukrycia.
Rodzaj: brzegowy

### S-WSP-27: ostrzeżenia kontroli wyświetlone przy wyniku
Warstwa: GUI
Źródło: index.html: „Uwaga: sprawdź te miejsca”; LLD §11
Warunki wstępne: dokument, dla którego kontrola zgłasza ostrzeżenie (np. tekst z nietypowo zapisaną daturą/numerem, którego reguły nie pokrywają).
Kroki: ukryj dokument i obejrzyj blok ostrzeżeń.
Oczekiwany stan końcowy: blok „Uwaga: sprawdź te miejsca” z listą konkretnych fragmentów/typów; blok „Szacowane ryzyko pominięcia” z liczbą R95
z etykietą „dokładność na korpusie wzorcowym”; **brak** procentowego „wskaźnika dokumentu”.
NIEJASNE: dokumentacja nie podaje przykładu wejścia, które pewnie wywołuje ostrzeżenie; wymagane uzgodnienie próbki z właścicielem.
Rodzaj: pozytywny

---

## 4. Przywracanie

### S-WSP-28: przywrócenie wklejonego tekstu bajt w bajt
Warstwa: oba
Źródło: KAMIENIE K4: „ukryj → przywróć odtwarza dane zastąpione znacznikami”
Warunki wstępne: zainstalowany Podstawowy; klucz mapy skonfigurowany.
Kroki: 1. Ukryj T-PISMO (poziom 2). 2. Pobierz wynik i mapę. 3. Zakładka *Przywróć dane*: wskaż wynik (.txt) i mapę (.nwidka). 4. „Przywróć dane”. 5. Pobierz przywrócony dokument.
Oczekiwany stan końcowy: HTTP 200 z `/api/przywroc`; blok „Nie wszystko wróciło idealnie” **nie** pojawia się; po usunięciu dopisku
przywrócony tekst jest **identyczny bajt w bajt** z T-PISMO (`cmp`). Lista rozbieżności pusta.
NIEJASNE: czy przywrócony plik zachowuje dopisek „ZANONIMIZOWANO…”, czy go usuwa? Porównanie bajt w bajt zakłada usunięcie dopisku.
Rodzaj: pozytywny

### S-WSP-29: przywrócenie po przestawieniu zdań i zmianie przez „zewnętrzne AI”
Warstwa: API
Źródło: LLD §7/§8: przywracanie po parze (oznaczenie, wariant), niezależne od pozycji
Warunki wstępne: wynik i mapa z S-WSP-28.
Kroki: 1. Przestaw kolejność zdań w wyniku i usuń jedno zdanie. 2. `POST /api/przywroc` (zmieniony wynik + mapa).
Oczekiwany stan końcowy: 200; każdy znacznik obecny w tekście zamieniony na właściwą formę powierzchniową; usunięte zdanie zgłoszone na liście rozbieżności
(brak wystąpień), brak 500.
Rodzaj: brzegowy

### S-WSP-30: mapa z innego dokumentu (odmowa)
Warstwa: oba
Źródło: LLD §8: „niezgodny albo nieznany identyfikator = BladMapy (422)”
Warunki wstępne: dwa niezależne ukrycia: A (T-PISMO) i B (T-ODMIANY), oba z własnymi mapami.
Kroki: 1. W *Przywróć dane* wskaż wynik A i mapę B. 2. „Przywróć dane”. 3. API: ten sam układ do `POST /api/przywroc`.
Oczekiwany stan końcowy: HTTP **422**. GUI pokazuje czytelny komunikat, że dokument i mapa nie pochodzą z tego samego ukrywania. Brak pobrania, żaden
tekst z danymi osoby B nie pojawia się w wyniku A.
Rodzaj: negatywny

### S-WSP-31: uszkodzona i obcy plik jako mapa
Warstwa: API
Źródło: LLD §15: „zła/uszkodzona mapa, zły tag GCM, wersja → BladMapy 422”
Warunki wstępne: wynik z S-WSP-28.
Kroki: `POST /api/przywroc` z (a) mapą z odwróconym jednym bajtem, (b) plikiem tekstowym podanym jako mapa, (c) pustym plikiem mapy, (d) mapą o zmienionym nagłówku wersji.
Oczekiwany stan końcowy: 422 w każdym przypadku, bez 500 i bez prób naprawy; treść błędu nie zawiera danych z mapy ani śladu stosu.
Rodzaj: negatywny

### S-WSP-32: przywracanie bez klucza mapy
Warstwa: API
Źródło: LLD §8/§15: „brak klucza = BrakKlucza / 500, bez fallbacku”
Warunki wstępne: wynik i mapa z S-WSP-28; klucz usunięty z keyringa/pliku (`NIEWIDKA_KLUCZ_PLIK` wskazuje nieistniejący plik).
Kroki: `POST /api/przywroc`.
Oczekiwany stan końcowy: błąd jawny o braku klucza (kod 500 wg LLD, komunikat po polsku bez ujawniania ścieżek ani sekretów); serwer nie generuje cicho nowego klucza.
Rodzaj: negatywny

### S-WSP-33: przywracanie przy braku jednego z plików
Warstwa: oba
Źródło: index.html: pola `required` w *Przywróć dane*
Warunki wstępne: zakładka *Przywróć dane*.
Kroki: 1. Kliknij „Przywróć dane” bez plików. 2. Z samym wynikiem. 3. Z samą mapą. 4. API: brak pola `mapa` / `wynik`.
Oczekiwany stan końcowy: GUI nie wysyła żądania, wyświetla komunikat, który plik jest potrzebny (komunikat w `aria-live`); API zwraca 4xx.
Rodzaj: negatywny

---

## 5. Pliki: DOCX, formaty, rozmiary

### S-WSP-34: plik DOCX (ukryj i przywróć)
Warstwa: oba
Źródło: KAMIENIE K3: adapter DOCX; zakres MVP „wklejony tekst + TXT + DOCX”
Warunki wstępne: wzorcowy DOCX (`narzedzia/generator_dokumentow.py`): akapity, tabela, nagłówek/stopka z nazwiskiem, komentarz, śledzona zmiana, metadane autora; dane z T-PISMO rozbite na kilka runów (pogrubienie w środku nazwiska).
Kroki: 1. Wybierz plik. 2. Poziom 2. 3. „Ukryj dane”. 4. Otwórz pobrany wynik w edytorze. 5. Przywróć z mapą.
Oczekiwany stan końcowy: wynik `ZANONIMIZOWANY_<id>.docx` otwiera się bez błędu, znaczniki na pozycjach danych także w tabeli i pogrubieniu. **Brak** komentarzy, nagłówków/stopek z danymi,
metadanych autora, miniatury i śledzonych zmian w pakiecie ZIP DOCX. Żaden oryginalny ciąg nie występuje w żadnej części ZIP (`unzip -p … | grep -a`). Przywrócony plik otwiera się
i zawiera dane zastąpione znacznikami w oryginalnej formie; usunięte komentarze/metadane nie wracają (zgodnie z dopiskiem).
Rodzaj: pozytywny

### S-WSP-35: DOCX z makrem lub osadzonym obiektem
Warstwa: oba
Źródło: LLD §9: „Blokada: makra VBA, osadzone obiekty → 422 z listą”
Warunki wstępne: plik `.docx` (lub `.docm` zmieniony na `.docx`) z `vbaProject.bin`; drugi z osadzonym obiektem OLE.
Kroki: wgraj każdy i kliknij „Ukryj dane”.
Oczekiwany stan końcowy: HTTP **422**, komunikat z listą nieobsługiwanych elementów (makra / osadzony obiekt). Brak pliku do pobrania, brak częściowego wyniku.
Rodzaj: negatywny

### S-WSP-36: DOCX z obrazem
Warstwa: oba
Źródło: index.html: „Obrazy w dokumentach… są usuwane”; LLD §9 polityka obrazów
Warunki wstępne: DOCX ze skanem podpisu (obraz) i tekstem z danymi.
Kroki: ukryj plik.
Oczekiwany stan końcowy: w wyniku nie ma obrazów (`word/media/` pusty lub brak odwołań), tekst zanonimizowany; GUI informuje o usunięciu obrazów (ostrzeżenie), nie przemilcza.
NIEJASNE: dokumentacja dopuszcza dwie polityki (usuń albo zostaw z ostrzeżeniem), a tekst w `index.html` mówi o usuwaniu. Zakładamy usuwanie z ostrzeżeniem.
Rodzaj: brzegowy

### S-WSP-37: nieobsługiwany format pliku
Warstwa: oba
Źródło: LLD §15: „nieznany format → 415 + lista obsługiwanych”; index.html: „Obsługuję pliki .txt i .docx”
Warunki wstępne: pliki `.pdf`, `.xlsx`, `.odt`, `.pptx`, `.rtf`, `.exe` (rozszerzenie), oraz plik `.docx` będący w rzeczywistości PNG.
Kroki: API: `POST /api/ukryj` z każdym plikiem. GUI: spróbuj wybrać plik .pdf (przeciągnij na strefę).
Oczekiwany stan końcowy: HTTP **415** z listą obsługiwanych formatów (txt, docx); dla zepsutego `.docx` kod 4xx (415 lub 422), nigdy 500. GUI pokazuje komunikat, że format jest nieobsługiwany,
i wskazuje .txt i .docx; nie ukrywa tekstu z pliku nieobsługiwanego.
Rodzaj: negatywny

### S-WSP-38: za duży plik
Warstwa: oba
Źródło: LLD §16: „plik ≤ 25 MB… limity sprawdzane przed buforowaniem”; index.html: „maksymalnie 25 MB”
Warunki wstępne: plik TXT 26 MB (wartość z `NIEWIDKA_MAX_ROZMIAR_MB`, domyślnie 25).
Kroki: GUI: wybierz plik. API: `POST /api/ukryj` z `Content-Length` > limitu.
Oczekiwany stan końcowy: HTTP **413**, odrzucenie przed zbuforowaniem treści (czas odpowiedzi krótki, pamięć serwera nie rośnie o 26 MB), komunikat z limitem. Plik 25 MB (równy limitowi) jest przyjęty.
Rodzaj: brzegowy

### S-WSP-39: wklejony tekst większy niż 1 MB
Warstwa: API
Źródło: LLD §16: „wklejony tekst ≤ 1 MB” (`NIEWIDKA_MAX_TEKST_MB`)
Warunki wstępne: zainstalowany Podstawowy.
Kroki: `POST /api/ukryj` z polem `tekst` 1,2 MB.
Oczekiwany stan końcowy: HTTP 413 z komunikatem o limicie tekstu; brak 500.
Rodzaj: brzegowy

### S-WSP-40: zip bomb w DOCX
Warstwa: API
Źródło: LLD §12/§16: „limit po dekompresji archiwów ZIP… zip bomb”
Warunki wstępne: DOCX małego rozmiaru (kilka KB), po rozpakowaniu przekraczający 200 MB.
Kroki: `POST /api/ukryj`.
Oczekiwany stan końcowy: HTTP 413 (lub 422) bez wyczerpania pamięci; serwer dalej odpowiada na `/api/stan`.
NIEJASNE: dokumentacja nie podaje, czy to 413 czy 422 dla przekroczenia po dekompresji (tabela §15 zbiorczo „413 przed buforowaniem albo po dekompresji”). Przyjęto 413.
Rodzaj: negatywny

### S-WSP-41: plik TXT w UTF-8 z BOM i w innym kodowaniu
Warstwa: API
Źródło: KAMIENIE K3: „TXT (segment pojedynczy, BOM tolerowany)”
Warunki wstępne: T-PISMO zapisany jako UTF-8 z BOM; drugi plik w Windows-1250.
Kroki: ukryj oba.
Oczekiwany stan końcowy: UTF-8 z BOM przetworzony jak bez BOM (dane ukryte). Dla Windows-1250 albo poprawne przetworzenie, albo jawny błąd 415/422; nigdy zniekształcony wynik, w którym dane pozostały jawne.
NIEJASNE: obsługa kodowania innego niż UTF-8 nie jest opisana w dokumentacji.
Rodzaj: brzegowy

---

## 6. Blokada kontroli i komunikaty

### S-WSP-42: blokada gdy kontrola znajdzie dane w zapisanym pliku
Warstwa: oba
Źródło: HLD §3: „nowe znaleziska blokują status »ukończony«”; LLD §10: `kontrola.blokada` domyślnie true
Warunki wstępne: `NIEWIDKA_KONTROLA_BLOKADA=true`; dokument spreparowany tak, aby ponowna kontrola znalazła dane, które pierwszy przebieg pominął (np. na poziomie 1 nietypowo zapisany numer telefonu `6O1 234 567` z literą O w roli zera po stronie kontroli rozszerzonej).
NIEJASNE: dokumentacja nie opisuje przykładowego wejścia gwarantującego rozjazd kontroli z detekcją; trzeba uzgodnić próbkę (albo wstrzyknąć detektor testowy).
Kroki: ukryj taki dokument.
Oczekiwany stan końcowy: status „ukończony” **nie** jest pokazany; komunikat „STOP: tego dokumentu nie wolno wysyłać…” (jak w zgłoszeniu 23:55) z **konkretną** listą znalezisk (typ i fragment); przyciski „Pobierz dokument…” i „Kopiuj” niedostępne
(blokada eksportu), podgląd nie pokazuje tekstu do skopiowania jako „gotowego”. API: odpowiedź bez pliku wyniku do pobrania jako „ukończony” (kod zgodny z dokumentacją błędów), treść błędu bez oryginalnych danych.
Rodzaj: negatywny

### S-WSP-43: blokada wyłączona konfiguracją
Warstwa: API
Źródło: LLD §14: `NIEWIDKA_KONTROLA_BLOKADA` = false
Warunki wstępne: jak S-WSP-42, ale `NIEWIDKA_KONTROLA_BLOKADA=false`.
Kroki: ukryj ten sam dokument.
Oczekiwany stan końcowy: wynik dostępny jako „niesprawdzony”, z ostrzeżeniami w nagłówku `X-Niewidka-ostrzezenia` i w GUI (blok „Uwaga: sprawdź te miejsca”); status nie sugeruje pełnego bezpieczeństwa.
Rodzaj: brzegowy

### S-WSP-44: dopisek nie wywołuje fałszywej blokady
Warstwa: API
Źródło: LLD §7 i §17 Gemini pkt 7: „dopisek celowo bez nawiasów kwadratowych — kontrola szuka wzorca znacznika”
Warunki wstępne: zainstalowany Podstawowy.
Kroki: ukryj T-CZYSTY i T-PISMO, dokument z dopiskiem sprawdź ponownie przez kontrolę (ukryj wynik drugi raz).
Oczekiwany stan końcowy: ani dopisek, ani znaczniki `[TYP_N]` nie są uznane za nowe dane osobowe; ponowne ukrycie wyniku nie kończy się blokadą i nie zagnieżdża znaczników.
Rodzaj: brzegowy

### S-WSP-45: dokument z danymi, które model oznacza z niską pewnością (poziom 1 a 3)
Warstwa: API
Źródło: README: poziom 2 obniża próg pewności OSOBA do 0.2 (`NIEWIDKA_PROG_OSOBA`)
Warunki wstępne: tekst z nazwiskiem w niestandardowej odmianie i kontekście (np. `Zgłoszenie złożyli państwo Szczepańscy oraz p. Bąk.`).
Kroki: ukryj na poziomach 1, 2, 3.
Oczekiwany stan końcowy: liczba ukrytych osób na poziomie wyższym ≥ liczby na niższym (nie maleje ze wzrostem poziomu); ostrzeżenia kontroli nie rosną w sposób sprzeczny z wyborem poziomu.
Rodzaj: brzegowy

---

## 7. Przełączanie poziomu i Ustawienia

### S-WSP-46: opis poziomu zmienia się z suwakiem
Warstwa: GUI
Źródło: index.html: skala „Szybko / Dokładniej / Najdokładniej” i `#opis-poziomu`
Warunki wstępne: zainstalowany Podstawowy.
Kroki: 1. Sprawdź domyślny poziom (2). 2. Strzałkami zmień suwak na 1, potem 3.
Oczekiwany stan końcowy: domyślnie poziom 2 z opisem „Wyważone: dobre do zwykłych dokumentów.”; opis zmienia się przy każdym poziomie, a `aria-valuenow` suwaka odpowiada poziomowi. Wartość wysłana w `poziom` zgadza się z pozycją suwaka.
NIEJASNE: dokumentacja nie podaje tekstów opisów dla poziomów 1 i 3. Do sprawdzenia, że istnieją i różnią się.
Rodzaj: pozytywny

### S-WSP-47: poziom 3 po usunięciu pakietu Rozszerzonego
Warstwa: oba
Źródło: README: Rozszerzony opcjonalny; Podstawowy pokrywa wszystkie poziomy
Warunki wstępne: zainstalowane oba pakiety; wynik wcześniej: `[LOGIN_1]` na poziomie 3.
Kroki: 1. *Ustawienia* → usuń Rozszerzony (potwierdź). 2. Wróć do *Ukryj dane*, poziom 3, ukryj T-ROZSZERZONY.
Oczekiwany stan końcowy: suwak nadal pozwala wybrać poziom 3 (pakiet podstawowy wystarcza); `stefan_wodorost` i `BREXPLPW` już nie są ukrywane; `[IP_1]` i `[KARTA_1]` nadal ukryte. Pamięć detektorów nie zachowuje starego stanu (cache zależy od zainstalowanych pakietów, `WYNIK-K7c.md`).
Rodzaj: brzegowy

### S-WSP-48: usunięcie pakietu podstawowego (wymaganego)
Warstwa: oba
Źródło: KAMIENIE K7b: „usuwanie z potwierdzeniem”; „suwak wyłączony bez pakietu”
Warunki wstępne: zainstalowane oba pakiety.
Kroki: 1. *Ustawienia* → „Usuń” przy Podstawowym → potwierdź. 2. Wróć do *Ukryj dane*.
Oczekiwany stan końcowy: przed usunięciem prośba o potwierdzenie (zaprzeczenie nie usuwa). Po usunięciu pojawia się ekran „Przygotowanie do pracy”, suwak wyłączony, `POST /api/ukryj` → 409 `brak_pakietu`.
NIEJASNE: czy GUI w ogóle pozwala usunąć pakiet wymagany, czy tylko ostrzega? Dokumentacja nie rozstrzyga.
Rodzaj: negatywny

### S-WSP-49: pobranie pakietu z Ustawień i anulowanie usuwania
Warstwa: GUI
Źródło: index.html: *Ustawienia*, `#lista-pakietow`, `#postep-pakietu`
Warunki wstępne: zainstalowany Podstawowy, brak Rozszerzonego.
Kroki: 1. *Ustawienia* → „Pobierz” przy Rozszerzonym. 2. Obserwuj pasek. 3. Po zakończeniu kliknij „Usuń”, w oknie potwierdzenia wybierz anuluj.
Oczekiwany stan końcowy: pasek i status (`aria-live`) aktualizują się; po pobraniu Rozszerzony „zainstalowany”; anulowanie nie usuwa pakietu. Podczas pobierania ten sam pakiet nie da się pobrać drugi raz (przycisk wyłączony albo ignorowany).
Rodzaj: pozytywny

### S-WSP-50: pobieranie pakietu przerwane zamknięciem aplikacji
Warstwa: oba
Źródło: pakiety: pobieranie atomowe, Range
Warunki wstępne: pobieranie Rozszerzonego w toku.
Kroki: 1. Zamknij aplikację. 2. Uruchom. 3. *Ustawienia*.
Oczekiwany stan końcowy: Rozszerzony nie jest „zainstalowany” (brak połówkowego pakietu uznanego za gotowy); ponowne pobranie kończy się sukcesem i zgodnym SHA-256.
Rodzaj: brzegowy

---

## 8. Bezpieczeństwo API

### S-WSP-51: brak tokenu sesji
Warstwa: API
Źródło: HLD §3 / LLD §12: „token sesji… walidacja Host/Origin”; KAMIENIE K4: „Host/Origin 403”
Warunki wstępne: serwer działa.
Kroki: wywołaj bez tokenu: `GET /api/stan`, `POST /api/ukryj`, `POST /api/przywroc`, `GET /api/pakiety`, `POST /api/pakiety`.
Oczekiwany stan końcowy: **403** na każdym punkcie `/api/*` i brak jakichkolwiek danych w treści błędu. Strona główna `/` nadal się ładuje i dostaje token wstrzyknięty w `<meta name="niewidka-token">`.
NIEJASNE: nazwa nagłówka/parametru tokenu nie jest podana w dokumentacji. Scenariusz zakłada, że token jest przekazywany tak, jak robi to `apka.js`.
Rodzaj: negatywny

### S-WSP-52: zły token sesji
Warstwa: API
Źródło: jak S-WSP-51
Warunki wstępne: serwer działa; token z poprzedniej sesji (po restarcie serwera).
Kroki: `POST /api/ukryj` ze starym tokenem; ze zmienionym ostatnim znakiem tokenu.
Oczekiwany stan końcowy: 403. Token po restarcie jest nowy (stary nie działa).
Rodzaj: negatywny

### S-WSP-53: obcy Origin
Warstwa: API
Źródło: KAMIENIE K4: „Host/Origin 403”; HLD §3
Warunki wstępne: poprawny token.
Kroki: `POST /api/ukryj` i `POST /api/przywroc` z nagłówkiem `Origin: https://zlosliwa.example`, następnie z `Origin: null`.
Oczekiwany stan końcowy: **403** („niedozwolony Origin”); treść żądania nie jest przetwarzana ani logowana. Z Originem własnej aplikacji (`http://127.0.0.1:<port>` lub adres serwera w WEB) odpowiedź 200.
Rodzaj: negatywny

### S-WSP-54: obcy nagłówek Host (DNS rebinding)
Warstwa: API
Źródło: HLD §3: „walidacja Host/Origin zamiast uwierzytelniania kont”
Warunki wstępne: poprawny token.
Kroki: `curl -H "Host: zlosliwa.example" http://127.0.0.1:<port>/api/stan -H "<token>"`.
Oczekiwany stan końcowy: 403.
NIEJASNE: dla WEB (serwer w organizacji, dostęp po nazwie DNS) dokumentacja nie określa listy dozwolonych Hostów. Do ustalenia z konfiguracją `NIEWIDKA_HOST`.
Rodzaj: negatywny

### S-OKNO-55: serwer okna nasłuchuje wyłącznie na 127.0.0.1
Warstwa: API
Źródło: HLD §4/§5: „FastAPI na 127.0.0.1”; okno: „serwer w środku na wolnym porcie 127.0.0.1”
Warunki wstępne: EXE uruchomione.
Kroki: 1. Ustal port okna. 2. `netstat`/`ss` dla procesu. 3. Z drugiego komputera w sieci połącz się z adresem IP maszyny i tym portem.
Oczekiwany stan końcowy: gniazdo tylko na `127.0.0.1`, połączenie z zewnątrz odrzucone.
Rodzaj: negatywny

### S-WSP-56: odpowiedzi API bez buforowania
Warstwa: API
Źródło: HLD §4.12: „Cache-Control: no-store na /api/*”
Warunki wstępne: poprawny token.
Kroki: wywołaj `GET /api/stan`, `POST /api/ukryj`, `POST /api/przywroc`.
Oczekiwany stan końcowy: w każdej odpowiedzi `Cache-Control: no-store`; po zamknięciu karty przeglądarki treść dokumentu nie zostaje w pamięci podręcznej (sprawdzenie w narzędziach deweloperskich).
Rodzaj: pozytywny

### S-WSP-57: logi serwera bez treści dokumentów
Warstwa: API
Źródło: HLD §4.7: „logowane tylko typy/liczby encji i błędy bez treści”; LLD §12: UUID błędu
Warunki wstępne: dostęp do logu serwera (WEB: log procesu, OKNO: log aplikacji).
Kroki: 1. Wykonaj ukrycie T-PISMO. 2. Wywołaj błąd (np. uszkodzona mapa, S-WSP-31). 3. Przeszukaj log pod kątem oryginalnych ciągów.
Oczekiwany stan końcowy: log nie zawiera żadnego ciągu z T-PISMO (nazwisk, PESEL itd.), ani klucza mapy. Błędy nieobsłużone mają jedynie UUID.
Rodzaj: pozytywny

### S-WSP-58: kolejka pełna
Warstwa: API
Źródło: LLD §12/§15: „kolejka maxsize=NIEWIDKA_KOLEJKA, pełna → 503 + Retry-After”
Warunki wstępne: `NIEWIDKA_KOLEJKA=4`; jedno wolne (duże) zadanie w toku.
Kroki: wyślij równolegle ≥ 6 żądań `POST /api/ukryj`.
Oczekiwany stan końcowy: nadmiarowe żądania dostają **503** z nagłówkiem `Retry-After`; `/api/stan` w trakcie odpowiada (pętla zdarzeń nie jest zablokowana); przyjęte zadania kończą się 200.
Rodzaj: brzegowy

### S-WSP-59: timeout przetwarzania
Warstwa: API
Źródło: LLD §14/§16: `NIEWIDKA_TIMEOUT_S` domyślnie 120
Warunki wstępne: `NIEWIDKA_TIMEOUT_S=1`; duży dokument.
Kroki: `POST /api/ukryj`.
Oczekiwany stan końcowy: przekroczenie czasu daje jawny błąd (kod 5xx/503 wg implementacji), bez częściowego wyniku; kolejne żądanie po tym działa.
NIEJASNE: kod HTTP dla timeoutu nie jest podany w tabeli §15.
Rodzaj: brzegowy

---

## 9. Wersja okienkowa

### S-OKNO-60: pierwsze uruchomienie bez klucza → ekran tworzenia klucza
Warstwa: GUI
Źródło: README: „program poprosi o utworzenie klucza mapy (trafia do systemowego sejfu haseł)”; KAMIENIE K6
Warunki wstępne: Windows, Credential Manager bez wpisu `niewidka`/`mapa`, czysty `%LOCALAPPDATA%\Niewidka`.
Kroki: 1. Uruchom `Niewidka.exe`. 2. Obejrzyj okno. 3. Wykonaj akcję tworzenia klucza. 4. Sprawdź Menedżer poświadczeń.
Oczekiwany stan końcowy: przed pracą pokazuje się ekran konfiguracji klucza (tytuł okna i treść wyjaśniająca), brak dostępu do ukrywania bez klucza. Po utworzeniu wpis klucza istnieje w Credential Manager (32 B, base64), a **nie** w pliku w katalogu aplikacji ani w konfiguracji. Następne uruchomienie omija ten ekran.
Rodzaj: pozytywny

### S-OKNO-61: istniejący klucz nie jest nadpisywany
Warstwa: GUI
Źródło: KAMIENIE K6: „odmowa nadpisania”; CLAUDE.md projektu: sekrety wyłącznie z keyring
Warunki wstępne: klucz istnieje; zrób ukrycie i zachowaj mapę.
Kroki: 1. Wymuś ponowne wywołanie tworzenia klucza (ponowne uruchomienie z flagą/akcją konfiguracji, jeśli dostępna). 2. Przywróć wcześniejszą mapę.
Oczekiwany stan końcowy: odmowa nadpisania z komunikatem; wcześniejsza mapa nadal się odszyfrowuje.
NIEJASNE: czy GUI w ogóle oferuje akcję ponownego tworzenia klucza przy istniejącym kluczu? Dokumentacja wspomina tylko o odmowie nadpisania w warstwie klucza.
Rodzaj: negatywny

### S-OKNO-62: zamknięcie okna zatrzymuje serwer
Warstwa: oba
Źródło: KAMIENIE K6: „zamknięcie okna = stop serwera”
Warunki wstępne: EXE uruchomione, port okna znany.
Kroki: 1. Zamknij okno przyciskiem X. 2. Po 5 s sprawdź proces `Niewidka.exe` (`tasklist`) i port (`netstat`). 3. `GET http://127.0.0.1:<port>/api/stan`.
Oczekiwany stan końcowy: brak procesu `Niewidka.exe` i procesów potomnych (msedgewebview2 związane z aplikacją), port zwolniony, `curl` kończy się odmową połączenia.
Rodzaj: pozytywny

### S-OKNO-63: zamknięcie okna w trakcie przetwarzania i pobierania pakietu
Warstwa: oba
Źródło: KAMIENIE K6 / pakiety atomowe
Warunki wstępne: trwa ukrywanie dużego dokumentu albo pobieranie pakietu.
Kroki: zamknij okno.
Oczekiwany stan końcowy: proces kończy się (nie wisi), brak plików tymczasowych z treścią dokumentu w `%TEMP%` i katalogu aplikacji, pobierany pakiet nie jest widoczny jako zainstalowany.
Rodzaj: brzegowy

### S-OKNO-64: wolny port i druga instancja
Warstwa: oba
Źródło: KAMIENIE K6: „wolny port albo NIEWIDKA_PORT”
Warunki wstępne: port 8390 zajęty przez inny proces; druga kopia EXE.
Kroki: 1. Uruchom EXE przy zajętym 8390. 2. Uruchom drugą instancję. 3. Uruchom z `NIEWIDKA_PORT` na zajęty port.
Oczekiwany stan końcowy: pierwsza instancja wybiera inny wolny port i działa (ukrywanie 200). Druga instancja albo działa na własnym porcie, albo pokazuje jawny komunikat (bez cichego zawieszenia). Z zajętym `NIEWIDKA_PORT` widoczny komunikat o błędzie, okno nie zostaje puste.
NIEJASNE: czy dozwolone są dwie jednoczesne instancje? Dokumentacja tego nie rozstrzyga.
Rodzaj: brzegowy

### S-OKNO-65: pełny przebieg w oknie (ukryj → pobierz → przywróć)
Warstwa: GUI
Źródło: README „Pobierz gotowy program”, krok 3-5; KAMIENIE K6: „startuje dwuklikiem i przechodzi pełny przepływ lokalnie”
Warunki wstępne: EXE rozpakowany, klucz utworzony, pakiet Podstawowy zainstalowany.
Kroki: 1. Wklej T-PISMO. 2. Ukryj na poziomie 2. 3. Pobierz wynik i mapę. 4. *Przywróć dane*. 5. Pobierz przywrócony dokument.
Oczekiwany stan końcowy: wynik bez oryginałów (S-WSP-10), przywrócony tekst identyczny z T-PISMO. To właśnie zgłoszenie 23:55 („nie zmienia się zupełnie nic”) musi zakończyć się wynikiem ze znacznikami.
Rodzaj: pozytywny (regresja)

### S-OKNO-66: brak WebView2 lub awaria silnika okna
Warstwa: GUI
Źródło: KAMIENIE K6: „awarie widoczne”
Warunki wstępne: maszyna bez Microsoft Edge WebView2 Runtime (lub z zablokowanym).
Kroki: uruchom EXE.
Oczekiwany stan końcowy: użytkownik dostaje jawny komunikat o braku komponentu i wskazówkę, co zainstalować; proces się kończy (brak ukrytych procesów w tle).
NIEJASNE: dokumentacja nie określa, czy WebView2 jest dołączony do paczki, czy wymagany z systemu.
Rodzaj: negatywny

### S-OKNO-67: aplikacja nie łączy się z internetem poza pobieraniem pakietów
Warstwa: oba
Źródło: README: „Potem program nie łączy się z internetem”; HLD §1: zero ruchu sieciowego podczas przetwarzania
Warunki wstępne: zainstalowany Podstawowy; monitor połączeń (np. `netstat -b`, firewall z logowaniem) lub zablokowany dostęp wychodzący.
Kroki: 1. Wykonaj S-OKNO-65 przy zablokowanym ruchu wychodzącym. 2. Sprawdź listę połączeń procesu.
Oczekiwany stan końcowy: pełny przepływ działa, brak połączeń poza `127.0.0.1`.
Rodzaj: pozytywny

### S-OKNO-68: aktualizacja zachowuje modele i mapy
Warstwa: GUI
Źródło: README: „Aktualizacja: pobierz nowy ZIP i rozpakuj w to samo miejsce. Pobrane modele zostają”
Warunki wstępne: zainstalowane pakiety, klucz, wcześniejsza mapa.
Kroki: 1. Rozpakuj nowy ZIP na stary katalog. 2. Uruchom. 3. Wykonaj przywrócenie starą mapą.
Oczekiwany stan końcowy: bez ponownego pobierania modeli, bez nowego klucza, przywrócenie starą mapą działa.
Rodzaj: pozytywny

---

## 10. Wersja web (serwer w organizacji)

### S-WEB-69: uruchomienie serwera i dostęp przeglądarką
Warstwa: oba
Źródło: HLD §5: „FastAPI na 127.0.0.1 + statyczne web/”; LLD §14: `NIEWIDKA_HOST/PORT`
Warunki wstępne: `python -m niewidka` (albo komenda uruchomienia z README/pakietu) z `NIEWIDKA_PORT=8800`.
NIEJASNE: dokładna komenda startu serwera WEB nie jest podana w README (opisuje EXE i budowę); wymagana do ustalenia przed przebiegiem.
Kroki: 1. Uruchom serwer. 2. W przeglądarce otwórz adres. 3. `GET /api/stan` z tokenem.
Oczekiwany stan końcowy: strona ładuje się z ekranem *Ukryj dane*, nagłówek „Na tym urządzeniu. Twoje dane nie opuszczają tego komputera.”, stopka z numerem wersji, `/api/stan` 200 z wersją, listą poziomów i limitami.
Rodzaj: pozytywny

### S-WEB-70: tryb „Na serwerze organizacji” jest poza MVP
Warstwa: GUI
Źródło: HLD §3 i §6: tryb serwerowy to v1 (uwierzytelnianie, HTTPS, klucz per dokument)
Warunki wstępne: serwer WEB na adresie innym niż `127.0.0.1`.
Kroki: wejdź na stronę z innego komputera w sieci.
Oczekiwany stan końcowy: ze względu na to, że uwierzytelnianie kont nie wchodzi do MVP, dostęp spoza `127.0.0.1` jest odrzucony (403 Host/Origin) albo wymaga jawnej konfiguracji, a UI **nie** zawiera przełącznika trybu „Na serwerze organizacji”.
NIEJASNE: zlecenie 23:36 wymaga „web (serwer w organizacji)”, a HLD zawęża MVP do localhost i przenosi tryb serwerowy do v1. Wymagana decyzja, czy test serwerowy wchodzi do bieżącego przebiegu.
Rodzaj: negatywny

### S-WEB-71: dwóch użytkowników równolegle i izolacja sesji
Warstwa: API
Źródło: HLD §4.6: „oryginały tylko w RAM, jeden proces inferencji”; LLD §12
Warunki wstępne: serwer WEB, dwa klienty (dwie przeglądarki).
Kroki: obaj ukrywają różne dokumenty równocześnie, potem każdy przywraca własny wynik własną mapą.
Oczekiwany stan końcowy: każdy dostaje własny wynik (inne `identyfikator`), nie pojawiają się dane drugiego użytkownika, kolejka obsługuje oba żądania (200 albo 503 z `Retry-After`).
NIEJASNE: w MVP klucz mapy jest jeden na instancję (bez kont), więc przywrócenie cudzej mapy tym samym kluczem działa technicznie. Dokumentacja uznaje to za ograniczenie v1 (Astra pkt 4).
Rodzaj: brzegowy

### S-WEB-72: czyszczenie sesji w przeglądarce
Warstwa: GUI
Źródło: PLAN T5.2: „czyszczenie sesji w UI (Astra pkt 12)”
Warunki wstępne: wynik widoczny.
Kroki: 1. Przełącz zakładkę na *Przywróć dane* i wróć. 2. Odśwież stronę (F5). 3. Kliknij „Wklej tekst zamiast tego” po wyborze pliku.
Oczekiwany stan końcowy: po odświeżeniu pole tekstu, podgląd i przyciski pobrania są puste/ukryte (treść dokumentu nie zostaje w stronie, `localStorage` i `sessionStorage` nie zawierają danych). Po „Wklej tekst zamiast tego” znika nazwa pliku i wraca pole tekstowe.
Rodzaj: pozytywny

### S-WEB-73: przeciągnięcie pliku na strefę
Warstwa: GUI
Źródło: index.html: „Możesz też przeciągnąć plik tutaj”
Warunki wstępne: strona *Ukryj dane*.
Kroki: 1. Przeciągnij plik `.docx` na strefę. 2. Przeciągnij plik `.pdf`. 3. Przeciągnij kilka plików naraz.
Oczekiwany stan końcowy: `.docx` wybrany (widoczna nazwa pliku w `#nazwa-pliku`, pole tekstu zastąpione), `.pdf` odrzucony z komunikatem o formacie, wiele plików: komunikat albo wybór jednego z jasną informacją.
NIEJASNE: dokumentacja nie opisuje obsługi wielu plików naraz.
Rodzaj: brzegowy

---

## 11. Dostępność

### S-WSP-74: obsługa wyłącznie klawiaturą
Warstwa: GUI
Źródło: index.html: link „Przejdź do treści”, role `tablist/tab/tabpanel`, `aria-selected`
Warunki wstępne: strona główna, mysz odłożona.
Kroki: 1. Tab od początku strony: pierwszy fokus. 2. Przejdź przez zakładki strzałkami i wejdź do panelu. 3. Wklej tekst, ustaw suwak strzałkami, uruchom „Ukryj dane” klawiszem Enter. 4. Dojdź do „Kopiuj” i „Pobierz…”. 5. *Przywróć dane*: wybór plików klawiaturą.
Oczekiwany stan końcowy: pierwszy Tab ustawia fokus na „Przejdź do treści”, Enter przenosi do `#glowna`. Zakładki przełączają strzałkami (aktywna ma `aria-selected="true"`, nieaktywne `tabindex="-1"`), cały przepływ da się wykonać bez myszy, fokus zawsze widoczny, bez pułapki fokusu. Etykiety „Wybierz plik” aktywują pole pliku Enterem/spacją.
Rodzaj: pozytywny

### S-WSP-75: komunikaty `aria-live`
Warstwa: GUI
Źródło: index.html: `aria-live="polite"` na `#status-ukryj`, `#status-przywroc`, postępach pobierania; `aria-live="assertive"` w `#zapowiedz`
Warunki wstępne: czytnik ekranu (NVDA) albo podgląd drzewa dostępności.
Kroki: 1. Wykonaj ukrycie. 2. Wywołaj błąd (np. S-WSP-30). 3. Pobierz pakiet. 4. Kliknij „Kopiuj”.
Oczekiwany stan końcowy: postęp i wynik ukrycia ogłaszane uprzejmie (polite), błędy blokujące ogłaszane natychmiast (assertive) z treścią zrozumiałą na słuch (bez samych kodów HTTP); status ukończenia zawiera informację, ile danych ukryto; komunikat „STOP” jest ogłoszony.
Rodzaj: pozytywny

### S-WSP-76: kontrast, powiększenie i reflow
Warstwa: GUI
Źródło: index.html: `meta viewport`, `theme-color`; zrzuty K5 (1440 i 390 px)
Warunki wstępne: przeglądarka; okno WebView2 w OKNO.
Kroki: 1. Powiększ stronę do 200%/400%. 2. Zwęż do 390 px. 3. Wyłącz animacje systemowe (`prefers-reduced-motion`).
Oczekiwany stan końcowy: brak poziomego przewijania przy 400% (reflow), wszystkie przyciski osiągalne, tekst czytelny; po wyłączeniu animacji brak ruchu poza zmianą stanu.
Rodzaj: brzegowy

### S-WSP-77: etykiety pól i opisy dla technologii asystujących
Warstwa: GUI
Źródło: index.html: `<label for>`, `aria-describedby`
Warunki wstępne: drzewo dostępności w narzędziach deweloperskich.
Kroki: sprawdź pola `#tekst`, `#plik`, `#poziom`, `#plik-wynik`, `#plik-mapa` i wszystkie przyciski.
Oczekiwany stan końcowy: każde pole ma nazwę dostępną zgodną z widoczną etykietą (np. „Wklej tekst do sprawdzenia”, „Jakość wykrywania danych”, „Mapa (.nwidka)”), suwak ma opis (`#opis-poziomu`), logo ma `alt="Niewidka"`, nagłówki układają się w hierarchię h1, h2, h3 bez przeskoków.
Rodzaj: pozytywny

### S-WSP-78: sekcja „Jak to działa” i zastrzeżenie
Warstwa: GUI
Źródło: index.html: `<details id="jak-to-dziala">`, „Ważne zastrzeżenie”
Warunki wstępne: strona *Ukryj dane*.
Kroki: 1. Rozwiń „Jak to działa” klawiaturą. 2. Sprawdź listę typów danych (`#lista-typow-danych`). 3. Rozwiń „Szczegóły techniczne”.
Oczekiwany stan końcowy: rozwija się i zwija klawiszami Enter/spacja; lista typów jest **niepusta** (uzupełniana z API/stanu: m.in. osoby, PESEL, NIP, REGON, adresy, telefony, e-maile, IBAN, numery dokumentów, daty); widoczne zastrzeżenie, że narzędzie nie gwarantuje wykrycia wszystkiego; informacja o usuwaniu obrazów.
Rodzaj: pozytywny

---

## 12. Szyfrowanie mapy i klucz

### S-WSP-79: mapa jest zaszyfrowana, unikalny nonce
Warstwa: API
Źródło: HLD §4.3: „AES-256-GCM z unikalnym nonce”; LLD §8: format `NWID` + wersja + nonce(12B)
Warunki wstępne: dwa ukrycia tego samego tekstu.
Kroki: porównaj pliki `.nwidka` z obu ukryć; sprawdź pierwsze bajty i brak oryginałów (`grep -a`).
Oczekiwany stan końcowy: oba pliki zaczynają się od `NWID` i bajtu wersji, nonce (12 B) różne, szyfrogramy różne, w żadnym nie występuje jawny tekst oryginału.
Rodzaj: pozytywny

### S-WSP-80: mapa bez właściwego klucza nie jest odszyfrowywana
Warstwa: API
Źródło: KAMIENIE K4: „mapa bez klucza nie odszyfrowuje”
Warunki wstępne: mapa z ukrycia A; instancja z innym kluczem (nowy plik klucza).
Kroki: `POST /api/przywroc` na instancji z innym kluczem.
Oczekiwany stan końcowy: 422 (zły tag GCM) bez prób naprawy i bez ujawnienia fragmentu mapy.
Rodzaj: negatywny

### S-WSP-81: klucz z pliku wskazanego zmienną środowiskową
Warstwa: API
Źródło: README/HLD: „keyring albo plik wskazany zmienną środowiskową”; LLD §8: 0600 tylko POSIX
Warunki wstępne: WEB na Linuksie; `NIEWIDKA_KLUCZ_PLIK` na plik base64 32 B.
Kroki: 1. Uruchom z kluczem o uprawnieniach 0600. 2. Uruchom z uprawnieniami 0644. 3. Uruchom z plikiem o długości różnej od 32 B.
Oczekiwany stan końcowy: 0600 działa; 0644 jest odrzucony z jasnym błędem (na POSIX); zła długość klucza daje jawny błąd. Klucz nigdzie nie wypisany w logach i odpowiedziach.
Rodzaj: brzegowy

---

## 13. Odporność i degradacja

### S-WSP-82: błąd detektora (fail-closed)
Warstwa: API
Źródło: LLD §4/§15: „Błąd detektora = BladDetektora (fail-closed)”
Warunki wstępne: plik wagi pakietu Podstawowego uszkodzony po starcie serwera (zmiana bajtu).
Kroki: `POST /api/ukryj` poziom 2.
Oczekiwany stan końcowy: 500 (albo 409/422 z informacją o pakiecie) bez zwrócenia dokumentu przetworzonego tylko regułami; żaden wynik z częściową detekcją nie jest przedstawiony jako „ukończony”.
Rodzaj: negatywny

### S-WSP-83: serwer pozostaje żywy po serii błędów
Warstwa: API
Źródło: LLD §12: middleware UUID, pula wątków
Warunki wstępne: serwer działa.
Kroki: wyślij kolejno żądania z S-WSP-31, S-WSP-37, S-WSP-38, następnie poprawne `POST /api/ukryj`.
Oczekiwany stan końcowy: błędy 4xx bez 500, a poprawne żądanie nadal zwraca 200 z tym samym wynikiem co przed serią.
Rodzaj: brzegowy

---

## Tabela scenariuszy

| ID | Warstwa | Wersja | Rodzaj |
|---|---|---|---|
| S-WSP-01 | oba | WSP | pozytywny |
| S-WSP-02 | oba | WSP | pozytywny |
| S-WSP-03 | oba | WSP | pozytywny |
| S-WSP-04 | oba | WSP | negatywny |
| S-WSP-05 | oba | WSP | negatywny |
| S-WSP-06 | API | WSP | negatywny |
| S-OKNO-07 | oba | OKNO | negatywny |
| S-WSP-08 | oba | WSP | pozytywny |
| S-WSP-09 | oba | WSP | pozytywny |
| S-WSP-10 | oba | WSP | pozytywny |
| S-WSP-11 | oba | WSP | pozytywny |
| S-WSP-12 | oba | WSP | brzegowy |
| S-WSP-13 | oba | WSP | pozytywny |
| S-WSP-14 | API | WSP | negatywny |
| S-WSP-15 | oba | WSP | brzegowy |
| S-WSP-16 | API | WSP | brzegowy |
| S-WSP-17 | oba | WSP | pozytywny (regresja) |
| S-WSP-18 | API | WSP | brzegowy |
| S-WSP-19 | oba | WSP | negatywny |
| S-WSP-20 | API | WSP | brzegowy |
| S-WSP-21 | API | WSP | pozytywny |
| S-WSP-22 | oba | WSP | pozytywny |
| S-WSP-23 | GUI | WSP | pozytywny |
| S-WSP-24 | GUI | WSP | negatywny |
| S-WSP-25 | oba | WSP | pozytywny |
| S-WSP-26 | GUI | WSP | brzegowy |
| S-WSP-27 | GUI | WSP | pozytywny |
| S-WSP-28 | oba | WSP | pozytywny |
| S-WSP-29 | API | WSP | brzegowy |
| S-WSP-30 | oba | WSP | negatywny |
| S-WSP-31 | API | WSP | negatywny |
| S-WSP-32 | API | WSP | negatywny |
| S-WSP-33 | oba | WSP | negatywny |
| S-WSP-34 | oba | WSP | pozytywny |
| S-WSP-35 | oba | WSP | negatywny |
| S-WSP-36 | oba | WSP | brzegowy |
| S-WSP-37 | oba | WSP | negatywny |
| S-WSP-38 | oba | WSP | brzegowy |
| S-WSP-39 | API | WSP | brzegowy |
| S-WSP-40 | API | WSP | negatywny |
| S-WSP-41 | API | WSP | brzegowy |
| S-WSP-42 | oba | WSP | negatywny |
| S-WSP-43 | API | WSP | brzegowy |
| S-WSP-44 | API | WSP | brzegowy |
| S-WSP-45 | API | WSP | brzegowy |
| S-WSP-46 | GUI | WSP | pozytywny |
| S-WSP-47 | oba | WSP | brzegowy |
| S-WSP-48 | oba | WSP | negatywny |
| S-WSP-49 | GUI | WSP | pozytywny |
| S-WSP-50 | oba | WSP | brzegowy |
| S-WSP-51 | API | WSP | negatywny |
| S-WSP-52 | API | WSP | negatywny |
| S-WSP-53 | API | WSP | negatywny |
| S-WSP-54 | API | WSP | negatywny |
| S-OKNO-55 | API | OKNO | negatywny |
| S-WSP-56 | API | WSP | pozytywny |
| S-WSP-57 | API | WSP | pozytywny |
| S-WSP-58 | API | WSP | brzegowy |
| S-WSP-59 | API | WSP | brzegowy |
| S-OKNO-60 | GUI | OKNO | pozytywny |
| S-OKNO-61 | GUI | OKNO | negatywny |
| S-OKNO-62 | oba | OKNO | pozytywny |
| S-OKNO-63 | oba | OKNO | brzegowy |
| S-OKNO-64 | oba | OKNO | brzegowy |
| S-OKNO-65 | GUI | OKNO | pozytywny (regresja) |
| S-OKNO-66 | GUI | OKNO | negatywny |
| S-OKNO-67 | oba | OKNO | pozytywny |
| S-OKNO-68 | GUI | OKNO | pozytywny |
| S-WEB-69 | oba | WEB | pozytywny |
| S-WEB-70 | GUI | WEB | negatywny |
| S-WEB-71 | API | WEB | brzegowy |
| S-WEB-72 | GUI | WEB | pozytywny |
| S-WEB-73 | GUI | WEB | brzegowy |
| S-WSP-74 | GUI | WSP | pozytywny |
| S-WSP-75 | GUI | WSP | pozytywny |
| S-WSP-76 | GUI | WSP | brzegowy |
| S-WSP-77 | GUI | WSP | pozytywny |
| S-WSP-78 | GUI | WSP | pozytywny |
| S-WSP-79 | API | WSP | pozytywny |
| S-WSP-80 | API | WSP | negatywny |
| S-WSP-81 | API | WSP | brzegowy |
| S-WSP-82 | API | WSP | negatywny |
| S-WSP-83 | API | WSP | brzegowy |

## Pytania `NIEJASNE` do rozstrzygnięcia

Zestawienie scenariuszy z otwartym pytaniem (S-WSP-08, 12, 14, 16, 19, 23, 25, 27, 28, 36, 40, 41, 42, 46, 48, 51, 54, 59, 61, S-OKNO-64, 66, S-WEB-69, 70, 71, 73):
najważniejsze to (1) czy poziom 3 bez Rozszerzonego ma ostrzegać o braku loginów i SWIFT (S-WSP-12), (2) czy przywrócony plik zawiera dopisek (S-WSP-28),
(3) komenda startu serwera WEB (S-WEB-69), (4) zakres „serwera w organizacji” w bieżącym przebiegu (S-WEB-70), (5) próbka wywołująca blokadę kontroli (S-WSP-42).
