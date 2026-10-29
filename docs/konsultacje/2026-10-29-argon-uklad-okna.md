# Argon (model „4 Argon”), 2026-10-29: układ aplikacji okienkowej

Wsad: zrzuty okna 1084x821 (start, podgląd, cała strona 2252 px), `C:\Users\uzytkownik\Desktop\C\Niewidka - okno przed zmianą układu.jpg`.

Najważniejsze zalecenia (streszczenie):
1. Wysokość 100vh, bez przewijania całej strony od 1100x800 wzwyż. Nagłówek ok. 56 px w jednym wierszu: logo, zakładki, zdanie o prywatności.
2. Dwa panele 40/60 (lewy min. 380 px). Lewy: pole tekstu z wczytaniem pliku w rogu (przeciąganie zostaje), jakość jako przełącznik segmentowy Szybko / Dokładnie / Najdokładniej, „Ukryj dane” na całą szerokość, pod spodem narzędzia korekty („Ukryj wszędzie”, zwinięte „Twoje poprawki (n)”).
3. Prawy: pasek podsumowania w jednym wierszu (pastylki „3 osoby, 1 PESEL…”) z „Szczegóły i ryzyko” do rozwinięcia; podgląd zajmuje całą resztę wysokości i jako jedyny się przewija; pasek akcji przyklejony na dole: Kopiuj tekst, Pobierz dokument (główny), Pobierz mapę.
4. Tabele „Ukryte dane” i „Szacowane ryzyko” oraz duże zielone i żółte ramki zwinąć do jednej etykiety stanu i rozwijanych szczegółów.
5. Stan pusty prawego panelu: „Jak to działa” w 3 krokach zamiast pustki; znika po pierwszym wyniku.
6. Poniżej 900 px: jedna kolumna; po ukryciu wejście zwija się do paska „Wczytano tekst (n znaków) [Zmień]”, wynik zajmuje ekran.
7. Najgorsze problemy dziś: zmarnowana szerokość i 2252 px wysokości; metryki testowe i ramki wypychają podgląd w dół; rozproszone akcje (Kopiuj nad podglądem, Ukryj wszędzie pod nim, Pobierz na samym dole).

Decyzje: wdrażamy 1-7, z wyjątkami: blokada kontroli (STOP) zostaje widoczna w całości, bo to bezpieczeństwo; ryzyko pominięcia zostaje dostępne w „Szczegółach” (wymóg właściciela „wzór na pewność”).
