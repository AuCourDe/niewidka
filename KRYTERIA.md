# KRYTERIA pomiaru jakości detekcji — spisane PRZED pierwszym pomiarem

Ustalono 2026-10-28 ok. 00:35, przed uruchomieniem `narzedzia/pomiar.py` na jakimkolwiek
detektorze (PLAN.md Etap 0, polecenie właściciela). Zmiana progu po zobaczeniu wyniku jest
zakazana — rewizja kryteriów to nowy plik i nowy pomiar, nigdy dopasowanie progu do wyniku.

## 1. Zasady pomiaru

1. Jednostką jest próbka z `tests/korpus/*.jsonl`. W K1 tekst próbki traktujemy jak jeden
   segment. Offsety w znakach Unicode (Python `str`).
2. Detektor zwraca kandydatów `Zakres(start, koniec, typ)`; przed porównaniem stosuje się
   `niewidka.scalanie.scal()` — maskowany obszar grupy nakładających się zakresów to ich
   unia, typ wybierany według priorytetów LLD §5 (zgodnie z pkt 1 przeglądu Astry,
   `docs/konsultacje/04-przeglad-astra.md`).
3. Dopasowanie dokładne: **TP** = detekcja o identycznych (start, koniec, typ) jak oczekiwana
   encja; **FN** = oczekiwana bez trafienia; **FP** = detekcja **pewna** (`podejrzana=False`)
   bez dokładnie pasującego oczekiwania. Pokrycie częściowe liczy się jednocześnie jako FN
   i FP (zero tolerancji).
   **PN** (podejrzane nadmaskowanie, doprecyzowanie definicji 2026-10-28): detekcja z
   flagą `podejrzana=True` (wzorzec pasuje, suma kontrolna błędna) bez dokładnie pasującego
   oczekiwania — liczona osobno, **nie** wchodzi do FP ani do precision. Powód: przyjęcie
   pkt 14 przeglądu Astry (`docs/konsultacje/04-przeglad-astra.md`) zmienia zachowanie reguł
   na polecenie właściciela — numer z błędną sumą (możliwa literówka prawdziwego numeru) jest
   od teraz świadomie maskowany z flagą, więc stare liczenie „trafienie na pułapce = FP"
   opisywałoby zamierzone nadmaskowanie jako błąd. Zmiana dotyczy WYŁĄCZNIE definicji —
   progi (tabela §3, bramy) zostają bez zmian; pomiar powtórzony po zmianie zachowania,
   wynik w dopisku `docs/WYNIK-K1.md`.
4. `recall(T) = TP/(TP+FN)`, `precision(T) = TP/(TP+FP)` per typ; **„łącznie”** =
   mikro-uśrednienie po wszystkich wystąpieniach typów mierzonych na danym poziomie.
5. Sanity narzędzia: detektor pusty daje recall 0 (test w `tests/test_pomiar.py`).

## 2. Konwencje oczekiwanych zakresów w korpusie

- **OSOBA** — imię i nazwisko dokładnie jak w tekście; bez tytułów i form grzecznościowych
  („pan”, „mgr”).
- **ADRES** — od wyróżnika (ul./ulica/al./aleja/pl.) do numeru z lokalem (np. „13/5”,
  „15 m. 3”); bez kodu pocztowego i miejscowości.
- **TELEFON** — cały zapis łącznie z prefiksem, jeśli występuje (+48, 0048).
- **DATA** — sama data: „13.05.1982” albo „13 maja 1982”; bez „r.”.
- **DOKUMENT** (dowód osobisty) — seria i numer łącznie ze spacją/myślnikiem, jeśli występuje
  („ABC 212345”).
- **PESEL, NIP, REGON, IBAN** — dokładnie taki zapis, jaki stoi w tekście.
- **Homonimy i nazwiska-rzeczowniki**: encję oczekujemy tylko tam, gdzie tekst faktycznie
  oznacza osobę albo dane („Róża kupiła róże” → OSOBA tylko na pierwszym słowie).
