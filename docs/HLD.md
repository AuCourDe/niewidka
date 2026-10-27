# Niewidka — HLD (architektura wysokiego poziomu)

Stan: 2026-10-27, wersja 1. Decyzje źródłowe: `KONSULTACJE.md` (wiążące).
Cel: lokalne ukrywanie danych osobowych (pseudonimizacja — mapa = odwracalność) w polskich
tekstach i dokumentach biurowych **przed** wysłaniem czegokolwiek do chmurowego AI.
Żadne dane nie opuszczają maszyny albo sieci organizacji.

## 1. Komponenty i granice

| Komponent | Odpowiedzialność | Celowo nie robi |
|---|---|---|
| rdzeń `niewidka/` (Python 3.11+) | model danych (Encja/Zakres), reguły + sumy kontrolne, detektory ONNX za jednym interfejsem, scalanie, grupowanie osób po odmianach, znaczniki `[TYP_N]`, mapa szyfrowana, adaptery formatów, kontrola wyniku, ocena jakości | HTTP, GUI, logów treści, połączeń sieciowych |
| API `api.py` (FastAPI) | `/api/ukryj`, `/api/przywroc`, `/api/stan`; limity, kolejka, ładowanie modeli raz | żadnej logiki detekcji — cienki adapter |
| web `niewidka/web/` | jeden ekran: wklej/wskaż plik → suwak jakości → wynik + wskaźnik + ostrzeżenia | frameworka; rozmawia wyłącznie z API |
| klucze `klucze.py` | klucz mapy z keyring systemowego albo pliku wskazanego env | fallbacków i cichego generowania klucza |
| desktop | pywebview ładuje to samo UI; PyInstaller pakuje | drugiego toolchainu (bez Tauri/Electrona) |
| Android | PWA jako klient serwera organizacji; opcjonalny TWA | przetwarzania lokalnego (poza MVP) |

Granice twarde:

- rdzeń jest biblioteką — używalny z CLI i testów bez API oraz GUI;
- wagi modeli poza repo (katalog z konfiguracji, manifest z SHA-256, sprawdzany przy ładowaniu);
- klucz mapy nigdy w repo, konfiguracji ani logach;
- podczas przetwarzania zero ruchu sieciowego; oryginał żyje w RAM — na dysk trafiają
  tylko wynik i zaszyfrowana mapa.

## 2. Przepływ danych

```
plik (docx/odt/xlsx/pptx/pdf/txt) albo wklejony tekst
        │
        ▼
┌─ rdzeń niewidka (bez HTTP/GUI) ───────────────────────────────────────────┐
│ 1. adapter formatu: tekst + mapa przesunięć znaków na runy/komórki        │
│ 2. detekcja per segment (akapit/komórka/linia):                           │
│      reguły (regex + sumy kontrolne)  +  detektory ONNX (bardsai, LFM2.5) │
│ 3. scalanie: unia zakresów; suma kontrolna > dłuższy zakres > pewność     │
│ 4. grupowanie osób po odmianach → wspólne [OSOBA_N]                       │
│ 5. zamiana na [TYP_N] + dopisek; nazwa pliku → ZANONIMIZOWANY_*           │
│        └── mapa (co było pod którym znacznikiem) ──AES-256-GCM──► .nwidka │
│ 6. kontrola wyniku (poziom 3): ponowny odczyt zapisanego pliku,           │
│      detekcja przesuniętymi oknami → ostrzeżenia                          │
└────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
wynik: plik ZANONIMIZOWANY_* (ten sam format co wejście)
       + plik mapy .nwidka + wskaźnik jakości + ostrzeżenia

odtwarzanie: wynik + mapa + klucz (keyring/plik)  ──►  oryginał  (/api/przywroc)
```

## 3. Tryby pracy

| Tryb | Gdzie liczy | Klucz mapy | Uwagi |
|---|---|---|---|
| „Na tym urządzeniu" | desktop (pywebview) albo web na localhost | keyring systemowy | oryginał nie opuszcza maszyny |
| „Na serwerze organizacji" | serwer w LAN (FastAPI) | plik sekretów montowany z zewnątrz | oryginał idzie przez LAN — tryb zawsze jawny w UI; serwer bez wystawiania na internet; pliki tylko w RAM; ograniczona kolejka, jeden proces inferencji, model ładowany raz |

