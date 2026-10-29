/* Niewidka: web lokalny (K5). Jedna strona, bez zależności, wszystko offline.
 * Token sesji przychodzi w meta (wstrzyknięty przez api.py przy serwowaniu strony),
 * nigdy w URL i nigdy w zasobach statycznych.
 */

"use strict";

const token = document.querySelector('meta[name="niewidka-token"]').content;
const NAGLOWKI = { "X-Niewidka-Token": token };

let limity = { rozmiar_mb: 25, tekst_mb: 1 };
let wynikPaczka = null; // { wynik: {nazwa, blob}, mapa: {nazwa, blob} }
let przywrocony = null; // {nazwa, blob}
let tekstPrzywroconego = ""; // surowy tekst z podglądu przywracania do „Kopiuj"
let mapyZapisane = { retencja_dni: 30, mapy: [] }; // GET /api/mapy

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
  DOWOD: ["numer dowodu osobistego", "numery dowodów osobistych"],
  DATA: ["data", "daty"],
  IP: ["adres IP", "adresy IP"],
  KARTA: ["numer karty płatniczej", "numery kart płatniczych"],
  SWIFT: ["kod SWIFT", "kody SWIFT"],
  LOGIN: ["login", "loginy"],
  INNE: ["inne dane", "inne dane"],
};

function etykieta(typ, ile) {
  const formy = ETYKIETY[typ] || [typ.toLowerCase(), typ.toLowerCase()];
  return `${ile} ${ile === 1 ? formy[0] : formy[1]}`;
}

/* ---------- daty po ludzku (listy map) ---------- */

function _godzina(data) {
  return `${String(data.getHours()).padStart(2, "0")}:${String(data.getMinutes()).padStart(2, "0")}`;
}

function kiedy(data) {
  const teraz = new Date();
  const tenDzien = new Date(data.getFullYear(), data.getMonth(), data.getDate());
  const roznica = Math.round((new Date(teraz.getFullYear(), teraz.getMonth(), teraz.getDate()) - tenDzien) / 86_400_000);
  if (roznica === 0) return `dziś ${_godzina(data)}`;
  if (roznica === 1) return `wczoraj ${_godzina(data)}`;
  const dzienMiesiac = `${String(data.getDate()).padStart(2, "0")}.${String(data.getMonth() + 1).padStart(2, "0")}`;
  if (data.getFullYear() === teraz.getFullYear()) return `${dzienMiesiac} ${_godzina(data)}`;
  return `${dzienMiesiac}.${data.getFullYear()} ${_godzina(data)}`;
}

function doDaty(iso) {
  const data = new Date(iso);
  return `${String(data.getDate()).padStart(2, "0")}.${String(data.getMonth() + 1).padStart(2, "0")}.${data.getFullYear()}`;
}

function opisStatystyk(statystyki) {
  const czesci = Object.entries(statystyki || {}).map(([typ, ile]) => etykieta(typ, ile));
  return czesci.length ? czesci.join(", ") : "bez wykrytych danych";
}

function etykietaZadania(wpis) {
  return `${kiedy(new Date(wpis.utworzono))} · ${opisStatystyk(wpis.statystyki)}`;
}

/* Sekcja „Jak to działa”: wykrywane dane. Nazwy typów pochodzą z ETYKIETY
   (jedno źródło z wynikiem); opisy i przykłady tylko tutaj. */
const TYPY_WYKRYWANE = [
  ["OSOBA", "imiona i nazwiska, także odmienione przez przypadki. Na przykład Jan Kowalski, Jana Kowalskiego, Janowi Kowalskiemu."],
  ["PESEL", "na przykład 85041212345."],
  ["NIP", "na przykład 526-10-40-828 lub 5261040828."],
  ["REGON", "na przykład 012345678."],
  ["IBAN", "numer rachunku bankowego, na przykład PL 61 1090 1014 0000 0712 1981 2874."],
  ["DOKUMENT", "dowód osobisty albo paszport, na przykład ABC 123456 lub ZE 1234567."],
  ["EMAIL", "na przykład j.kowalski@urzad.gov.pl."],
  ["TELEFON", "na przykład +48 600 700 800 lub (22) 123 45 67."],
  ["ADRES", "adres zamieszkania, na przykład ul. Polna 14 m. 5, 00-001 Warszawa."],
  ["DATA", "na przykład data urodzenia, 12 kwietnia 1985 r. albo 12.04.1985."],
  ["KARTA", "numer karty płatniczej, na przykład 4556 7788 9901 2232."],
  ["IP", "adres IP urządzenia, na przykład 192.168.14.201 albo 2001:db8::1."],
  ["SWIFT", "kod banku SWIFT albo BIC, na przykład EBOSPLPW. Wykrywany przy rozszerzonym pakiecie modeli."],
  ["LOGIN", "login do serwisu internetowego, na przykład stefan_wodorost. Wykrywany przy rozszerzonym pakiecie modeli."],
];

