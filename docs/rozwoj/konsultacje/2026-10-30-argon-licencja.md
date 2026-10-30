# Argon, 2026-10-30: licencja, CITATION i publikacja

Pytania: wybór licencji, czy podpisywać się nazwiskiem, jak oddzielić licencje modeli, minimum dla publicznego repo, czyszczenie historii.

| Uwaga Argona | Co zrobiono |
|---|---|
| MIT. Unlicense/CC0 odpada, bo w prawie polskim nie da się zrzec praw osobistych. Wystarczy pseudonim w linii Copyright | `LICENSE`: MIT, „Copyright (c) 2026 AuCourDe” |
| CITATION.cff wypada, to prośba o wskazanie źródła. Nazwisko daje wiarygodność, ale kosztuje prywatność i przyciąga prośby o pomoc. Rekomendacja: pseudonim albo bez pliku | `CITATION.cff` z pseudonimem AuCourDe; nazwisko do decyzji właściciela |
| LICENSE bez zmian (GitHub rozpoznaje licencję); w README sekcja, że MIT nie obejmuje modeli | README, sekcja „Licencja” |
| Paczka z przerobionym modelem LFM (ONNX) wymaga kopii licencji i NOTICE | przy wydaniu paczek, `docs/WYDANIE.md` |
| Zastrzeżenie o braku gwarancji po polsku w README, krótki SECURITY.md, lista licencji zależności | README, `SECURITY.md`, `docs/LICENCJE.md` |
| Historię gita wyczyścić przed publikacją (nazwa instytucji w ścieżkach, `~`) | `git filter-repo --replace-text`; pełna kopia przed zmianą zostaje prywatnie |
