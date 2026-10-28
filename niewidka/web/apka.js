/* Niewidka — web lokalny (K5). Jedna strona, bez zależności, wszystko offline.
 * Token sesji przychodzi w meta (wstrzyknięty przez api.py przy serwowaniu strony),
 * nigdy w URL i nigdy w zasobach statycznych.
 */

"use strict";

const token = document.querySelector('meta[name="niewidka-token"]').content;
const NAGLOWKI = { "X-Niewidka-Token": token };

let limity = { rozmiar_mb: 25, tekst_mb: 1 };
let wynikPaczka = null; // { wynik: {nazwa, blob}, mapa: {nazwa, blob} }
let przywrocony = null; // {nazwa, blob}

/* ---------- etykiety po ludzku ---------- */

const ETYKIETY = {
  OSOBA: ["osoba", "osoby"],
  PESEL: ["numer PESEL", "numery PESEL"],
  NIP: ["numer NIP", "numery NIP"],
  REGON: ["numer REGON", "numery REGON"],
  IBAN: ["numer konta IBAN", "numery kont IBAN"],
  ADRES: ["adres", "adresy"],
  TELEFON: ["numer telefonu", "numery telefonów"],
  EMAIL: ["adres e-mail", "adresy e-mail"],
  DOKUMENT: ["numer dokumentu", "numery dokumentów"],
  DOWOD: ["numer dowodu", "numery dowodów"],
  DATA: ["data", "daty"],
  INNE: ["inne dane", "inne dane"],
};

function etykieta(typ, ile) {
  const formy = ETYKIETY[typ] || [typ.toLowerCase(), typ.toLowerCase()];
  return `${ile} ${ile === 1 ? formy[0] : formy[1]}`;
}

function ryzykoOpis(r95) {
  if (r95 == null) return "nie oszacowano dla tego poziomu jakości";
  if (r95 <= 0.02) return "bardzo małe — co najwyżej 1 na 50";
  const na = Math.round(1 / r95);
  if (r95 <= 0.3) return `małe do umiarkowanego — co najwyżej ok. 1 na ${na}`;
  return "podwyższone — przejrzyj wynik własnym okiem";
}

const NAZWY_POZIOMOW = { 1: "Szybko", 2: "Dokładniej", 3: "Najdokładniej" };

const OPOWIEDZI_POZIOMOW = {
  1: "Najszybszy — do szybkiego przeglądu dokumentu.",
  2: "Wyważony — dobry do zwykłych dokumentów.",
  3: "Najstaranniejszy — najwolniejszy, do pism najważniejszych.",
};

const KOMUNIKATY = {
  403: "Sesja wygasła. Odśwież stronę (F5) i spróbuj ponownie.",
  413: () => `Za duże wejście — plik może mieć najwyżej ${limity.rozmiar_mb} MB, wklejony tekst ${limity.tekst_mb} MB.`,
  415: "Nieobsługiwany format pliku — przyjmuję .txt i .docx.",
  422: (blad) => `Nie mogę przetworzyć tego dokumentu. ${blad || ""}`,
  503: "Program właśnie zajmuje się innym dokumentem. Poczekaj chwilę i spróbuj ponownie.",
  500: (blad) => `Coś się zepsuło po stronie programu. Podaj osobie opiekującej się numer zdarzenia: ${blad}`,
};

/* ---------- drobne narzędzia ---------- */

function zapowiedz(tresc) {
  const pole = document.getElementById("zapowiedz");
  pole.textContent = "";
  pole.textContent = tresc;
}

function pobierzBlob(blob, nazwa) {
  const adres = URL.createObjectURL(blob);
  const lacznik = document.createElement("a");
  lacznik.href = adres;
  lacznik.download = nazwa;
  document.body.append(lacznik);
  lacznik.click();
  lacznik.remove();
  setTimeout(() => URL.revokeObjectURL(adres), 10_000);
}