Suwak „Jakość wykrywania danych" (wg `KONSULTACJE.md`):
1 = reguły + bardsai (ONNX INT8), 2 = + LFM2.5-350M (tylko po wykazaniu zysku pomiarem),
3 = + kontrola wyniku (ponowne wczytanie zapisanego pliku i skan przesuniętymi oknami).

## 4. Bezpieczeństwo — model zagrożeń

1. **Pominięta encja → fałszywe „gotowe"** (zagrożenie nr 1): UI pokazuje R95 z kalibracji
   (nie średnią pewność, która o pominięciach nic nie mówi), wskaźnik dokumentu i ostrzeżenia
   z kontroli wyniku; elementu nieobsługiwanego się nie pomija cicho — blokuje eksport.
2. **Uboczne kanały formatu**: metadane, komentarze, śledzone zmiany, nagłówki/stopki,
   notatki prelegenta, ukryte arkusze — adapter usuwa je z wyniku; czego nie umie bezpiecznie
   usunąć, blokuje (eksport niemożliwy, z listą przyczyn).
3. **Kradzież pliku mapy**: mapa poza dokumentem (osobny plik `.nwidka`), AES-256-GCM
   z unikalnym nonce; bez klucza bezużyteczna.
4. **Słaby albo źle trzymany klucz**: wyłącznie keyring systemowy albo plik z env (uprawnienia
   0600); nigdy w repo, konfiguracji, logach; brak klucza = jawny błąd, nie fallback.
5. **Przejęcie procesu**: kto kontroluje proces, odczyta mapę w RAM — ograniczamy powierzchnię
   (brak sieci, brak logów treści), ale absolutnej gwarancji nie ma; ograniczenie udokumentowane.
6. **Serwer organizacji jako powierzchnia ataku**: oryginały tylko w RAM, jeden proces
   inferencji, ograniczona kolejka, nasłuch wyłącznie w sieci organizacji.
7. **Logi i telemetria**: logowane tylko typy/liczby encji i błędy bez treści; zero telemetrii,
   zero połączeń wychodzących w trakcie przetwarzania.
8. **Łańcuch dostaw modeli**: wagi z katalogu z konfiguracji, manifest z SHA-256 sprawdzany
   przy ładowaniu, żadnego pobierania w runtime; pobieranie z HF (tylko narzędziowo) przez `httpx`.
9. **Re-identyfikacja z resztek kontekstu** (rzadkie nazwisko + miejscowość): poza MVP;
   ograniczamy grupowaniem osób i poziomami czułości; znane ograniczenie odnotowane w dokumentacji.
10. **Nazwa pliku**: wynik zawsze `ZANONIMIZOWANY_*` — oryginalna nazwa może zawierać nazwisko.
11. **Układ i podpis cyfrowy**: „ten sam format" ≠ identyczny układ, podpis cyfrowy przepada —
    jawne ostrzeżenie w wyniku, nigdy cisza.
12. **Pozostałości w przeglądarce (PWA)**: `Cache-Control: no-store` na `/api/*`; service worker
    cache'uje tylko statyczną powłokę — treść dokumentów nie zostaje po zamknięciu karty.

## 5. Dystrybucja

| Kanał | Technologia | Pakowanie |
|---|---|---|
| web (serwer organizacji) | FastAPI + statyczne `web/` | systemd/Docker; konfiguracja env + TOML; bez wystawiania na internet |
| desktop Win/Mac/Linux | pywebview (ten sam interfejs web) | PyInstaller (onedir); wagi w katalogu zasobów obok albo ścieżka z env |
| Android | PWA (manifest + service worker: cache tylko powłoki, nigdy `/api/*`) | przeglądarka; opcjonalnie TWA (Bubblewrap) |

Wszystkie trzy kanały używają tej samej paczki rdzenia i tego samego UI.

## 6. Poza MVP (celowo)

OCR, RTF, dokumenty z makrami (blokowane), integracje z chmurowym AI, Android offline
(Kotlin + ORT Mobile — dopiero po pomiarze), trenowanie własnych modeli, GLiNER
(wchodzi tylko, gdy pomiar pokaże zysk).
