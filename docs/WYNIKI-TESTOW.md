# Wyniki testów anonimizacji na 30 pismach

Test z 2026-11-04. Sprawdza, ile danych osobowych program ukrywa w realistycznych polskich
pismach, których wcześniej nie widział. Wszystkie dane w pismach są fikcyjne.

## Jak przebiegał test

- **Pisma.** Dwa niezależne generatory tekstu napisały po 15 pism: decyzje, umowy, skargi,
  notatki policji, dokumentację medyczną, korespondencję e-mail, testament, fakturę i inne.
  Celowo wpleciono trudne przypadki: nazwiska będące zwykłymi słowami (Kot, Lis, Wróbel, Zając),
  odmianę przez przypadki, zdrobnienia, nazwiska dwuczłonowe, dwie osoby o tym samym nazwisku,
  inicjały, adresy bez „ul.”, numery w różnych zapisach.
- **Lista danych do ukrycia.** Autor każdego pisma wypisał wszystkie dane osobowe dokładnie tak,
  jak stoją w tekście, każdą formę odmiany osobno. Łącznie 455 pozycji. Listę uzupełniono o jeden
  numer VIN, który wskazali sędziowie, a którego autor nie wpisał.
- **Sędzia.** Pozycja jest ukryta, gdy po anonimizacji nie występuje w wyniku jako całe słowo.
  Każdy wynik sprawdzili też trzej niezależni sędziowie, którzy nie pisali pism. Odpowiadali,
  czy pismo można bezpiecznie wysłać do czatu AI, i wskazywali wycieki.
- **Poziom.** Tabele dotyczą poziomu 2 („Dokładniej”, domyślny). Sumy dla poziomów 1 i 3 są niżej.
- **Przed i po.** „Przed” to wersja programu sprzed testu. „Po” to wersja z poprawkami wprowadzonymi
  na podstawie tego testu.

Gwiazdka `*` oznacza pozycję, która po sprawdzeniu nie jest daną osobową: godzinę, miasto
bez adresu, nazwę komendy, numer dyspozytora. Autor pisma wpisał ją na listę na wszelki wypadek.

## Wynik zbiorczy

| Poziom | Ukryte przed | % przed | Ukryte po | % po |
|---|---:|---:|---:|---:|
| 1 Szybko | 432 z 455 | 94,9 | 441 z 455 | 96,9 |
| 2 Dokładniej | 435 z 455 | 95,6 | 443 z 455 | 97,4 |
| 3 Najdokładniej | 435 z 455 | 95,6 | 443 z 455 | 97,4 |

Bez 8 pozycji z gwiazdką zostaje 447 prawdziwych danych osobowych. Na poziomie 2 program ukrył
przed poprawkami 435 z nich (97,3%), a po poprawkach 443 (99,1%).

Pozostałe miary na poziomie 2:

| Miara | Przed | Po |
|---|---:|---:|
| numery osób na 116 prawdziwych osób | 138 | 121 |
| pisma przywrócone z mapy bez jednej zmiany | 30 z 30 | 30 z 30 |
| pisma zablokowane przez kontrolę wyniku | 0 | 0 |
| sędziowie: pisma bezpieczne do wysłania, ocena większością | 28 z 30, wersja pośrednia | nie oceniano ponownie |

Sędziowie oceniali wersję pośrednią. Dwa pisma, które uznali za niebezpieczne, zawierały numer
VIN i numer polisy OC. Oba numery program ukrywa w wersji „po”.

## Wyniki dla każdego pisma

