# WYNIK pomiaru K2e — LFM2.5 fp32 SOLO per typ (nie tylko OSOBA) + typy poza Niewidką

Data: 2026-10-28 (sesja opencode/glm). Pytanie właściciela: „nazwisko to jedno, a inne?
pesel, ulica, numer dowodu?”. Progi: `KRYTERIA.md` — **nieprzesunięte**. Produkt (`niewidka/`)
bez zmian poza funkcją mapowania `detektory.mapuj_typ_lfm25` (z testem) — pomiar służy
decyzji o rozszerzeniu zakresu, nie zmienia dziś detekcji produktu.

Korpus główny: **190 próbek** (`tests/korpus/probki.jsonl`, jak w K2d). Nowy korpus
typów poza Niewidką: **40 próbek / 41 encji** (`tests/korpus/probki_nowe_typy.jsonl`,
fikcyjne polskie zdania, offsety liczone skryptem; `tests/test_korpus.py` rozszerzony
o `TYPY_NOWE` tylko dla tego pliku).

Model: `~/models/niewidka/lfm25/fp32/` (K2b: eksport sanity 1,5e-05 względem
torch; INT8 odpada solo — recall 0,398 vs 0,553). Schemat etykiet: 27 typów BIOES
(`label_schema.json`). Solo = `OnnxDetektor` z pełną mapą klas, bez progu ponad argmax
(jak `wczytaj_lfm25` w K2b), detektor pomiarowy `lfm25-solo` w `narzedzia/pomiar.py`.

## 1. Mapowanie klas LFM2.5 -> typy Niewidki (polecenie pkt 1)

Mapa w `niewidka/detektory.py` (`_MAPA_LFM25` + `mapuj_typ_lfm25`), test
`tests/test_mapowanie_lfm25.py`. Tabela:

| klasa LFM2.5 | typ Niewidki | uwagi |
|---|---|---|
| `identity.person_name` | OSOBA | jak w K2b |
| `identity.national_id` | PESEL / NIP / REGON | kształtem zapisu: 10 cyfr = NIP, 9/14 = REGON, 11 = PESEL; z literami = DOKUMENT — model NIE odróżnia polskich numerów |
| `identity.passport` | DOKUMENT | |
| `identity.drivers_license` | DOKUMENT | |
| `contact.address` | ADRES | granice modelu rozmyte względem konwencji KRYTERIA §2 (kod+miejscowość JEDNĄ całość; model łamie — sekcja 2) |
| `contact.postal_code` | ADRES | |
| `contact.phone` | TELEFON | |
| `contact.email` | EMAIL | |
| `financial.iban` | IBAN | |
| `financial.bank_account` | IBAN | |
| `identity.date_of_birth` | DATA | |
| pozostałe 16 klas | bez mapowania (surowa nazwa) | pomiar sekcja 3: `healthcare.*`, `org.company_name`, `online.url/username`, `contact.ip_address`, `financial.credit_card`, `financial.swift_bic`, `legal.case_number`, `special.*`; `identity.ssn` widoczna jako FP na korpusie głównym (sekcja 2); `credential.api_key`, `device.mac_address`, `location.gps_coordinates` nie wchodziły do korpusu nowego |

Uwaga praktyczna z pomiaru: klasa `identity.ssn` (US) łapie nasze PESEL-e (np.
pesel-wniosek, p=0.50). Po mapie te zakresy zostają jako surowy `identity.ssn` — część
wiedzy modelu o polskich numerach jest bezużyteczna; do PESEL prowadzi tylko
`national_id`.

## 2. Pomiar solo fp32 na korpusie głównym (190) — per typ, obok reguł (polecenie pkt 2)

### Poziom 1 (reguły + bardsai, referencja)

| typ | TP | FP | PN | FN | recall | precision |
|---|---|---|---|---|---|---|
| ADRES | 16 | 0 | 0 | 0 | 1.000 | 1.000 |
| DATA | 8 | 0 | 0 | 0 | 1.000 | 1.000 |
| DOKUMENT | 5 | 0 | 4 | 0 | 1.000 | 1.000 |
| EMAIL | 7 | 0 | 0 | 0 | 1.000 | 1.000 |
| IBAN | 6 | 0 | 4 | 0 | 1.000 | 1.000 |
| NIP | 7 | 0 | 4 | 0 | 1.000 | 1.000 |
| OSOBA | 100 | 6 | 0 | 3 | 0.971 | 0.943 |
| PESEL | 7 | 0 | 5 | 0 | 1.000 | 1.000 |
| REGON | 7 | 0 | 4 | 0 | 1.000 | 1.000 |
| TELEFON | 8 | 0 | 0 | 0 | 1.000 | 1.000 |
| **łącznie (K1, bez OSOBA)** | 71 | 0 | 21 | 0 | 1.000 | 1.000 |
| **łącznie (wszystkie)** | 171 | 6 | 21 | 3 | 0.983 | 0.966 |

