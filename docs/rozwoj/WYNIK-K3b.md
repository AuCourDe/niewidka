# WYNIK K3b — zamknięcie wycieków DOCX + kontrola zapisu niezależna od adaptera

Data: 2026-10-28. Zakres: 15 punktów przeglądu DOCX (`docs/konsultacje/05-przeglad-docx-gemini.md`)
+ notka pod przeglądem (kontrola przez ten sam adapter ma te same martwe punkty).
Metoda: TDD — dla każdego punktu plik wzorcowy w generatorze + test, który padał
(dane osobowe obecne w wyniku), potem poprawka. Wszystkie 15 punktów okazało się
PRAWDZIWYCH — żaden nie został odrzucony jako fałszywy.

## Krok 1: kontrola zapisu niezależna od adaptera (najważniejszy)

`niewidka/kontrola.py`: po skanie segmentów (adapter) dokument przechodzi **druga
siatkę**: archiwa ZIP są skanowane SUROWO, część po części — wszystkie węzły tekstowe
i wartości **wszystkich atrybutów** części XML/rels bezpiecznym parserem
(`resolve_entities=False, no_network=True`), części binarne bajt po bajcie. Ta sama
warstwa szuka **oryginałów z mapy** (`ORYGINAL`): każdy oryginał obecny gdziekolwiek
w archiwum = ostrzeżenie krytyczne, blokujące status „zablokowany" w rdzeniu.
Rdzeń przekazuje oryginały z wystąpień i form wpisów; API serializuje `czesc`.

- Dedup per (typ, fragment, część) — to samo znalezisko w dwóch częściach to dwa wycieki.
- `DATA` wyłączone ze skanu surowego: reguła daty krzyczałaby na metadane techniczne
  (w:date rewizji, stała `1980-01-01` w core.xml); prawdziwe daty wrażliwe łapie
  warstwa oryginałów z mapy. Dowód: `TestSkanSurowy::test_czysty_wynik_z_oryginalami_zero_ostrzezen`.
- Testy: `tests/test_kontrola.py::TestSkanSurowy` (4), rdzeń:
  `test_kontrola_oryginal_z_mapy_w_czesci_nieczytanej_blokuje` — PESEL ukryty w
  `word/media/skrytka.bin` (adapter nie parsuje) → `ORYGINAL` + status `zablokowany`.

## Punkt po punkcie (przegląd Gemini)