function budujListeTypow() {
  const lista = document.getElementById("lista-typow-danych");
  if (!lista) return;
  for (const [typ, opis] of TYPY_WYKRYWANE) {
    const wiersz = document.createElement("li");
    const nazwa = document.createElement("strong");
    nazwa.textContent = (ETYKIETY[typ] || [typ])[0];
    nazwa.textContent = nazwa.textContent.charAt(0).toUpperCase() + nazwa.textContent.slice(1);
    wiersz.append(nazwa, `: ${opis}`);
    lista.append(wiersz);
  }
}

const NAZWY_POZIOMOW = { 1: "Szybko", 2: "Dokładniej", 3: "Najdokładniej" };

const OPOWIEDZI_POZIOMOW = {
  1: "Najszybszy: do szybkiego przeglądu dokumentu.",
  2: "Wyważony: dobry do zwykłych dokumentów.",
  3: "Najstaranniejszy: działa najwolniej, najlepszy do najważniejszych pism.",
};

const KOMUNIKATY = {
  403: "Sesja wygasła. Odśwież stronę (F5) i spróbuj ponownie.",
  409: (blad, calosc) =>
    `${blad || ""} ${calosc && calosc.brak_pakietu ? "Otwórz Ustawienia i pobierz pakiet modeli." : ""}`.trim(),
  413: () => `Za duże wejście: plik może mieć najwyżej ${limity.rozmiar_mb} MB, wklejony tekst ${limity.tekst_mb} MB.`,
  415: "Nieobsługiwany format pliku: przyjmuję .txt i .docx.",
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

   SIMPLIFICATION: czyta wyłącznie ZIP bez zip64, metody stored i deflate,
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
  if (eocd < 0) throw new Error("Ten plik jest uszkodzony albo ma nieprawidłowy format (to nie jest archiwum ZIP).");
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
const POCZATEK_DOPISEKU = "ZANONIMIZOWANY.";

// surowy tekst wyniku do „Kopiuj": podgląd pokazuje znaczniki jako plakietki
// („OSOBA 1"), a skopiowany tekst musi mieć prawdziwe [OSOBA_1_F2], inaczej mapa
// go nie przywróci (przegląd Codex 2026-10-29, P1)
let tekstPodgladu = "";

function wypelnijPodglad(tekst, idMiejsca) {
  const miejsce = document.getElementById(idMiejsca);
  miejsce.textContent = "";
  let tresc = tekst;
  if (tresc.startsWith(POCZATEK_DOPISEKU)) tresc = pokazDopisek(miejsce, tresc);
  pokazZaslepki(miejsce, tresc);
}

function pokazPodglad(tekst) {
  tekstPodgladu = tekst;
  wypelnijPodglad(tekst, "podglad-tekstu");
}

function pokazPodgladPrzywrocony(tekst) {
  tekstPrzywroconego = tekst;
  wypelnijPodglad(tekst, "podglad-przywroconego");
}

/* wspólne „Kopiuj" dla podglądu ukrywania i przywracania */
async function skopiujDoSchowka(tekst, przycisk) {
  let tresc;
  try {
    await navigator.clipboard.writeText(tekst);
    tresc = "Skopiowano";
  } catch {
    tresc = "Nie udało się skopiować. Pobierz dokument przyciskiem obok.";
  }
  zapowiedz(tresc);
  przycisk.textContent = tresc;
  setTimeout(() => { przycisk.textContent = "Kopiuj"; }, 2500);
}

/* K5c: pełny dopisek z identyfikatorem mapy zostaje w pliku wynikowym; w podglądzie
   zwinięty do pierwszych słów, żeby długim kodem mapy nie przysłaniać tekstu. */
function pokazDopisek(miejsce, tresc) {
  const koniecLinii = tresc.indexOf("\n");
  const linia = koniecLinii === -1 ? tresc : tresc.slice(0, koniecLinii);
  const szczegoly = document.createElement("details");
  szczegoly.className = "dopisek";
  const podsumowanie = document.createElement("summary");
  podsumowanie.textContent = "ZANONIMIZOWANY. …";
  const pelny = document.createElement("span");
  pelny.className = "dopisek-pelny";
  pelny.textContent = linia;
  szczegoly.append(podsumowanie, pelny);
  miejsce.append(szczegoly);
  return koniecLinii === -1 ? "" : tresc.slice(koniecLinii + 1);
}

function pokazZaslepki(miejsce, tekst) {
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

function komunikatOdpowiedzi(statusId, status, blad, calosc) {
  const przepis = KOMUNIKATY[status];
  const tresc = typeof przepis === "function" ? przepis(blad, calosc) : przepis || `Błąd ${status}. ${blad || ""}`;
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
  tytul.textContent = "STOP: tego dokumentu nie wolno wysyłać.";
  blok.append(tytul);
  const opis = document.createElement("p");
  const typyTekst = Object.entries(typy || {})
    .map(([typ, ile]) => etykieta(typ, ile))
    .join(", ");
  opis.textContent = "Wynik zatrzymany przez kontrolę jakości. W dokumencie mogły zostać dane osobowe. "
    + (typyTekst
      ? `Ponowne sprawdzenie znalazło: ${typyTekst}. `
      : "Ponowne sprawdzenie znalazło dane przypominające oryginalne. ")
    + "Dokument zablokowano, nic nie zostało zapisane ani skopiowane. Popraw dane w oryginale i spróbuj ponownie.";
  blok.append(opis);
  pole.append(blok);
}

function pokazWynik(naglowki, czesci) {
  const identyfikator = naglowki.get("x-niewidka-identyfikator");
  const statystyki = JSON.parse(naglowki.get("x-niewidka-statystyki") || "{}");
  const r95 = JSON.parse(naglowki.get("x-niewidka-r95") || "{}");
  const ostrzezenia = JSON.parse(naglowki.get("x-niewidka-ostrzezenia") || "{}");

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
  // „zaliczona" tylko przy pustej liście ostrzeżeń (przegląd Codex 2026-10-29, P2)
  const zaliczona = Object.keys(ostrzezenia).length === 0;
  blok.className = zaliczona ? "komunikat komunikat-ok" : "komunikat komunikat-ostrzezenie";
  const tytul = document.createElement("h3");
  tytul.textContent = zaliczona ? "Kontrola jakości: zaliczona" : "Kontrola jakości: sprawdź wynik";
  blok.append(tytul);
  const opis = document.createElement("p");
  opis.textContent = zaliczona
    ? "Ponowne sprawdzenie wyniku nie znalazło danych, które program umie wykrywać. "
      + "Program nie wykrywa wszystkiego, dlatego przejrzyj wynik przed wysłaniem."
    : "Ponowne sprawdzenie znalazło w wyniku dane przypominające oryginalne. Lista jest niżej.";
  blok.append(opis);
  const uwagi = JSON.parse(naglowki.get("x-niewidka-uwagi") || "[]");
  for (const uwaga of uwagi) {
    const wiersz = document.createElement("p");
    wiersz.textContent = uwaga;
    blok.append(wiersz);
  }
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
  /* K5c: teksty ryzyka przychodzą gotowe z serwera (próg małej próby liczy serwer) */
  const oszacowane = Object.entries(r95).filter(([, wpis]) => wpis && wpis.opis != null);
  for (const [typ, wpis] of oszacowane) {
    const wiersz = document.createElement("li");
    const co = document.createElement("span");
    co.textContent = (ETYKIETY[typ] || [typ])[0];
    co.textContent = co.textContent.charAt(0).toUpperCase() + co.textContent.slice(1);
    const ile = document.createElement("span");
    ile.textContent = wpis.opis;
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
  for (const [typ, ile] of Object.entries(ostrzezenia)) {
    /* K4b pkt 8: nagłówek niesie wyłącznie typy i liczniki, nigdy fragmenty danych */
    const wiersz = document.createElement("li");
    wiersz.textContent = `W wyniku zostały dane przypominające oryginalne: ${etykieta(typ, ile)}. Zobacz, gdzie dokładnie, zanim dokument opuści ten komputer.`;
    listaOstrzezenia.append(wiersz);
  }
  blokOstrzezenia.hidden = listaOstrzezenia.children.length === 0;

  const trescTekstowa = new TextDecoder().decode(czesci[nazwaWyniku]);
  const podglad = document.getElementById("blok-podglad");
  const wygladaNaTekst = nazwaWyniku.endsWith(".txt") && !trescTekstowa.slice(0, 100).includes("\0");
  podglad.hidden = !wygladaNaTekst;
  if (wygladaNaTekst) pokazPodglad(trescTekstowa);

  document.getElementById("blok-pobrania").hidden = false;

  /* docs/MAPY-I-AKTUALIZACJE.md §1: mapa zapisuje się sama; nagłówek jest wtedy,
     gdy program próbował: z datą wygaśnięcia albo „blad", gdy zapisać się nie dało
     (§9 pkt 5: wynik i tak wydany, ale mapę trzeba pobrać). */
  const blokMapy = document.getElementById("mapa-zapisana");
  const zapisanaDo = naglowki.get("x-niewidka-mapa-zapisana");
  if (zapisanaDo === "blad") {
    blokMapy.className = "komunikat komunikat-ostrzezenie";
    blokMapy.innerHTML = "";
    const opis = document.createElement("p");
    opis.textContent = "Nie udało się zapisać mapy na tym komputerze. "
      + "Pobierz mapę, bo nie została zapisana.";
    blokMapy.append(opis);
    blokMapy.hidden = false;
  } else if (zapisanaDo) {
    blokMapy.className = "komunikat komunikat-ok";
    blokMapy.innerHTML = "";
    const opis = document.createElement("p");
    opis.textContent = `Mapa zapisana na tym komputerze do ${doDaty(zapisanaDo)}. `
      + "Przywrócisz dane, wklejając odpowiedź na zakładce Przywróć.";
    blokMapy.append(opis);
    blokMapy.hidden = false;
    odswiezMapy();
  } else {
    blokMapy.hidden = true;
  }
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
  const hasz = wybrana.id === "zakladka-przywroc" ? "#przywroc" : wybrana.id === "zakladka-ustawienia" ? "#ustawienia" : "#ukryj";
  if (history.replaceState) history.replaceState(null, "", hasz);
}

function inicjalizujZakladki() {
  const zakladki = [...document.querySelectorAll('[role="tab"]')];
  if (location.hash === "#przywroc") ustawZakladke(document.getElementById("zakladka-przywroc"));
  if (location.hash === "#ustawienia") ustawZakladke(document.getElementById("zakladka-ustawienia"));
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
      /* starsze przeglądarki nie pozwalają przypisać files: pokażę nazwę i tak */
    }
    pokazTrybPliku(plik);
  });
}

