# Centralny serwer modeli (instrukcja dla administratora)

Jedna maszyna w sieci lokalnej trzyma modele i wykrywa dane osobowe, a aplikacje
użytkowników wysyłają do niej tekst przez sieć. Użytkownik nie pobiera pakietów modeli.

## Co serwer widzi, a czego nie

| Serwer widzi | Serwer NIE widzi i nie robi |
|---|---|
| tekst przesłany do wykrycia (w pamięci, na czas przetwarzania) | kluczy map, map, przywracania danych |
| długość tekstu, poziom, czas (w logu, bez treści) | zapisu tekstu na dysk, treści w logach |
| | list stałych, poprawek i kontroli wyniku (zostają u użytkownika) |

Dokument jest wczytywany, ukrywany i szyfrowany (mapa) na komputerze użytkownika.
Do serwera trafiają fragmenty tekstu, a wraca lista zakresów (początek, koniec, typ).
Dlatego serwer może nasłuchiwać w sieci lokalnej, w przeciwieństwie do aplikacji
użytkownika, która nasłuchuje wyłącznie na `127.0.0.1`.

## Wymagania

- Python z Niewidką (w folderze repozytorium `uv sync`), modele pobrane do katalogu modeli
  (te same pakiety co u użytkownika, weryfikowane sumami SHA-256).
- Procesor wystarcza (domyślnie). Dla karty NVIDIA: `pip install onnxruntime-gpu`
  (zamiast `onnxruntime`), sterownik i CUDA zgodne z wydaniem onnxruntime. Na Windowsie
  z kartą innego producenta: `onnxruntime-directml`.
- Certyfikat TLS (patrz niżej) albo sieć wydzielona.

## Uruchomienie w 3 krokach

1. Skopiuj `konfiguracja/serwer-inferencji.przyklad.toml` jako `serwer-inferencji.toml`
   i dopasuj ścieżki. Każda opcja ma tam komentarz.
2. Wygeneruj token: `python -m niewidka.serwer_inferencji nowy-token /etc/niewidka/token`.
3. Uruchom: `python -m niewidka.serwer_inferencji --konfig serwer-inferencji.toml`.

Przy starcie serwer ładuje wszystkie wskazane poziomy. Brak modeli, brak tokenu, brak GPU
przy `urzadzenie = "gpu"` albo adres w sieci bez TLS kończą start czytelnym komunikatem
(kod wyjścia 2). Serwer nigdy nie startuje „na pół gwizdka”.

## Procesor czy karta graficzna

W `[modele]`: `urzadzenie = "auto"` (najlepszy dostępny, z powrotem na procesor),
`"cpu"` albo `"gpu"` (CUDA, a na Windowsie także DirectML; bez GPU serwer nie startuje).
`watki` ogranicza wątki obliczeń na procesorze (0 = automatycznie), `rownolegle` ustala,
ile tekstów liczy się jednocześnie. Faktycznie użyty provider widać w `GET /v1/stan`.

## Token i użytkownicy

Token to plik (base64, uprawnienia 0600 na Linuxie). Serwer sprawdza go nagłówkiem
`Authorization: Bearer <token>` porównaniem odpornym na pomiar czasu. Bez pliku tokenu
serwer nie wystartuje. Wartości tokenu nigdy nie wpisuje się do pliku TOML ani do logów.

Rozdanie: przekaż użytkownikom ten sam plik bezpiecznym kanałem (udział z uprawnieniami,
menedżer haseł, narzędzie wdrożeniowe) i wskaż go w ich `niewidka.toml`
(`konfiguracja/klient-web.przyklad.toml`, sekcja `[inferencja]`). Wymiana tokenu:
wygeneruj nowy plik, podmień go na serwerze i u użytkowników, zrestartuj serwer.

## TLS z wewnętrznym urzędem certyfikacji

1. Wystaw certyfikat serwera dla nazwy, której używają użytkownicy
   (np. `niewidka-serwer.urzad.local`) w wewnętrznym urzędzie certyfikacji.
2. Wpisz `cert_plik` i `klucz_plik` (PEM) w `[siec]`; klucz prywatny miej z dostępem
   tylko dla konta usługi.
3. Użytkownikom daj plik CA (PEM) i wskaż go w `ca_plik`, chyba że CA jest już zaufany
   w ich systemie. Weryfikacja certyfikatu po stronie aplikacji jest zawsze włączona.

Poza loopbackiem serwer bez TLS odmawia startu. Tylko dla sieci wydzielonej albo testu
można ustawić `zezwol_bez_tls = true` (w logu pojawia się ostrzeżenie), a użytkownik
musi wtedy mieć `zezwol_bez_tls = true` w `[inferencja]`.

## Usługa systemd (Linux)

```ini
# /etc/systemd/system/niewidka-serwer.service
[Unit]
Description=Niewidka, serwer modeli
After=network-online.target

[Service]
User=niewidka
WorkingDirectory=/opt/niewidka
ExecStart=/opt/niewidka/.venv/bin/python -m niewidka.serwer_inferencji --konfig /etc/niewidka/serwer-inferencji.toml
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`systemctl enable --now niewidka-serwer`. Logi: `journalctl -u niewidka-serwer`.

## Zadanie harmonogramu (Windows)

```
schtasks /Create /TN "Niewidka serwer" /SC ONSTART /RU SYSTEM /RL HIGHEST ^
  /TR "C:\Niewidka\.venv\Scripts\python.exe -m niewidka.serwer_inferencji --konfig C:\Niewidka\serwer-inferencji.toml"
```

Plik tokenu i klucz TLS umieść w katalogu dostępnym tylko dla konta usługi.

## Interfejs (dla wdrożeniowców)

- `POST /v1/wykryj`, treść `{"tekst": "...", "poziom": 1}`; odpowiedź
  `{"zakresy": [{start, koniec, typ, pewnosc, zrodlo, suma_kontrolna, podejrzana}]}`.
  Błędy: 401 (token), 413 (tekst ponad `max_tekst_mb`), 422 (poziom spoza listy), 503 (kolejka pełna).
- `GET /v1/stan`: `{wersja, poziomy, urzadzenie}`.

## Co widzi użytkownik, gdy serwer padnie

Aplikacja nie ukrywa dokumentu „bez modelu”: odpowiada komunikatem „Serwer modeli nie
odpowiada” (kod 503) i niczego nie zwraca. Ekran stanu pokazuje wtedy brak dostępnych poziomów.
Każdy dokument to wiele krótkich zapytań (po jednym na akapit), więc opóźnienie sieci
przekłada się na czas ukrywania; serwer trzymaj w tej samej sieci lokalnej co użytkownicy.
