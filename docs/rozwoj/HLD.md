# Niewidka — HLD (architektura wysokiego poziomu)

Stan: 2026-10-28 (wersja 1 z 2026-10-27 po przeglądach Astry i Gemini). Decyzje źródłowe:
`KONSULTACJE.md` (wiążące); odpowiedzi na przeglądy: `LLD.md` §17.
Cel: lokalne ukrywanie danych osobowych (pseudonimizacja — mapa = odwracalność) w polskich
tekstach i dokumentach biurowych **przed** wysłaniem czegokolwiek do chmurowego AI.
Żadne dane nie opuszczają maszyny albo sieci organizacji.

**MVP zawężone 2026-10-28 po przeglądach** (Astra pkt 15, Gemini): wejście to **wklejony
tekst, TXT i DOCX**, kanał to **web lokalny** („Na tym urządzeniu"). Pozostałe formaty
(odt, xlsx, pptx, pdf), tryb „Na serwerze organizacji", desktop i Android — **v1, po
kamieniach K0–K5** (§6, `KAMIENIE.md`).

## 1. Komponenty i granice

| Komponent | Odpowiedzialność | Celowo nie robi |
|---|---|---|
| rdzeń `niewidka/` (Python 3.11+) | model danych (Encja/Zakres), reguły + sumy kontrolne, detektory ONNX za jednym interfejsem, scalanie, grupowanie osób po odmianach, znaczniki `[TYP_N]` / `[OSOBA_N_Fk]`, mapa szyfrowana, adaptery formatów, kontrola wyniku, ocena jakości | HTTP, GUI, logów treści, połączeń sieciowych |
| API `api.py` (FastAPI) | `/api/ukryj`, `/api/przywroc`, `/api/stan`; limity, kolejka, ładowanie modeli raz | żadnej logiki detekcji — cienki adapter |
| web `niewidka/web/` | jeden ekran: wklej/wskaż plik → suwak jakości → wynik + R95 + ostrzeżenia | frameworka; rozmawia wyłącznie z API |
| klucze `klucze.py` | klucz mapy z keyring systemowego albo pliku wskazanego env | fallbacków i cichego generowania klucza |
| desktop (v1) | pywebview ładuje to samo UI; PyInstaller pakuje | drugiego toolchainu (bez Tauri/Electrona) |
| Android (v1) | PWA jako klient serwera organizacji; opcjonalny TWA | przetwarzania lokalnego |

Granice twarde:

- rdzeń jest biblioteką — używalny z CLI i testów bez API oraz GUI;
- wagi modeli poza repo (katalog z konfiguracji, manifest z SHA-256, sprawdzany przy ładowaniu);
- klucz mapy nigdy w repo, konfiguracji ani logach;
- podczas przetwarzania zero ruchu sieciowego; oryginał żyje w RAM — na dysk trafiają
  tylko wynik i zaszyfrowana mapa.

## 2. Przepływ danych

```
plik (TXT/DOCX w MVP; odt/xlsx/pptx/pdf w v1) albo wklejony tekst
        │
        ▼
┌─ rdzeń niewidka (bez HTTP/GUI) ───────────────────────────────────────────┐
│ 1. adapter formatu: tekst + mapa przesunięć znaków na runy/komórki        │
│ 2. detekcja per segment (akapit/komórka/linia):                           │
│      reguły (regex + sumy kontrolne)  +  detektory ONNX (bardsai, LFM2.5) │
│      numer z błędną sumą kontrolną = encja „podejrzana", nie odrzucenie   │
│ 3. scalanie: maskowany obszar = unia zakresów; etykieta wg priorytetów    │
│ 4. grupowanie osób po odmianach → wspólne [OSOBA_N_Fk]                    │
│ 5. zamiana na [TYP_N] (osoby z wariantem formy) + dopisek; nazwa pliku    │
│    → ZANONIMIZOWANY_<krótki-id>.<ext> (neutralna, bez oryginalnej)        │
│        └── mapa (co było pod którym znacznikiem) ──AES-256-GCM──► .nwidka │
│ 6. kontrola zapisu ZAWSZE: ponowny odczyt zapisanego pliku → nowe         │
│      znaleziska blokują status „ukończony"; poziom 3 = okna rozszerzone   │
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
| „Na tym urządzeniu" (**MVP**) | web na localhost | keyring systemowy | oryginał nie opuszcza maszyny; token sesji + walidacja Host/Origin zamiast uwierzytelniania kont |
| „Na serwerze organizacji" (**v1**) | serwer w LAN (FastAPI) | klucz per dokument albo wywodzony z hasła klienta (nie globalny sekret serwera) | wymaga uwierzytelniania, właściciela mapy, autoryzacji odszyfrowania i HTTPS w LAN (Astra pkt 4, Gemini pkt 1); tryb zawsze jawny w UI; pliki tylko w RAM; ograniczona kolejka, jeden proces inferencji |

Suwak „Jakość wykrywania danych" (wg `KONSULTACJE.md`):
1 = reguły + bardsai (ONNX INT8), 2 = + LFM2.5-350M (tylko po wykazaniu zysku pomiarem),
3 = + rozszerzona kontrola wyniku (okna przesunięte). Weryfikacja zapisu (ponowne wczytanie
zapisanego pliku) działa **na każdym poziomie**; nowe znaleziska blokują status „ukończony"
(przegląd Astry pkt 8).

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
10. **Nazwa pliku**: wynik zawsze `ZANONIMIZOWANY_<krótki-id>.<ext>` — nazwa neutralna,
    bez przenoszenia oryginalnej nazwy (często zawiera nazwisko; przegląd Astry pkt 5,
    Gemini pkt 9). Oryginalna nazwa, jeśli potrzebna, wraca przy przywracaniu z mapy.
11. **Układ i podpis cyfrowy**: „ten sam format" ≠ identyczny układ, podpis cyfrowy przepada —
    jawne ostrzeżenie w wyniku, nigdy cisza.
12. **Pozostałości w przeglądarce (PWA)**: `Cache-Control: no-store` na `/api/*`; service worker
    cache'uje tylko statyczną powłokę — treść dokumentów nie zostaje po zamknięciu karty.

## 5. Dystrybucja

| Kanał | Technologia | Pakowanie |
|---|---|---|
| web lokalny (**MVP**) | FastAPI na 127.0.0.1 + statyczne `web/` | uruchomienie lokalne; konfiguracja env + TOML |
| web (serwer organizacji) (**v1**) | FastAPI + statyczne `web/` | systemd/Docker; uwierzytelnianie + HTTPS; bez wystawiania na internet |
| desktop Win/Mac/Linux (**v1**) | pywebview (ten sam interfejs web) | PyInstaller (onedir); wagi w katalogu zasobów obok albo ścieżka z env |
| Android (**v1**) | PWA (manifest + service worker: cache tylko powłoki, nigdy `/api/*`) | przeglądarka; opcjonalnie TWA (Bubblewrap) |

Wszystkie kanały używają tej samej paczki rdzenia i tego samego UI.

## 6. Poza MVP (celowo)

Przeniesione do **v1** zawężeniem 2026-10-28: formaty odt, xlsx, pptx, pdf; tryb „Na
serwerze organizacji" (z uwierzytelnianiem i HTTPS); desktop; Android. Nadal poza zakresem
do odwołania: OCR, RTF, dokumenty z makrami (blokowane), integracje z chmurowym AI,
Android offline (Kotlin + ORT Mobile — dopiero po pomiarze), trenowanie własnych modeli,
GLiNER (wchodzi tylko, gdy pomiar pokaże zysk).
