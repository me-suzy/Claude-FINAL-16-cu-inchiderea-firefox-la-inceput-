# -*- coding: utf-8 -*-
"""
DOWNLOAD FULL - Metoda 1
========================
Bazat pe structura din "Claude-FINAL 15 ... Firefox.py", dar SINGURA diferenta
este METODA de preluare a datelor: NU se mai descarca PDF (are limita). In schimb,
pentru fiecare pagina se preia IMAGINEA SURSA din browser (METODA 1 = fetch la
blob-ul <img class="page-canvas">), apoi toate imaginile unui document se pun
intr-un PDF.

Stocare (ca scriptul mare - fara spatiu pe D:):
  - imaginile (staging/backup):  g:\\Temporare\\<Colectie>\\<Document>\\pageNNNN.jpg
  - PDF final per document:      G:\\<Colectie>\\<Document>.pdf
  - state de resume:             d:\\TEST\\arcanum_capture\\state.json

Resume: la repornire se sar colectiile/documentele deja terminate (din state.json)
si, in plus, paginile deja salvate pe disc -> un document intrerupt se reia de unde
a ramas.

Login: copiaza profilul Firefox activ in temp (cookie-uri => deja logat);
Firefox-ul tau normal ramane deschis si neatins.
"""

import os
import re
import sys
import json
import time
import glob
import base64
import shutil
import tempfile
from datetime import datetime, date

# consola Windows e cp1252 -> titlurile cu ș/ţ/etc ar crapa la print
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException
from PIL import Image

# ======================= CONFIG =======================
ADDITIONAL_COLLECTIONS = [
    "https://adt.arcanum.com/ro/collection/FilmeNoi/",
    "https://adt.arcanum.com/ro/collection/ITTrends/",
    "https://adt.arcanum.com/ro/collection/SzatmariMuzeumKiadvanyai_Evkonyv_ADT/",
    "https://adt.arcanum.com/ro/collection/Afirmarea/",
]

G_ROOT     = "G:\\"                                       # PDF-urile finale: G:\<Colectie>\<Document>.pdf
TEMP_ROOT  = r"g:\Temporare"                              # imaginile (staging): g:\Temporare\<Colectie>\<Document>\
STATE_PATH = r"d:\TEST\arcanum_capture\state.json"        # resume

PAGE_WAIT = 5      # secunde de asteptare intre pagini (cerinta)
PDF_WAIT  = 120    # 2 minute pauza dupa PDF-ul fiecarui document

# --- mod test (dezactivat: rulam complet pe toate colectiile) ---
TEST_MODE      = False  # False = rulare completa pe toate documentele/paginile
TEST_MAX_DOCS  = 1
TEST_MAX_PAGES = 3
if TEST_MODE:
    PDF_WAIT = 5
# ======================================================

SKIP_DIRS = {
    "cache2", "startupCache", "shader-cache", "OfflineCache", "thumbnails",
    "crashes", "datareporting", "saved-telemetry-pings", "minidumps",
    "security_state", "settings", "gmp", "gmp-gmpopenh264", "gmp-widevinecdm",
}
IMG_EXT = ("jpg", "png", "webp")


# ----------------------- state / resume -----------------------
# Format (ca scriptul mare):
# {
#   "date": "YYYY-MM-DD",
#   "count": <suma paginilor descarcate>,
#   "downloaded_issues": [
#       {"url","title","pages","completed_at","last_successful_segment_end","total_pages"}
#   ]
# }
def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as fh:
                s = json.load(fh)
            if isinstance(s, dict):
                s.setdefault("downloaded_issues", [])
                return s
        except Exception:
            pass
    return {"date": date.today().isoformat(), "count": 0, "downloaded_issues": []}


def save_state(state):
    state["date"] = date.today().isoformat()
    state["count"] = sum(int(it.get("pages", 0)) for it in state["downloaded_issues"])
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def issue_url_norm(view_url):
    return view_url.rstrip("/") + "/"


def get_issue(state, view_url):
    u = issue_url_norm(view_url)
    for it in state["downloaded_issues"]:
        if it.get("url") == u:
            return it
    return None


def issue_is_complete(entry):
    # complet = PDF-ul a fost facut cu succes (completed_at setat)
    return entry is not None and bool(entry.get("completed_at"))


def upsert_issue(state, view_url, title, pages, total_pages, last_idx, completed=False, pdf=None):
    u = issue_url_norm(view_url)
    entry = get_issue(state, view_url)
    if entry is None:
        entry = {}
        state["downloaded_issues"].append(entry)
    # ordine ca in exemplu + campul "pdf" (calea PDF-ului facut)
    entry.clear()
    entry["url"] = u
    entry["title"] = title
    entry["pages"] = pages
    entry["completed_at"] = datetime.now().isoformat(timespec="seconds") if completed else None
    entry["last_successful_segment_end"] = last_idx
    entry["total_pages"] = total_pages
    entry["pdf"] = pdf
    save_state(state)
    return entry


