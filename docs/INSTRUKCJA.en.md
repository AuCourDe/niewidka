# Niewidka: user guide

[Polski](INSTRUKCJA.md) · **English**

This guide covers both versions of the program. The desktop version and the browser
version have the same buttons and work the same way. The program interface is in Polish,
so button and tab names are given in Polish with an English gloss on first use.

## First start

**Map key.** In the desktop version the program asks you to create a key. Click
„Utwórz klucz” (Create key). The key is saved permanently in Windows Credential Manager. It encrypts
the maps, that is, the lists of data hidden behind the placeholders. Do not delete the key. Without it
you cannot read old maps.

In the browser version the key is created by the person who installs the program (`docs/KONFIGURACJA.en.md`).

**Models.** On the „Przygotowanie do pracy” (Getting ready) screen choose one of the options:

- „Pobierz podstawowy (zalecane)” (Download basic, recommended): about 190 MB. Enough for work at every level.
- „Pobierz wszystko” (Download everything): adds the extended package (about 230 MB). At the
  Najdokładniej (Most thorough) level it also detects IP addresses, SWIFT codes and logins.
- „Później” (Later): you can download the models in Ustawienia (Settings).

Next to each package you will find the model's address on Hugging Face and its license.
Read the license before downloading. You download the models once. After that the program works without internet.

If the administrator has set up a shared model server, this screen does not appear. The header
then shows a note that data does not leave the local network.

## Hiding data

1. On the **Ukryj** (Hide) tab paste text or click „Wybierz plik” (Choose file). You can also
   drag a file onto the field. The program accepts `.txt` and `.docx` files up to 25 MB.
2. Set the **Jakość wykrywania danych** (Detection quality) slider:
   - **Szybko** (Fast): shortest time, for simple texts.
   - **Dokładniej** (More thorough): the default setting, for ordinary letters and documents.
   - **Najdokładniej** (Most thorough): slowest, for the most important documents.
3. Click **Ukryj dane** (Hide data).

On the right you will see a preview. Hidden data appears as black badges, for example
`[OSOBA_1]`. The same person or the same number gets the same placeholder throughout the text.

The first line of the result starts with the word „ZANONIMIZOWANY” (ANONYMIZED) and ends with a map identifier.
Copy the text together with this line. If an AI chat keeps it, the program finds the right map
by itself when restoring.

The bar above the preview shows the result of the quality check. When you see „sprawdź wynik” (check the result),
review the places in the „Uwaga: sprawdź te miejsca” (Attention: check these places) box.

You can then:

- copy the finished result with the **Kopiuj tekst** (Copy text) button,
- save it with the **Pobierz dokument** (Download document) button (in the format of the input file),
- save the map for your records with the **Pobierz mapę (.nwidka)** (Download map) button. You do not have to do this,
  because the program remembers the map by itself.

After changing the text or moving the slider, click **Ukryj ponownie** (Hide again).

## Correcting the result

The program may miss something or hide too much. You can fix mistakes right in the preview.

**The program hid an ordinary word.** Click the badge in the preview and choose
„To nie dane osobowe” (This is not personal data). The word returns to the text everywhere. For words from the permanent list
use the „Odkryj tylko w tym dokumencie” (Unhide only in this document) button.

You cannot unhide PESEL, NIP, REGON, IBAN, card numbers and ID card numbers. They have a valid
checksum, so they are certainly personal data.

**The program missed an item.** Select it with the mouse in the preview and click „Ukryj wszędzie” (Hide everywhere).
You can also type it into the „Ukryj wszędzie” field under the preview. The fragment gets the placeholder
`[INNE_1]` and disappears from the whole text.

**A placeholder has the wrong type.** Click the badge and choose „Oznacz jako inne dane” (Mark as other data).

You will find all changes in the **Twoje poprawki** (Your corrections) section. You can undo each one. Click
„Ukrywaj zawsze” (Always hide) and the word goes onto the permanent list. The program will hide it in every following document.

## When the check stops the result

Sometimes the quality check finds suspicious fragments in the text. You will then see the message
„STOP: kontrola ma wątpliwości” (STOP: the check has doubts) and a list of places. For each one click „Ukryj” (Hide) or
„To nie dane” (This is not data). Once you have decided on all of them, copying and downloading are unlocked.

## Restoring data

1. Send the hidden text to an AI chat and copy the reply.
2. On the **Przywróć** (Restore) tab choose „Wklej odpowiedź z czatu AI” (Paste a reply from an AI chat) and paste the copied text.
3. From the **Zadanie** (Job) list choose the document the text comes from. The newest one is selected by default.
   If the reply contains a map identifier, the program chooses the right map by itself.
4. Click **Przywróć dane** (Restore data).

The real data replaces the placeholders. If the chat changed or removed a placeholder, you will see it
in the „Nie wszystko wróciło idealnie” (Not everything came back perfectly) box.

Do you have the document file and the map file? Choose „Mam plik dokumentu i mapę (.nwidka)” (I have the document file and the map),
point to both files and click **Przywróć dane**. You get the document in the same format.

## Settings

**Pakiety modeli** (Model packages). Downloading and removing models, licenses. A computer without internet: paste
into the field above the list the path to a folder with package files from IT and click „Zainstaluj z folderu” (Install from folder)
next to the package.

**Aktualizacje modeli** (Model updates). By default the program checks once a day whether there are new versions.
It downloads only the version list and never sends your documents. A new version is installed
only after a successful trial on sample sentences. To roll back an update, click
„Wróć do poprzedniej wersji” (Go back to the previous version). On a network without internet, an IT person pastes the path to the folder
with the update and clicks „Zainstaluj z folderu”.

**Stałe listy** (Permanent lists). Enter one word or phrase per line:

- **Zawsze ukrywaj** (Always hide): for example the name of a department or a rare nickname.
- **Nigdy nie ukrywaj** (Never hide): for example the name of your company.

The program recognizes inflected forms. The entry „Biuro Rachunkowe” (Accounting Office) also works for „Biura Rachunkowego” (the same name in another grammatical case).
Click „Zapisz listy” (Save lists). Lists set by the administrator can only be viewed.

**Zapisane mapy** (Saved maps). The program automatically saves an encrypted map of each document. Maps disappear
after a time set by the administrator, by default after 30 days. Here you can review them
and delete them earlier.

## Important

Niewidka helps with the work but does not guarantee that all data is detected. Always review the
preview before sending the text. The decision to hand over a document is yours.

The program does not read text from photos and scans. It removes images from `.docx` files.

## Troubleshooting

| What you see | What to do |
|---|---|
| „Nie można wystartować” (Cannot start) | Models are missing. Download them in Ustawienia or contact IT. |
| „Serwer modeli nie odpowiada” (The model server is not responding) | The shared model server is down. Report it to the administrator. |
| Restoring does not know the map | The map expired or someone deleted it. Load the `.nwidka` file if you have it. |
| A file does not load | The program accepts `.txt` and `.docx` files smaller than 25 MB. |
