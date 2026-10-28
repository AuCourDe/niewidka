# DESIGN.md — Niewidka (interfejs web, `niewidka/web/`)

Zapis zbudowanego stanu (K5, październik 2026). Źródło prawdy: `styl.css`, `index.html`,
`apka.js`, zrzuty `docs/zrzuty/k5-*.png`. Wartości wprost z kodu, nie z intencji.

## Identity

Papier i atrament: lokalne narzędzie urzędowe. Tło to papier (`--papier`), treść leży na
białej kartce (`--kartka`), akcja to `--tusz` (atrament pióra), dane zasłonięte czarną
zaślepką z białym monospace — jak zaklejony numer w piśmie. Jedna kolumna, maks. 46rem,
zero ozdób: cisza wizualna jest funkcją, bo narzędzie pracuje na wrażliwych danych.
Całość w pełni offline: Lato w repo (`fonty/`, OFL), brak CDN, `color-scheme: light`,
`theme-color` = `#FBFBF9`. Favicon to odwrócona zaślepka (ciemny prostokąt `#1A1D21`).

## Palette

Tokeny w `:root` (`styl.css:19-34`) — każdy w użyciu:

| Token | Wartość | Rola |
|---|---|---|
| `--papier` | `#FBFBF9` | tło strony, tło `textarea` |
| `--kartka` | `#FFFFFF` | powierzchnie treści: nagłówek, pola, kartka, przycisk wtórny |
| `--atrament` | `#23282D` | tekst główny, obramowanie przycisku wtórnego |
| `--atrament-slaby` | `#565D64` | tekst wtórny, podpowiedzi, placeholder, stopka |
| `--tusz` | `#2D4A6B` | akcja: wypełnienie przycisku głównego, aktywna zakładka, focus, linki |
| `--tusz-nacisniety` | `#243B57` | hover przycisku głównego i linków |
| `--linie` | `#D9D6CF` | włosowe linie 1px: obramowania, separatory, kropkowane wiersze list |
| `--zaslepka` | `#1A1D21` | tło zaslepki (czarny pasek) |
| `--blad` / `--blad-tlo` | `#A62B22` / `#FAEEEC` | komunikaty błędu (kolor = tekst na jasnym tle) |
| `--ostrzegaj` / `--ostrzegaj-tlo` | `#7A4D0B` / `#FBF3E1` | ostrzeżenia i blok „Zachowaj mapę" |
| `--ok` | `#1E6B4E` | komunikat „zaliczona", tryb „Na tym urządzeniu" |

Semantyczne tła i obramowania komunikatów dobrane parami (tło + 1px border + tekst tym
samym hue): `#FAEEEC/#E5C4C0`, `#FBF3E1/#E8D9B4`, `#EAF4EF/#C4DED2`. Zasada: kolor
semantyczny pojawi się tylko jako stan (błąd / ostrzeżenie / sukces) — nigdy dekoracyjnie.
`::selection` = `#D9E2EC`.

## Type

- **Lato** Regular 400 i Bold 700, `@font-face` z katalogu `fonty/`, `font-display: swap`,
  `<link rel="preload">` obu odmian. Fallback: `"Segoe UI", sans-serif`. Dwa ciężary —
  to cała rampa wag; hierarchia robi się rozmiarem, nie trzecim stylem.
- Baza: `1rem` / `line-height 1.55`. Ramp: h1 nazwa `1.35rem` (ls `-0.01em`), h2 wyniku
  `1.2rem`, h3 i przycisk główny ~`1rem`, tekst pomocniczy `0.92rem`, drobny `0.88rem`.
- **Mono** wyłącznie dla danych maszynowych (zaślepka): `ui-monospace, "Cascadia Mono",
  Consolas, "Courier New", monospace`, `0.82em`, `letter-spacing: 0.03em`,
  `font-variant-numeric: tabular-nums`. `tabular-nums` także na listach liczb.
- `text-wrap: balance` na h1–h3.

## Space

Jedna kolumna `max-width: 46rem`, padding boczny `1.25rem` (`1rem` ≤ 480px). Rytm
pionowy w krokach ~`0.4/0.55/0.7/0.9/1.1/1.3/1.5/1.6rem`; panel `1.6rem 0 2.5rem`.
Promienie maleją z powierzchnią: `6px` (komunikat, pole dokumentu), `5px` (przyciski),
`4px` (textarea, skip-link), `3px` (kartka), `2px` (zaslepka). Suwak quality: `accent-color: var(--tusz)`.

## Elevation

Jeden cień w całym systemie, tylko na kartce podglądu: `0 1px 2px rgba(35,40,45,.08),
0 10px 26px rgba(35,40,45,.1)` — kontaktowy + miękki rozległy. Wszystko inne oddziela
włosowa linia `1px solid var(--linie)` (w listach wariant kropkowany), a hierarchia
aktywności — `3px` podkreślenie zakładki kolorem `--tusz`. Żadnych twardych offsetów,
żadnego cienia na przyciskach.

