"""Smoke GUI poprawek w podglądzie: serwer z atrapą detektora + headless Chrome przez CDP na pipe
(bez portu debugowania). Uruchom: .venv/bin/python testy_e2e/gui_poprawki.py (wymaga google-chrome)."""
import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn

sp = importlib.util.spec_from_file_location("t", str(Path(__file__).resolve().parents[1] / "tests" / "test_poprawki.py"))
t = importlib.util.module_from_spec(sp); sp.loader.exec_module(t)

tmp = Path(tempfile.mkdtemp())
klucz = tmp / "k"; klucz.write_bytes(base64.b64encode(t.KLUCZ)); klucz.chmod(0o600)
PORT = int(os.environ.get("PORT", "8391"))
app = t.create_app(t.Konfig(port=PORT, klucz_plik=str(klucz), mapy_katalog=tmp / "m"), detektor=t.DetektorUparty(frazy=("Jan Nowak", "Maria Lis")))
serwer = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=serwer.run, daemon=True).start()
time.sleep(1.5)

r1, w1 = os.pipe(); r2, w2 = os.pipe()  # chrome czyta r1 (fd3), pisze w2 (fd4)
def pre():
    os.dup2(r1, 3); os.dup2(w2, 4)
chrome = subprocess.Popen(["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-pipe",
                           f"--user-data-dir={tmp/'profil'}", "about:blank"], preexec_fn=pre, pass_fds=(3, 4),  # noqa: PLW1509 - tylko os.dup2 (chrome oczekuje fd 3 i 4)
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
os.close(r1); os.close(w2)
wej = os.fdopen(w1, "wb", buffering=0); wyj = os.fdopen(r2, "rb", buffering=0)
_id = 0; bufor = b""
def wyslij(metoda, params=None, sesja=None):
    global _id, bufor
    _id += 1
    msg = {"id": _id, "method": metoda, "params": params or {}}
    if sesja: msg["sessionId"] = sesja
    wej.write(json.dumps(msg).encode() + b"\0")
    while True:
        while b"\0" not in bufor:
            bufor += wyj.read(65536)
        raw, bufor = bufor.split(b"\0", 1)
        odp = json.loads(raw)
        if odp.get("id") == _id:
            if "error" in odp: raise RuntimeError(odp["error"])
            return odp["result"]
cel = wyslij("Target.createTarget", {"url": "about:blank"})["targetId"]
sesja = wyslij("Target.attachToTarget", {"targetId": cel, "flatten": True})["sessionId"]
def js(kod, czekaj=True):
    w = wyslij("Runtime.evaluate", {"expression": kod, "awaitPromise": czekaj, "returnByValue": True}, sesja)
    if "exceptionDetails" in w: raise RuntimeError(w["exceptionDetails"])
    return w["result"].get("value")
def poczekaj(warunek, sek=15):
    for _ in range(int(sek * 10)):
        if js("!!(" + warunek + ")"): return True
        time.sleep(0.1)
    print("DOM:", js("JSON.stringify({w:document.getElementById('wynik').hidden,p:document.getElementById('podglad-tekstu').innerHTML.slice(0,300),t:document.getElementById('tekst').value.slice(0,20)})"))
    print("STATUS:", js("document.getElementById('status-ukryj').textContent"), "| KOMUNIKAT:", js("document.getElementById('komunikat-poprawek').textContent"))
    raise TimeoutError(warunek)
wyslij("Page.enable", sesja=sesja)
wyslij("Emulation.setDeviceMetricsOverride", {"width": 1000, "height": 1100, "deviceScaleFactor": 1, "mobile": False}, sesja)
wyslij("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"}, sesja)
poczekaj("document.readyState==='complete' && !!document.getElementById('form-ukryj')")
wyniki = []
def ok(nazwa, warunek):
    wyniki.append((nazwa, bool(warunek))); print(("OK   " if warunek else "FAIL ") + nazwa)

# 1. ukrycie zwykłego tekstu
js("""document.getElementById('tekst').value='Jan Nowak i Maria Lis spotkali Wronę. Lis poszedł. Listopad zimny. biuro@firma-example.pl';
document.getElementById('form-ukryj').requestSubmit(); 1""")
poczekaj("!document.getElementById('wynik').hidden && document.getElementById('podglad-tekstu').querySelector('button.zaslepka-przycisk')")
ok("plakietki są przyciskami", js("document.querySelectorAll('#podglad-tekstu button.zaslepka-przycisk').length>=3"))
ok("blok poprawek widoczny", js("!document.getElementById('blok-poprawek').hidden"))
# 2. zaznaczenie -> pływający przycisk -> Ukryj wszędzie
js("""(()=>{const p=document.getElementById('podglad-tekstu');
 const w=document.createTreeWalker(p,NodeFilter.SHOW_TEXT);let n;while(n=w.nextNode()){const i=n.data.indexOf('Wronę');if(i>=0){
 const r=document.createRange();r.setStart(n,i);r.setEnd(n,i+5);const s=getSelection();s.removeAllRanges();s.addRange(r);return 1}}return 0})()""")