/* ---------- formularze ---------- */

// trwające zlecenie blokuje „Ukryj" także przy odświeżaniu pakietów w tle
// (Codex 2026-10-29: polling postępu odblokowywał przycisk w trakcie ukrywania)
let trwaZlecenie = false;
// sekcja 9 pkt 5: numerowane żądania - odpowiedź starszego zlecenia nie renderuje
// się, gdy użytkownik zdążył już wysłać nowsze
let licznikZlecen = 0;

function ustawTrwa(pole, trwa) {
  trwaZlecenie = trwa;
  for (const przycisk of pole.querySelectorAll('button[type="submit"]')) przycisk.disabled = trwa;
}

async function wyslij(url, dane) {
  let odpowiedz;
  try {
    odpowiedz = await fetch(url, { method: "POST", headers: NAGLOWKI, body: dane });
  } catch {
    throw new Error("Brak połączenia z programem. Uruchom go ponownie i spróbuj jeszcze raz.");
  }
  if (!odpowiedz.ok) {
    let tresc = {};
    try {
      tresc = await odpowiedz.json();
    } catch {
      /* odpowiedź błędu bez JSON: użyję samego kodu */
    }
    // FastAPI HTTPException zwraca „detail", nasze odpowiedzi „blad" (Codex 2026-10-29)
    const opis = tresc.blad || (typeof tresc.detail === "string" ? tresc.detail : "");
    const wyjatek = new Error(opis || String(odpowiedz.status));
    wyjatek.status = odpowiedz.status;
    wyjatek.blad = opis;
    wyjatek.odpowiedz = tresc;
    throw wyjatek;
  }
  return odpowiedz;
}

