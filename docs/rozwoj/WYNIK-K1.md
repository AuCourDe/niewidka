# WYNIK pomiaru K1 — rdzeń regułowy

Data: 2026-10-28 ok. 01:10. Detektor: reguły + scalanie (`--detektor reguly`).
Korpus: 62 próbki, autor zewnętrzny (opencode/deepseek, commit `1a3320c`) — autor
inny niż autor detektorów (PLAN T0.2). Progi: `KRYTERIA.md` (commit `2d173a6`,
scommitowany **przed** pierwszym pomiarem; poniżej pierwszy w historii pomiar).
Polecenie: `.venv/bin/python -m narzedzia.pomiar --detektor reguly`.
Sanity narzędzia: detektor pusty daje recall 0,0 na wszystkich typach (KRYTERIA §1.5).

## Liczby per typ vs progi

| typ | TP | FP | FN | recall | próg recall | precision | próg precision | werdykt |
|---|---|---|---|---|---|---|---|---|
| PESEL | 5 | 0 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| NIP | 5 | 0 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| REGON | 5 | 0 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| IBAN | 4 | 0 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| DOKUMENT | 3 | 0 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| EMAIL | 4 | 0 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| TELEFON | 4 | 0 | 0 | 1.000 | ≥ 0.90 | 1.000 | ≥ 0.95 | **spełnia** |
| ADRES | 6 | 0 | 0 | 1.000 | ≥ 0.80 | 1.000 | ≥ 0.90 | **spełnia** |
| DATA | 4 | 0 | 0 | 1.000 | ≥ 0.90 | 1.000 | ≥ 0.95 | **spełnia** |
| **łącznie (K1, bez OSOBA)** | **40** | **0** | **0** | **1.000** | ≥ 0.90 | **1.000** | ≥ 0.95 | **spełnia** |
| OSOBA (poza bramą K1) | 0 | 0 | 23 | 0.000 | — (K2) | n/d | — | poza zakresem reguł |

Brama K1 z KAMIENIE.md: 100% numerów z poprawną sumą kontrolną wykrytych
(40/40 TP na typach z walidatorem — **tak**) i 0 fałszywych trafficień na numerach
z błędną sumą (pułapki: PESEL 3, NIP 2, REGON 2, IBAN 2, DOWÓD 2 — 0 trafficień,
precision 1.000 — **tak**). Progi nie były przesuwane; nic nie wymagało przesunięcia.

## Co nie spełnia i dlaczego

Nic z bramy K1. OSOBA ma recall 0,0 — to oczekiwane i zgodne z KRYTERIA §3: reguły
celowo nie wykrywają osób, typ wchodzi z modelem na poziomie 1 (kamień K2); nie
wlicza się do „łącznie". 23 oczekiwane OSOBA to FN do skasowania dopiero w K2.

## Słabości zwycięzcy (zapisane zgodnie z regułą wariantów)

Wynik 1.000/1.000 jest realny (autor korpusu ≠ autor reguł; pułapki na błędnych
sumach zweryfikowane stdnum), ale korpus był mały (62 próbki) i formy korpusu
pokrywają się z formami, które reguły obsłużyły świadomie. Znane słabości:

1. **Telefon vs REGON**: 9 cyfr ciągłych bez prefiksu, zaczynające się od 5-8,
   to zgodnie z regułą telefon; gdyby taki zapis był jednocześnie poprawnym
   REGON-em, scalanie dałoby etykietę REGON (suma kontrolna wygrywa). W korpusie
   nie wystąpiło. Telefony zaczynające się od 1-4 bez prefiksu i separatorów
   nie są wykrywane (świadome ograniczenie — komentarz w `reguly.py`).
2. **Odmiany mnogie nazwisk**: „Kowalscy" daje rdzeń „kowalsc", a „Kowalski" —
   „kowalsk" (heurystyka końcówek, `SIMPLIFICATION` z LLD §6). Dotyczy grupowania
   osób; rozbudować po pomiarze K2, gdy model zacznie dostarczać OSOBA.