/* ---------- czytnik ZIP ----------

   SIMPLIFICATION: czyta wyłącznie ZIP bez zip64, metody stored i deflate —
   dokładnie to, co zwraca POST /api/ukryj (dwa wpisy, bez szyfrowania).
   Rozbudować, gdy API zacznie zwracać cokolwiek innego. Deflate rozpakowuje
   natywny DecompressionStream przeglądarki. */

async function odczytajWpis(widok, wpis) {
  const dane = new Uint8Array(widok.buffer, wpis.startDanych, wpis.spakowane);
  if (wpis.metoda === 0) return dane;
  const strumien = new Blob([dane]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(strumien).arrayBuffer());
}

async function otworzZip(blob) {
  const widok = new DataView(await blob.arrayBuffer());
  const bajty = new Uint8Array(widok.buffer);
  let eocd = bajty.length - 22;
  while (eocd >= 0 && widok.getUint32(eocd, true) !== 0x06054b50) eocd -= 1;
  if (eocd < 0) throw new Error("to nie jest archiwum ZIP");
  const ile = widok.getUint16(eocd + 10, true);
  let pozycja = widok.getUint32(eocd + 16, true);
  const dekoder = new TextDecoder();
  const wpisy = {};
  for (let i = 0; i < ile; i += 1) {
    if (widok.getUint32(pozycja, true) !== 0x02014b50) break;
    const metoda = widok.getUint16(pozycja + 10, true);
    const spakowane = widok.getUint32(pozycja + 20, true);
    const dlNazwy = widok.getUint16(pozycja + 28, true);
    const dlExtra = widok.getUint16(pozycja + 30, true);
    const dlKomentarza = widok.getUint16(pozycja + 32, true);
    const nazwa = dekoder.decode(bajty.slice(pozycja + 46, pozycja + 46 + dlNazwy));
    const naglowek = widok.getUint32(pozycja + 42, true);
    const dlNazwyLokalnej = widok.getUint16(naglowek + 26, true);
    const dlExtraLokalnej = widok.getUint16(naglowek + 28, true);
    wpisy[nazwa] = {
      metoda,
      spakowane,
      startDanych: naglowek + 30 + dlNazwyLokalnej + dlExtraLokalnej,
    };
    pozycja += 46 + dlNazwy + dlExtra + dlKomentarza;
  }
  const wynik = {};
  for (const [nazwa, wpis] of Object.entries(wpisy)) wynik[nazwa] = await odczytajWpis(widok, wpis);
  return wynik;
}

/* ---------- podgląd z zaślepkami ---------- */

const WZORZEC_ZNACZNIKA = /\[([A-Z]+)_(\d+)(?:_F\d+)?\]/g;

function pokazPodglad(tekst) {
  const miejsce = document.getElementById("podglad-tekstu");
  miejsce.textContent = "";
  let koniec = 0;
  for (const trafienie of tekst.matchAll(WZORZEC_ZNACZNIKA)) {
    miejsce.append(tekst.slice(koniec, trafienie.index));
    const zaslepka = document.createElement("span");
    zaslepka.className = "zaslepka";
    zaslepka.textContent = `${trafienie[1]} ${trafienie[2]}`;
    miejsce.append(zaslepka);
    koniec = trafienie.index + trafienie[0].length;
  }
  miejsce.append(tekst.slice(koniec));
}

/* ---------- komunikaty i wynik ---------- */

function komunikat(statusId, klasa, naglowek, tresc) {
  const pole = document.getElementById(statusId);
  pole.innerHTML = "";
  const blok = document.createElement("div");
  blok.className = `komunikat ${klasa}`;
  if (naglowek) {
    const tytul = document.createElement("h3");
    tytul.textContent = naglowek;
    blok.append(tytul);
  }
  const opis = document.createElement("p");
  opis.textContent = tresc;
  blok.append(opis);
  pole.append(blok);
  return blok;
}

function komunikatOdpowiedzi(statusId, status, blad) {
  const przepis = KOMUNIKATY[status];
  const tresc = typeof przepis === "function" ? przepis(blad) : przepis || `Błąd ${status}. ${blad || ""}`;
  komunikat(statusId, "komunikat-blad", "Nie udało się", tresc);
}

