Jesteś architektem oprogramowania. Projekt open-source (pokazówka na GitHubie): „Cichociemny” – lokalna anonimizacja danych osobowych w tekstach po polsku, zanim trafią do chmurowego AI.

WYMAGANIA
1. Użytkownik wkleja tekst albo wskazuje plik biurowy (docx, odt, xlsx, pptx, pdf, txt, rtf?). Narzędzie zwraca TEN SAM format pliku, z dopiskiem „ZANONIMIZOWANY” na początku treści (i w nazwie pliku).
2. Wykrywanie lokalnym modelem (CPU, GPU jeśli jest): imiona i nazwiska w odmianie, PESEL, NIP, REGON, adresy, telefony, e-maile, IBAN, numery dowodu/paszportu, KRS, daty urodzenia. Kandydaci: LiquidAI LFM2.5-Encoder-350M-PII-Detector, bardsai/eu-pii-anonimization-multilang (XLM-RoBERTa, ONNX INT8), nvidia/gliner-PII, plus reguły z sumami kontrolnymi (PESEL/NIP/REGON/IBAN).
3. Suwak „Jakość wykrywania” = 1, 2 albo 3 przebiegi/modele (szybko vs dokładnie), bez szczegółów technicznych dla użytkownika.
4. Ocena jakości anonimizacji w trakcie: wskaźnik pewności, że wykryto wszystko (zaproponuj WZÓR).
5. Odwracalność: znaczniki numerowane [OSOBA_1], [PESEL_2]..., spójne dla odmian tego samego nazwiska („Kowalski”, „Kowalskiego” -> ta sama osoba), mapa przywracania zapisywana lokalnie (szyfrowana?), żeby po odpowiedzi chmurowego AI przywrócić dane.
6. Formy dystrybucji: (a) aplikacja webowa – lokalny serwer w organizacji (serwer inferencji), (b) aplikacja okienkowa Windows/Mac/Linux (exe/instalator/skrypt z GUI) – standalone albo jako klient serwera, (c) aplikacja mobilna Android.
7. Kluczowe: prosta, szybka, niezawodna, multiplatformowa, wygodna dla osób nietechnicznych (instalacja przez IT), minimalne zasoby, działa lokalnie lub centralnie.
8. Bezpieczeństwo: żadnych sekretów w aplikacji – jeśli jest klucz, to z key vault / pliku sekretów zarządzanego przez system; włamanie do aplikacji nie wydaje sekretów. Dane nigdy nie opuszczają maszyny/serwera.
9. Kod: prosty, bez duplikacji, testy na początku.

PYTANIA (odpowiedz konkretnie, z rekomendacją i uzasadnieniem, maks. ~1200 słów):
A. Języki i technologie: jeden stos czy miks? (np. Python+FastAPI+ONNX Runtime jako rdzeń i serwer; GUI: Tauri/Electron/PySide/webview; Android: ONNX Runtime Mobile w Kotlinie albo tylko klient serwera / PWA). Co daje najmniej kodu i jedno źródło logiki dla 3 platform?
B. Architektura: HLD – komponenty, granice, przepływ danych; jak współdzielić rdzeń między web, desktop i Androidem.
C. Modele: który jako przebieg 1, 2, 3; jak łączyć wyniki (unia, głosowanie); format ONNX/INT8; rozmiary paczek.
D. Wzór oceny jakości anonimizacji (wskaźnik ryzyka resztkowego) – konkretna formuła.
E. Odwracalność: format mapy, spójność odmian (lematyzacja nazwisk polskich?), szyfrowanie mapy.
F. Zachowanie formatu dokumentów: biblioteki do docx/odt/xlsx/pptx/pdf, pułapki (tekst rozbity na runy w docx, PDF).
G. Największe ryzyka i czego NIE robić w MVP.
H. Kamienie milowe (5-7) dla MVP -> v1.