# ----------------------- login / profil -----------------------
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


# doar fisierele necesare pentru sesiunea logata (profilul complet poate avea sute de MB!)
ESSENTIAL_FILES = [
    "cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm",
    "key4.db", "logins.json", "cert9.db", "prefs.js", "permissions.sqlite",
    "webappsstore.sqlite", "webappsstore.sqlite-wal", "webappsstore.sqlite-shm",
    "handlers.json", "containers.json",
]


def copy_profile(src):
    dst = tempfile.mkdtemp(prefix="ff_dl1_")
    for name in ESSENTIAL_FILES:
        s = os.path.join(src, name)
        if not os.path.exists(s):
            continue
        d = os.path.join(dst, name)
        try:
            shutil.copy2(s, d)
        except Exception:
            try:
                with open(s, "rb") as fh:
                    data = fh.read()
                with open(d, "wb") as fh:
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
    drv.set_window_size(1500, 1200)
    drv.set_script_timeout(60)
    return drv


class Browser:
    """Manager Firefox cu auto-recuperare daca fereastra se inchide din greseala."""
    def __init__(self):
        self.drv = None
        self.tmp = None

    def start(self):
        self.tmp = copy_profile(find_active_profile())
        self.drv = start_firefox(self.tmp)

    def quit(self):
        try:
            if self.drv:
                self.drv.quit()
        except Exception:
            pass
        self.drv = None
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None

    def alive(self):
        try:
            _ = self.drv.current_url
            return True
        except Exception:
            return False

    def restart(self):
        print("   >>> repornesc Firefox (recuperare)...")
        self.quit()
        time.sleep(3)
        self.start()
        print("   >>> Firefox repornit, continui de unde am ramas.")


def retry_browser(br, fn, what, retries=6):
    """Ruleaza fn(); daca browserul a fost inchis/pierdut, repornește Firefox si reincearca."""
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except WebDriverException as e:
            msg = (str(e) or type(e).__name__).splitlines()[0]
            print(f"   !! eroare browser la {what} (incercare {attempt}/{retries}): {msg[:120]}")
            if attempt >= retries:
                raise
            if not br.alive():
                print("   ... fereastra inchisa/pierduta -> recuperare ...")
                for tryno in range(3):
                    try:
                        br.restart()
                        break
                    except Exception as e2:
                        print(f"   restart esuat ({e2}); reincerc in 5s...")
                        time.sleep(5)
            else:
                time.sleep(2)
    return None


# ----------------------- JS -----------------------
JS_PAGECOUNT = "return document.querySelectorAll('ul.thumbs li.thumb-item').length;"

JS_BIGIMG = r"""
var imgs = Array.from(document.querySelectorAll('img.page-canvas, img[src^="blob:"]'))
             .filter(function(i){ return i.naturalWidth > 0; });
if(!imgs.length){ return null; }
imgs.sort(function(a,b){ return b.naturalWidth*b.naturalHeight - a.naturalWidth*a.naturalHeight; });
var i = imgs[0];
return {nw:i.naturalWidth, nh:i.naturalHeight};
"""

JS_GRAB_BLOB = r"""
var cb = arguments[arguments.length-1];
var imgs = Array.from(document.querySelectorAll('img.page-canvas, img[src^="blob:"]'))
             .filter(function(i){ return i.naturalWidth > 0; });
if(!imgs.length){ cb({ok:false, err:'no img'}); return; }
imgs.sort(function(a,b){ return b.naturalWidth*b.naturalHeight - a.naturalWidth*a.naturalHeight; });
var img = imgs[0];
fetch(img.src).then(function(r){return r.blob();}).then(function(b){
  var fr = new FileReader();
  fr.onload = function(){ cb({ok:true, ct:b.type, nw:img.naturalWidth, nh:img.naturalHeight, data:fr.result}); };
  fr.onerror = function(){ cb({ok:false, err:'reader'}); };
  fr.readAsDataURL(b);
}).catch(function(e){ cb({ok:false, err:String(e)}); });
"""


def save_dataurl(data_url, path):
    # scriere atomica: .part -> rename, ca o oprire brusca sa nu lase imagine corupta
    b64 = data_url.split(",", 1)[1]
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(base64.b64decode(b64))
    os.replace(tmp, path)


# ----------------------- logica colectie -----------------------
def collection_name(coll_url):
    return coll_url.rstrip("/").split("/collection/")[-1].split("/")[0]


def doc_name(view_url):
    return view_url.split("/view/")[-1].strip("/").split("/")[0]