function pokazBlokade(statusId, typy) {
  /* K4b pkt 1: zablokowany wynik przychodzi jako 422 bez dokumentu. Nie ma
     czego pobierać ani kopiować, więc pokazuję tylko STOP z typami znalezisk. */
  const pole = document.getElementById(statusId);
  pole.innerHTML = "";
  const blok = document.createElement("div");
  blok.className = "komunikat komunikat-blad";
  const tytul = document.createElement("h3");
  tytul.textContent = "STOP — tego dokumentu nie wolno wysyłać";
  blok.append(tytul);
  const opis = document.createElement("p");
  const typyTekst = Object.entries(typy || {})
    .map(([typ, ile]) => etykieta(typ, ile))
    .join(", ");
  opis.textContent = typyTekst
    ? `Ponowne sprawdzenie znalazło dane przypominające oryginalne (${typyTekst}). Dokument zablokowano, nic nie zostało zapisane ani skopiowane. Popraw dane w oryginale i spróbuj ponownie.`
    : "Ponowne sprawdzenie znalazło dane przypominające oryginalne. Dokument zablokowano, nic nie zostało zapisane ani skopiowane. Popraw dane w oryginale i spróbuj ponownie.";
  blok.append(opis);
  pole.append(blok);
}

function pokazWynik(naglowki, czesci) {
  const identyfikator = naglowki.get("x-niewidka-identyfikator");
  const statystyki = JSON.parse(naglowki.get("x-niewidka-statystyki") || "{}");
  const r95 = JSON.parse(naglowki.get("x-niewidka-r95") || "{}");
  const ostrzezenia = JSON.parse(naglowki.get("x-niewidka-ostrzezenia") || "[]");

  const nazwaWyniku = Object.keys(czesci).find((n) => !n.endsWith(".nwidka"));
  const nazwaMapy = Object.keys(czesci).find((n) => n.endsWith(".nwidka"));
  wynikPaczka = {
    wynik: { nazwa: nazwaWyniku, blob: new Blob([czesci[nazwaWyniku]]) },
    mapa: { nazwa: nazwaMapy, blob: new Blob([czesci[nazwaMapy]], { type: "application/octet-stream" }) },
  };

  const poleStatusu = document.getElementById("komunikat-status");
  poleStatusu.hidden = false;
  poleStatusu.innerHTML = "";
  const blok = document.createElement("div");
  blok.className = "komunikat komunikat-ok";
  const tytul = document.createElement("h3");
  tytul.textContent = "Kontrola jakości: zaliczona";
  blok.append(tytul);
  const opis = document.createElement("p");
  opis.textContent = "Ponowne sprawdzenie wyniku nie znalazło żadnych danych osobowych.";
  blok.append(opis);
  poleStatusu.append(blok);

  const zamienione = document.getElementById("blok-zamienione");
  const lista = document.getElementById("lista-zamienionych");
  lista.innerHTML = "";
  for (const [typ, ile] of Object.entries(statystyki)) {
    const wiersz = document.createElement("li");
    const co = document.createElement("span");
    co.textContent = etykieta(typ, ile);
    wiersz.append(co);
    lista.append(wiersz);
  }
  zamienione.hidden = lista.children.length === 0;

  const blokRyzyka = document.getElementById("blok-ryzyka");
  const listaRyzyka = document.getElementById("lista-ryzyka");
  listaRyzyka.innerHTML = "";
  const oszacowane = Object.entries(r95).filter(([, wartosc]) => wartosc != null);
  for (const [typ, wartosc] of oszacowane) {
    const wiersz = document.createElement("li");
    const co = document.createElement("span");
    co.textContent = (ETYKIETY[typ] || [typ])[0];
    co.textContent = co.textContent.charAt(0).toUpperCase() + co.textContent.slice(1);
    const ile = document.createElement("span");
    ile.textContent = ryzykoOpis(wartosc);
    wiersz.append(co, ile);
    listaRyzyka.append(wiersz);
  }
  if (statystyki && oszacowane.length === 0 && Object.keys(statystyki).length > 0) {
    const wiersz = document.createElement("li");
    const co = document.createElement("span");
    co.textContent = "Szacunek ryzyka";
    const ile = document.createElement("span");
    ile.textContent = "dostępny na poziomie Szybko";
    wiersz.append(co, ile);
    listaRyzyka.append(wiersz);
  }
  blokRyzyka.hidden = listaRyzyka.children.length === 0;

  const blokOstrzezenia = document.getElementById("blok-ostrzezenia");
  const listaOstrzezenia = document.getElementById("lista-ostrzezenia");
  listaOstrzezenia.innerHTML = "";
  for (const ostrzezenie of ostrzezenia) {
    const wiersz = document.createElement("li");
    const krotszy = ostrzezenie.fragment.length > 10 ? `${ostrzezenie.fragment.slice(0, 10)}…` : ostrzezenie.fragment;
    wiersz.textContent = `W wyniku pozostał fragment podobny do oryginalnych danych („${krotszy}”) — sprawdź to miejsce.`;
    listaOstrzezenia.append(wiersz);
  }
  blokOstrzezenia.hidden = listaOstrzezenia.children.length === 0;

  const trescTekstowa = new TextDecoder().decode(czesci[nazwaWyniku]);
  const podglad = document.getElementById("blok-podglad");
  const wygladaNaTekst = nazwaWyniku.endsWith(".txt") && !trescTekstowa.slice(0, 100).includes("\0");
  podglad.hidden = !wygladaNaTekst;
  if (wygladaNaTekst) pokazPodglad(trescTekstowa);

  document.getElementById("blok-pobrania").hidden = false;
  zapowiedz("Dane ukryte, wynik gotowy");
}

