# WYNIK K7c — naprawa 11 znalezisk audytu Codex/astra #2 + uczciwy tekst kontroli

Data: 2026-10-28 (zlecenie orkiestratora 18:40; audyt: `docs/konsultacje/07-przeglad-codex-astra-2.md`).
Metoda: TDD — dla każdego punktu najpierw test odtwarzający (pada na wzorcu z audytu),
potem poprawka; commit po każdym zielonym kroku. Reużyte moduły: middleware tokenu/
Host/Origin z `api.py`, `archiwum.py`, menedżer pakietów, `scalanie` — bez nowych zależności.

Pełny bieg po naprawach: **527 passed, 1 xfailed** (`NIEWIDKA_MODELE_KATALOG=~/models/niewidka`,
79,6 s) + ruff czysty (`niewidka/ tests/ narzedzia/`). Trzy znaleziska z pełnego biegu
opisane niżej w sekcji „Znaleziska z pełnego biegu".

## Tabela 12 punktów

| # | test (RED) | poprawka | commit |
|---|---|---|---|
| 1 | `test_api.py::test_pakiet_rozszerzony_uczestniczy_w_anonimizacji_przez_api` (integracyjny, z wagami, marker `model`; instalacja przez POST /api/pakiety, bez ręcznych flag) + jednostkowe: `test_zbuduj_detektor_przekazuje_stan_pakietu_rozszerzonego`, `test_menedzer_stan_pakietu`, `test_menedzer_on_zmiana_po_kazdej_operacji` | `rdzen.zbuduj_detektor(..., pakiet_rozszerzony)`; API bierze stan z menedżera (`stan_pakietu`); zwrot `on_zmiana` czyści cache detektorów po każdej zakończonej operacji (pobranie/usunięcie/instalacja) i po odświeżeniu wykrywającym zmianę z zewnątrz | `347c580` |
| 2 | `test_detektory.py`: `test_wczytaj_bardsai_podmieniony_model_z_pustym_manifestem_odpada`, `test_wczytaj_bardsai_komplet_plikow_obowiazkowy`, `test_wczytaj_bardsai_symlink_zamiast_pliku_odpada`, `test_wczytaj_bardsai_laduje_zweryfikowane_bajty` | `pakiety.wczytaj_bajty_pakietu`: ZAUFANY `pakiety.json` wyznacza komplet i sumy (lokalny manifest nie ma głosu); symlink = odmowa | `48c3331` |
| 3 | ten sam zestaw + instalacyjna połowa w pkt 4 (`test_pobierz_...` / `test_instaluj_...`) | każdy wymagany plik czytany do pamięci RAZ: SHA z tych samych bajtów, które wracają do `ort.InferenceSession` / `Tokenizer.from_str` / `json.loads`; przy publikacji haszowane są dokładnie bajty, które zapisujemy (koniec okna sprawdź-użyj) | `48c3331` + `bd3db81` |
| 4 | `test_pakiety.py`: `test_pobierz_nie_niszczy_ofiary_przez_symlink_czesciowego`, `test_instaluj_offline_nie_niszczy_ofiary_przez_symlink`, `test_manifest_atomowo_nie_niszczy_ofiary`, `test_pobierz_odrzucca_symlink_w_sciezce_podkatalogu` | pliki tymczasowe wyłącznie `O_CREAT\|O_EXCL` (+`O_NOFOLLOW`, przy wznowieniu `O_APPEND\|O_NOFOLLOW`); symlink/reparse point w pośrednim katalogu ścieżki = odmowa (`_odrzuc_dowiazania`, `FILE_ATTRIBUTE_REPARSE_POINT` na Windows); publikacja `os.replace` (rename zastępuje podstawione dowiązanie, nie pisze przez nie); manifest atomowo | `bd3db81` |
| 5 | `test_api.py::test_get_pakiety_i_stan_wymagaja_tokenu_hosta_origin`, `test_pakiety.py::test_blad_pobierania_kontrolowany_bez_hasla_i_url`, `test_web.py::test_gety_pakietow_i_stanu_wysylaja_token` | GET `/api/pakiety` i `/api/stan` za tokenem i Host/Origin (ten sam middleware co POST); apka.js wysyła token w tych GET-ach i zostawia poprzedni stan przy odpowiedzi != ok; komunikat pobierania kontrolowany: „HTTP 503" / „błąd sieci", bez URL i tekstu wyjątku (hasło lustra nie wycieka do `postep.blad`) | `81e7fd9` |
| 6 | `test_wydanie.py::test_akcje_przypiete_do_pelnych_sha_z_komentarzem_wersji`, `test_budowa_read_publikacja_write_w_osobnym_zadaniu`, `test_workflow_jest_poprawnym_yaml` | wszystkie akcje (tylko first-party `actions/`) przypięte do pełnych SHA z komentarzem wersji (checkout v4.2.2, setup-python v5.6.0, upload-artifact v4.6.2); top-level i budowa `contents: read`, `persist-credentials: false`; publikacja w osobnym zadaniu `contents: write` przez wbudowane `gh` (softprops usunięty) | `14943e3` |
| 7 | `test_wydanie.py::test_lockfile_z_haszami_wspolny_dla_workflow_i_skryptu` | lockfile `narzedzia/wymagania-budowy.in` → `.txt` (uv, `--generate-hashes`, Windows/py3.13, ~340 pakietów z haszami SHA-256); workflow i `zbuduj_windows.ps1` instalują `pip install --require-hashes -r` z TEGO SAMEGO pliku | `14943e3` |
| 8 | `test_pakiety.py`: `test_pobierz_twardy_limit_bajtow`, `test_pobierz_limit_bajtow_przy_wznowieniu`, `test_pobierz_calkowity_limit_czasu`, `test_instaluj_z_katalogu_odrzuca_plik_inny_niz_w_katalogu`, `test_menedzer_instaluj_w_tle_anulowanie`, `test_menedzer_anuluj_pobieranie`, `test_limit_czasu_z_env` | rozmiar z katalogu pilnowany przed KAŻDYM zapisem (też `start + kawałek` przy Range i dla pliku lustra), całkowity limit czasu operacji `NIEWIDKA_PAKIETY_LIMIT_CZASU_S` (domyślnie 1800 s), anulowanie (`anuluj()`, POST akcja `anuluj`, Event sprawdzany przy każdym kawałku), instalacja offline w tle (202) z tymi samymi limitami | `01e21ba` |
| 9 | `test_pakiety.py::test_menedzer_lista_z_cache_bez_haszowania`, `test_menedzer_zmiana_z_zewnatrz_odswiezana_w_tle` | stan pakietów ZAPAMIĘTANY: pełna weryfikacja SHA przy starcie i po każdej operacji w wątku tła; `lista()/poziomy_dostepne()/brakujacy_wymagany()` czytają cache; fingerprint obecności plików (stat, bez SHA) wykrywa wgranie wag z zewnątrz i odpala odświeżenie w tle (z unieważnieniem detektorów ze starego stanu); polling UI nie generuje haszowania | `08906c5` |
| 10 | `test_pakiety.py`: `test_przekierowanie_do_loopback_odrzucone`, `..._https_na_http_poza_lustrem_odrzucone`, `..._do_sieci_prywatnej_przez_https_odrzucone` + dwa strażnicze (lustro http wewnętrzne i publiczny https dopuszczone) | `follow_redirects=False`, przekierowania prowadzone ręcznie (limit 5) z walidacją każdego kroku: tylko https, wyjątek dla hosta `NIEWIDKA_MODELE_ZRODLO` (może być http, także loopback ze scenariusza K7b); loopback/prywatne/link-local/rezerwowane (dosłowne i po DNS) poza lustrem odrzucane | `dcd9383` |
| 11 | `test_pakiety.py::test_blad_404_potem_poprawne_ponowienie`, `test_oserror_przez_strumien_kontrolowany_i_do_ponowienia`, `test_web.py::test_ui_ponawia_pobieranie_po_bledzie` | czyszczenie stanu operacji w `finally` (także OSError; weszło w przebudowę `praca()` z pkt 1), komunikat błędu przechowywany osobno (pkt 5/8), UI: przyciski zależne od aktualnego `postep.pakiet` (po błędzie włączone), ponowienie bez restartu udowodnione testem (404 → naprawa lustra → zainstalowany) | `dedfe29` |
| 12 | `test_web.py::test_kontrola_jakosci_tekst_uczciwy` | tekst wyniku: „Ponowne sprawdzenie wyniku nie znalazło danych, które program umie wykrywać. Program nie wykrywa wszystkiego, dlatego przejrzyj wynik przed wysłaniem." (bez półpauz, istniejący test pilnuje) | `413f8cb` |