poczekaj("!document.getElementById('ukryj-zaznaczone').hidden")
ok("pływający przycisk po zaznaczeniu", True)
js("document.getElementById('ukryj-zaznaczone').click(); 1")
poczekaj("document.getElementById('komunikat-poprawek').textContent.includes('Skopiuj go ponownie')")
ok("komunikat 'Tekst się zmienił. Skopiuj go ponownie.'", js("document.getElementById('komunikat-poprawek').textContent==='Tekst się zmienił. Skopiuj go ponownie.'"))
ok("Wronę ukryte (INNE)", js("!document.getElementById('podglad-tekstu').textContent.includes('Wron') && document.getElementById('podglad-tekstu').textContent.includes('INNE 1')"))
ok("lista Twoje poprawki ma pozycję", js("document.querySelectorAll('#lista-poprawek li').length===1"))
# 3. klik w plakietkę OSOBA_2 -> To nie dane
js("document.querySelector('#podglad-tekstu button[data-znacznik=\"OSOBA_2\"]').click(); 1")
ok("panel akcji z przyciskiem", js("!document.getElementById('akcja-znacznika').hidden && document.getElementById('akcja-znacznika-przycisk').textContent==='To nie dane osobowe'"))
js("document.getElementById('akcja-znacznika-przycisk').click(); 1")
poczekaj("!document.querySelector('#podglad-tekstu button[data-znacznik=\"OSOBA_2\"]')")
ok("OSOBA_2 zdjęta, OSOBA_1 zostaje", js("!!document.querySelector('#podglad-tekstu button[data-znacznik=\"OSOBA_1\"]') && document.getElementById('podglad-tekstu').textContent.includes('Maria Lis')"))
ok("INNE_1 nadal (numery stabilne)", js("!!document.querySelector('#podglad-tekstu button[data-znacznik=\"INNE_1\"]')"))
# 4. typ z sumą: brak 'To nie dane'
js("document.querySelector('#podglad-tekstu button[data-znacznik=\"EMAIL_1\"]').click(); 1")
ok("EMAIL można zdjąć", js("!document.getElementById('akcja-znacznika-przycisk').disabled"))
# 5. cofnięcie własnej poprawki
js("document.querySelector('#podglad-tekstu button[data-znacznik=\"INNE_1\"]').click(); 1")
ok("własna poprawka -> Cofnij", js("document.getElementById('akcja-znacznika-przycisk').textContent==='Cofnij tę poprawkę'"))
js("document.getElementById('akcja-znacznika-przycisk').click(); 1")
poczekaj("document.getElementById('podglad-tekstu').textContent.includes('Wron')")
ok("po cofnięciu Wronę znów widać", js("document.getElementById('podglad-tekstu').textContent.includes('Wron')"))
# 6. pole klawiaturowe
js("document.getElementById('pole-ukryj-wszedzie').value='Listopad'; document.getElementById('przycisk-ukryj-wszedzie').click(); 1")
poczekaj("!document.getElementById('podglad-tekstu').textContent.includes('Listopad')")
ok("pole 'Ukryj wszędzie' działa z klawiatury", True)
# 7. blokada z miejscami
js("""document.getElementById('tekst').value='Wczoraj Jan Nowak spał.';document.getElementById('form-ukryj').requestSubmit();1""")
poczekaj("!document.getElementById('blok-decyzji').hidden")
ok("blokada: lista decyzji", js("document.querySelectorAll('#lista-decyzji li').length===1"))
ok("blokada: Kopiuj nieaktywne, pobranie ukryte", js("document.getElementById('kopiuj').disabled && document.getElementById('blok-pobrania').hidden"))
ok("blokada: miejsce zaznaczone w podglądzie", js("document.querySelectorAll('#podglad-tekstu mark.watpliwe').length===1"))
js("document.querySelectorAll('#lista-decyzji li button')[1].click(); 1")
poczekaj("document.getElementById('blok-decyzji').hidden")
ok("po 'To nie dane' wynik gotowy, Kopiuj aktywne", js("!document.getElementById('kopiuj').disabled && !document.getElementById('blok-pobrania').hidden"))
ok("pobrania dostępne", js("!document.getElementById('blok-pobrania').hidden"))
# 8. wygaśnięcie -> 410
app.state.poprawki._wpisy.clear()
js("document.getElementById('pole-ukryj-wszedzie').value='spał'; document.getElementById('przycisk-ukryj-wszedzie').click(); 1")
poczekaj("document.getElementById('komunikat-poprawek').textContent.includes('ukryj dokument ponownie')")
ok("410 -> komunikat 'Ukryj dokument ponownie' widoczny", js("document.getElementById('komunikat-poprawek').offsetParent!==null") and js("document.getElementById('blok-poprawek').hidden"))
js("document.getElementById('naglowek-wyniku').scrollIntoView()")
szer = wyslij("Page.captureScreenshot", {"format": "png"}, sesja)["data"]
Path("/tmp/gui-popr.png").write_bytes(base64.b64decode(szer))
chrome.terminate()
print("\nRAZEM", sum(1 for _, v in wyniki if v), "/", len(wyniki))
sys.exit(0 if all(v for _, v in wyniki) else 1)