/* ---------- zakładki ---------- */

function ustawZakladke(wybrana) {
  for (const zakladka of document.querySelectorAll('[role="tab"]')) {
    const aktywne = zakladka === wybrana;
    zakladka.setAttribute("aria-selected", String(aktywne));
    zakladka.tabIndex = aktywne ? 0 : -1;
    document.getElementById(zakladka.getAttribute("aria-controls")).hidden = !aktywne;
  }
  if (history.replaceState) history.replaceState(null, "", wybrana.id === "zakladka-przywroc" ? "#przywroc" : "#ukryj");
}

function inicjalizujZakladki() {
  const zakladki = [...document.querySelectorAll('[role="tab"]')];
  if (location.hash === "#przywroc") ustawZakladke(document.getElementById("zakladka-przywroc"));
  for (const zakladka of zakladki) {
    zakladka.addEventListener("click", () => ustawZakladke(zakladka));
    zakladka.addEventListener("keydown", (zdarzenie) => {
      const biezaca = zakladki.indexOf(zakladka);
      if (zdarzenie.key === "ArrowRight") ustawZakladke(zakladki[(biezaca + 1) % zakladki.length]);
      if (zdarzenie.key === "ArrowLeft") ustawZakladke(zakladki[(biezaca - 1 + zakladki.length) % zakladki.length]);
      if (zdarzenie.key === "ArrowRight" || zdarzenie.key === "ArrowLeft") {
        document.querySelector('[role="tab"][aria-selected="true"]').focus();
        zdarzenie.preventDefault();
      }
    });
  }
}

/* ---------- wejście: tekst albo plik ---------- */

let wybranyPlik = null;

function pokazTrybPliku(plik) {
  wybranyPlik = plik;
  document.getElementById("widok-tekstu").hidden = Boolean(plik);
  document.getElementById("widok-pliku").hidden = !plik;
  document.getElementById("nazwa-pliku").textContent = plik ? plik.name : "";
}