(czyli: reguły 1.000/1.000 na wszystkich typach regułowych — identycznie jak K2b/K2d;
OSOBA od bardsai 0.971/0.943. Czas poziomu 1: 11,6 ms/próbkę, RAM 798 MiB.)

### LFM2.5 fp32 SOLO — pełna mapa

| typ | TP | FP | FN | recall | precision |
|---|---|---|---|---|---|
| ADRES | 2 | 12 | 14 | 0.125 | 0.143 |
| DATA | 2 | 0 | 6 | 0.250 | 1.000 |
| DOKUMENT | 2 | 1 | 3 | 0.400 | 0.667 |
| EMAIL | 6 | 0 | 1 | 0.857 | 1.000 |
| IBAN | 4 | 2 | 2 | 0.667 | 0.667 |
| NIP | 1 | 1 | 6 | 0.143 | 0.500 |
| OSOBA | 57 | 13 | 46 | 0.553 | 0.814 |
| PESEL | 6 | 4 | 1 | 0.857 | 0.600 |
| REGON | 0 | 0 | 7 | 0.000 | n/d |
| TELEFON | 6 | 0 | 2 | 0.750 | 1.000 |
| (surowe) `identity.ssn` | 0 | 6 | 0 | — | 0.000 |
| (surowe) `healthcare.medical_record` | 0 | 1 | 0 | — | 0.000 |
| (surowe) `online.username` | 0 | 1 | 0 | — | 0.000 |
| **łącznie (bez OSOBA)** | 29 | 28 | 42 | 0.408 | 0.509 |
| **łącznie (wszystkie)** | 86 | 41 | 88 | 0.494 | 0.677 |

Czas na próbkę (CPU): średnia 82,4 ms, mediana 76,2 ms (próbek: 190); RAM 2214 MiB.
OSOBA 0.553/0.814 = identycznie jak K2b (adapter niezmienny — sanity pomiaru).

### Co LFM2.5 łapie, a reguły nie (polecenie pkt 2 — wypis)

Dokładnych TPs modelu poza OSOBA, których nie ma w regułach: **0**. Model nie dodaje
ani jednego dokładnego trafienia na typach regułowych (reguły 1.000/1.000). Model łapie
57 OSOBA samodzielnie (m.in. wszystkie 8 inicjałów „J. Nowak” i nazwiska złożone
„Anna Maria Kowalska-Nowak” — grupy, gdzie uzupełniający wariant K2c/K2d był mierzony).

Szczegółowo o przypadkach z polecenia (kod pocztowy+miejscowość, adres bez „ul.”,
dowód w nietypowym zapisie) — model **nie łapie ich dokładnie**:

- `adr-kod-ulica` — oczekiwane „ul. Długa 15/3, 00-238 Warszawa”: LFM daje dwa
  rozłączne „ul. Długa 15/3” (p=0.72) i „00-238” (p=0.55) bez „Warszawa” → każdy
  fragment pokrywa część encji = FN+FP (zero tolerancji, KRYTERIA §1.3).
- `adr-kod-sam` — „00-238 Warszawa” (ADRES bez ulicy): LFM = „00-238” bez miejscowości → FN+FP.
- `adr-miejscowosc-dwie` — „41-100 Siemianowice Śląskie”: LFM = „41-100” i
  „Siemianowice Śląskie” osobno (p=0.69) → 2 FP w miejsce 1 TP.
- `adres-zamieszkaly` — „ul. Lipowa 13/5”: LFM = „ul” (sam wyróżnik, p=0.59) +
  „Lipowa 13/5” → FN+FP.
- dowody: „MHC300003” LFM daje jako `healthcare.medical_record` (zła klasa, p=0.94);
  „TJZ400001” i „ALW400001” — brak trafienia; recall DOKUMENT 0.400.