- Oczekiwane encje w próbce nie nakładają się na siebie (waliduje `tests/test_korpus.py`).

## 3. Progi K1 — rdzeń regułowy (bez modeli ONNX)

Twarde minimum K1 (KAMIENIE.md): 100% numerów z poprawną sumą kontrolną wykrytych i 0
trafficień na numerach z błędną sumą. W tabeli odpowiadają temu wiersze „= 1.00”:

| typ | recall | precision |
|---|---|---|
| PESEL | = 1.00 | = 1.00 |
| NIP | = 1.00 | = 1.00 |
| REGON | = 1.00 | = 1.00 |
| IBAN | = 1.00 | = 1.00 |
| DOKUMENT | = 1.00 | = 1.00 |
| EMAIL | = 1.00 | = 1.00 |
| TELEFON | ≥ 0.90 | ≥ 0.95 |
| ADRES | ≥ 0.80 | ≥ 0.90 |
| DATA | ≥ 0.90 | ≥ 0.95 |
| **łącznie (typy powyżej)** | **≥ 0.90** | **≥ 0.95** |

- **OSOBA**: poza zakresem reguł — wykrywa ją dopiero model na poziomie 1 (kamień K2).
  W K1 pomiar wypisuje OSOBA osobno, ale nie wchodzi ona do bramy ani do „łącznie”.
- **INNE**: typ rezerwowy, bez progów w K1.

## 4. Progi poziomów 1-3 (suwak jakości; rozliczane w K2+)

| poziom | kryterium |
|---|---|
| 1 (reguły + bardsai) | wszystkie progi K1 oraz OSOBA recall ≥ 0.90 i precision ≥ 0.95; „łącznie” z OSOBA: recall ≥ 0.90, precision ≥ 0.95 |
| 2 (+ LFM2.5, po wykazaniu zysku pomiarem) | progi poziomu 1 oraz OSOBA recall ≥ 0.95; precision żadnego typu nie spada poniżej poziomu 1 |
| 3 (+ kontrola wyniku) | kontrola wykrywa ≥ 0.95 celowo pozostawionych encji na pliku wzorcowym z wyciekiem; R95 policzony i zapisany w `dane/r95.json` |

## 5. Korpus — wymagania (K0)

- ≥ 40 próbek; każdy typ z tabeli K1 ma ≥ 2 oczekiwane encje pozytywne.
- Każdy typ z walidatorem sumy kontrolnej (PESEL, NIP, REGON, IBAN, DOKUMENT) ma ≥ 1
  wystąpienie z **błędną** sumą — bez oczekiwanej encji; pewne trafienie tam liczy się
  jako FP, nadmaskowanie z flagą `podejrzana` — jako PN (§1.3).
- Homonimy („Róża”, „Wiśniewski”/„wiśnie”) i nazwiska-rzeczowniki („Kowal”, „Nowak”)
  obecne jako próbki z tagami `homonim` / `rzeczownik-nazwisko` (łącznie ≥ 4 próbki).
- ≥ 2 próbki negatywne (bez żadnej oczekiwanej encji).
- Numery generuje `narzedzia/numery.py` (deterministycznie); poprawność sum weryfikuje
  `tests/test_korpus.py` przez python-stdnum oraz algorytm dowodu (wagi 7,3,1,9,7,3,1,7,3;
  litery A=10..Z=35; suma iloczynów mod 10 = wartość 4. znaku; źródło: algorytm.org,
  „Numer dowodu osobistego”).

## 6. Autorstwo

Teksty i oczekiwane encje korpusu: agent zewnętrzny (opencode) — autor inny niż autor
detektorów (PLAN T0.2). `KRYTERIA.md`, `narzedzia/numery.py` (mechaniczny generator numerów),
`narzedzia/pomiar.py` oraz detektory: sesja claude-glm.
