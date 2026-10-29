# Synteza konsultacji architektonicznej

Źródła: `konsultacje/03-odpowiedzi-www.md` (Astra, Argon), `konsultacje/02-gemini-agy2-nazwa.md`.
Rozstrzygał orkiestrator (Opus); przy sprzeczności wygrywa głos z uzasadnieniem i pomiarem, nie liczba głosów.

## Nazwa: **Niewidka**

Astra (TOP 3: Niewidka, Skrytopis, Pseudonim) i Gemini/agy2 (TOP 3: Niewidka, Kryptonim, Płachta)
niezależnie rekomendują **Niewidka** — czapka niewidka z polskich baśni (m.in. Korczak): ukrywa postać,
nie unicestwiając jej, czyli dokładnie odwracalne maskowanie. Argon (Flash-Lite) wskazał „Kryptonim”,
ale Astra sprawdziła: to nazwa portfela kryptowalutowego — odrzucone. Repo: `niewidka`.

## Zgodne tezy (obaj)

| Obszar | Decyzja |
|---|---|
| Rdzeń | **Python + ONNX Runtime (CPU INT8, GPU opcjonalnie)**. Ekosystem NLP PL jest w Pythonie; bez PyTorcha w paczce. |
| Serwer | **FastAPI jako cienki adapter** nad rdzeniem. Rdzeń nie zna HTTP ani GUI. |
| Reguły | Wyrażenia regularne + **sumy kontrolne** (PESEL, NIP, REGON, IBAN, dowód) — najwyższy priorytet przy scalaniu. |
| Scalanie | Unia zakresów; nakładające się → reguła z sumą kontrolną wygrywa, potem dłuższy zakres / wyższa pewność. |
| Mapa | JSON **poza dokumentem**, AES-256-GCM, unikalny nonce, **klucz w magazynie systemowym** (Credential Manager / Keychain / libsecret; serwer: plik sekretów montowany z zewnątrz). |
| Formaty | python-docx+lxml, odfpy/lxml, openpyxl, python-pptx, PyMuPDF. Pułapka nr 1: tekst DOCX rozbity na runy -> scalić akapit, mapować przesunięcia znaków z powrotem na runy. |
| MVP bez | OCR, RTF, makr, integracji z chmurowym AI, Androida offline, trenowania własnych modeli. |

## Rozstrzygnięcia przy różnicy zdań

| Temat | Astra | Argon | Decyzja i powód |
|---|---|---|---|
| GUI desktop | **pywebview + PyInstaller** (jeden interfejs web, bez Rusta) | Tauri | **pywebview**: jeden język backendu, ten sam interfejs co web, brak drugiego procesu/toolchainu. Najmniej kodu. |
| Android | **PWA jako klient serwera organizacji**; APK = cienkie opakowanie; offline (Kotlin + ORT Mobile) osobny etap | PWA/klient lub Flutter | **PWA + opcjonalny wrapper APK (TWA)**. Offline na telefonie dopiero po pomiarze. |
| Wzór jakości | średnia pewność **nie mówi nic o pominięciach**; kalibracja na zbiorze walidacyjnym: górna granica **Cloppera–Pearsona** `R95 = Beta⁻¹(0,95; k+1, n−k)` (k = dokumenty z wyciekiem na n) | wzór z ważonej pewności wykrytych encji × współczynnik poziomu | **Oba, rozdzielone**: (1) **Ryzyko resztkowe** dla poziomu = R95 z kalibracji (rzetelne, liczone offline na korpusie testowym, wbudowane w aplikację); (2) **Wskaźnik dokumentu** = heurystyka bieżąca (udział encji potwierdzonych sumą kontrolną/2 modelami, liczba „podejrzanych resztek” znalezionych w kontroli wyniku). UI pokazuje (1) jako liczbę, (2) jako ostrzeżenia. |
| Poziomy suwaka | 1: reguły+bardsai; 2: +LFM2.5 (po wykazaniu zysku); 3: +kontrola gotowego pliku (ponowna ekstrakcja, przesunięte okna) | 1: reguły+lekki NER; 2: +bardsai/LFM; 3: +GLiNER | **Astra**: 1 = reguły + bardsai XLM-RoBERTa ONNX INT8 (279 MB); 2 = + LFM2.5-Encoder-350M; 3 = + **kontrola wyniku** (ponowne wczytanie zapisanego pliku i skan przesuniętymi oknami). GLiNER wchodzi tylko, jeśli pomiar pokaże zysk. |
| Odmiany nazwisk | lematyzacja (Morfeusz 2), nie scalać Jana i Piotra Kowalskiego; `[OSOBA_1]` traci formę — rozważ `[OSOBA_1_F2]`; ręczne „połącz/rozdziel” | spaCy pl / pymorphy | **MVP**: grupowanie po rdzeniu nazwiska (heurystyka końcówek) + imię; mapa przechowuje każdą formę powierzchniową. Znacznik zostaje czytelny `[OSOBA_1]`. Przywracanie: forma z mapy dla danego wystąpienia, gdy pozycja się zgadza, inaczej forma podstawowa. Morfeusz jako ulepszenie po pomiarze. `SIMPLIFICATION`. |
| Dopisek | pierwszy akapit / slajd / strona; XLSX: arkusz informacyjny; nazwa `ZANONIMIZOWANY_<bezpieczna-nazwa>` (oryginalna nazwa może zawierać nazwisko) | dopisek w treści i nazwie | **Astra** (nazwa pliku też jest anonimizowana). |
| Słownictwo | to **pseudonimizacja** (mapa = odwracalne), nie anonimizacja w sensie RODO | — | W UI i README nazywać rzetelnie: „ukrywanie danych osobowych (pseudonimizacja)”. |

