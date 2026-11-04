# Anonymisation test results on 30 documents

Test of 2026-11-04. It checks how much personal data the program hides in realistic Polish
documents it has never seen. All data in the documents is fictional.

## How the test was run

- **Documents.** Two independent text generators wrote 15 documents each: decisions, contracts,
  complaints, police notes, medical records, e-mail correspondence, a will, an invoice and more.
  Hard cases were added on purpose: surnames that are common words (Kot, Lis, Wróbel, Zając),
  grammatical cases, diminutives, double-barrelled surnames, two people with the same surname,
  initials, addresses without „ul.”, numbers written in different ways.
- **List of data to hide.** The author of each document listed all personal data exactly as it
  appears in the text, each inflected form separately. 455 items in total. One VIN number, found by
  the judges and missing from the author's list, was added.
- **Judge.** An item counts as hidden when it no longer appears in the result as a whole word.
  Three independent judges, who did not write the documents, also checked every result. They said
  whether the document could be safely sent to a chat AI and pointed out leaks.
- **Level.** The tables refer to level 2 („Dokładniej”, the default). Totals for levels 1 and 3 are below.
- **Before and after.** „Before” is the program version from before the test. „After” is the version
  with the fixes made because of this test.

An asterisk `*` marks an item that is not personal data on closer review: a time of day, a city
without an address, a police unit name, a dispatcher number. The author listed it as a precaution.

## Summary

| Level | Hidden before | % before | Hidden after | % after |
|---|---:|---:|---:|---:|
| 1 Fast | 432 of 455 | 94.9 | 441 of 455 | 96.9 |
| 2 More thorough | 435 of 455 | 95.6 | 443 of 455 | 97.4 |
| 3 Most thorough | 435 of 455 | 95.6 | 443 of 455 | 97.4 |

Without the 8 asterisk items, 447 real personal data items remain. At level 2 the program hid
435 of them before the fixes (97.3%) and 443 after the fixes (99.1%).

Other measures at level 2:

| Measure | Before | After |
|---|---:|---:|
| person numbers for 116 real people | 138 | 121 |
| documents restored from the map without a single change | 30 of 30 | 30 of 30 |
| documents blocked by the result check | 0 | 0 |
| judges: documents safe to send, majority vote | 28 of 30, intermediate version | not rated again |

The judges rated an intermediate version. The two documents they found unsafe contained a VIN and
an insurance policy number. The „after” version hides both.

## Results per document

| Document | Type | Data to hide | Hidden before | Hidden after | % after | Not hidden after fixes (before fixes) |
|---|---|---|---:|---:|---:|---|
| A01 | Municipal tax decision | 13 | 13 | 13 | 100.0 | - |
| A02 | Complaint to a bank | 12 | 12 | 12 | 100.0 | - |
| A03 | Employment contract | 10 | 10 | 10 | 100.0 | - |
| A04 | Police note, domestic intervention | 14 | 14 | 14 | 100.0 | - |
| A05 | Hospital discharge summary | 12 | 12 | 12 | 100.0 | - |
| A06 | Payment claim (lawsuit) | 16 | 16 | 16 | 100.0 | - |
| A07 | Housing community minutes | 10 | 10 | 10 | 100.0 | - |
| A08 | Recruitment e-mail with CV | 10 | 10 | 10 | 100.0 | - |
| A09 | Notarial will | 13 | 13 | 13 | 100.0 | - |
| A10 | Teacher's opinion on a school report | 16 | 16 | 16 | 100.0 | - |
| A11 | Child benefit application | 17 | 17 | 17 | 100.0 | - |
| A12 | Notarial power of attorney | 16 | 16 | 16 | 100.0 | - |
| A13 | Complaint to the Patient Ombudsman | 11 | 11 | 11 | 100.0 | - |
| A14 | Lease termination notice | 14 | 14 | 14 | 100.0 | - |
| A15 | Motor damage claim | 18 | 15 | 18 | 100.0 | - („KR 99182”, „WI 7824A”, „POL-99882211/2026”) |
| B01 | Social insurance pension decision | 10 | 10 | 10 | 100.0 | - |
| B02 | Bailiff's summons | 14 | 14 | 14 | 100.0 | - |
| B03 | Invoice to a private person | 13 | 13 | 13 | 100.0 | - |
| B04 | HR department e-mails | 8 | 8 | 8 | 100.0 | - |
| B05 | Indictment (excerpt) | 20 | 20 | 20 | 100.0 | - |
| B06 | Psychological opinion | 15 | 15 | 15 | 100.0 | - |
| B07 | Car sale agreement | 20 | 19 | 20 | 100.0 | - („JTDKB20U0J3123456”) |
| B08 | Family court order | 11 | 11 | 11 | 100.0 | - |
| B09 | Mortgage application | 17 | 17 | 17 | 100.0 | - |
| B10 | Internal audit report | 18 | 18 | 18 | 100.0 | - |
| B11 | Wedding invitation with guest list | 26 | 22 | 24 | 92.3 | „14:00”*, „Krakowie (30-001)” („osiedlu Słoneczne 12”, „500 333 444”) |
| B12 | Apartment handover protocol | 16 | 16 | 16 | 100.0 | - |
| B13 | Complaint about a neighbour | 22 | 17 | 17 | 77.3 | „5 kwietnia ok. 23:30”*, „Komendatu Miejskiego w Poznaniu”*, „dyspozytor nr 47 88 99”*, „m. 10”, „m. 14” |
| B14 | Road accident witness statement | 27 | 21 | 23 | 85.2 | „Gdańsku”*, „16:45”*, „al. Grunwaldzkiej i ul. Podwale Grodzkiego”, „Gdańsku”* („GD12345”, „GD54321”) |
| B15 | Cover letter | 16 | 15 | 15 | 93.8 | „Lublinie”* |
| **total** | 30 documents | **455** | **435** (95.6%) | **443** | **97.4** | |