| Pkt | Werdykt | Poprawka | Test (RED → GREEN) |
|---|---|---|---|
| 1 rozbicie encji na runy | prawdziwy | `podziel_segment`: punkt podziału wewnątrz przedziału zamiany nie przepisuje końcówki (wcześniej wynik `[OSOBA_1]Kowalski`) | `TestPodzielSegment::test_zamiana_przez_granice_runu_nie_przepisuje_koncowki` |
| 2 `w:instrText` | prawdziwy | instrukcja pola usuwana, **wynik pola zostaje jako tekst** (zgodnie z zleceniem) | `test_instrText_usuniete_wynik_pola_zostaje` |
| 3 `w:fldSimple w:instr` | prawdziwy | atrybut `w:instr` czyszczony, wynik pola zostaje | `test_fldSimple_bez_instr` |
| 4 `w:ins` z `w:t` bez `w:r` | prawdziwy | normalizacja: osierocone `w:t` opakowane w `w:r` → tekst **wchodzi do segmentów** i detekcji | `test_ins_osierocone_wt_wchodzi_do_segmentow` |
| 5 `w:author`/`w:initials`/`w:date` | prawdziwy | akceptacja zmian: `w:ins` rozpakowane, `w:del` usuwane (było), author/date/initials usuwane ze wszystkich elementów | `test_atrybuty_rewizji_czyste` |
| 6 pusty `w:tc` po `w:del` | prawdziwy | gwarancja w zapisie: każda `w:tc` bez `w:p` dostaje pusty akapit | `test_komorka_po_del_ma_akapit_i_plik_poprawny` |
| 7 relacje usuwanych części | prawdziwy | ogólna reguła: `*_rels/X.rels` dziedziczy los części X (nagłówek → relacje nagłówka usuwane, settings → relacje dozwolone) | `test_rels_usuwanych_czesci_nie_blokuja_i_znikaja` |
| 8 `settings.xml` | prawdziwy | usuwane `attachedTemplate`, `documentProtection`, `writeProtection`, `mailMerge`, `rsids` + atrybuty `rsid*`; relacje settings bez wskazania znikają (ścieżka `jan.kowalski` z szablonu) | `test_settings_czyste` |
| 9 nazwy zakładek | prawdziwy | `w:name` → neutralne `_Bm1..` (deterministycznie); systemowe `_*` zostają | `test_zakladki_i_anchor_neutralne` |
| 10 SDT alias/tag | prawdziwy | węzły `w:alias`/`w:tag` usuwane | `test_sdt_alias_tag_czyste` |
| 11 query string w URL | prawdziwy | zewnętrzne URL relacji obcinane po `?` i `#` (domena zostaje) | `test_query_string_w_rels_obciete` |
| 12 docPr name/title + VML | prawdziwy | `wp:docPr` name/title/descr → puste; VML title/alt/descr usuwane | `test_docpr_i_vml_czyste` |
| 13 people/custom/glossary | prawdziwy | `word/people`, `docProps/custom`, `word/glossary` w `USUWANE` (+Content_Types +relacje, też root) | `test_people_custom_glossary_usuwane` |
| 14 anchor hiperłączy | prawdziwy | `w:anchor` neutralizowany tą samą mapą co zakładki; nieznany → `_Bm0` | `test_zakladki_i_anchor_neutralne` |
| 15 smartTag | prawdziwy | `w:smartTag` rozpakowane (treść zostaje), `w:smartTagPr` z `w:attr` usunięte | `test_smarttag_rozpakowany` |

Notka pod przeglądem (kontrola cierpi na te same martwe punkty co adapter) — potwierdzona
i załatwiona przez krok 1: kontrola widzi surowe archiwum niezależnie od adaptera.

## Krok 3: poprawność wyników

`tests/test_formaty.py::TestPoprawnoscWyniku` (3 testy): wynik pełnych pułapek,
wynik podstawowego wzorca i dokument **po pełnym cyklu ukryj/przywóć** — python-docx
otwiera bez „unreadable content", XML poprawny, każda `w:tc` ma `w:p`.

Znalezisko kroku 3 (bonus): python-docx nosi `customXml/item1.xml` w szablonie;
adapter usuwał część, ale relacja `Target="../customXml/item1.xml"` przetrwała filtr
i psuła otwarcie wyniku. Naprawa przyczyny: `_relacja_celu_w` rozwiązuje ścieżki
względne przez `posixpath.normpath`.

## Pełny zestaw

```
NIEWIDKA_MODELE_KATALOG=~/models/niewidka .venv/bin/python -m pytest tests/ -q
314 passed, 1 xfailed in 26.97s
```

Ruff: pliki K3b czyste (`All checks passed`). 4 pozostałe błędy ruff leżą w
`tests/test_detektory.py` — plik w toku równoległej sesji K2d (słownik imion),
poza zakresem K3b.

## Uwagi

- Test rdzenia K3b pierwotnie wstrzykiwał PESEL w `settings.xml`; po naprawie pkt 8
  settings przestał wyciekać (czyli poprawka działa), pułapka przeniesiona do
  `word/media/skrytka.bin` — części, której adapter nigdy nie parsuje i nie czyści.
- Commity: `75934bc` (krok 1), `343eb80` (pkt 1), `2a74061` (pkt 2-6), `57fce36` (pkt 7),
  `baa79bf` (pkt 8), `97cdd18` (pkt 9-15), `f0da419` (krok 3).
