# Logo Niewidki

| Plik | Przeznaczenie |
|---|---|
| `logo.svg` | znak (czapka, napis „Niewidka” i podtytuł), 640x200 |
| `logo.png`, `logo-240.png` | wersje rastrowe |
| `logo-favicon.svg` | sam znak czapki do małych rozmiarów |
| `logo-favicon.png`, `logo-favicon-32.png` | favicon rastrowy |

W interfejsie (`niewidka/web/`):

- `logo.svg` to znak bez tła, w nagłówku strony;
- `favicon.svg` to kopia `logo-favicon.svg`, a `favicon-32.png` i `apple-touch-icon.png`
  to jego wersje rastrowe;
- `ikona.ico` (16, 32, 48 i 256 px) to ten sam znak z pełnym konturem, bo gradient
  w 16 i 32 px wychodzi zbyt blado. Używa jej budowa Windows.

Przebudowa ikony (wymaga `rsvg-convert`):

    sed -e 's/url(#fav-stroke-fade)/#2c4560/g' -e 's/fill="url(#fav-veil)"/fill="#2c4560" fill-opacity="0.06"/g' \
      -e 's/stroke-width="12"/stroke-width="13"/g' -e 's/stroke-width="8"/stroke-width="9"/g' \
      docs/logo/logo-favicon.svg > /tmp/favicon-solid.svg
    for r in 16 32 48 256; do rsvg-convert -w $r -h $r /tmp/favicon-solid.svg -o /tmp/solid-$r.png; done

Pliki PNG składa się w `ikona.ico`. Gotowy plik `.ico` jest w repozytorium.