function inicjalizujWejscie() {
  const wejscie = document.getElementById("plik");
  wejscie.addEventListener("change", () => pokazTrybPliku(wejscie.files[0] || null));
  document.getElementById("przycisk-tekst-zamiast").addEventListener("click", () => {
    wejscie.value = "";
    pokazTrybPliku(null);
    document.getElementById("tekst").focus();
  });
  const strefa = document.getElementById("strefa-dokumentu");
  for (const rodzaj of ["dragover", "dragenter"]) {
    strefa.addEventListener(rodzaj, (zdarzenie) => {
      zdarzenie.preventDefault();
      strefa.classList.add("upuszczenie");
    });
  }
  for (const rodzaj of ["dragleave", "drop"]) {
    strefa.addEventListener(rodzaj, (zdarzenie) => {
      zdarzenie.preventDefault();
      strefa.classList.remove("upuszczenie");
    });
  }
  strefa.addEventListener("drop", (zdarzenie) => {
    const plik = zdarzenie.dataTransfer?.files?.[0];
    if (!plik) return;
    try {
      wejscie.files = zdarzenie.dataTransfer.files;
    } catch {
      /* starsze przeglądarki nie pozwalają przypisać files — pokażę nazwę i tak */
    }
    pokazTrybPliku(plik);
  });
}

/* ---------- formularze ---------- */

function ustawTrwa(pole, trwa) {
  for (const przycisk of pole.querySelectorAll('button[type="submit"]')) przycisk.disabled = trwa;
}

async function wyslij(url, dane) {
  const odpowiedz = await fetch(url, { method: "POST", headers: NAGLOWKI, body: dane });
  if (!odpowiedz.ok) {
    let tresc = {};
    try {
      tresc = await odpowiedz.json();
    } catch {
      /* odpowiedź błędu bez JSON — użyję samego kodu */
    }
    const wyjatek = new Error(tresc.blad || String(odpowiedz.status));
    wyjatek.status = odpowiedz.status;
    wyjatek.blad = tresc.blad || "";
    wyjatek.odpowiedz = tresc;
    throw wyjatek;
  }
  return odpowiedz;
}

function inicjalizujUkrywanie() {
  const formularz = document.getElementById("form-ukryj");
  const suwak = document.getElementById("poziom");
  const opis = document.getElementById("opis-poziomu");
  const odswiezOpis = () => {
    opis.textContent = OPOWIEDZI_POZIOMOW[suwak.value];
    suwak.setAttribute("aria-valuetext", NAZWY_POZIOMOW[suwak.value]);
  };
  suwak.addEventListener("input", odswiezOpis);
  odswiezOpis();

  formularz.addEventListener("submit", async (zdarzenie) => {
    zdarzenie.preventDefault();
    document.getElementById("status-ukryj").innerHTML = "";
    document.getElementById("wynik").hidden = true;

    const tekst = document.getElementById("tekst").value.trim();
    if (!wybranyPlik && !tekst) {
      komunikat("status-ukryj", "komunikat-blad", "Pusto", "Wklej tekst albo wybierz plik, który mam sprawdzić.");
      (wybranyPlik ? document.getElementById("plik") : document.getElementById("tekst")).focus();
      return;
    }
    const dane = new FormData();
    dane.set("poziom", suwak.value);
    if (wybranyPlik) dane.set("plik", wybranyPlik);
    else dane.set("tekst", tekst);

    ustawTrwa(formularz, true);
    komunikat("status-ukryj", "komunikat-ok", null, "Sprawdzam dokument — to może potrwać kilkadziesiąt sekund…");
    try {
      const odpowiedz = await wyslij("/api/ukryj", dane);
      const czesci = await otworzZip(await odpowiedz.blob());
      document.getElementById("wynik").hidden = false;
      pokazWynik(odpowiedz.headers, czesci);
      document.getElementById("status-ukryj").innerHTML = "";
    } catch (blad) {
      if (blad.odpowiedz && blad.odpowiedz.status === "zablokowany") {
        document.getElementById("wynik").hidden = true;
        pokazBlokade("status-ukryj", blad.odpowiedz.typy);
      } else {
        komunikatOdpowiedzi("status-ukryj", blad.status, blad.blad || blad.message);
      }
    } finally {
      ustawTrwa(formularz, false);
    }
  });

  document.getElementById("kopiuj").addEventListener("click", async () => {
    const tekst = document.getElementById("podglad-tekstu").textContent;
    try {
      await navigator.clipboard.writeText(tekst);
      zapowiedz("Skopiowano do schowka");
    } catch {
      zapowiedz("Przeglądarka nie pozwoliła skopiować — zaznacz tekst ręcznie");
    }
  });

  document.getElementById("pobierz-wynik").addEventListener("click", () => {
    if (wynikPaczka) pobierzBlob(wynikPaczka.wynik.blob, wynikPaczka.wynik.nazwa);
  });
  document.getElementById("pobierz-mape").addEventListener("click", () => {
    if (wynikPaczka) pobierzBlob(wynikPaczka.mapa.blob, wynikPaczka.mapa.nazwa);
  });
}