3. **Daty**: tylko zapis liczbowy (dd.mm.rrrr / dd-mm-rrrr) i słowny w dopełniaczu;
   ISO („2023-05-13") nieobsługiwany — nie występuje w korpusie.
4. **Adres**: heurystyka bez kodu pocztowego i miejscowości (konwencja KRYTERIA §2);
   ulice zaczynające się od cyfry obsługiwane, od „Św." / skrótów świętych — nie.

## Otwarte decyzje z przeglądów (wykraczają poza K1, dotyczą K2-K4)

- Astra #2 / Gemini #3: sekwencyjny licznik `kolejny` nie przeżyje parafrazy
  przez chmurowe AI; docelowo stabilne identyfikatory wystąpień w znacznikach
  (dotyczy mapy i przywracania — K4; `znaczniki.py` trzyma obecnie format LLD §7).
- Astra #14: numer z błędną sumą kontrolną może być literówką prawdziwego PESEL-u —
  „brak detekcji" jest zgodny z bramą K1, ale decyzję o obsłudze (np. detekcja
  z niską pewnością jako INNE) musi podjąć dyrygent przed K2.
- Gemini #12: pole `forma` w mapie bez lematyzatora jest fikcją — do rozstrzygnięcia
  w K4 wraz z formatem mapy.

## Powtarzalność

```
.venv/bin/pytest tests/ -q          # 76 testów zielonych (po dopisku niżej)
.venv/bin/python -m narzedzia.pomiar --detektor reguly
```

---

## Dopisek 2026-10-28 — podejrzane nadmaskowanie (przegląd Astry pkt 14)

Otwarta decyzja „Astra #14" z sekcji powyżej **rozstrzygnięta** na polecenie właściciela:
numer z błędną sumą kontrolną nie jest odrzucany — dostaje encję z flagą `podejrzana=True`
(pewność 0.5) i wchodzi do maskowania. Definicja pomiaru doprecyzowana w `KRYTERIA.md`
§1.3 (**tylko definicja**: nadmaskowanie z flagą liczone jako PN, nie FP; progi nietknięte;
powód zmiany zapisany w KRYTERIA). Pomiar powtórzony po zmianie zachowania:

| typ | TP | FP | PN | FN | recall | próg recall | precision | próg precision | werdykt |
|---|---|---|---|---|---|---|---|---|---|
| PESEL | 5 | 0 | 3 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| NIP | 5 | 0 | 2 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| REGON | 5 | 0 | 2 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| IBAN | 4 | 0 | 2 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| DOKUMENT | 3 | 0 | 2 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| EMAIL | 4 | 0 | 0 | 0 | 1.000 | = 1.00 | 1.000 | = 1.00 | **spełnia** |
| TELEFON | 4 | 0 | 0 | 0 | 1.000 | ≥ 0.90 | 1.000 | ≥ 0.95 | **spełnia** |
| ADRES | 6 | 0 | 0 | 0 | 1.000 | ≥ 0.80 | 1.000 | ≥ 0.90 | **spełnia** |
| DATA | 4 | 0 | 0 | 0 | 1.000 | ≥ 0.90 | 1.000 | ≥ 0.95 | **spełnia** |
| **łącznie (K1, bez OSOBA)** | **40** | **0** | **11** | **0** | **1.000** | ≥ 0.90 | **1.000** | ≥ 0.95 | **spełnia** |
| OSOBA (poza bramą K1) | 0 | 0 | 0 | 23 | 0.000 | — (K2) | n/d | — | poza zakresem reguł |

Wszystkie 11 pułapek z błędną sumą (PESEL 3, NIP 2, REGON 2, IBAN 2, DOWÓD 2) jest
zamaskowanych z flagą — dokładnie zamierzone nadmaskowanie; brama K1 (40/40 pewnych TP,
0 pewnych FP na pułapkach) dalej spełniona.
