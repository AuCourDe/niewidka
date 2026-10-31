# Model package release: signing and publishing

[Polski](WYDANIE.md) · **English**

Guide for the person releasing Niewidka. Tool: `narzedzia/podpisz_katalog.py`.

## What an update release publishes

1. `katalog-pakietow.json`: the version listing: `wersja_katalogu`, the list of packages
   (`wersja`, `min_wersja`, files with `zrodlo`, `rozmiar`, `sha256`).
2. `katalog-pakietow.json.sig`: the Ed25519 signature of the catalog (raw 64 B).
3. Package files under the source names from the `zrodlo` field (GitHub release
   attachments or an IT mirror). The program downloads them relative to `NIEWIDKA_MODELE_ZRODLO`.

The catalog and the signature must be made from exactly the same bytes: sign
the file AFTER the last change, not before.

## Keys (once, before the first signed release)

```bash
# test/production pair; the private key lives OUTSIDE the repo (the publisher's secret store)
python narzedzia/podpisz_katalog.py --generuj-pare /sciezka/do/klucza/wydawcy.key
# prints the public key (base64 of the raw 32 bytes): this one goes into the repo
```

The public key is entered in `niewidka/dane/klucz-katalogu.pub`: one per line,
lines starting with `#` are comments. The private key is read ONLY from the variable
`NIEWIDKA_KLUCZ_PODPISU` (never from an argument, never from the repo, never in logs):

```bash
NIEWIDKA_KLUCZ_PODPISU=/sciezka/do/klucza/wydawcy.key \
  python narzedzia/podpisz_katalog.py katalog-pakietow.json   # produces katalog-pakietow.json.sig
```

Until the first release, the repo (`niewidka/dane/klucz-katalogu.pub`) contains
a placeholder. Without a valid key the program works normally on the built-in catalog,
but updates (remote and from a folder) are unavailable, with a clear message.

### Key rotation

1. The new public key is ADDED to `klucz-katalogu.pub` and the program is released.
2. From that release on, catalogs are signed with the new key; the old one stays in the file,
   because installations of older program versions keep verifying with it.
3. The old key is removed from the file only when we stop supporting the program versions
   that know it.

## Numbering rules

- `wersja_katalogu`: +1 on EVERY acceptance for publication. The program accepts
  only versions HIGHER than the last accepted one (rollback protection),
  and stores the highest accepted one separately in `ustawienia.json`, so a
  damaged or swapped catalog file cannot lower it.
- package `wersja`: +1 for new files of that package; new SHA-256 values and sizes
  are mandatory. The program will not offer a version lower than or equal to the installed one.
- `min_wersja`: raised when an older package version is faulty and going back
  to it should be blocked (the „Wróć do poprzedniej wersji” (Go back to the previous version) button will refuse).
- `probka-kontrolna.json`: when detection behavior changes, add sentences
  to `musi_wykryc` (new capabilities) and `nie_moze_wykryc` (e.g. former false
  alarms). The new version must pass the WHOLE sample, otherwise the installation is
  rejected and the previous version stays in place.

## Offline installation (network without internet)

The folder on an IT pendrive contains: `katalog-pakietow.json`, `katalog-pakietow.json.sig`
and the package files under the `zrodlo` names. The user pastes the path in Ustawienia (Settings)
(„Zainstaluj z folderu” (Install from folder)). The program applies THE SAME verification as for downloading:
signature, version threshold, SHA-256 of every file, control sample, and only then
an atomic swap with a copy of the previous version in `modele/.poprzednie/`.

Note the distinction: „Zainstaluj z folderu” next to a package in Ustawienia
(`POST /api/pakiety`, action `instaluj`) is a DIFFERENT path. It is for installing versions pinned in the
built-in catalog of the given program (sha256 is enforced by the built-in catalog, the folder holds
only files). Versioned news goes exclusively through the signed catalog.

## Release checklist

- [ ] `wersja_katalogu` is 1 higher than the last published one.
- [ ] Changed packages have a bumped `wersja` and fresh `sha256` + `rozmiar`.
- [ ] `probka-kontrolna.json` reflects the expected behavior of the new version.
- [ ] The signature was made AFTER the final catalog content, with the key from the variable
      `NIEWIDKA_KLUCZ_PODPISU`; the `.sig` matches the published file.
- [ ] Verification before publishing: a test program accepts the catalog and passes
      the sample (pytest `tests/test_aktualizacje.py` passes on this catalog).
- [ ] Release attachments: the catalog, the signature and all files from the `zrodlo` fields.
- [ ] Model licenses next to the packages: `podstawowy-LICENSE.txt` (Apache 2.0 from the bardsai
      repository), `rozszerzony-LICENSE.txt` (LFM Open License v1.0 from the LiquidAI repository)
      and `NOTICE.txt` stating that the ONNX files were produced from these models by export
      and Q4 quantization (both packages). Template: the `NOTICE.txt` attachment of release 0.1.0. Both licenses require this.
- [ ] The private key never left the secret store (never: repo, CI cache, log).