## Dowód pkt 1 (polecenie: ukrycie „Kontakt na czacie: stefan_wodorost.", poziom 3, katalog jak po instalacji)

`rdzeń.ukryj` na `~/models/niewidka-pakiety-k7b` (detektor przez produktową
`zbuduj_poziom(3, katalog, pakiet_rozszerzony=<stan z menedżera>)`):

| wariant | wynik | statystyki |
|---|---|---|
| poziom 3 BEZ pakietu Rozszerzonego | `Kontakt na czacie: stefan_wodorost.` | `{}` — dokładnie objaw z audytu (i zrzutu orkiestratora) |
| poziom 3 Z pakietem Rozszerzonym | `Kontakt na czacie: [LOGIN_1].` | `{'LOGIN': 1}` |

Test integracyjny przechodzi całą ścieżkę produktu: instalacja przez POST /api/pakiety
(katalog lustra z realnymi wagami), detektory leniwe w tym samym procesie aplikacji,
invalidacja cache po instalacji — login znika bez żadnej ręcznej flagi.

## Zmiany środowiskowe (poza repo)

- `~/models/niewidka/model.onnx`: był INT8 (278 MB), zaufany `pakiety.json`
  przypina Q4 bl32 (174 MB) — zamieniony na Q4 z `bardsai-q4-bl32/`; INT8 zachowany
  w `~/models/niewidka/bardsai-int8/`. Od pkt 2/3 weryfikacja zaufanym
  katalogiem i tak odrzuciłaby INT8 (produkt = Q4).