function odswiezOpisPoziomu() {
  const suwak = document.getElementById("poziom");
  const opis = document.getElementById("opis-poziomu");
  opis.textContent = OPOWIEDZI_POZIOMOW[suwak.value];
  suwak.setAttribute("aria-valuetext", NAZWY_POZIOMOW[suwak.value]);
}

function inicjalizujUkrywanie() {
  const formularz = document.getElementById("form-ukryj");
  const suwak = document.getElementById("poziom");
  suwak.addEventListener("input", odswiezOpisPoziomu);
  odswiezOpisPoziomu();

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
    const mojaKolejna = ++licznikZlecen;
    komunikat("status-ukryj", "komunikat-ok", null, "Sprawdzam dokument. To może potrwać kilkadziesiąt sekund.");
    try {
      const odpowiedz = await wyslij("/api/ukryj", dane);
      if (mojaKolejna !== licznikZlecen) return; // nowsze żądanie wygrało
      const czesci = await otworzZip(await odpowiedz.blob());
      document.getElementById("wynik").hidden = false;
      pokazWynik(odpowiedz.headers, czesci);
      document.getElementById("status-ukryj").innerHTML = "";
    } catch (blad) {
      if (mojaKolejna !== licznikZlecen) return;
      if (blad.odpowiedz && blad.odpowiedz.status === "zablokowany") {
        document.getElementById("wynik").hidden = true;
        pokazBlokade("status-ukryj", blad.odpowiedz.typy);
      } else {
        komunikatOdpowiedzi("status-ukryj", blad.status, blad.blad || blad.message, blad.odpowiedz);
        if (blad.status === 409) odswiezPakiety();
      }
    } finally {
      if (mojaKolejna === licznikZlecen) ustawTrwa(formularz, false);
    }
  });

  const przyciskKopiuj = document.getElementById("kopiuj");
  przyciskKopiuj.addEventListener("click", async () => {
    await skopiujDoSchowka(tekstPodgladu, przyciskKopiuj);
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
  const radiotryby = [...document.querySelectorAll('input[name="tryb-przywroc"]')];

  const przelaczTryby = () => {
    const tryb = radiotryby.find((radio) => radio.checked).value;
    document.getElementById("tryb-tekst").hidden = tryb !== "tekst";
    document.getElementById("tryb-plik").hidden = tryb !== "plik";
  };
  for (const radio of radiotryby) radio.addEventListener("change", przelaczTryby);
  przelaczTryby();

  const mapaJest = document.getElementById("mapa-tekst-jest");
  mapaJest.addEventListener("change", () => {
    document.getElementById("plik-mapa-tekst").hidden = !mapaJest.checked;
    if (!mapaJest.checked) document.getElementById("plik-mapa-tekst").value = "";
  });

  formularz.addEventListener("submit", async (zdarzenie) => {
    zdarzenie.preventDefault();
    document.getElementById("status-przywroc").innerHTML = "";
    document.getElementById("wynik-przywroc").hidden = true;

    const tryb = radiotryby.find((radio) => radio.checked).value;
    const dane = new FormData();
    let mapaZPliku = false;
    if (tryb === "tekst") {
      const wklejone = document.getElementById("tekst-przywroc").value.trim();
      if (!wklejone) {
        komunikat("status-przywroc", "komunikat-blad", "Pusto", "Wklej odpowiedź z czatu AI, którą mam przywrócić.");
        document.getElementById("tekst-przywroc").focus();
        return;
      }
      dane.set("tekst", wklejone);
      const wybraneZadanie = document.getElementById("lista-zadan").value;
      if (wybraneZadanie) dane.set("identyfikator", wybraneZadanie);
      const plikMapy = document.getElementById("plik-mapa-tekst").files[0];
      if (mapaJest.checked && plikMapy) {
        dane.set("mapa", plikMapy);
        mapaZPliku = true;
      }
    } else {
      const plikWynik = document.getElementById("plik-wynik").files[0];
      const plikMapa = document.getElementById("plik-mapa").files[0];
      if (!plikWynik || !plikMapa) {
        komunikat("status-przywroc", "komunikat-blad", "Brakuje pliku", "Wybierz oba pliki: dokument z ukrytymi danymi i mapę (.nwidka).");
        (plikWynik ? document.getElementById("plik-mapa") : document.getElementById("plik-wynik")).focus();
        return;
      }
      dane.set("wynik", plikWynik);
      dane.set("mapa", plikMapa);
      mapaZPliku = true;
    }

    ustawTrwa(formularz, true);
    const mojaKolejna = ++licznikZlecen;
    komunikat("status-przywroc", "komunikat-ok", null, "Przywracam dane…");
    try {
      const odpowiedz = await wyslij("/api/przywroc", dane);
      if (mojaKolejna !== licznikZlecen) return; // nowsze żądanie wygrało
      const blob = await odpowiedz.blob();
      // wklejony tekst wraca jako text/plain, bez content-disposition (tylko plik go ma)
      const nazwaPliku = (odpowiedz.headers.get("content-disposition") || "").match(/filename="(.*)"/);
      przywrocony = {
        nazwa: (nazwaPliku && nazwaPliku[1]) || "PRZYWROCONY.txt",
        blob,
      };
      const rozbieznosci = JSON.parse(odpowiedz.headers.get("x-niewidka-rozbieznosci") || "[]");
      const lista = document.getElementById("lista-rozbieznosci");
      lista.innerHTML = "";
      for (const rozbieznosc of rozbieznosci) {
        const wiersz = document.createElement("li");
        wiersz.textContent =
          rozbieznosc.typ === "znacznik_bez_wpisu"
            ? `${rozbieznosc.opis}. To miejsce zostaje bez zmian.`
            : `${rozbieznosc.opis}`;
        lista.append(wiersz);
      }
      document.getElementById("blok-rozbieznosci").hidden = lista.children.length === 0;

      /* jawnie: z której zapisanej mapy wróciły dane (przegląd Argona pkt 2); przy
         mapie z pliku .nwidka źródło jest oczywiste, więc komunikat zbędny */
      const blokAuto = document.getElementById("mapa-wybrana-auto");
      const wpisMapy = (mapyZapisane.mapy || []).find(
        (m) => m.id === odpowiedz.headers.get("x-niewidka-identyfikator"),
      );
      if (wpisMapy && !mapaZPliku) {
        blokAuto.innerHTML = "";
        const opis = document.createElement("p");
        opis.textContent = odpowiedz.headers.get("x-niewidka-mapa-wybrana-automatycznie")
          ? `Przywrócono z mapy zadania: ${etykietaZadania(wpisMapy)} (jedyna pasująca).`
          : `Przywrócono z mapy zadania: ${etykietaZadania(wpisMapy)}.`;
        blokAuto.append(opis);
        blokAuto.hidden = false;
      } else {
        blokAuto.hidden = true;
      }

      const podglad = document.getElementById("blok-podglad-przywroc");
      if (tryb === "tekst") {  // wklejony tekst wraca do podglądu; plik odpowiedzi do pobrania
        const tekst = await blob.text();
        pokazPodgladPrzywrocony(tekst);
        podglad.hidden = false;
      } else {
        podglad.hidden = true;
      }
      document.getElementById("wynik-przywroc").hidden = false;
      document.getElementById("status-przywroc").innerHTML = "";
      zapowiedz("Dane przywrócone");
    } catch (blad) {
      if (mojaKolejna !== licznikZlecen) return;
      if (blad.odpowiedz && blad.odpowiedz.kod === "wybierz_mape") {
        /* docs/MAPY-I-AKTUALIZACJE.md §3: komunikat prowadzi do listy zadań */
        komunikat("status-przywroc", "komunikat-ostrzezenie", "Wskaż mapę", `${blad.blad} Wybierz zadanie z listy.`);
        document.getElementById("lista-zadan").focus();
      } else {
        komunikatOdpowiedzi("status-przywroc", blad.status, blad.blad || blad.message);
      }
    } finally {
      if (mojaKolejna === licznikZlecen) ustawTrwa(formularz, false);
    }
  });

  document.getElementById("pobierz-przywrocony").addEventListener("click", () => {
    if (przywrocony) pobierzBlob(przywrocony.blob, przywrocony.nazwa);
  });
  document.getElementById("kopiuj-przywrocony").addEventListener("click", async (zdarzenie) => {
    await skopiujDoSchowka(tekstPrzywroconego, zdarzenie.currentTarget);
  });
}

/* ---------- zapisane mapy (docs/MAPY-I-AKTUALIZACJE.md §1-2) ---------- */

async function odswiezMapy() {
  try {
    const odpowiedz = await fetch("/api/mapy", { headers: NAGLOWKI });
    if (!odpowiedz.ok) return; // sesja wygasła albo błąd: zostawiam poprzedni stan
    mapyZapisane = await odpowiedz.json();
  } catch {
    return; // serwer nieodpowiada: nic nie zmieniamy
  }
  wypelnijListeZadan();
  rysujListeMapZapisanych();
}

function wypelnijListeZadan() {
  const lista = document.getElementById("lista-zadan");
  lista.innerHTML = "";
  const wpisy = mapyZapisane.mapy || [];
  if (wpisy.length === 0) {
    const pusta = document.createElement("option");
    pusta.value = "";
    pusta.textContent = "Brak zapisanych map";
    pusta.disabled = true;
    pusta.selected = true;
    lista.append(pusta);
    return;
  }
  for (const [i, wpis] of wpisy.entries()) {
    const opcja = document.createElement("option");
    opcja.value = wpis.id;
    opcja.textContent = etykietaZadania(wpis);
    if (i === 0) opcja.selected = true; // domyślnie najnowsze
    lista.append(opcja);
  }
}

function rysujListeMapZapisanych() {
  const lista = document.getElementById("lista-map-zapisanych");
  lista.innerHTML = "";
  const okres = document.getElementById("okres-map");
  if (mapyZapisane.retencja_dni === 0) {
    okres.textContent = "Mapy nie są zapisywane automatycznie. Pobierz mapę po każdym ukryciu.";
  } else {
    okres.textContent = `Mapy są usuwane automatycznie po ${mapyZapisane.retencja_dni} dniach. Okres ustawia administrator.`;
  }
  for (const wpis of mapyZapisane.mapy || []) {
    const wiersz = document.createElement("li");
    const opis = document.createElement("span");
    opis.textContent = `${etykietaZadania(wpis)}, przechowywana do ${doDaty(wpis.wygasa)}`;
    const przycisk = document.createElement("button");
    przycisk.type = "button";
    przycisk.className = "przycisk-wtorny";
    przycisk.textContent = "Usuń";
    przycisk.addEventListener("click", async () => {
      await usunMape(wpis.id);
      odswiezMapy();
    });
    wiersz.append(opis, przycisk);
    lista.append(wiersz);
  }
  document.getElementById("usun-wszystkie-mapy").hidden = (mapyZapisane.mapy || []).length === 0;
}

async function usunMape(identyfikator) {
  try {
    const odpowiedz = await fetch(`/api/mapy/${identyfikator}`, { method: "DELETE", headers: NAGLOWKI });
    zapowiedz(odpowiedz.ok ? "Mapa usunięta" : "Nie udało się usunąć mapy");
  } catch {
    zapowiedz("Nie udało się usunąć mapy");
  }
}

function inicjalizujMapy() {
  document.getElementById("usun-wszystkie-mapy").addEventListener("click", async () => {
    if (!confirm("Usunąć wszystkie zapisane mapy? Pobrane pliki map (.nwidka) zostają.")) return;
    try {
      const odpowiedz = await fetch("/api/mapy", { method: "DELETE", headers: NAGLOWKI });
      zapowiedz(odpowiedz.ok ? "Mapy usunięte" : "Nie udało się usunąć map");
    } catch {
      zapowiedz("Nie udało się usunąć map");
    }
    odswiezMapy();
  });
}

/* ---------- pakiety modeli (K7b) ---------- */

let stanPakietow = { pakiety: [], poziomy_dostepne: [], postep: { pakiet: null, blad: null } };
let ekranPakietowOdrzucony = false; // „Później" w tej sesji
let odpytywaniePostepu = null;
let kolejkaPakietow = []; // „Pobierz wszystko": rozszerzony po podstawowym

function sformatujRozmiar(bajty) {
  return `${Math.round(bajty / (1024 * 1024))}\u00A0MB`;
}

const OPISY_STANOW = {
  zainstalowany: "gotowy",
  brak: "nie pobrany",
  uszkodzony: "uszkodzony, pobierz ponownie",
};

function podswietlStatusPakietu(id) {
  const wpis = stanPakietow.pakiety.find((p) => p.id === id);
  return wpis ? OPISY_STANOW[wpis.stan] || wpis.stan : "";
}

function odswiezSuwakZPakietow() {
  const suwak = document.getElementById("poziom");
  const przycisk = document.getElementById("ukryj");
  const opis = document.getElementById("opis-poziomu");
  const pusto = stanPakietow.poziomy_dostepne.length === 0;
  suwak.disabled = pusto;
  przycisk.disabled = pusto || trwaZlecenie;
  if (pusto) {
    opis.textContent = "Modele nie są jeszcze pobrane. Pobierz pakiet podstawowy w Ustawieniach.";
  } else {
    odswiezOpisPoziomu();
  }
}

function rysujListePakietow() {
  const lista = document.getElementById("lista-pakietow");
  lista.innerHTML = "";
  for (const pakiet of stanPakietow.pakiety) {
    const wiersz = document.createElement("div");
    wiersz.className = "pakiet-wiersz";
    const naglowek = document.createElement("div");
    naglowek.className = "pakiet-naglowek";
    const nazwa = document.createElement("h3");
    nazwa.textContent = pakiet.nazwa;
    const stan = document.createElement("span");
    stan.className = `pakiet-stan pakiet-stan-${pakiet.stan}`;
    stan.textContent = podswietlStatusPakietu(pakiet.id);
    naglowek.append(nazwa, stan);
    const opis = document.createElement("p");
    opis.textContent = `${pakiet.opis} Rozmiar do pobrania: ${sformatujRozmiar(pakiet.rozmiar_bajtow)}.`;
    const akcje = document.createElement("div");
    akcje.className = "pakiet-akcje";
    const przycisk = document.createElement("button");
    przycisk.type = "button";
    przycisk.className = pakiet.stan === "zainstalowany" ? "przycisk-wtorny" : "przycisk-glowny";
    if (pakiet.stan === "zainstalowany") {
      przycisk.textContent = "Usuń";
      przycisk.addEventListener("click", () => {
        if (!confirm(`Usunąć pakiet ${pakiet.nazwa}? Przywrócenie pracy będzie wymagało pobrania go ponownie.`)) return;
        akcjaPakietu("usun", pakiet.id);
      });
    } else {
      przycisk.textContent = "Pobierz";
      przycisk.disabled = stanPakietow.postep.pakiet !== null;
      przycisk.addEventListener("click", () => akcjaPakietu("pobierz", pakiet.id));
    }
    akcje.append(przycisk);
    wiersz.append(naglowek, opis, akcje);
    lista.append(wiersz);
  }
}

// postęp i błąd widać i w Ustawieniach, i na ekranie pierwszego uruchomienia
// (wcześniej ekran startowy nie pokazywał nic, a błąd znikał razem z postępem)
const MIEJSCA_POSTEPU = [
  ["postep-pakietu", "postep-pakietu-pasek", "postep-pakietu-status"],
  ["ekran-pakietow-postep", "ekran-pakietow-pasek", "ekran-pakietow-status"],
];

function pokazPostepPostepu(pakietId, pobrane, razem, blad) {
  const procent = razem > 0 ? Math.round((pobrane / razem) * 100) : 0;
  const tekst = blad
    ? `Nie udało się pobrać pakietu: ${blad}`
    : `Pobieranie pakietu ${pakietId}: ${procent}%…`;
  for (const [idBloku, idPaska, idStatusu] of MIEJSCA_POSTEPU) {
    document.getElementById(idBloku).hidden = !pakietId && !blad;
    document.getElementById(idPaska).value = procent;
    document.getElementById(idStatusu).textContent = pakietId || blad ? tekst : "";
  }
}

async function odswiezPakiety() {
  try {
    const odpowiedz = await fetch("/api/pakiety", { headers: NAGLOWKI });
    if (!odpowiedz.ok) return; // sesja wygasła albo błąd: zostawiam poprzedni stan
    stanPakietow = await odpowiedz.json();
  } catch {
    return; // serwer nieodpowiada: nic nie zmieniamy
  }
  rysujListePakietow();
  odswiezSuwakZPakietow();
  pokazPostepPostepu(
    stanPakietow.postep.pakiet,
    stanPakietow.postep.pobrane,
    stanPakietow.postep.razem,
    stanPakietow.postep.blad,
  );

  const brakujeWymagany = stanPakietow.pakiety.some(
    (p) => p.wymagany && p.stan !== "zainstalowany",
  );
  const ekran = document.getElementById("ekran-pakietow");
  const pokazEkran = brakujeWymagany && !ekranPakietowOdrzucony;
  ekran.hidden = !pokazEkran;
  document.getElementById("ekran-pakietow-wybor").hidden = stanPakietow.postep.pakiet !== null;
  return stanPakietow;
}

function pollujPostep() {
  if (odpytywaniePostepu) clearInterval(odpytywaniePostepu);
  odpytywaniePostepu = setInterval(async () => {
    const stan = await odswiezPakiety();
    if (!stan) return; // chwilowy błąd odczytu: pytamy dalej, nie ogłaszamy końca (Codex 2026-10-29)
    if (stan.postep.pakiet === null) {
      clearInterval(odpytywaniePostepu);
      odpytywaniePostepu = null;
      zapowiedz("Operacja na pakiecie zakończona");
      const nastepny = kolejkaPakietow.shift();
      if (nastepny) akcjaPakietu("pobierz", nastepny);
    }
  }, 300);
}

async function akcjaPakietu(akcja, identyfikator, katalog) {
  const dane = { akcja, pakiet: identyfikator };
  if (katalog) dane.katalog = katalog;
  try {
    const odpowiedz = await wyslij("/api/pakiety", JSON.stringify(dane));
    if (akcja === "pobierz") {
      pollujPostep();
      odswiezPakiety();
    } else {
      zapowiedz(odpowiedz.ok ? "Gotowe" : "Nie udało się");
      odswiezPakiety();
    }
  } catch (blad) {
    komunikatOdpowiedziDlaPakietow(blad);
  }
}

function komunikatOdpowiedziDlaPakietow(blad) {
  for (const [idBloku, , idStatusu] of MIEJSCA_POSTEPU) {
    document.getElementById(idBloku).hidden = false;
    document.getElementById(idStatusu).textContent = `Nie udało się: ${blad.blad || blad.message}`;
  }
}

function inicjalizujPakiety() {
  document.getElementById("pakiet-pobierz-podstawowy").addEventListener("click", () => {
    akcjaPakietu("pobierz", "podstawowy");
  });
  document.getElementById("pakiet-pobierz-wszystko").addEventListener("click", () => {
    kolejkaPakietow = ["rozszerzony"];
    akcjaPakietu("pobierz", "podstawowy");
  });
  document.getElementById("pakiet-pozniej").addEventListener("click", () => {
    ekranPakietowOdrzucony = true;
    document.getElementById("ekran-pakietow").hidden = true;
    odswiezSuwakZPakietow();
  });
}

/* ---------- start ---------- */

async function wczytajStan() {
  try {
    const odpowiedz = await fetch("/api/stan", { headers: NAGLOWKI });
    if (!odpowiedz.ok) return;
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
inicjalizujPakiety();
inicjalizujMapy();
budujListeTypow();
wczytajStan();
odswiezPakiety();
odswiezMapy();
/* Ekran pierwszego uruchomienia znika sam, gdy pakiet pojawi się z zewnątrz
   (IT instaluje z katalogu albo drugie okno pobiera): lekki odpyt tylko,
   dopóki ekran jest widoczny. */
setInterval(() => {
  if (odpytywaniePostepu) return;
  if (!document.getElementById("ekran-pakietow").hidden) odswiezPakiety();
}, 2500);

window.addEventListener("beforeunload", (zdarzenie) => {
  if (document.getElementById("tekst").value.trim()) zdarzenie.preventDefault();
});
