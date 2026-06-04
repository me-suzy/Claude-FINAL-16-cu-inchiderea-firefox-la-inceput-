# -*- coding: utf-8 -*-
"""
Arcanum - METODA 2: printscreen real + deplasare controlata + lipire pe geometrie.

Gandire diferita fata de metoda 1 (care preia blob-ul sursa cu fetch). Aici
capturam PIXELII DE PE ECRAN, dar NU ne bazam pe scroll-ul viewer-ului (care e
virtual/clamp-uit). In schimb:
  1. luam <img> paginii (cea mai mare), o mutam in <body>;
  2. o fixam la rezolutie nativa (position:fixed, z-index maxim, NW x NH);
  3. o deplasam noi pe verticala (top:-offset) banda cu banda;
  4. la fiecare banda: screenshot la fereastra + decupam + lipim dupa geometrie
     (offset + devicePixelRatio). Control total, fara scroll fragil.

Login: copiaza profilul Firefox activ in temp (cookie-uri => logat); Firefox-ul
normal ramane deschis si neatins.

Rezultat: PNG + PDF in  d:\\TEST\\arcanum_capture\\arcanum_capture\\
"""

import os
import time
import glob
import shutil
import tempfile
from io import BytesIO

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image

URL = "https://adt.arcanum.com/ro/view/FilmeNoi_1971/?pg=67&layout=s"
OUT_DIR = r"d:\TEST\arcanum_capture\arcanum_capture"
OUT_NAME = "FilmeNoi_1971_pg67_metoda2"

SKIP_DIRS = {
    "cache2", "startupCache", "shader-cache", "OfflineCache", "thumbnails",
    "crashes", "datareporting", "saved-telemetry-pings", "minidumps",
    "security_state", "settings", "gmp", "gmp-gmpopenh264", "gmp-widevinecdm",
}


def find_active_profile():
    base = os.path.join(os.environ["APPDATA"], r"Mozilla\Firefox\Profiles")
    cands = glob.glob(os.path.join(base, "*.default-release")) \
        or glob.glob(os.path.join(base, "*.default")) \
        or [p for p in glob.glob(os.path.join(base, "*")) if os.path.isdir(p)]
    if not cands:
        raise RuntimeError("Nu am gasit niciun profil Firefox.")
    cands.sort(key=lambda p: os.path.getmtime(os.path.join(p, "cookies.sqlite"))
               if os.path.exists(os.path.join(p, "cookies.sqlite")) else 0, reverse=True)
    return cands[0]


def copy_profile(src):
    dst = tempfile.mkdtemp(prefix="ff_arc2_")
    for name in os.listdir(src):
        s = os.path.join(src, name)
        if os.path.isdir(s):
            if name in SKIP_DIRS:
                continue
            try:
                shutil.copytree(s, os.path.join(dst, name), dirs_exist_ok=True)
            except Exception:
                pass
        else:
            try:
                shutil.copy2(s, os.path.join(dst, name))
            except Exception:
                try:
                    with open(s, "rb") as fh:
                        data = fh.read()
                    with open(os.path.join(dst, name), "wb") as fh:
                        fh.write(data)
                except Exception:
                    pass
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
    drv.set_window_size(2000, 1300)
    return drv


# JS setup: alege imaginea cea mai mare, o muta in body si o fixeaza la rezolutie nativa
JS_SETUP = r"""
var imgs = Array.from(document.querySelectorAll('img.page-canvas, img[src^="blob:"]'))
             .filter(function(i){ return i.naturalWidth > 0; });
if(!imgs.length){ return {ok:false}; }
imgs.sort(function(a,b){ return b.naturalWidth*b.naturalHeight - a.naturalWidth*a.naturalHeight; });
var img = imgs[0];
if(img.naturalWidth < 600){ return {ok:false}; }
var NW = img.naturalWidth, NH = img.naturalHeight;
document.body.appendChild(img);          // scoatem din containerul viewer-ului
var s = img.style;
s.setProperty('position','fixed','important');
s.setProperty('left','0px','important');
s.setProperty('top','0px','important');
s.setProperty('margin','0','important');
s.setProperty('width',  NW+'px','important');
s.setProperty('height', NH+'px','important');
s.setProperty('max-width','none','important');
s.setProperty('max-height','none','important');
s.setProperty('transform','none','important');
s.setProperty('z-index','2147483647','important');
s.setProperty('background','#ffffff','important');
window.__capimg = img;
return {ok:true, NW:NW, NH:NH, dpr:window.devicePixelRatio||1,
        vh:window.innerHeight, vw:window.innerWidth};
"""