- `~/models/niewidka-pakiety-k7b`: katalog z sesji K7b trzymał wagi przez
  **symlinki** — naprawa pkt 4 słusznie je odrzuca (symlink w katalogu modeli to
  wzorzec z audytu); zamienione na twarde dowiązania (realne pliki, ten sam i-węzeł),
  `lfm25/q4-bl32` jako realny katalog. Stan = zgodny z `pakiety.json` (hash zaświadczony).

## Znaleziska z pełnego biegu (każde naprawione osobnym commitem, `c121872`)

1. **Wyścig odświeżenia stanu (funkcjonalny, od pkt 9):** `czekaj()`/polling wychodziły,
   gdy `_w_toku` gasło, a odświeżenie stanu (pełne haszowanie po operacji) liczyło się
   dopiero potem — pierwszy detektor poziomu 3 mógł zbudować się ze STAREGO stanu
   (rozszerzony „brak") i zostać w cache do następnej operacji na pakietach.
   Naprawa: odświeżenie przed zwolnieniem flagi operacji.
2. **Kalibracja testów suwaka pod Q4:** wagi produktu są teraz Q4 bl32 z zaufanego
   `pakiety.json` (skutek pkt 2/3); Q4 na poziomie 1 wykrywa całą osobę z osoba-011
   (w próbce K2d różnicę wyznaczano na INT8), a poziomy 1 i 2 dają na korpusie 190
   identyczne wyniki OSOBA (0 różnic). Nowy różnicujący probe z korpusu: **inst-061**
   „Muzeum im. Adama Mickiewicza zaprasza." — poziom 3 (słownik imion) go łapie,
   poziom 1 nie. Testy `test_ukryj_poziom_suwa_dzialanie_detektora` (API) i
   `test_poziom3_lapie_co_poziom1_przeoczy` (rdzeń) przepisane na ten probe; progi
   KRYTERIA bez zmian.
3. **Token w testach okna:** po pkt 5 atrapa webview bierze token z meta strony głównej
   (dokładnie ten przepływ co przeglądarka); bonus: walidacja YAML wykryła, że dwukropek
   w niecytowanej nazwie kroku „Testy (bez wag: …)" unieważniałby CAŁY workflow wydania
   (istniejący błąd z K7b, NIE uruchamiany dotąd) — cytowany + test `test_workflow_jest_poprawnym_yaml`.

## Ograniczenia i notatki

- Budowa EXE na Windows NIE była robiona (zlecenie: orkiestrator zleci osobno). Lockfile
  z pkt 7 wymaga potwierdzenia biegiem budowy na Windows (rozwiązanie uv dla win/py3.13).
- Publikacja wydania: draft, dopiero po przeglądzie właściciela (decyzja 2c) — bez zmian.
- Rezydualne ryzyko przy instalacji (dokumentowane w kodzie): napastnik z prawem zapisu
  do katalogu wag wyścigu na węźle katalogu (SIMPLIFICATION komentarz w `_opublikuj`);
  pełna izolacja wymagałaby prywatnego poddrzewa na wspólnym FS.
- `pip` w workflow podnoszony przed `--require-hashes` (instalator sam w sobie nie jest
  w lockfile — konwencja; do przemyślenia przy kolejnym audycie).
