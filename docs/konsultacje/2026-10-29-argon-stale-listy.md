# Argon (model „4 Argon”, Gemini www), 2026-10-29: stałe listy i znacznik INNE

Pytanie: krytyczna ocena poprawek w podglądzie, nowych stałych list i decyzji, by nie zmieniać typu znacznika
„Zielony Dąb” (model uznał go za OSOBA_3). Odpowiedź streszczona, z decyzją przy każdym punkcie.

| # | Uwaga Argona | Decyzja |
|---|---|---|
| 1 | Zostawienie OSOBA dla nazwy referatu psuje odpowiedź chmurowego AI („Pan [OSOBA_3]”). Pozwolić zmienić typ w menu znacznika, bez przenumerowania pozostałych; komunikat ma mówić, że fragment jest już ukryty, i odsyłać do znacznika. | Przyjęte: „Oznacz jako inne dane” w panelu znacznika (nowy numer INNE, luka w numeracji OSOBA), nowy komunikat. |
| 2 | Rdzeń końcówkowy: fałszywe dopasowania krótkich słów, oboczności (Dąb/Dębu) nie łączone. Morfeusz albo minimalna długość rdzenia. | Częściowo już jest (całe słowa, krótkie słowa bez odmian). Oboczności zostają jako znane ograniczenie do lematyzacji (SIMPLIFICATION w poprawki.py). |
| 3 | „Ukrywaj zawsze” przy `tylko_administrator` i przy sprzeczności z listą „Nigdy” administratora. | Przycisk był już ukryty przy `tylko_administrator`; dodana blokada z komunikatem przy sprzeczności z listą administratora. |
| 4 | „Nigdy” tylko przy równości całego fragmentu jest za sztywne (przyimki, dłuższe nazwy). | Odłożone: zostaje bezpieczna równość (fałszywe zdjęcie = wyciek). Opisane w LOGIKA.md. |
| 5 | Znacznik z listy „Zawsze” bez „To nie dane” to ślepy zaułek (cytat, lista narzucona przez administratora). | Przyjęte: „Odkryj tylko w tym dokumencie”. |
| 6 | Wygaśnięcie poprawek po 15 minutach może skończyć się skopiowaniem tekstu bez poprawek. | Odrzucone po sprawdzeniu: podgląd zostaje z ostatnim przeliczonym wynikiem (z poprawkami), wygasa tylko możliwość dalszych zmian; interfejs mówi to wprost. |
| 7 | Suma kontrolna przepuszcza ok. 1 na 10 losowych ciągów cyfr (sygnatury, KW, działki); blokada „To nie dane” dla PESEL/NIP uniemożliwia odsłonięcie takiego numeru. Zezwolić jednorazowo z potwierdzeniem. | Do decyzji właściciela (pytanie w raporcie). |