## Ostrzeżenia, które przyjmujemy
- Największy wyciek: **metadane, komentarze, rewizje (track changes), nagłówki/stopki, notatki prelegenta, ukryte arkusze**. Element nieobsługiwany = eksport **blokowany**, nie „gotowe”.
- „Ten sam format” ≠ identyczny układ; podpis cyfrowy przepada.
- „Włamanie nic nie ujawni” jest niewykonalne absolutnie — przejęty proces z prawem odszyfrowania mapy odczyta ją. Ograniczamy: mapa szyfrowana, klucz poza aplikacją, brak logów treści, brak telemetrii, brak połączeń sieciowych podczas przetwarzania.
- Serwer: ograniczona kolejka, **jeden proces inferencji**, model ładowany raz.
- Tryb w UI jawny: „Na tym urządzeniu” / „Na serwerze organizacji” (drugi = oryginał idzie przez LAN).

## Konsultacja logiki aplikacji (2026-10-29, `docs/LOGIKA.md`, commit 8e62ba5)

Argon (Gemini „4 Argon”) i Astra (ChatGPT, GPT-6 Astra, bez danych klienta) dostali ten sam opis logiki
i 4 pytania. Każde twierdzenie sprawdzone w kodzie, zanim trafiło do planu.

### Sprawdzone w kodzie

| Uwaga | Kto | Stan po sprawdzeniu |
|---|---|---|
| Przywracanie odpowiedzi AI pada, bo czat nie powtarza dopisku z identyfikatorem mapy | obaj | **Potwierdzone i naprawione** `a84946f`: brak dopisku = przywrócenie z ostrzeżeniem, dopisek innej mapy = odmowa |
| DOCX: komentarze, historia zmian, metadane wyciekną | obaj | **Nieaktualne**: `formaty/docx_.py` usuwa `word/comments`, `w:del`, `docProps/*`, autorów rewizji; opis w LOGIKA.md tego nie mówił |
| AI zgubi przyrostek `_F1` | Argon | **Obsłużone**: znacznik bez wariantu wraca w formie domyślnej (`mapa.przygotuj_zamiany`) |
| Wariant F odtwarza dawną odmianę, nie dobiera jej do nowego zdania | obaj | **Prawda**, ograniczenie znane; dobór odmiany do kontekstu = osobny projekt |
| „Później” przy wymaganym pakiecie | Argon | Do sprawdzenia w UI: suwak zostaje bez modelu, pierwsze „Ukryj” musi jasno mówić, czego brakuje |

### Zgodne obu konsultantów (kandydaci do następnego etapu)

1. **Blokada: pokazać podgląd z zaznaczonym miejscem wątpliwym**, „Kopiuj/Pobierz” wyłączone do decyzji
   („Ukryj ten fragment” / „Zostaw, to nie dane osobowe”). Bez uniwersalnego „wyślij mimo wszystko”.
2. **Ręczna korekta w podglądzie**: zaznacz słowo → „Ukryj też to (wszędzie)”; klik w plakietkę → „To nie są dane osobowe”.
3. **Mapa zapisywana automatycznie** (szyfrowana, z okresem przechowywania) i **przywracanie przez samo wklejenie**
   odpowiedzi; Astra: dobór mapy jednoznacznie po znacznikach, nie „ostatnia użyta”; identyfikator w każdym znaczniku.
4. **Jeden zalecany tryb domyślny** zamiast suwaka 3 poziomów (sprzeczne z zamówieniem właściciela → decyzja właściciela).
5. **Ryzyko bez żargonu**: zamiast „górna granica 95%, 1 na 14” zadanie: „Ukryto 18 informacji. Przejrzyj przed wysłaniem”.
6. Astra: „ZANONIMIZOWANY” to w rozumieniu EROD pseudonimizacja (odwracalna) → np. „DANE UKRYTE” (dopisek zamówił właściciel → jego decyzja).

### Brakujące typy danych (obaj, scalone)

Księga wieczysta (format i cyfra kontrolna), sygnatury akt (sąd, komornik, prokuratura), paszport, karta pobytu,
prawo jazdy, numer PWZ i wpisu na listę adwokatów/radców, numery polis, umów, klienta, pracownika, faktur,
działka ewidencyjna i obręb, IMEI i numery seryjne, VIN, rejestracja, KRS, adres e-Doręczeń i skrytka ePUAP,
hasła/PIN-y/tokeny, kody ICD-10 (dane szczególnej kategorii), symbole niepełnosprawności, nazwy JDG zawierające
nazwisko, kwoty i daty słownie. Astra: IP i SWIFT regułami już w pakiecie podstawowym.

### Pozostałe uwagi

- Astra: wersja web w organizacji wymaga uwierzytelnienia użytkowników, izolacji ich map i HTTPS; token strony tego nie zastępuje.
- Astra: kontrola tym samym detektorem nie jest niezależna; „0 blokad na 8 pismach” nic nie mówi o wyciekach (wycieki mierzy `testy_e2e`).
- Argon: doliczanie słów z wielkiej litery do osoby potrafi wciągnąć nazwę urzędu; lista słów zatrzymujących (Urzędu, Sądu, Miasta, Prezes…).
- Astra: niepoprawna suma kontrolna powinna obniżać pewność, nie wykluczać maskowania (u nas „pułapka” z błędną sumą i tak jest maskowana).
