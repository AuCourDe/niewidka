# Niewidka: guide

[Polski](PRZEWODNIK.md) · **English**

What the program can do, how it works inside and how to deploy it. The click-by-click guide is
in `docs/INSTRUKCJA.en.md`, all settings are in `docs/KONFIGURACJA.en.md`. The interface is in Polish,
so button and level names are given in Polish with an English gloss on first use.

## What it is for

You want an AI chat to summarize a letter, improve a reply to a complaint or prepare
a note. The letter contains personal data, so you cannot send it. Niewidka replaces this data
with placeholders and, after the chat replies, puts it back.

```
Jan Kowalski, PESEL 44051401359, ul. Lipowa 5, Gdańsk
          ↓ Ukryj
[OSOBA_1], PESEL [PESEL_1], [ADRES_1]
          ↓ the AI chat works on the text with placeholders
          ↓ Przywróć
Jan Kowalski, PESEL 44051401359, ul. Lipowa 5, Gdańsk
```

## What it detects

| Placeholder | What it is | How it is detected |
|---|---|---|
| `OSOBA` | first and last names, also in inflected forms | language model, at level 3 also the GUS first-name dictionary |
| `PESEL`, `NIP`, `REGON`, `IBAN`, `KARTA` | numbers with a checksum, an account number also without „PL” | rules and checksum |
| `DOKUMENT` | ID card and passport numbers | rules; for an ID card also the checksum |
| `ADRES`, `TELEFON`, `EMAIL`, `DATA` | addresses, phone numbers, e-mails, dates | rules and model |
| `IP`, `SWIFT`, `LOGIN` | IP addresses, bank codes, logins | rules; Extended package at level 3 |
| `INNE` | anything you add yourself | your corrections and permanent lists |

The same person has the same placeholder throughout the text, also in another form
(„Jana Kowalskiego”, a grammatical case of the name, is still `[OSOBA_1]`). Dates can be turned off in the settings.

## Three quality levels

| Level | What it does | When |
|---|---|---|
| Szybko (Fast) | rules and model, one pass | short, simple texts |
| Dokładniej (More thorough) | lower confidence threshold for persons and a second pass shifted by half a window | ordinary letters and documents, the default setting |
| Najdokładniej (Most thorough) | as above plus the GUS first-name dictionary, with the Extended package also IP, SWIFT and logins | documents where a mistake costs the most |

Measurement results for each level are in `docs/MODELE.en.md`.

## Quality check

After hiding, the program reads the result back like a foreign document and searches it again for personal
data. Everything it finds that is not a placeholder goes onto a list to review.
For a `.docx` file it additionally scans the raw content, part by part.

- **zaliczona** (passed): nothing suspicious was left;
- **sprawdź wynik** (check the result): there are places to review, the list shows each of them;
- **STOP**: copying and downloading wait until you decide on every place.

The check reduces the risk but does not remove it. A person always reviews the result.

## Map

The map is a list: which placeholder replaced which piece of data. Without it the text cannot be restored.

- The program saves the map of each document on your computer, encrypted with an AES-256
  key. The key is in the system password store or in a file specified by IT.
  The program does not store it itself.
- The map expires after 30 days. The administrator sets the period.
- The first line of the result contains the map identifier. If the chat keeps it, the program
  picks the map by itself when restoring.
- You can also download the map as a `.nwidka` file and attach it to the case file.

## When the program makes a mistake

You correct the result in the preview, without hiding again:

- a word hidden unnecessarily: click the badge, „To nie dane osobowe” (This is not personal data);
- an item missed: select it and click „Ukryj wszędzie” (Hide everywhere);
- a recurring problem: add the word to the permanent list „Zawsze ukrywaj” (Always hide) or
  „Nigdy nie ukrywaj” (Never hide). The administrator can set lists for everyone.

Numbers with a valid checksum cannot be unhidden. The program always treats them as personal data.

## Files

The program accepts `.txt` and `.docx` up to 25 MB. The result has the same format as the input file,
and a `.docx` document keeps the layout and styles of the content. From `.docx` the program removes comments,
footnotes and endnotes, headers, footers, the thumbnail, document variables and extra file properties,
because names and e-mails often remain there. It accepts tracked changes and turns fields (for example
mail merge fields) into plain text. Text in text boxes is hidden
like the rest of the content. By default it removes images, because it does not read text from them. A document
with an unknown internal part is rejected. Scans and PDF are not supported.

## Deployment options

**One computer.** The desktop version from the ZIP, models downloaded at first start.
Nothing else is needed.

**Many computers without internet.** IT downloads the package files once and puts them in a
network folder. The user pastes the path in Ustawienia (Settings) and clicks „Zainstaluj z folderu” (Install from folder). You can also
expose the folder on an HTTP server and set `NIEWIDKA_MODELE_ZRODLO`. The program checks
the SHA-256 sum of every file.

**Shared model server.** The models run on one server in the local network, on a CPU
or a graphics card. Only the program itself goes to users' computers. Only the text to be checked
goes to the server, over TLS and with a token. Maps and keys stay with the users.
Description: `docs/SERWER-INFERENCJI.en.md`.

## Security in brief

- The program listens only on `127.0.0.1`. Every request requires a session token from the page.
- The content of documents does not go into the log. In case of an error the log gets only an identifier.
- On a model error the program returns nothing. It will not hand over text it has not checked.
- Model updates are signed. The program installs a new version only after a test
  on sample sentences and keeps the previous one for rollback.

## What the program does not do

- It does not guarantee detection of all data. Rare surnames, nicknames and descriptions
  that let someone identify a person („sąsiad z trzeciego piętra”, the neighbor from the third floor) may get through.
- It does not read images, scans or PDF.
- The browser version has no user accounts, so everyone runs it on their own machine.
