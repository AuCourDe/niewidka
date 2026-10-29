"""Dymny test nowych funkcji API na żywym serwerze (fikcyjne dane)."""
import io, re, sys, zipfile, httpx
B = sys.argv[1]
c = httpx.Client(base_url=B, timeout=120)
t = re.search(r'name="niewidka-token" content="([^"]+)"', c.get("/").text).group(1)
H = {"X-Niewidka-Token": t, "Origin": B}
wyn = []
c.delete("/api/mapy", headers=H)  # czysty magazyn: jeden kandydat
def ok(nazwa, warunek, info=""):
    wyn.append(bool(warunek)); print(("OK  " if warunek else "BLAD"), nazwa, info)
tekst = "Pismo do Pana Jana Kowalskiego, PESEL 44051401359, tel. 600 100 200. Z poważaniem, Anna Nowak."
r = c.post("/api/ukryj", headers=H, data={"tekst": tekst, "poziom": "3"})
ok("ukryj 200", r.status_code == 200, r.status_code)
zapis = r.headers.get("x-niewidka-mapa-zapisana"); ok("mapa zapisana automatycznie", zapis and zapis != "blad", zapis)
z = zipfile.ZipFile(io.BytesIO(r.content)); wynik = z.read(next(n for n in z.namelist() if n.endswith(".txt"))).decode("utf-8")
zad = r.headers.get("x-niewidka-zadanie"); ok("identyfikator zadania do poprawek", zad, zad)
ok("dopisek ZANONIMIZOWANY", wynik.startswith("ZANONIMIZOWANY"))
ok("PESEL ukryty", "44051401359" not in wynik)
# odpowiedź AI: same znaczniki, bez dopisku
znaczniki = re.findall(r"\[[A-Z_]+_\d+(?:_F\d+)?\]", wynik)
odp = "Szanowny " + " ".join(znaczniki) + " - odpowiedź przygotowana."
r = c.post("/api/przywroc", headers=H, data={"tekst": odp})
ok("przywróć wklejony tekst bez mapy", r.status_code == 200 and "44051401359" in r.text, r.status_code)
ok("wybór automatyczny zgłoszony", r.headers.get("x-niewidka-mapa-wybrana-automatycznie"))
# odpowiedź z dopiskiem
r2 = c.post("/api/przywroc", headers=H, data={"tekst": wynik})
ok("przywróć z dopiskiem", r2.status_code == 200 and "Kowalsk" in r2.text, r2.status_code)
r = c.get("/api/mapy", headers=H); m = r.json()
ok("lista map", r.status_code == 200 and len(m.get("mapy", [])) >= 1, f"retencja={m.get('retencja_dni')} n={len(m.get('mapy', []))}")
# poprawki: ukryj słowo, To nie dane dla osoby
r = c.post("/api/popraw", headers=H, json={"zadanie": zad, "ukryj": ["poważaniem"], "nie_dane": []})
ok("popraw: ukryj wszędzie", r.status_code == 200, r.status_code)
osoba = re.sub(r"^\[|_F\d+\]$|\]$", "", next((z for z in znaczniki if z.startswith("[OSOBA")), ""))

r = c.post("/api/popraw", headers=H, json={"zadanie": zad, "ukryj": [], "nie_dane": [osoba]})
ok("popraw: to nie dane (osoba)", r.status_code == 200, (r.status_code, r.text[:150]))
pesel = next((z for z in znaczniki if z.startswith("[PESEL")), "").strip("[]")
r = c.post("/api/popraw", headers=H, json={"zadanie": zad, "ukryj": [], "nie_dane": [pesel]})
ok("popraw: PESEL nie da się zdjąć (422, suma kontrolna)", r.status_code == 422 and "sum" in r.text, r.text[:80])
r = c.post("/api/popraw", headers=H, json={"zadanie": "0"*32, "ukryj": ["x"], "nie_dane": []})
ok("popraw: nieznane zadanie 410", r.status_code == 410, r.status_code)
r = c.get("/api/aktualizacje", headers=H); a = r.json()
ok("aktualizacje: stan", r.status_code == 200, {k: a.get(k) for k in ("tryb", "stan", "klucz_wydawcy")})
r = c.post("/api/aktualizacje", headers=H, json={"akcja": "sprawdz"})
ok("aktualizacje: sprawdź bez klucza wydawcy = czytelny 422", r.status_code == 422, r.text[:120])
r = c.get("/api/mapy")
ok("lista map bez tokenu = 403", r.status_code == 403, r.status_code)
pierwsza = c.get("/api/mapy", headers=H).json()["mapy"][0]["id"]
r = c.delete(f"/api/mapy/{pierwsza}", headers=H); ok("usuń mapę", r.status_code in (200, 204), r.status_code)
r = c.delete("/api/mapy/abc", headers=H); ok("usuń mapę: zły identyfikator odrzucony", r.status_code in (404, 422), r.status_code)
r = c.delete("/api/mapy", headers=H); ok("usuń wszystkie", r.status_code in (200, 204), r.status_code)
ok("lista pusta", c.get("/api/mapy", headers=H).json()["mapy"] == [])
print(f"\n{sum(wyn)}/{len(wyn)} zaliczonych")