# JS pas: deplaseaza imaginea cu -offset si raporteaza geometria reala
JS_STEP = r"""
var img = window.__capimg; if(!img){ return {ok:false}; }
img.style.setProperty('top', (-arguments[0])+'px','important');
var r = img.getBoundingClientRect();
return {ok:true, dpr:window.devicePixelRatio||1, vh:window.innerHeight, vw:window.innerWidth,
        top:r.top, left:r.left, w:r.width, h:r.height};
"""


def grab(drv):
    return Image.open(BytesIO(drv.get_screenshot_as_png())).convert("RGB")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("1) Profil Firefox activ...")
    src = find_active_profile()
    print("2) Copiez profilul (Firefox-ul tau ramane deschis)...")
    tmp = copy_profile(src)

    drv = None
    try:
        print("3) Pornesc Firefox de automatizare...")
        drv = start_firefox(tmp)
        print(f"4) Navighez: {URL}")
        drv.get(URL)
        WebDriverWait(drv, 40).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        print("5) Astept imaginea paginii si o fixez la rezolutie nativa...")
        setup = {"ok": False}
        for _ in range(40):
            setup = drv.execute_script(JS_SETUP)
            if setup.get("ok"):
                break
            time.sleep(1)
        if not setup.get("ok"):
            print("!! Nu am gasit imaginea paginii.")
            drv.save_screenshot(os.path.join(OUT_DIR, OUT_NAME + "_control.png"))
            return

        NW, NH, dpr, vh = setup["NW"], setup["NH"], setup["dpr"], setup["vh"]
        finalW, finalH = round(NW * dpr), round(NH * dpr)
        final = Image.new("RGB", (finalW, finalH), (255, 255, 255))
        print(f"   nativ={NW}x{NH}  dpr={dpr}  vh={vh}  imagine finala={finalW}x{finalH}px")
        time.sleep(0.6)

        # benzi verticale: pas putin mai mic decat inaltimea ferestrei (mica suprapunere)
        band = max(100, int(vh) - 40)
        offsets = list(range(0, int(NH), band))
        print(f"6) Capturez {len(offsets)} benzi (band={band} CSS px)...")

        for i, off in enumerate(offsets):
            m = drv.execute_script(JS_STEP, off)
            time.sleep(0.30)
            shot = grab(drv)                      # px reali = CSS * dpr
            top = m["top"]                        # ~ -off
            # zona vizibila a imaginii in viewport (CSS px)
            sy0 = max(0.0, top)                   # de obicei 0
            sy1 = min(float(vh), top + m["h"])    # pana unde mai e imagine
            sx0 = max(0.0, m["left"])
            sx1 = min(float(m["vw"]), m["left"] + m["w"])
            if sy1 - sy0 < 1 or sx1 - sx0 < 1:
                continue
            crop = shot.crop((int(round(sx0*dpr)), int(round(sy0*dpr)),
                              int(round(sx1*dpr)), int(round(sy1*dpr))))
            # pozitia in imaginea finala = (y_sursa) * dpr ; y_sursa = sy - top
            px = int(round((sx0 - m["left"]) * dpr))
            py = int(round((sy0 - top) * dpr))
            if px + crop.width > finalW:
                crop = crop.crop((0, 0, finalW - px, crop.height))
            if py + crop.height > finalH:
                crop = crop.crop((0, 0, crop.width, finalH - py))
            if crop.width < 1 or crop.height < 1:
                continue
            final.paste(crop, (px, py))
            print(f"   banda {i+1}/{len(offsets)} off={off}  y[{py}..{py+crop.height}]  {crop.width}x{crop.height}")

        png_path = os.path.join(OUT_DIR, OUT_NAME + ".png")
        final.save(png_path)
        print(f"   PNG salvat: {png_path}  ({final.width}x{final.height}px)")

        print("7) Convertesc in PDF...")
        pdf_path = os.path.join(OUT_DIR, OUT_NAME + ".pdf")
        final.save(pdf_path, "PDF", resolution=200.0)
        print(f"   PDF salvat: {pdf_path}")
        print("\n GATA (metoda 2). Folder:", OUT_DIR)

    finally:
        if drv:
            try:
                drv.quit()
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