| Pismo | Rodzaj | Danych do ukrycia | Ukryte przed | Ukryte po | % po | Nieukryte po naprawach (przed naprawami) |
|---|---|---|---:|---:|---:|---|
| A01 | Decyzja podatkowa gminy | 13 | 13 | 13 | 100,0 | - |
| A02 | Reklamacja do banku | 12 | 12 | 12 | 100,0 | - |
| A03 | Umowa o pracę | 10 | 10 | 10 | 100,0 | - |
| A04 | Notatka policji z interwencji domowej | 14 | 14 | 14 | 100,0 | - |
| A05 | Karta informacyjna ze szpitala | 12 | 12 | 12 | 100,0 | - |
| A06 | Pozew o zapłatę | 16 | 16 | 16 | 100,0 | - |
| A07 | Protokół zebrania wspólnoty | 10 | 10 | 10 | 100,0 | - |
| A08 | E-mail rekrutacyjny z CV | 10 | 10 | 10 | 100,0 | - |
| A09 | Testament notarialny | 13 | 13 | 13 | 100,0 | - |
| A10 | Opinia wychowawcy na świadectwie | 16 | 16 | 16 | 100,0 | - |
| A11 | Wniosek o 800 plus | 17 | 17 | 17 | 100,0 | - |
| A12 | Pełnomocnictwo notarialne | 16 | 16 | 16 | 100,0 | - |
| A13 | Skarga do Rzecznika Praw Pacjenta | 11 | 11 | 11 | 100,0 | - |
| A14 | Wypowiedzenie umowy najmu | 14 | 14 | 14 | 100,0 | - |
| A15 | Zgłoszenie szkody komunikacyjnej | 18 | 15 | 18 | 100,0 | - („KR 99182”, „WI 7824A”, „POL-99882211/2026”) |
| B01 | Decyzja ZUS o rencie | 10 | 10 | 10 | 100,0 | - |
| B02 | Wezwanie komornika | 14 | 14 | 14 | 100,0 | - |
| B03 | Faktura dla osoby fizycznej | 13 | 13 | 13 | 100,0 | - |
| B04 | E-maile działu kadr | 8 | 8 | 8 | 100,0 | - |
| B05 | Akt oskarżenia (fragment) | 20 | 20 | 20 | 100,0 | - |
| B06 | Opinia psychologiczna | 15 | 15 | 15 | 100,0 | - |
| B07 | Umowa sprzedaży samochodu | 20 | 19 | 20 | 100,0 | - („JTDKB20U0J3123456”) |
| B08 | Postanowienie sądu rodzinnego | 11 | 11 | 11 | 100,0 | - |
| B09 | Wniosek o kredyt hipoteczny | 17 | 17 | 17 | 100,0 | - |
| B10 | Raport z audytu wewnętrznego | 18 | 18 | 18 | 100,0 | - |
| B11 | Zaproszenie na wesele z listą gości | 26 | 22 | 24 | 92,3 | „14:00”*, „Krakowie (30-001)” („osiedlu Słoneczne 12”, „500 333 444”) |
| B12 | Protokół odbioru mieszkania | 16 | 16 | 16 | 100,0 | - |
| B13 | Skarga na sąsiada do spółdzielni | 22 | 17 | 17 | 77,3 | „5 kwietnia ok. 23:30”*, „Komendatu Miejskiego w Poznaniu”*, „dyspozytor nr 47 88 99”*, „m. 10”, „m. 14” |
| B14 | Oświadczenie świadka wypadku | 27 | 21 | 23 | 85,2 | „Gdańsku”*, „16:45”*, „al. Grunwaldzkiej i ul. Podwale Grodzkiego”, „Gdańsku”* („GD12345”, „GD54321”) |
| B15 | List motywacyjny | 16 | 15 | 15 | 93,8 | „Lublinie”* |
| **razem** | 30 pism | **455** | **435** (95,6%) | **443** | **97,4** | |

## Które dane są wykrywane najsłabiej

Rodzaje danych od najsłabiej do najlepiej wykrywanych przed poprawkami.

