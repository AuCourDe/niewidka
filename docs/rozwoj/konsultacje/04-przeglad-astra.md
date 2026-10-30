# Przegląd adwersarialny HLD/LLD — Astra (2026-10-28 00:25, 2 min 28 s)
Rozmowa: https://chatgpt.com/c/6ae12958-2c28-83eb-97e4-ec775bda54b9 (streszczenie orkiestratora, nie werbatim)

KRYTYCZNE
1. Scalanie: „unia” w HLD vs „wybór zwycięzcy” w LLD. Zakresy [0,12) i [8,20): wybór jednego zostawia 12–20 jawne. -> Maskowany obszar = SUMA wszystkich zaakceptowanych zakresów; typ wybierany osobno. Test tej własności.
2. Przywracanie po kolejności wystąpień nie działa po odpowiedzi AI (zdania usunięte/przestawione). -> Stabilne identyfikatory osoby i wariantu, np. [OSOBA_1_F2]; bez zgadywania po pozycji. Obietnica „odtworzysz oryginał” tylko dla danych zastąpionych.
3. Mapa może należeć do innego dokumentu (wspólne [OSOBA_1] -> ciche podstawienie cudzych personaliów). -> Mapa wiąże się z dokumentem (identyfikator zadania w znacznikach lub nagłówku, lista dozwolonych identyfikatorów; nieznane = błąd).
4. LAN zamiast uwierzytelniania; wspólny klucz = każdy z cudzą mapą może ją odszyfrować przez /api/przywroc. -> Uwierzytelnianie, właściciel mapy, autoryzacja odszyfrowania; HTTPS w LAN (wymaga go też service worker PWA); lokalnie token sesji + walidacja Host/Origin.
5. Czyszczenie nie obejmuje całego pliku: hiperłącza, pola tekstowe, teksty alternatywne, custom XML, miniatury, nieużywane części archiwum, nazwa pliku. -> Profil dozwolonej struktury per format (allowlist): każda inna część przetworzona, usunięta albo blokada. Nazwa wyniku neutralna: ZANONIMIZOWANY_<krótki-id>.<ext>.
6. XLSX tylko komórki tekstowe: PESEL/telefon jako liczby, formuły, wartości w cache. -> Skanować liczby (formatowane jak w arkuszu), formuły i cache.
7. PDF mieszany (część tekst, część skan) przejdzie kontrolę „ma warstwę tekstową”. -> W MVP blokować obrazy i profile mieszane; redakcja PyMuPDF (apply_redactions + pełny zapis + garbage), nie adnotacje.
8. Kontrola eksportu tylko na poziomie 3, a wyciek = ostrzeżenie. -> Weryfikacja zapisu ZAWSZE (każdy poziom); poziom 3 = rozszerzone wykrywanie; nowe podejrzenia blokują status „ukończony”.

WAŻNE
9. Wskaźnik dokumentu premiuje ślepotę (0 encji -> 100). R95 per typ ≠ ryzyko dokumentu. -> Usunąć procentową heurystykę; pokazywać R95 z kalibracji dla poziomu + listę ostrzeżeń.
10. Grupowanie osób: domyślnie NIE łączyć niejednoznacznych („J. Kowalski”, dwie osoby o tym samym nazwisku); podgląd „połącz/rozdziel”; heurystykę sprawdzić na kontrprzykładach.
11. Segmenty odcinają kontekst (etykieta w jednej komórce, wartość w drugiej). -> Rozdzielić jednostkę zapisu od okna detekcji; kontekst z sąsiednich elementów, mapowanie znak -> źródło, segment_id.
12. „Tylko RAM” nieuzasadnione: upload FastAPI może zapisać plik tymczasowy; no-store nie czyści DOM. -> Kontrola buforowania multipart, plików tymczasowych; czyszczenie sesji w UI; nie obiecywać więcej, niż zmierzone.
13. Limity: ograniczać przed buforowaniem, rozmiar po dekompresji (zip bomb), liczbę elementów, pamięć; parser bez kluczy i sieci, przerywalny.
14. Detektory: wspólny Protocol, ale osobne adaptery (BIO/BIOES, tokeny specjalne, normalizacja); testy zgodności zakresów; błędna suma kontrolna nie może automatycznie wykluczać danych (może to literówka w prawdziwym PESEL); manifest model+tokenizer+etykiety z sumą SHA.
15. Za szeroki MVP (6 formatów, 3 kanały, 2 modele) bez kryteriów odbioru. -> Zawęzić MVP.