- PESEL-e: część trafia jako `identity.ssn` (np. pesel-wniosek, p=0.50) — do PESEL
  prowadzi wyłącznie `national_id`.

## 3. Typy poza Niewidką — korpus 40 zdań + pomiar (polecenie pkt 3)

Korpus `tests/korpus/probki_nowe_typy.jsonl` (41 encji). Autor prób: ta sesja; dla
nowych typów pułapki sum kontrolnych nie obowiązują (typy bez sum). Pomiar
`--detektor lfm25-solo --wariant fp32 --plik probki_nowe_typy.jsonl`:

| typ | encje | TP | FP | FN | recall | precision |
|---|---|---|---|---|---|---|
| contact.ip_address | 3 | 3 | 0 | 0 | 1.000 | 1.000 |
| financial.credit_card | 3 | 3 | 0 | 0 | 1.000 | 1.000 |
| online.username | 3 | 2 | 0 | 1 | 0.667 | 1.000 |
| financial.swift_bic | 3 | 2 | 0 | 1 | 0.667 | 1.000 |
| online.url | 3 | 1 | 1 | 2 | 0.333 | 0.500 |
| org.company_name | 5 | 1 | 1 | 4 | 0.200 | 0.500 |
| special.political | 3 | 1 | 0 | 2 | 0.333 | 1.000 |
| special.religion | 3 | 1 | 0 | 2 | 0.333 | 1.000 |
| healthcare.condition | 4 | 0 | 0 | 4 | 0.000 | n/d |
| healthcare.medication | 4 | 0 | 0 | 4 | 0.000 | n/d |
| healthcare.medical_record | 3 | 0 | 1 | 3 | 0.000 | 0.000 |
| legal.case_number | 4 | 0 | 0 | 4 | 0.000 | n/d |
| (OSOBA) | — | 0 | 1 | 0 | — | 0.000 |
| **łącznie (bez OSOBA)** | 41 | 14 | 3 | 27 | 0.341 | 0.824 |

Czas na próbkę: 86,5 ms (próbek: 40); RAM 2285 MiB. FP OSOBA = „Marzenka1988”
(login) rozpoznany jako imię.

## 4. Wniosek (polecenie pkt 4) — czy LFM2.5 wnosi wartość dla typów innych niż OSOBA?

**Nie na tym modelu — LFM2.5 nie wchodzi** (decyzja zgodna z K2b; progi KRYTERIA
nieprzesunięte):

1. **Na typach regułowych nie dodaje ani jednego dokładnego trafienia** (reguły
   1.000/1.000), ma za to 28 FP i rozmyte granice (kod pocztowy bez miejscowości,
   „ul” bez ulicy) — dokładnie ten mechanizm psujący unie scalania, który K2b/K2c
   pokazały dla OSOBA.
2. **Na typach poza zakresem reguł recall 0.341**. Realny zysk: IP (1.000/1.000),
   karta płatnicza (1.000/1.000) i połowa SWIFT/loginów trafna dokładnie. Natomiast
   healthcare (choroby/leki/karty medyczne w polskim zdaniu): 0.000 poza 1 FP,
   sygnatury akt: 0.000, firmy: 0.200, URL: 0.333 — za mało, by obciążać produkt.
3. **Koszt**: 82-87 ms/próbkę i ~2,2 GB RAM (fp32; INT8 odpada jeszcze mocniej).
4. **Analiza mapy**: jednej narodowej klasy numerów (national_id) nie da się uczciwie
   rozdzielić na PESEL/NIP/REGON bez zgadywania kształtem; a i tak model łapie część
   PESEL-i jako amerykański `identity.ssn` — wiedza o polskich numerach jest u modelu
   szczątkowa.

Jedyny realny surowy zysk na dziś: **IP, karta kredytowa i częściowo SWIFT** —
przypadki, gdy reguły milczą. To za wąski zakres i za słaby ogólny recall, by brać
1,4-GB model na 3 typy; jeśli zasięg tych trzech typów kiedyś będzie potrzebny,
realniejszy jest prosty regex/suma Luhna K1 niż LFM2.5. Re-pomiar przy nowym modelu:
wymagaj osobnych klas narodowych numerów (PESEL/NIP/REGON), granic ADRES zgodnych
z KRYTERIA §2 oraz pracy na odmianie polskiej w healthcare/legal.
