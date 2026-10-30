Oto 15 zidentyfikowanych scenariuszy podatności w adapterze DOCX oraz mechanizmach anonimizacji projektu Niewidka, posortowanych według wagi (Krytyczne → Ważne → Drobne).

---

### 1. Rozbicie encji na granicy wielu runów (`podziel_segment`) – wyciek końcówki danych
* **Plik:linia:** [`niewidka/formaty/__init__.py:46-66`](file://~/niewidka/niewidka/formaty/__init__.py#L46-L66) (w zw. z [`niewidka/formaty/docx_.py:144-153`](file://~/niewidka/niewidka/formaty/docx_.py#L144-L153))
* **Scenariusz:** Wykryta encja rozciąga się na więcej niż jeden run (np. run 0: `"Jan "`, run 1: `"Kowalski"`). Do zbioru `granice` trafia offset `4` (start runu 1). W pętli `pairwise(punkty)` przedział `(0, 4)` jest zastępowany znacznikiem `[OSOBA_1]`, lecz kolejny przedział `(4, 12)` nie figuruje w słowniku `znaczniki`, przez co gałąź `else` przepisuje `"Kowalski"` z runu 1 jako jawny tekst. Wynik w dokumencie to `[OSOBA_1]Kowalski` (nazwisko wycieka w całości).
* **Waga:** Krytyczne
* **Propozycja poprawki:** Zmodyfikować `podziel_segment`, aby punkty podziału leżące ściśle wewnątrz otwartego przedziału zamiany `(start, koniec)` były pomijane i nie generowały fragmentów z oryginalnego tekstu.

---

### 2. Kody instrukcji pól Worda (`w:instrText`, np. AUTHOR, MERGEFIELD)
* **Plik:linia:** [`niewidka/formaty/docx_.py:133-138`](file://~/niewidka/niewidka/formaty/docx_.py#L133-L138)
* **Scenariusz:** Dokument zawiera pole złożone (`w:fldChar`), np. `<w:instrText> AUTHOR "Jan Kowalski" </w:instrText>` lub `<w:instrText> MERGEFIELD Klient_PESEL </w:instrText>`. Metoda `_segmenty()` wyciąga tekst wyłącznie z węzłów `<w:t>`, całkowicie pomijając `<w:instrText>`. Nawet po zanonimizowaniu buforowanej wartości w `<w:t>`, instrukcja pola w `word/document.xml` pozostaje nienaruszona i ujawnia PII po wciśnięciu Alt+F9 lub odświeżeniu pól w Wordzie.
* **Waga:** Krytyczne
* **Propozycja poprawki:** Dodać ekstrakcję i anonimizację tekstu z węzłów `w:instrText` do segmentów albo usuwać instrukcje pól niosące dane osobowe w `_wyczysc_drzewo()`.

---

### 3. Pola proste `w:fldSimple` z PII w atrybucie `w:instr`
* **Plik:linia:** [`niewidka/formaty/docx_.py:130-140`](file://~/niewidka/niewidka/formaty/docx_.py#L130-L140)
* **Scenariusz:** Dokument zawiera konstrukcję `<w:fldSimple w:instr="AUTHOR &quot;Jan Kowalski&quot;"> <w:r><w:t>Jan Kowalski</w:t></w:r> </w:fldSimple>`. Tekst w `<w:t>` zostaje zamieniony na znacznik, lecz atrybut `w:instr` nie jest parsowany do tekstu segmentu ani czyszczony w drzewie XML. Dane osobowe autora wyciekają w strukturze XML i zostaną przywrócone w treści dokumentu przy pierwszym przeliczeniu pól przez Word.
* **Waga:** Krytyczne
* **Propozycja poprawki:** W `_wyczysc_drzewo()` zanonimizować lub wyczyścić atrybuty `w:instr` w elementach `w:fldSimple`.

---

### 4. Śledzone zmiany – `w:ins` zawierające bezpośrednio `<w:t>` bez `<w:r>`
* **Plik:linia:** [`niewidka/formaty/docx_.py:133-138`](file://~/niewidka/niewidka/formaty/docx_.py#L133-L138)
* **Scenariusz:** Wstawiony tekst znajduje się bezpośrednio w węźle wstawienia: `<w:ins><w:t>Jan Kowalski, PESEL 44051401359</w:t></w:ins>`. Ponieważ `_segmenty()` iteruje wyłącznie po `akapit.iter(_q("r"))`, węzeł `<w:t>` znajdujący się poza `<w:r>` nie trafia do tekstu segmentu, omija detektor PII i trafia do pliku wynikowego w postaci jawnej.
* **Waga:** Krytyczne
* **Propozycja poprawki:** W `_wyczysc_drzewo()` znormalizować strukturę dokumentu, opakowując osierocone węzły `w:t` wewnątrz `w:ins` w standardowy element `w:r`.

---

### 5. Śledzone zmiany – tożsamość autora w atrybutach `w:author`
* **Plik:linia:** [`niewidka/formaty/docx_.py:99-105`](file://~/niewidka/niewidka/formaty/docx_.py#L99-L105)
* **Scenariusz:** Dokument z historią edycji zawiera wstawki `<w:ins w:id="1" w:author="Jan Kowalski" w:date="2026-10-28T10:00:00Z">` oraz znaczniki rewizji formatowania `<w:rPrChange w:author="Anna Nowak">`. Adapter usuwa `w:del`, lecz pozostawia `w:ins` bez modyfikacji atrybutów, wskutek czego dane osobowe autorów poprawek wyciekają w `word/document.xml`.
* **Waga:** Krytyczne
* **Propozycja poprawki:** W `_wyczysc_drzewo()` usuwać atrybuty `w:author` ze wszystkich elementów rewizji (`w:ins`, `w:rPrChange`, `w:pPrChange`) lub spłaszczać `w:ins` do bezpośrednich dzieci akapitu.

---

### 6. Usunięcie `w:del` w komórce tabeli tworzy pusty `w:tc` (uszkodzenie pliku)
* **Plik:linia:** [`niewidka/formaty/docx_.py:99-100`](file://~/niewidka/niewidka/formaty/docx_.py#L99-L100)
* **Scenariusz:** Cała zawartość komórki tabeli została usunięta w trybie śledzenia zmian: `<w:tc><w:del><w:p>...</w:p></w:del></w:tc>`. Usunięcie węzła `w:del` pozostawia pusty tag `<w:tc></w:tc>` bez akapitu, co stanowi naruszenie schematu OOXML (ECMA-376) i skutkuje błędem uszkodzenia pliku ("Word unreadable content") przy próbie otwarcia dokumentu.
* **Waga:** Krytyczne
* **Propozycja poprawki:** Po usunięciu `w:del` weryfikować, czy rodzic nie pozostał pustą komórką `w:tc`, i w razie potrzeby wstawiać pusty akapit `<w:p/>`.

---

### 7. Relacje usuwanych nagłówków/stopek (`word/_rels/header1.xml.rels`) blokują wczytanie
* **Plik:linia:** [`niewidka/formaty/docx_.py:49-66, 79-83`](file://~/niewidka/niewidka/formaty/docx_.py#L49-L83)
* **Scenariusz:** Dokument zawiera nagłówek z grafiką (logo) lub linkiem, co tworzy plik relacji `word/_rels/header1.xml.rels`. Funkcja `_usuwana()` sprawdza `nazwa.startswith("word/header")` (co nie pasuje do ścieżki w `word/_rels/`), a `_dozwolona()` dopuszcza jedynie `word/_rels/document.xml.rels`. W efekcie `wczytaj()` zgłasza `ElementNieobslugiwany`, odrzucając poprawny dokument biznesowy.
* **Waga:** Krytyczne
* **Propozycja poprawki:** Rozszerzyć `_usuwana()` o pliki relacji usuwanych części (np. `word/_rels/(header|footer|comments|footnotes)`).

---

### 8. `word/settings.xml` – wyciek ścieżek szablonów (`w:attachedTemplate`) i autorów ochrony
* **Plik:linia:** [`niewidka/formaty/docx_.py:60, 185-197`](file://~/niewidka/niewidka/formaty/docx_.py#L60-L197)
* **Scenariusz:** Plik `word/settings.xml` znajduje się na allowliście, lecz nie jest w ogóle czyszczony przed zapisem. Dokument utworzony z szablonu zawiera `<w:attachedTemplate>` z pełną ścieżką użytkownika (`C:\Users\jan.kowalski\AppData\Roaming\...`), `<w:writeProtection w:author="Jan Kowalski"/>` lub sekcję `<w:mailMerge>` z nazwą użytkownika bazy danych, które bez zmian trafiają do wyniku.
* **Waga:** Ważne
* **Propozycja poprawki:** Zaimplementować oczyszczanie `word/settings.xml` z węzłów `w:attachedTemplate`, `w:writeProtection`, `w:mailMerge` oraz atrybutów identyfikujących użytkowników.

---

### 9. Nazwy zakładek `w:bookmarkStart w:name="..."`
* **Plik:linia:** [`niewidka/formaty/docx_.py:130-140`](file://~/niewidka/niewidka/formaty/docx_.py#L130-L140)
* **Scenariusz:** Systemy generujące dokumenty tworzą zakładki o nazwach zawierających dane klientów, np. `<w:bookmarkStart w:id="0" w:name="_Jan_Kowalski_PESEL_44051401359"/>`. Ponieważ `_segmenty()` czyta wyłącznie elementy `<w:t>`, atrybut `w:name` nie jest skanowany ani czyszczony i w całości wycieka w wynikowym XML.
* **Waga:** Ważne
* **Propozycja poprawki:** W `_wyczysc_drzewo()` anonimizować wartości atrybutu `w:name` w elementach `w:bookmarkStart` (z pominięciem zakładek systemowych, np. `_GoBack`).

---

### 10. Formularze i Content Controls (SDT) – wyciek z `w:alias` i `w:tag`
* **Plik:linia:** [`niewidka/formaty/docx_.py:130-140`](file://~/niewidka/niewidka/formaty/docx_.py#L130-L140)
* **Scenariusz:** Formularz bankowy zawiera kontrolki SDT: `<w:sdt><w:sdtPr><w:alias w:val="Jan Kowalski"/><w:tag w:val="44051401359"/></w:sdtPr><w:sdtContent><w:p><w:r><w:t>PL</w:t></w:r></w:p></w:sdtContent></w:sdt>`. Treść w `w:sdtContent` zostaje zanonimizowana, lecz metadane kontrolki w `w:alias` i `w:tag` nie są pobierane do segmentów i przechodzą jawnie do pliku wyjściowego.
* **Waga:** Ważne
* **Propozycja poprawki:** W `_wyczysc_drzewo()` usuwać lub czyścić elementy `w:alias` i `w:tag` wewnątrz wszystkich `w:sdtPr`.

---

### 11. Zewnętrzne adresy URL w relacjach (`http/https`) zawierające parametry PII
* **Plik:linia:** [`niewidka/formaty/docx_.py:121`](file://~/niewidka/niewidka/formaty/docx_.py#L121)
* **Scenariusz:** Hiperłącze wskazuje na intranet lub formularz: `https://portal.firma.pl/ankieta?pesel=44051401359&nazwisko=Kowalski`. Linia 121 zachowuje linki `http/https` bez zmian. Tekst wyświetlany w dokumencie to np. `"Link"`, więc detektor nie wykrywa encji w tekście akapitu, a pełne dane osobowe wyciekają w `word/_rels/document.xml.rels`.
* **Waga:** Ważne
* **Propozycja poprawki:** W `_przefiltruj_rels()` usuwać parametry query string z zewnętrznych adresów URL w relacjach.

---

### 12. Obiekty graficzne – atrybuty `name` i `title` w DrawingML oraz kształty VML
* **Plik:linia:** [`niewidka/formaty/docx_.py:116-117`](file://~/niewidka/niewidka/formaty/docx_.py#L116-L117)
* **Scenariusz:** Wstawiony skan dokumentu lub podpis posiada właściwości `<wp:docPr name="Skan_Jan_Kowalski_PESEL.png" descr="..." title="Jan Kowalski"/>` lub VML `<v:shape title="Jan Kowalski">`. Linia 117 czyści jedynie atrybut `descr` w DrawingML, pozostawiając `name` oraz `title` nienaruszone, co powoduje wyciek PII z metadanych grafiki.
* **Waga:** Ważne
* **Propozycja poprawki:** Wyczyścić również atrybuty `name` i `title` w `wp:docPr` oraz atrybuty tekstowe w elementach graficznych VML.

---

### 13. Blokada dokumentów z `word/people.xml`, `docProps/custom.xml` i `word/glossary`
* **Plik:linia:** [`niewidka/formaty/docx_.py:32-40, 51-66`](file://~/niewidka/niewidka/formaty/docx_.py#L32-L66)
* **Scenariusz:** Dokumenty z Office 365 zawierają `word/people.xml` (autorzy komentarzy i e-maile), systemy obiegu dodają `docProps/custom.xml` (właściwości niestandardowe), a szablony zawierają `word/glossary/document.xml` (Szybkie części/AutoTekst). Żadna z tych części nie jest w `USUWANE` ani w `_dozwolona()`, co wywołuje `ElementNieobslugiwany`; z kolei dopisanie ich do allowlisty bez mechanizmu czyszczenia spowoduje bezpośredni wyciek PII.
* **Waga:** Ważne
* **Propozycja poprawki:** Dodać `word/people.xml`, `docProps/custom.xml` oraz `word/glossary/` do krotki `USUWANE` i usuwać je z wynikowego archiwum oraz `[Content_Types].xml`.

---

### 14. Hiperłącza z wewnętrzną kotwicą (`w:hyperlink w:anchor="..."`)
* **Plik:linia:** [`niewidka/formaty/docx_.py:118-126`](file://~/niewidka/niewidka/formaty/docx_.py#L118-L126)
* **Scenariusz:** Dokument posiada odsyłacz do sekcji klienta: `<w:hyperlink w:anchor="Jan_Kowalski_PESEL"><w:r><w:t>profil</w:t></w:r></w:hyperlink>`. Ponieważ element nie posiada `r:id`, zmienna `id_relacji` przyjmuje `None`, warunek `cel is not None` jest fałszywy i odsyłacz nie jest rozpakowywany, a wartość kotwicy zawierająca PII pozostaje w wynikowym pliku.
* **Waga:** Drobne
* **Propozycja poprawki:** W `_wyczysc_drzewo()` usuwać lub anonimizować wartość atrybutu `w:anchor` w elementach `w:hyperlink`.

---

### 15. Smart Tagi – metadane w atrybutach `w:smartTagPr`
* **Plik:linia:** [`niewidka/formaty/docx_.py:130-140`](file://~/niewidka/niewidka/formaty/docx_.py#L130-L140)
* **Scenariusz:** Dokument zawiera strukturę Smart Tag: `<w:smartTag w:element="PersonName"><w:smartTagPr><w:attr w:name="GivenName" w:val="Jan"/><w:attr w:name="FamilyName" w:val="Kowalski"/></w:smartTagPr><w:r><w:t>Jan Kowalski</w:t></w:r></w:smartTag>`. Po podstawieniu znacznika pod `<w:t>` dane imienia i nazwiska w atrybutach `<w:attr>` wewnątrz `w:smartTagPr` pozostają nienaruszone w pliku wyjściowym.
* **Waga:** Drobne
* **Propozycja poprawki:** W `_wyczysc_drzewo()` rozpakować elementy `w:smartTag` do ich dzieci tekstowych i usunąć węzły `w:smartTagPr`.

---

> [!NOTE]
> Warto zauważyć, że funkcja weryfikująca [`niewidka/kontrola.py:kontroluj()`](file://~/niewidka/niewidka/kontrola.py#L24-L37) ponownie wczytuje dokument przez ten sam adapter (`adapter.wczytaj(dane)`), co oznacza, że cierpi na dokładnie te same martwe punkty ekstrakcji tekstu i raportuje wynik jako czysty (0 ostrzeżeń), stwarzając fałszywe poczucie bezpieczeństwa.
