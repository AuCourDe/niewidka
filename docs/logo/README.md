# Logo Niewidki

Wybór właściciela: **wariant B** (sygnet czapki + napis), 2026-10-28.
Autor: Gemini (Antigravity, konto **agy4**).

## Pliki

| plik | przeznaczenie |
|---|---|
| `logo-agy4-2.svg` | główny znak (czapka + napis „Niewidka" + podtytuł), 640x200 |
| `logo-agy4-2.png` / `-240.png` | wersje raster do podglądu |
| `logo-agy4-2-favicon.svg` | znak czapki do małych rozmiarów (favicon, ikona aplikacji) |
| `logo-agy4-2-favicon.png` / `-favicon-32.png` | raster favicon |

## Użycie w produkcie (niewidka/web/)

- `logo.svg` = `logo-agy4-2.svg` bez tła (`<rect>`), żeby znak pasował do nagłówka strony
  na dowolnym tle; wpięty w `<h1>` (alt „Niewidka", 134x42).
- `favicon.svg` = kopia `logo-agy4-2-favicon.svg`; `favicon-32.png` = raster 32 px
  (sprawdzony w 32 px: znak czytelny), `apple-touch-icon.png` = raster 180 px
  (oba rasteryzowane `rsvg-convert` z favicon.svg).
- `ikona.ico` (16/32/48/256) = ten sam znak, rasteryzowany z **wariantu o pełnym
  konturze** (#2c4560, bez zanikającego gradientu): w 16-32 px gradient wychodził
  zbyt blado. Używa jej budowa Windows (`narzedzia/zbuduj_windows.ps1`).

Przebudowa ikony.ico (wymaga `rsvg-convert`):

    sed -e 's/url(#fav-stroke-fade)/#2c4560/g' -e 's/fill="url(#fav-veil)"/fill="#2c4560" fill-opacity="0.06"/g' \
      -e 's/stroke-width="12"/stroke-width="13"/g' -e 's/stroke-width="8"/stroke-width="9"/g' \
      docs/logo/logo-agy4-2-favicon.svg > /tmp/favicon-solid.svg
    for r in 16 32 48 256; do rsvg-convert -w $r -h $r /tmp/favicon-solid.svg -o /tmp/solid-$r.png; done

(wyniki składa się do `ikona.ico` jako wpisy PNG; skrypt składający nie jest
częścią repo, bo `.ico` jest w repo gotowe).