## Components

- **Zaślepka** (`.zaslepka`): czarny pasek `--zaslepka`, biały tekst mono, `TYP numer`
  (np. `PESEL 1`) parsowany z markerów `[]`… regexem `apka.js:130`. Format: `padding
  0.05rem 0.4rem`, radius `2px`, `white-space: nowrap`. To sygnatura systemu.
- **Kartka** (`.kartka`): `--kartka`, linia `--linie`, radius `3px`, jedyny cień,
  `padding 1.4rem 1.5rem`; tekst w środku `line-height 1.9`, `pre-wrap` — imituje pismo.
- **Zakładki**: `role="tablist"`, przyciski bez tła, `border-bottom: 3px transparent`;
  wybrana: kolor `--atrament` + `border-bottom-color: var(--tusz)`; hash (`#ukryj`,
  `#przywroc`) i strzałki w `apka.js`.
- **Komunikaty** (`.komunikat` + 3 stany): padding `0.9rem 1.1rem`, radius `6px`, h3 +
  akapit, para tło/obramowanie/kolor wg sekcji Palette. Treści po polsku wg kodów HTTP
  (`KOMUNIKATY`, `apka.js:53-60`); status „Sprawdzam…" to komunikat `--ok`.
- **Przyciski**: główny — wypełnienie `--tusz`, biały tekst, hover `--tusz-nacisniety`,
  `:active translateY(1px)`, disabled `opacity .55; cursor: wait`; wtórny — `--kartka`,
  `1px solid --atrament`, hover `#F1EFEA`; linkowy — podkreślenie, `--tusz`. Na ≤480px
  główny na całą szerokość.
- **Lista danych** (`.lista-danych`): wiersz flex „etykieta — wartość", kropkowana linia
  `--linie`, wartości `tabular-nums`, prawa kolumna `--atrament-slaby`; na mobile w kolumnę.

## Motion

Brak autorskiego ruchu. Jedyna transformacja to `:active` przycisku głównego
(`translateY(1px)`) — wciśnięcie, nie animacja. `@media (prefers-reduced-motion: reduce)`
wyłącza globalnie wszystkie `transition` i `animation`. `touch-action: manipulation`
(znakomy cel: zero podwójnego tapnięcia-zoomu). Docelowo: nowych animacji nie dodawać.

## Accessibility

- Skip-link `.przeskok`, widoczny na focus (`top: -3rem → 0.5rem`), `2px solid --tusz`.
- `:focus-visible` jednolity: `outline: 2px solid var(--tusz); outline-offset: 2px` —
  łącznie z ukrytym `input[type=file]` (wzorzec `#plik:focus-visible + .przycisk-wtorny`).
- `aria-live`: statusy `polite` w panelach + offscreen `#zapowiedz` `assertive` na
  „wynik gotowy" / „skopiowano" (z `apka.js`).
- Suwak jakości: `aria-valuetext` = nazwa poziomu („Dokładniej"), skala `aria-hidden`.
- Walidacja formularza: komunikat + focus na brakujące pole; `beforeunload` przy treści.
- Kontrasty AA wszędzie: `--atrament`/`--atrament-slaby` na `--papier`, semantyczne kolory
  zawsze jako ciemny tekst na swojej jasnej parze tła, nigdy kolor na papierze bez pary.
- Upuszczenie pliku (drag&drop) ma widoczny stan: border + outline `--tusz`.

## Principles

1. **Papier, nie aplikacja.** Powierzchnie to kartka i włosowa linia; żadnych gradientów,
   szkieletu dashboardu ani siatki kart — jedna kolumna, jeden przepływ.
2. **Kolor semantyczny tylko jako stan.** `blad/ostrzegaj/ok` wyłącznie w komunikatach
   i oznaczeniach trybu; dekoracyjnie nigdy. Akcja to zawsze `--tusz`.
3. **Mono = maszyna, Lato = człowiek.** Dane od programu (zaślepki, liczby) mono
   tabular; wszystko dla czytelnika — Lato.
4. **Jeden cień, jedna kolumna, dwa ciężary.** Nowa elevacja, font albo waga = zmiana
   systemu, nie lokalna decyzja.
5. **Offline jest cechą wyglądu.** Fonty z repo, brak CDN, brak zasobów zewnętrznych;
   interfejs działa bez sieci tak samo.
6. **Stan zawsze widoczny i nazwany po polsku.** Focus, hover, disabled, drag, wybrana
   zakładka — każdy stan ma kolor lub kontur z tej palety, komunikat z `KOMUNIKATY`.