| Rodzaj danych | Liczba | Ukryte przed | % przed | Ukryte po | % po | Nieukryte przed naprawami |
|---|---:|---:|---:|---:|---:|---|
| godzina | 3 | 0 | 0,0 | 0 | 0,0 | „14:00”*, „5 kwietnia ok. 23:30”*, „16:45”* |
| inne | 1 | 0 | 0,0 | 0 | 0,0 | „dyspozytor nr 47 88 99”* |
| pojazd / polisa | 6 | 0 | 0,0 | 6 | 100,0 | „KR 99182”, „WI 7824A”, „POL-99882211/2026”, „JTDKB20U0J3123456”, „GD12345”, „GD54321” |
| samo nazwisko, miejscowość, nazwa | 34 | 30 | 88,2 | 30 | 88,2 | „Komendatu Miejskiego w Poznaniu”*, „Gdańsku”*, „Gdańsku”*, „Lublinie”* |
| adres | 99 | 94 | 94,9 | 95 | 96,0 | „osiedlu Słoneczne 12”, „Krakowie (30-001)”, „m. 10”, „m. 14”, „al. Grunwaldzkiej i ul. Podwale Grodzkiego” |
| telefon | 37 | 36 | 97,3 | 37 | 100,0 | „500 333 444” |
| NIP | 2 | 2 | 100,0 | 2 | 100,0 | - |
| PESEL | 35 | 35 | 100,0 | 35 | 100,0 | - |
| REGON | 2 | 2 | 100,0 | 2 | 100,0 | - |
| data | 20 | 20 | 100,0 | 20 | 100,0 | - |
| dowód / paszport | 13 | 13 | 100,0 | 13 | 100,0 | - |
| e-mail | 30 | 30 | 100,0 | 30 | 100,0 | - |
| imię i nazwisko | 133 | 133 | 100,0 | 133 | 100,0 | - |
| numer rachunku | 20 | 20 | 100,0 | 20 | 100,0 | - |
| samo imię lub zdrobnienie | 20 | 20 | 100,0 | 20 | 100,0 | - |


## Co poprawiono po teście

1. Telefon w nawiasie, np. „(500 333 444)”.
2. Adres z odmienionym słowem: „przy ulicy”, „na osiedlu”, „alei”, „placu”.
3. Adres bez „ul.” z numerem mieszkania („Świętojańska 45 m. 12, 81-391 Gdynia”) oraz w dwóch
   liniach nagłówka pisma.
4. Numery rejestracyjne pojazdów po „nr rej.”, numery VIN i numery polis po „polisa … nr”.
5. Patroni po „im.” („Szpital im. Mikołaja Kopernika”) nie są ukrywani jako osoby.
6. Zdrobnienie („Kasia”, „Bartek”) dostaje numer jedynej osoby o pełnym imieniu.

Pomiar na 233 próbkach z `tests/korpus/` nie zmienił się po żadnej z tych poprawek.

## Znane słabe miejsca

- Sam numer mieszkania bez ulicy („pani Nowak z m. 10”) zostaje widoczny.
- Kod pocztowy w nawiasie przy odmienionej nazwie miasta („w Krakowie (30-001)”) zostaje widoczny.
- Skrzyżowanie ulic bez numeru („al. Grunwaldzkiej i ul. Podwale Grodzkiego”) zostaje widoczne.
- Godziny nie są ukrywane: nie są daną osobową, chyba że razem z innymi danymi wskazują osobę.
- Samo nazwisko, gdy w piśmie są dwie osoby o tym nazwisku, dostaje osobny numer. Dana jest
  ukryta, ale czat AI widzi o jedną osobę więcej. Program celowo nie zgaduje, o kogo chodzi.
- Dane urzędów i firm (adres siedziby, rachunek, NIP, REGON, numer KRS) są ukrywane. To bezpieczne,
  ale tekst staje się mniej czytelny.

## Ograniczenia testu

- Poprawki powstały na tych samych 30 pismach, więc wynik „po” jest optymistyczny. Rzetelną ocenę
  po poprawkach da dopiero nowy zestaw pism.
- Pisma są fikcyjne i krótkie, od 77 do 244 słów. Prawdziwe dokumenty bywają dłuższe i mniej
  uporządkowane.
- Lista danych do ukrycia pochodzi od autora pisma. Sędziowie znaleźli jedną pozycję spoza listy.