function inicjalizujPrzywracanie() {
  const formularz = document.getElementById("form-przywroc");
  formularz.addEventListener("submit", async (zdarzenie) => {
    zdarzenie.preventDefault();
    document.getElementById("status-przywroc").innerHTML = "";
    document.getElementById("wynik-przywroc").hidden = true;

    const plikWynik = document.getElementById("plik-wynik").files[0];
    const plikMapa = document.getElementById("plik-mapa").files[0];
    if (!plikWynik || !plikMapa) {
      komunikat("status-przywroc", "komunikat-blad", "Brakuje pliku", "Wybierz oba pliki: dokument z ukrytymi danymi i mapę (.nwidka).");
      (plikWynik ? document.getElementById("plik-mapa") : document.getElementById("plik-wynik")).focus();
      return;
    }
    const dane = new FormData();
    dane.set("wynik", plikWynik);
    dane.set("mapa", plikMapa);

    ustawTrwa(formularz, true);
    komunikat("status-przywroc", "komunikat-ok", null, "Przywracam dane…");
    try {
      const odpowiedz = await wyslij("/api/przywroc", dane);
      const rozbieznosci = JSON.parse(odpowiedz.headers.get("x-niewidka-rozbieznosci") || "[]");
      przywrocony = {
        nazwa: (odpowiedz.headers.get("content-disposition").match(/filename="(.*)"/) || [])[1] || "PRZYWROCONY.txt",
        blob: await odpowiedz.blob(),
      };
      const lista = document.getElementById("lista-rozbieznosci");
      lista.innerHTML = "";
      for (const rozbieznosc of rozbieznosci) {
        const wiersz = document.createElement("li");
        wiersz.textContent =
          rozbieznosc.typ === "znacznik_bez_wpisu"
            ? `${rozbieznosc.opis} — to miejsce zostawiłem bez zmian.`
            : `${rozbieznosc.opis}`;
        lista.append(wiersz);
      }
      document.getElementById("blok-rozbieznosci").hidden = lista.children.length === 0;
      document.getElementById("wynik-przywroc").hidden = false;
      document.getElementById("status-przywroc").innerHTML = "";
      zapowiedz("Dane przywrócone");
    } catch (blad) {
      komunikatOdpowiedzi("status-przywroc", blad.status, blad.blad || blad.message);
    } finally {
      ustawTrwa(formularz, false);
    }
  });

  document.getElementById("pobierz-przywrocony").addEventListener("click", () => {
    if (przywrocony) pobierzBlob(przywrocony.blob, przywrocony.nazwa);
  });
}

/* ---------- start ---------- */

async function wczytajStan() {
  try {
    const odpowiedz = await fetch("/api/stan");
    const stan = await odpowiedz.json();
    limity = stan.limity;
    document.getElementById("wersja").textContent = `v${stan.wersja}`;
    document.getElementById("podpowiedz-plik").textContent =
      `Obsługuję pliki .txt i .docx, maksymalnie ${limity.rozmiar_mb} MB. Możesz też przeciągnąć plik tutaj.`;
  } catch {
    document.getElementById("wersja").textContent = "";
  }
}

inicjalizujZakladki();
inicjalizujWejscie();
inicjalizujUkrywanie();
inicjalizujPrzywracanie();
wczytajStan();

window.addEventListener("beforeunload", (zdarzenie) => {
  if (document.getElementById("tekst").value.trim()) zdarzenie.preventDefault();
});