def extract_document_urls(drv):
    """Ca in scriptul mare: linkuri unice de /view/ din colectie (documentele/anii)."""
    try:
        WebDriverWait(drv, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/view/"]')))
    except Exception:
        pass
    time.sleep(2)
    anchors = drv.find_elements(By.CSS_SELECTOR, 'li.list-group-item a[href*="/view/"]')
    if not anchors:
        anchors = drv.find_elements(By.CSS_SELECTOR, 'a[href*="/view/"]')
    seen, unique = set(), []
    for a in anchors:
        href = a.get_attribute("href")
        if href and "/view/" in href:
            norm = href.split("?")[0].rstrip("/")
            if norm not in seen:
                seen.add(norm)
                unique.append(norm)
    return unique


def existing_page_file(stage_dir, pg):
    for ext in IMG_EXT:
        p = os.path.join(stage_dir, f"page{pg:04d}.{ext}")
        if os.path.exists(p) and os.path.getsize(p) > 1024:
            return p
    return None


def collect_page_files(stage_dir):
    files = []
    for ext in IMG_EXT:
        files += glob.glob(os.path.join(stage_dir, f"page*.{ext}"))
    files.sort(key=lambda p: os.path.basename(p))
    return files


def page_index(path):
    m = re.search(r"page(\d+)\.", os.path.basename(path))
    return int(m.group(1)) if m else -1


def get_issue_title(drv):
    """Titlul din breadcrumb activ (ex: 'Filme Noi, 1971 (nr. 1-10)1971 / nr. 1')."""
    for _ in range(20):
        try:
            t = drv.find_element(By.CSS_SELECTOR, "li.breadcrumb-item.active").text.strip()
            if t:
                return t
        except Exception:
            pass
        time.sleep(0.5)
    return ""


def wait_for_page_image(drv, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        info = drv.execute_script(JS_BIGIMG)
        if info and info["nw"] > 600:
            return (info["nw"], info["nh"])
        time.sleep(0.5)
    return None


def capture_document(br, view_url, stage_dir, state):
    name = doc_name(view_url)
    print(f"\n=== DOCUMENT: {name} ===")

    def _open():
        drv = br.drv
        drv.get(view_url + "/?pg=0&layout=s")
        WebDriverWait(drv, 40).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        title = get_issue_title(drv)
        total = 0
        for _ in range(40):
            total = drv.execute_script(JS_PAGECOUNT) or 0
            if total > 0:
                break
            time.sleep(1)
        return title, total

    title, total = retry_browser(br, _open, f"deschidere {name}")
    if not total:
        print("   !! Nu am putut afla numarul de pagini, sar peste document.")
        return None
    print(f"   titlu: {title}")
    print(f"   pagini in document (total_pages): {total}")
    total_pages = total

    if TEST_MODE:
        total = min(total, TEST_MAX_PAGES)
        print(f"   [TEST] capturez doar primele {total} pagini")

    os.makedirs(stage_dir, exist_ok=True)
    pages_done = 0
    last_idx = -1
    for pg in range(total):
        # RESUME: pagina deja salvata -> sarim (dar o numaram)
        ex = existing_page_file(stage_dir, pg)
        if ex:
            print(f"   pg {pg:04d}: deja exista ({os.path.basename(ex)}), sar")
            pages_done += 1
            last_idx = pg
            upsert_issue(state, view_url, title, pages_done, total_pages, last_idx)
            continue

        def _capture():
            drv = br.drv
            drv.get(f"{view_url}/?pg={pg}&layout=s")
            time.sleep(PAGE_WAIT)
            wait_for_page_image(drv, timeout=30)
            return drv.execute_async_script(JS_GRAB_BLOB)

        res = None
        for attempt in range(3):
            res = retry_browser(br, _capture, f"pagina {pg} din {name}")
            if res and res.get("ok"):
                break
            print(f"   pg {pg:04d}: fetch nereusit (incercare {attempt + 1}/3), reincerc...")
            time.sleep(2)
        if not res or not res.get("ok"):
            print(f"   pg {pg:04d}: ESEC final ({res.get('err') if res else 'None'}) - "
                  f"se reia la urmatoarea rulare")
            continue
        ct = res.get("ct", "")
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(ct, "jpg")
        img_path = os.path.join(stage_dir, f"page{pg:04d}.{ext}")
        save_dataurl(res["data"], img_path)
        pages_done += 1
        last_idx = pg
        print(f"   pg {pg:04d}: OK  {res.get('nw')}x{res.get('nh')}  -> {os.path.basename(img_path)}")
        # SALVAM PROGRESUL DUPA FIECARE PAGINA (resume exact de unde s-a oprit)
        upsert_issue(state, view_url, title, pages_done, total_pages, last_idx)

    complete = pages_done >= total_pages
    return {"title": title, "total_pages": total_pages,
            "pages_done": pages_done, "complete": complete}


def open_image_robust(p, retries=4):
    """Deschide o imagine cu reincercari (trece peste blip-uri de I/O pe G:)."""
    for attempt in range(retries):
        try:
            im = Image.open(p)
            im.load()                 # forteaza citirea completa (prinde I/O tranzitoriu)
            return im.convert("RGB")
        except Exception as e:
            if attempt == retries - 1:
                print(f"   !! pagina ilizibila dupa {retries} incercari: {os.path.basename(p)} ({e})")
            time.sleep(1.0)
    return None


def build_pdf(image_paths, pdf_path, total_pages):
    # nu facem PDF daca lipsesc pagini
    if total_pages and len(image_paths) < total_pages:
        print(f"   (PDF amanat: doar {len(image_paths)}/{total_pages} pagini pe disc)")
        return False
    if not image_paths:
        print("   (fara imagini, nu fac PDF)")
        return False
    imgs = []
    for p in image_paths:
        im = open_image_robust(p)
        if im is None:
            print("   !! NU fac PDF (o pagina e ilizibila) - se reincearca la urmatoarea rulare")
            return False
        imgs.append(im)
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    tmp = pdf_path + ".part"
    imgs[0].save(tmp, "PDF", resolution=200.0, save_all=True, append_images=imgs[1:])
    os.replace(tmp, pdf_path)
    print(f"   PDF salvat: {pdf_path}  ({len(imgs)} pagini)")
    return True


def main():
    print("Login: copiez profilul Firefox activ (Firefox-ul tau ramane deschis)...")
    state = load_state()
    br = Browser()
    try:
        br.start()

        for coll_url in ADDITIONAL_COLLECTIONS:
            cname = collection_name(coll_url)
            print(f"\n########## COLECTIE: {cname}  ({coll_url}) ##########")

            def _load_collection():
                drv = br.drv
                drv.get(coll_url)
                WebDriverWait(drv, 40).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(2)
                return extract_document_urls(drv)

            docs = retry_browser(br, _load_collection, f"enumerare {cname}") or []
            print(f"  documente (sub-colectii) gasite: {len(docs)}")
            for d in docs[:8]:
                print("    -", d)
            if not docs:
                print("  !! niciun document gasit, trec la urmatoarea colectie.")
                continue

            if TEST_MODE:
                docs = docs[:TEST_MAX_DOCS]
                print(f"  [TEST] procesez doar primele {len(docs)} document(e)")

            for view_url in docs:
                name = doc_name(view_url)
                pdf_path = os.path.join(G_ROOT, cname, name + ".pdf")
                entry = get_issue(state, view_url)

                # COMPLET = marcat in state.json SI PDF-ul chiar exista pe disc
                if issue_is_complete(entry) and os.path.exists(pdf_path):
                    print(f"\n=== DOCUMENT {name}: deja complet + PDF exista, sar ===")
                    continue
                if issue_is_complete(entry) and not os.path.exists(pdf_path):
                    print(f"\n=== DOCUMENT {name}: marcat complet DAR PDF lipseste -> il refac ===")

                stage_dir = os.path.join(TEMP_ROOT, cname, name)
                info = capture_document(br, view_url, stage_dir, state)
                if info is None:
                    continue

                if info["complete"]:
                    # toate paginile sunt pe disc -> incercam PDF-ul
                    files = collect_page_files(stage_dir)
                    if build_pdf(files, pdf_path, info["total_pages"]):
                        # marcam COMPLET doar daca PDF-ul s-a facut cu succes
                        upsert_issue(state, view_url, info["title"], info["pages_done"],
                                     info["total_pages"], info["total_pages"] - 1,
                                     completed=True, pdf=pdf_path)
                        print(f"   [state] COMPLET {info['pages_done']}/{info['total_pages']}  PDF OK")
                        print(f"   ... pauza {PDF_WAIT}s (PDF) ...")
                        time.sleep(PDF_WAIT)
                    else:
                        print("   !! PDF nereusit acum - documentul ramane neterminat "
                              "(se reia la urmatoarea rulare)")
                else:
                    print(f"   document INCOMPLET ({info['pages_done']}/{info['total_pages']}) "
                          f"- PDF-ul se va face cand documentul e gata")

        print("\nGATA.")
    except KeyboardInterrupt:
        print("\n[oprit manual] progresul e salvat in state.json - reia de aici la repornire.")
    except WebDriverException as e:
        print(f"\n[oprit] browserul nu s-a putut recupera: {str(e).splitlines()[0][:120]}")
        print("Progresul e salvat in state.json - reporneste scriptul ca sa reia de aici.")
    finally:
        br.quit()


if __name__ == "__main__":
    main()
