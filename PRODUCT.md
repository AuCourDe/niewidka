# Niewidka

Lokalna anonimizacja danych osobowych w polskich dokumentach: tekst albo plik (TXT,
DOCX) wchodzi, na wyjściu jest ten sam format z danymi zastąpionymi znacznikami plus
zaszyfrowana mapa przywracania (`.nwidka`).

**Odbiorca:** urzędnik i pracownik biurowy — osoba nietechniczna, która musi wysłać
pismo na zewnątrz i nie może w nim zostawić personaliów. Komunikacja w całości po polsku,
bez żargonu technicznego.

**Twardy ogranicznik:** wszystko dzieje się na jednym komputerze — nasłuch 127.0.0.1,
mode lokalne, brak zewnętrznych wywołań, interfejs bez frameworka i bez CDN (font w repo),
działa offline. Sekret mapy tylko z keyring albo pliku 0600.

**Gotowe znaczy:** wklejony tekst albo dokument przechodzi ukryj → wynik z zaślepkami
→ pobranie wyniku i mapy → przywrócenie odtwarza oryginał; kontrola jakości wyraźnie
blokuje wynik z podejrzanymi fragmentami („nie wolno wysyłać”).
