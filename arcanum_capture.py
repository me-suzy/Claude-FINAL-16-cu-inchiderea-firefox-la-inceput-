# -*- coding: utf-8 -*-
"""
Arcanum - captura pagina la rezolutie maxima din <canvas> (metoda PDF.js / toDataURL).
NU inchide Firefox-ul care ruleaza: copiaza profilul activ intr-un folder temp
(cookie-urile se mostenesc => deja logat) si porneste un Firefox de automatizare separat.

Rezultat: PNG + PDF in .\arcanum_capture\
"""

import os
import sys
import time
import glob
import json
import base64
import shutil
import tempfile

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://adt.arcanum.com/ro/view/FilmeNoi_1971/?pg=67&layout=s"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arcanum_capture")
OUT_NAME = "FilmeNoi_1971_pg67"

# foldere/fisiere mari sau blocate pe care le sarim cand copiem profilul
SKIP_DIRS = {
    "cache2", "startupCache", "shader-cache", "OfflineCache", "thumbnails",
    "crashes", "datareporting", "saved-telemetry-pings", "minidumps",
    "security_state", "settings", "gmp", "gmp-gmpopenh264", "gmp-widevinecdm",
}


def find_active_profile():
    base = os.path.join(os.environ["APPDATA"], r"Mozilla\Firefox\Profiles")
    cands = glob.glob(os.path.join(base, "*.default-release"))
    if not cands:
        cands = glob.glob(os.path.join(base, "*.default"))
    if not cands:
        cands = [p for p in glob.glob(os.path.join(base, "*")) if os.path.isdir(p)]
    if not cands:
        raise RuntimeError("Nu am gasit niciun profil Firefox.")
    # alege cel mai recent folosit (dupa mtime la cookies.sqlite)
    def score(p):
        c = os.path.join(p, "cookies.sqlite")
        return os.path.getmtime(c) if os.path.exists(c) else 0
    cands.sort(key=score, reverse=True)
    return cands[0]


def copy_profile(src):
    dst = tempfile.mkdtemp(prefix="ff_arc_")
    copied, skipped = 0, 0
    for name in os.listdir(src):
        s = os.path.join(src, name)
        if os.path.isdir(s):
            if name in SKIP_DIRS:
                continue
            try:
                shutil.copytree(s, os.path.join(dst, name), dirs_exist_ok=True)
                copied += 1
            except Exception:
                skipped += 1
        else:
            try:
                shutil.copy2(s, os.path.join(dst, name))
                copied += 1
            except Exception:
                # fisier blocat de Firefox (ex. sqlite) -> incearca citire bruta
                try:
                    with open(s, "rb") as fh:
                        data = fh.read()
                    with open(os.path.join(dst, name), "wb") as fh:
                        fh.write(data)
                    copied += 1
                except Exception:
                    skipped += 1
    print(f"   profil copiat: {copied} intrari, {skipped} sarite -> {dst}")
    return dst


def start_firefox(profile_dir):
    opts = FirefoxOptions()
    opts.add_argument("--no-remote")
    opts.add_argument("-profile")
    opts.add_argument(profile_dir)
    opts.set_preference("pdfjs.disabled", False)
    opts.set_preference("browser.tabs.remote.autostart", False)
    opts.set_preference("general.useragent.override",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0")
    drv = webdriver.Firefox(options=opts, service=FirefoxService())
    drv.set_window_size(1500, 1200)
    return drv


# JS: gaseste imaginea paginii (blob) si raporteaza rezolutia reala
JS_DIAG = r"""
var imgs = Array.from(document.querySelectorAll('img.page-canvas, img[src^="blob:"]'));
return imgs.map(function(i){
  return {nw:i.naturalWidth, nh:i.naturalHeight, src:(i.src||'').slice(0,40)};
});
"""

# JS async: preia blob-ul paginii (fetch same-origin) ca dataURL la rezolutie reala
JS_GRAB_BLOB = r"""
var cb = arguments[arguments.length-1];
var img = document.querySelector('img.page-canvas[src^="blob:"]')
       || document.querySelector('img[src^="blob:"]');
if(!img){ cb({ok:false, err:'no blob img'}); return; }
fetch(img.src).then(function(r){return r.blob();}).then(function(b){
  var fr = new FileReader();
  fr.onload = function(){
    cb({ok:true, ct:b.type, nw:img.naturalWidth, nh:img.naturalHeight, data:fr.result});
  };
  fr.onerror = function(){ cb({ok:false, err:'reader error'}); };
  fr.readAsDataURL(b);
}).catch(function(e){ cb({ok:false, err:String(e)}); });
"""


def save_dataurl_png(data_url, path):
    b64 = data_url.split(",", 1)[1]
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(b64))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("1) Caut profilul Firefox activ...")
    src = find_active_profile()
    print(f"   profil: {src}")

    print("2) Copiez profilul (Firefox-ul tau ramane deschis)...")
    tmp = copy_profile(src)

    drv = None
    try:
        print("3) Pornesc Firefox de automatizare...")
        drv = start_firefox(tmp)

        print(f"4) Navighez: {URL}")
        drv.get(URL)
        WebDriverWait(drv, 40).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        print("5) Astept randarea imaginii paginii (blob)...")
        ok = False
        for _ in range(40):
            diag = drv.execute_script(JS_DIAG)
            big = [d for d in diag if d["nw"] > 300 and d["nh"] > 300]
            if big:
                ok = True
                break
            time.sleep(1)

        diag = drv.execute_script(JS_DIAG)
        print(f"   imagini blob gasite ({len(diag)}):")
        for d in diag:
            print("     ", d)

        if not ok:
            print("!! Nu am gasit imaginea paginii. Salvez screenshot de control si DOM-ul.")
            drv.save_screenshot(os.path.join(OUT_DIR, OUT_NAME + "_control.png"))
            with open(os.path.join(OUT_DIR, "page_source.html"), "w", encoding="utf-8") as fh:
                fh.write(drv.page_source)
            return

        print("6) Preiau blob-ul paginii (rezolutie reala)...")
        drv.set_script_timeout(60)
        res = drv.execute_async_script(JS_GRAB_BLOB)
        if not res.get("ok"):
            print(f"!! fetch blob a esuat: {res.get('err')}")
            drv.save_screenshot(os.path.join(OUT_DIR, OUT_NAME + "_control.png"))
            return

        ct = res.get("ct", "")
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(ct, "bin")
        img_path = os.path.join(OUT_DIR, OUT_NAME + "." + ext)
        save_dataurl_png(res["data"], img_path)
        print(f"   imagine salvata: {img_path}")
        print(f"   tip: {ct} | rezolutie reala: {res.get('nw')}x{res.get('nh')} px")

        print("7) Convertesc in PDF...")
        from PIL import Image
        img = Image.open(img_path).convert("RGB")
        pdf_path = os.path.join(OUT_DIR, OUT_NAME + ".pdf")
        img.save(pdf_path, "PDF", resolution=200.0)
        print(f"   PDF salvat: {pdf_path}  ({img.width}x{img.height} px)")

        print("\n GATA. Verifica calitatea in:", OUT_DIR)

    finally:
        if drv:
            try:
                drv.quit()
            except Exception:
                pass
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