## Which data is detected worst

Kinds of data from the worst to the best detected before the fixes.

| Kind of data | Count | Hidden before | % before | Hidden after | % after | Not hidden before fixes |
|---|---:|---:|---:|---:|---:|---|
| time of day | 3 | 0 | 0.0 | 0 | 0.0 | „14:00”*, „5 kwietnia ok. 23:30”*, „16:45”* |
| other | 1 | 0 | 0.0 | 0 | 0.0 | „dyspozytor nr 47 88 99”* |
| vehicle / insurance policy | 6 | 0 | 0.0 | 6 | 100.0 | „KR 99182”, „WI 7824A”, „POL-99882211/2026”, „JTDKB20U0J3123456”, „GD12345”, „GD54321” |
| surname alone, place, name | 34 | 30 | 88.2 | 30 | 88.2 | „Komendatu Miejskiego w Poznaniu”*, „Gdańsku”*, „Gdańsku”*, „Lublinie”* |
| address | 99 | 94 | 94.9 | 95 | 96.0 | „osiedlu Słoneczne 12”, „Krakowie (30-001)”, „m. 10”, „m. 14”, „al. Grunwaldzkiej i ul. Podwale Grodzkiego” |
| phone | 37 | 36 | 97.3 | 37 | 100.0 | „500 333 444” |
| NIP (tax ID) | 2 | 2 | 100.0 | 2 | 100.0 | - |
| PESEL | 35 | 35 | 100.0 | 35 | 100.0 | - |
| REGON | 2 | 2 | 100.0 | 2 | 100.0 | - |
| date | 20 | 20 | 100.0 | 20 | 100.0 | - |
| ID card / passport | 13 | 13 | 100.0 | 13 | 100.0 | - |
| e-mail | 30 | 30 | 100.0 | 30 | 100.0 | - |
| first and last name | 133 | 133 | 100.0 | 133 | 100.0 | - |
| bank account | 20 | 20 | 100.0 | 20 | 100.0 | - |
| first name or diminutive alone | 20 | 20 | 100.0 | 20 | 100.0 | - |


## What was fixed after the test

1. A phone number in parentheses, e.g. „(500 333 444)”.
2. An address with an inflected street word: „przy ulicy”, „na osiedlu”, „alei”, „placu”.
3. An address without „ul.” with a flat number („Świętojańska 45 m. 12, 81-391 Gdynia”) and an
   address split over two lines of a letter header.
4. Vehicle registration plates after „nr rej.”, VIN numbers and insurance policy numbers after „polisa … nr”.
5. Patrons after „im.” („Szpital im. Mikołaja Kopernika”) are no longer hidden as people.
6. A diminutive („Kasia”, „Bartek”) gets the number of the only person with the full first name.

The measurement on 233 samples from `tests/korpus/` did not change after any of these fixes.

## Known weak spots

- A flat number alone, without a street („pani Nowak z m. 10”), stays visible.
- A postal code in parentheses next to an inflected city name („w Krakowie (30-001)”) stays visible.
- A street crossing without a number („al. Grunwaldzkiej i ul. Podwale Grodzkiego”) stays visible.
- Times of day are not hidden: they are not personal data unless they identify a person together with other data.
- A bare surname, when two people in the document share it, gets a separate number. The data is
  hidden, but the chat AI sees one person too many. The program deliberately does not guess.
- Data of offices and companies (address, account, NIP, REGON, KRS number) is hidden. This is safe
  but makes the text less readable.

## Limits of the test

- The fixes were made on the same 30 documents, so the „after” result is optimistic. Only a new
  set of documents will give a fair measurement after the fixes.
- The documents are fictional and short, 77 to 244 words. Real documents are often longer and less tidy.
- The list of data to hide comes from the document's author. The judges found one item missing from it.
