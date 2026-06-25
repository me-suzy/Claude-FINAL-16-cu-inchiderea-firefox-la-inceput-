# -*- coding: utf-8 -*-
"""
magazin-ist-rendered.py
=======================

Recaptureaza numerele Magazin Istoric noi, unde textul nu este in JPG-ul
substrat, ci intr-un layer randat separat de FlippingBook in browser.

Interval implicit:
  200912 (decembrie 2009) -> ultimul numar gasit in arhiva.

Metoda:
  - foloseste enumerarea/cookie-urile din magazin-ist.py;
  - deschide revista in Firefox prin Selenium;
  - asteapta randarea paginii (5s la deschiderea numarului, 3s intre pagini);
  - face screenshot pe .page-content, adica pagina randata cu poze + text;
  - construieste PDF-ul final din capturile PNG;
  - suprascrie PDF-ul vechi numai dupa ce PDF-ul nou a fost creat complet.

State separat:
  D:\\TEST\\Magazin Istoric\\state-rendered.json

Staging separat:
  G:\\Magazin Istoric\\Temporare_Rendered\\<cod>\\pageNNNN.png
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from PIL import Image

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait


SCRIPT_DIR = Path(__file__).resolve().parent
BASE_SCRIPT = SCRIPT_DIR / "magazin-ist.py"
OUTPUT_ROOT = Path(r"G:\Magazin Istoric")
TEMP_ROOT = OUTPUT_ROOT / "Temporare_Rendered"
STATE_PATH = SCRIPT_DIR / "state-rendered.json"
LOG_DIR = SCRIPT_DIR / "Logs"
APP_ID = "magazin-istoric-rendered"

DEFAULT_START_CODE = "200912"
DEFAULT_FIRST_WAIT = 5.0
DEFAULT_PAGE_WAIT = 3.0
DEFAULT_BROWSER_START_RETRIES = 3
DEFAULT_BROWSER_RESTART_WAIT = 5.0
DEFAULT_WIDTH = 1800
DEFAULT_HEIGHT = 1200
MIN_PAGE_WIDTH = 300
MIN_PAGE_HEIGHT = 400
MIN_PNG_BYTES = 2_048

USER_ENV = "MAGAZIN_ISTORIC_USERNAME"
PASS_ENV = "MAGAZIN_ISTORIC_PASSWORD"
DEFAULT_USERNAME = "ioan.fantanaru"
DEFAULT_PASSWORD = "fant8472+"

RUN_LOG_FILE = None


class Tee:
    def __init__(self, *streams):
        self.streams = streams
        self.encoding = getattr(streams[0], "encoding", "utf-8")
        self.errors = getattr(streams[0], "errors", "replace")

    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
                stream.flush()
            except Exception:
                pass

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


def setup_console_and_logging() -> None:
    global RUN_LOG_FILE
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"magazin-ist-rendered_{datetime.now():%Y%m%d_%H%M%S}.log"
        RUN_LOG_FILE = open(path, "a", encoding="utf-8", buffering=1)
        sys.stdout = Tee(sys.stdout, RUN_LOG_FILE)
        sys.stderr = Tee(sys.stderr, RUN_LOG_FILE)
        print(f"Log rulare rendered: {path}")
    except Exception as e:
        print(f"(nu pot activa logul: {e})")


def load_base_module():
    spec = importlib.util.spec_from_file_location("magazin_ist_base", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nu pot incarca {BASE_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def new_state() -> Dict:
    return {
        "version": 1,
        "app": APP_ID,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "downloaded_issues": [],
    }


def load_state() -> Dict:
    if not STATE_PATH.exists():
        return new_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("app") not in (None, APP_ID):
            backup = STATE_PATH.with_suffix(f".foreign_{datetime.now():%Y%m%d_%H%M%S}.json")
            backup.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[state] state strain pentru rendered; backup: {backup}")
            return new_state()
        data.setdefault("version", 1)
        data.setdefault("app", APP_ID)
        data.setdefault("downloaded_issues", [])
        return data
    except Exception as e:
        print(f"[state] nu pot citi state-rendered.json ({e}); pornesc state nou.")
        return new_state()


def save_state(state: Dict) -> None:
    state["app"] = APP_ID
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def get_entry(state: Dict, code: str) -> Optional[Dict]:
    for item in state.setdefault("downloaded_issues", []):
        if item.get("code") == code:
            return item
    return None


def upsert_entry(
    state: Dict,
    issue: Dict,
    title: str,
    total_pages: int,
    stage_dir: Path,
    pages_done: int,
    last_page: int,
    completed: bool = False,
    pdf_path: Optional[Path] = None,
) -> Dict:
    entry = get_entry(state, issue["code"])
    if entry is None:
        entry = {"code": issue["code"]}
        state.setdefault("downloaded_issues", []).append(entry)
    entry.update(
        {
            "code": issue["code"],
            "year": issue.get("year"),
            "month": issue.get("month"),
            "title": title,
            "url": issue_reader_base(issue),
            "issue_url": issue.get("issue_url"),
            "total_pages": int(total_pages),
            "pages": int(pages_done),
            "last_successful_page": int(last_page),
            "stage_dir": str(stage_dir),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    if completed:
        entry["completed_at"] = datetime.now().isoformat(timespec="seconds")
    if pdf_path:
        entry["pdf"] = str(pdf_path)
    state["downloaded_issues"].sort(key=lambda x: x.get("code", ""))
    save_state(state)
    return entry


def issue_is_complete(entry: Optional[Dict], pdf_path: Path) -> bool:
    return bool(
        entry
        and entry.get("completed_at")
        and entry.get("pdf")
        and pdf_path.exists()
        and pdf_path.stat().st_size > 1024
    )


def issue_reader_base(issue: Dict) -> str:
    return f"https://magazinistoric.ro/revista/{issue['year']}/{issue['code']}/"


def stage_dir_for(issue: Dict) -> Path:
    return TEMP_ROOT / issue["code"]


def pdf_path_for(mi, issue: Dict) -> Path:
    # Pastram exact naming-ul scriptului vechi, ca sa suprascriem fara duplicate.
    return mi.pdf_path_for_issue(issue)


def page_path(stage_dir: Path, page_no: int) -> Path:
    return stage_dir / f"page{page_no:04d}.png"


def collect_pages(stage_dir: Path) -> List[Path]:
    files = sorted(stage_dir.glob("page*.png"))
    return [p for p in files if p.stat().st_size > 1024]


def existing_pages(stage_dir: Path) -> Set[int]:
    out: Set[int] = set()
    for p in collect_pages(stage_dir):
        m = re.search(r"page(\d+)\.png$", p.name)
        if m:
            out.add(int(m.group(1)))
    return out


def parse_page_list(value: str) -> Optional[Set[int]]:
    if not value.strip():
        return None
    pages: Set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a), int(b) + 1))
        else:
            pages.add(int(part))
    return pages


def firefox_binary() -> str:
    candidates = [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Mozilla Firefox\firefox.exe"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    raise RuntimeError("Nu gasesc firefox.exe.")


def gecko_service() -> FirefoxService:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    gecko_log = LOG_DIR / f"geckodriver-rendered_{datetime.now():%Y%m%d_%H%M%S_%f}.log"
    kwargs = {"log_output": str(gecko_log)}
    print(f"[browser] geckodriver log: {gecko_log}")
    candidates = [
        r"C:\WINDOWS\geckodriver.exe",
        str(SCRIPT_DIR / "geckodriver.exe"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return FirefoxService(p, **kwargs)
    return FirefoxService(**kwargs)


def driver_service_pid(drv_or_service) -> Optional[int]:
    service = getattr(drv_or_service, "service", drv_or_service)
    process = getattr(service, "process", None)
    pid = getattr(process, "pid", None)
    return int(pid) if pid else None


def kill_process_tree(pid: Optional[int]) -> None:
    if not pid:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
    except Exception as e:
        print(f"[browser] nu pot opri fortat procesul {pid}: {type(e).__name__}: {str(e)[:160]}")


def cleanup_orphaned_selenium_firefox() -> None:
    if os.name != "nt":
        return
    script = (
        "Get-CimInstance Win32_Process -Filter \"name='firefox.exe'\" | "
        "Where-Object { $_.CommandLine -like '*--marionette*' -and "
        "$_.CommandLine -like '*rust_mozprofile*' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception as e:
        print(f"[browser] nu pot verifica procese Selenium orfane: {type(e).__name__}: {str(e)[:160]}")
        return
    pids = sorted({int(x) for x in re.findall(r"\d+", result.stdout or "")})
    for pid in pids:
        kill_process_tree(pid)
    if pids:
        print(f"[browser] procese Firefox Selenium orfane oprite: {', '.join(str(pid) for pid in pids)}")


def start_browser_once(args: argparse.Namespace) -> webdriver.Firefox:
    opts = FirefoxOptions()
    opts.binary_location = firefox_binary()
    if args.headless:
        opts.add_argument("--headless")
    opts.set_preference("layout.css.devPixelsPerPx", "1.0")
    opts.set_preference("permissions.default.image", 1)
    opts.set_preference("dom.webnotifications.enabled", False)
    opts.set_preference("media.volume_scale", "0.0")
    opts.set_preference("browser.shell.checkDefaultBrowser", False)
    opts.set_preference("browser.tabs.warnOnClose", False)
    opts.set_preference("toolkit.telemetry.reportingpolicy.firstRun", False)

    service = gecko_service()
    try:
        drv = webdriver.Firefox(options=opts, service=service)
    except Exception:
        kill_process_tree(driver_service_pid(service))
        cleanup_orphaned_selenium_firefox()
        raise
    drv.set_window_size(args.window_width, args.window_height)
    drv.set_page_load_timeout(180)
    drv.set_script_timeout(90)
    print(f"[browser] Firefox pornit (geckodriver pid {driver_service_pid(drv) or '?'})")
    return drv


def start_browser(args: argparse.Namespace) -> webdriver.Firefox:
    attempts = max(1, int(args.browser_start_retries))
    last_error: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return start_browser_once(args)
        except Exception as e:
            last_error = e
            print(f"[browser] pornire Firefox esuata ({attempt}/{attempts}): {type(e).__name__}: {str(e)[:220]}")
            if attempt < attempts:
                time.sleep(max(0.0, float(args.browser_restart_wait)))
    assert last_error is not None
    raise last_error


def load_driver_cookies(drv: webdriver.Firefox, cookie_path: Path) -> None:
    if not cookie_path.exists():
        return
    drv.get("https://magazinistoric.ro/")
    time.sleep(1)
    data = json.loads(cookie_path.read_text(encoding="utf-8"))
    added = 0
    for c in data:
        try:
            ck = {
                "name": c["name"],
                "value": c["value"],
                "path": c.get("path") or "/",
            }
            if c.get("domain"):
                ck["domain"] = c["domain"]
            drv.add_cookie(ck)
            added += 1
        except Exception:
            pass
    print(f"[browser] cookies incarcate in Firefox: {added}")


def save_driver_cookies(drv: webdriver.Firefox, cookie_path: Path) -> None:
    try:
        data = []
        for c in drv.get_cookies():
            data.append(
                {
                    "name": c.get("name"),
                    "value": c.get("value"),
                    "domain": c.get("domain"),
                    "path": c.get("path") or "/",
                    "expires": c.get("expiry"),
                }
            )
        cookie_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[browser] cookies salvate din Firefox: {cookie_path}")
    except Exception as e:
        print(f"[browser] nu pot salva cookies: {e}")


def close_browser(
    drv: Optional[webdriver.Firefox],
    cookie_path: Optional[Path] = None,
    save_cookies: bool = True,
    force: bool = False,
) -> None:
    if drv is None:
        return
    pid = driver_service_pid(drv)
    if save_cookies and cookie_path is not None:
        try:
            save_driver_cookies(drv, cookie_path)
        except Exception as e:
            print(f"[browser] nu pot salva cookies la inchidere: {type(e).__name__}: {str(e)[:180]}")

    if force and pid:
        print(f"[browser] opresc fortat Firefox/geckodriver blocat (pid {pid})...")
        kill_process_tree(pid)
        return

    try:
        drv.quit()
    except Exception as e:
        print(f"[browser] quit esuat; opresc fortat procesul: {type(e).__name__}: {str(e)[:180]}")
        kill_process_tree(pid)


DRIVER_DEAD_EXCEPTION_NAMES = {
    "ConnectionRefusedError",
    "MaxRetryError",
    "NewConnectionError",
    "ProtocolError",
    "ReadTimeout",
    "ReadTimeoutError",
    "RemoteDisconnected",
    "TimeoutError",
}

DRIVER_DEAD_TEXT_MARKERS = (
    "actively refused",
    "connection refused",
    "disconnected",
    "failed to decode response",
    "failed to establish a new connection",
    "invalid session id",
    "marionette",
    "max retries exceeded",
    "no connection could be made",
    "process unexpectedly closed",
    "read timed out",
    "target closed",
)


def exception_chain(exc: BaseException) -> Iterable[BaseException]:
    seen: Set[int] = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ or cur.__context__


def driver_needs_restart(exc: BaseException) -> bool:
    for cur in exception_chain(exc):
        name = type(cur).__name__
        text = str(cur).lower()
        if name in DRIVER_DEAD_EXCEPTION_NAMES:
            return True
        if isinstance(cur, WebDriverException) and (
            not text or any(marker in text for marker in DRIVER_DEAD_TEXT_MARKERS)
        ):
            return True
        if any(marker in text for marker in DRIVER_DEAD_TEXT_MARKERS):
            return True
    return False


def pager_inputs(drv: webdriver.Firefox):
    return drv.find_elements(By.ID, "pager-val") or drv.find_elements(By.CSS_SELECTOR, ".pager input[type='text']")


def first_pager_input(drv: webdriver.Firefox):
    inputs = pager_inputs(drv)
    return inputs[0] if inputs else False


def viewer_is_ready(drv: webdriver.Firefox) -> bool:
    return bool(pager_inputs(drv) and (drv.find_elements(By.CSS_SELECTOR, ".page-wrapper[page]") or drv.find_elements(By.CSS_SELECTOR, "#book .page[data-page-id]")))


def browser_login(drv: webdriver.Firefox, args: argparse.Namespace, return_url: str, cookie_path: Path) -> None:
    username = args.username or os.environ.get(USER_ENV) or DEFAULT_USERNAME
    password = args.password or os.environ.get(PASS_ENV) or DEFAULT_PASSWORD
    print("[browser] login automat WordPress...")
    drv.get("https://magazinistoric.ro/")
    wait = WebDriverWait(drv, 20)
    try:
        user = wait.until(lambda d: d.find_element(By.ID, "user_login"))
    except TimeoutException:
        print("[browser] formularul de login nu apare; sesiunea pare deja activa.")
        drv.get(return_url)
        return
    pwd = wait.until(lambda d: d.find_element(By.ID, "user_pass"))
    user.clear()
    user.send_keys(username)
    pwd.clear()
    pwd.send_keys(password)
    drv.find_element(By.ID, "wp-submit").click()
    time.sleep(4)
    save_driver_cookies(drv, cookie_path)
    drv.get(return_url)


def ensure_viewer_loaded(drv: webdriver.Firefox, issue: Dict, args: argparse.Namespace, cookie_path: Path) -> None:
    url = issue_reader_base(issue)
    drv.get(url)
    try:
        WebDriverWait(drv, 20).until(
            lambda d: viewer_is_ready(d)
            or "abonamente" in (d.current_url or "").lower()
            or d.find_elements(By.ID, "user_login")
        )
    except TimeoutException:
        pass
    if "abonamente" in (drv.current_url or "").lower() or not viewer_is_ready(drv):
        browser_login(drv, args, url, cookie_path)
    WebDriverWait(drv, 60).until(viewer_is_ready)
    time.sleep(args.first_wait)
    print(f"  viewer deschis: {drv.title} ({drv.current_url})")


def go_to_page(drv: webdriver.Firefox, page_no: int, wait_seconds: float) -> None:
    inp = WebDriverWait(drv, 30).until(first_pager_input)
    inp.click()
    inp.send_keys(Keys.CONTROL, "a")
    inp.send_keys(str(page_no))
    inp.send_keys(Keys.ENTER)
    time.sleep(wait_seconds)


def visible_page_numbers(drv: webdriver.Firefox, total_pages: int) -> List[int]:
    nums = drv.execute_script(
        """
        const out = [];
        const vw = window.innerWidth || document.documentElement.clientWidth;
        const vh = window.innerHeight || document.documentElement.clientHeight;
        const nodes = [
          ...document.querySelectorAll('.page-wrapper[page]'),
          ...document.querySelectorAll('#book .page[data-page-id]')
        ];
        for (const el of nodes) {
          const r = el.getBoundingClientRect();
          const cs = window.getComputedStyle(el);
          const n = parseInt(el.getAttribute('page') || el.getAttribute('data-page-id'), 10);
          const visibleW = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
          const visibleH = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
          if (n && n >= 1 && n <= arguments[0] && cs.display !== 'none' &&
              el.getAttribute('aria-hidden') !== 'true' &&
              cs.visibility !== 'hidden' && r.width > 50 && r.height > 50 &&
              visibleW * visibleH > 5000) {
            out.push(n);
          }
        }
        return Array.from(new Set(out)).sort((a,b)=>a-b);
        """,
        total_pages,
    )
    return [int(n) for n in nums]


def best_visible_page_wrapper(drv: webdriver.Firefox, page_no: int):
    selectors = [
        f'.page-wrapper[page="{page_no}"]',
        f'#book .page[data-page-id="{page_no}"]:not([aria-hidden="true"])',
    ]
    candidates = []
    elements = []
    for selector in selectors:
        elements.extend(drv.find_elements(By.CSS_SELECTOR, selector))
    for el in elements:
        try:
            if not el.is_displayed():
                continue
            info = drv.execute_script(
                """
                const el = arguments[0];
                const r = el.getBoundingClientRect();
                const vw = window.innerWidth || document.documentElement.clientWidth;
                const vh = window.innerHeight || document.documentElement.clientHeight;
                const visibleW = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
                const visibleH = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
                return {
                  width: r.width,
                  height: r.height,
                  area: r.width * r.height,
                  visibleArea: visibleW * visibleH
                };
                """,
                el,
            )
            if (
                info
                and float(info.get("width", 0)) > 50
                and float(info.get("height", 0)) > 50
                and float(info.get("visibleArea", 0)) > 5000
            ):
                candidates.append((float(info.get("visibleArea", 0)), float(info.get("area", 0)), el))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[-1][2]


def wait_for_page_ready(drv: webdriver.Firefox, page_no: int, timeout: int = 30):
    end = time.time() + timeout
    last_el = None
    while time.time() < end:
        last_el = best_visible_page_wrapper(drv, page_no)
        if last_el is not None:
            ok = drv.execute_script(
                """
                const wrap = arguments[0];
                const pre = wrap.querySelector('.preloader');
                const preVisible = pre && getComputedStyle(pre).display !== 'none';
                const r = wrap.getBoundingClientRect();
                const pendingImg = Array.from(wrap.querySelectorAll('img')).some(img =>
                  img.src && (!img.complete || img.naturalWidth <= 0)
                );
                return r.width > 50 && r.height > 50 && !pendingImg && !preVisible;
                """,
                last_el,
            )
            if ok:
                return last_el
        time.sleep(0.25)
    if last_el is not None:
        return last_el
    raise RuntimeError(f"pagina {page_no} nu a devenit vizibila")


def element_to_rgb_image(element) -> Image.Image:
    im = Image.open(io.BytesIO(element.screenshot_as_png)).convert("RGBA")
    bg = Image.new("RGB", im.size, "white")
    bg.paste(im, mask=im.getchannel("A"))
    return bg


def save_page_screenshot(drv: webdriver.Firefox, page_no: int, out_path: Path) -> None:
    wrap = wait_for_page_ready(drv, page_no)
    content_candidates = wrap.find_elements(By.CSS_SELECTOR, ".page-content")
    content = content_candidates[0] if content_candidates else wrap
    bg = element_to_rgb_image(content)
    if bg.width < MIN_PAGE_WIDTH or bg.height < MIN_PAGE_HEIGHT:
        bg = element_to_rgb_image(wrap)

    tmp = out_path.with_suffix(".png.part")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg.save(tmp, "PNG", optimize=True)
    if bg.width < MIN_PAGE_WIDTH or bg.height < MIN_PAGE_HEIGHT or tmp.stat().st_size < MIN_PNG_BYTES:
        size = tmp.stat().st_size if tmp.exists() else 0
        try:
            tmp.unlink()
        except Exception:
            pass
        raise RuntimeError(
            f"screenshot prea mic pentru pagina {page_no} "
            f"({bg.width}x{bg.height}, {size} bytes)"
        )
    os.replace(tmp, out_path)


def save_diagnostic_screenshot(drv: webdriver.Firefox, stage_dir: Path, page_no: int) -> None:
    try:
        diag = stage_dir / f"_diagnostic_page{page_no:04d}.png"
        drv.save_screenshot(str(diag))
        print(f"  diagnostic browser salvat: {diag.name}")
    except Exception:
        pass


def direct_page_url(issue: Dict, page_no: int) -> str:
    return issue_reader_base(issue).rstrip("/") + f"/{page_no}/"


def build_pdf(image_paths: Sequence[Path], pdf_path: Path, total_pages: int) -> bool:
    if len(image_paths) < total_pages:
        print(f"  PDF amanat: {len(image_paths)}/{total_pages} pagini")
        return False
    try:
        import img2pdf

        tmp = pdf_path.with_suffix(pdf_path.suffix + ".part")
        if tmp.exists():
            tmp.unlink()
        total_mb = sum(p.stat().st_size for p in image_paths) / (1024 * 1024)
        print(f"  construiesc PDF randat: {len(image_paths)} pagini, PNG {total_mb:.1f} MB -> {pdf_path}")
        with open(tmp, "wb") as fh:
            try:
                layout = img2pdf.get_fixed_dpi_layout_fun((100, 100))
            except Exception:
                layout = None
            kwargs = {"outputstream": fh}
            engine = getattr(getattr(img2pdf, "Engine", None), "pikepdf", None)
            if engine is not None:
                kwargs["engine"] = engine
            if layout is not None:
                kwargs["layout_fun"] = layout
            img2pdf.convert([str(p) for p in image_paths], **kwargs)
        if tmp.stat().st_size < 1024:
            raise RuntimeError("PDF .part prea mic")
        os.replace(tmp, pdf_path)
        print(f"  PDF randat salvat: {pdf_path}")
        return True
    except Exception as e:
        print(f"  !! PDF randat esuat: {type(e).__name__}: {str(e)[:180]}")
        return False


def capture_issue(
    mi,
    drv: webdriver.Firefox,
    session,
    state: Dict,
    issue: Dict,
    args: argparse.Namespace,
) -> None:
    code = issue["code"]
    stage_dir = stage_dir_for(issue)
    pdf_path = pdf_path_for(mi, issue)
    entry = get_entry(state, code)
    if issue_is_complete(entry, pdf_path) and not args.force:
        print(f"\n=== {code}: deja complet in state-rendered.json, sar ===")
        return

    print(f"\n=== RENDERED: {code}  {issue.get('month', '')} ===")
    meta_total, meta_title, _guid = mi.parse_viewer_metadata(session, issue)
    total_pages = int(meta_total or (entry or {}).get("total_pages") or 0)
    title = meta_title or (entry or {}).get("title") or f"Magazin Istoric {code}"
    if not total_pages:
        total_pages = mi.probe_page_count(session, issue, [3, 2, 1], 320)
    if not total_pages:
        print("  !! nu pot afla numarul de pagini, sar.")
        return
    print(f"  titlu: {title}")
    print(f"  pagini: {total_pages}")

    only_pages = parse_page_list(args.only_pages)
    target_pages = set(range(1, total_pages + 1))
    if args.max_pages and not only_pages:
        target_pages = set(range(1, min(total_pages, args.max_pages) + 1))
    if only_pages:
        target_pages = {p for p in only_pages if 1 <= p <= total_pages}
        print(f"  [TEST] capturez doar paginile: {sorted(target_pages)}")

    ensure_viewer_loaded(drv, issue, args, mi.COOKIE_PATH)

    done = set() if args.force_pages else existing_pages(stage_dir)
    pages_done = len(done.intersection(set(range(1, total_pages + 1))))
    last_page = max(done) if done else 0
    fail_counts: Dict[int, int] = {}
    max_page_retries = max(1, int(args.max_page_retries))

    while True:
        missing = sorted(p for p in target_pages if p not in done)
        if not missing:
            break
        target = missing[0]
        print(f"  navighez la pagina {target:04d}...")
        go_to_page(drv, target, args.page_wait)
        visible = visible_page_numbers(drv, total_pages)
        if target not in visible:
            # Uneori readerul mai are nevoie de un tact dupa salt.
            time.sleep(1.0)
            visible = visible_page_numbers(drv, total_pages)
        if not visible:
            fail_counts[target] = fail_counts.get(target, 0) + 1
            print(f"  !! nici o pagina vizibila dupa navigare; reincerc targetul ({fail_counts[target]}/{max_page_retries}).")
            if fail_counts[target] == 2:
                print("  reincarc pagina direct din URL...")
                drv.get(direct_page_url(issue, target))
                time.sleep(args.first_wait)
            if fail_counts[target] >= max_page_retries:
                save_diagnostic_screenshot(drv, stage_dir, target)
                raise RuntimeError(f"pagina {target} nu devine vizibila dupa {max_page_retries} incercari")
            continue

        for pg in visible:
            if pg not in target_pages or pg in done:
                continue
            out = page_path(stage_dir, pg)
            try:
                save_page_screenshot(drv, pg, out)
                done.add(pg)
                fail_counts.pop(pg, None)
                pages_done = len(done.intersection(set(range(1, total_pages + 1))))
                last_page = max(last_page, pg)
                print(f"  pg {pg:04d}: OK screenshot -> {out.name}")
                upsert_entry(state, issue, title, total_pages, stage_dir, pages_done, last_page)
            except Exception as e:
                fail_counts[pg] = fail_counts.get(pg, 0) + 1
                print(
                    f"  pg {pg:04d}: ESEC screenshot "
                    f"({fail_counts[pg]}/{max_page_retries}; {type(e).__name__}: {str(e)[:140]})"
                )
                if fail_counts[pg] == 2:
                    print("  reincarc pagina direct din URL...")
                    drv.get(direct_page_url(issue, pg))
                    time.sleep(args.first_wait)
                if fail_counts[pg] >= max_page_retries:
                    save_diagnostic_screenshot(drv, stage_dir, pg)
                    raise RuntimeError(f"pagina {pg} a esuat dupa {max_page_retries} incercari")
        time.sleep(0.25)

    files = collect_pages(stage_dir)
    full_files = [page_path(stage_dir, p) for p in range(1, total_pages + 1)]
    complete = all(p.exists() and p.stat().st_size > 1024 for p in full_files)

    if args.no_pdf or only_pages or args.max_pages:
        print(f"  test/partial: {len(files)}/{total_pages} PNG in {stage_dir}; nu fac PDF acum.")
        return

    if complete and build_pdf(full_files, pdf_path, total_pages):
        upsert_entry(
            state,
            issue,
            title,
            total_pages,
            stage_dir,
            total_pages,
            total_pages,
            completed=True,
            pdf_path=pdf_path,
        )
        if args.pdf_wait:
            time.sleep(args.pdf_wait)
    else:
        print(f"  document inca incomplet: {len(files)}/{total_pages}")


def filter_issues(issues: List[Dict], args: argparse.Namespace) -> List[Dict]:
    if args.only_code:
        wanted = set(args.only_code)
        issues = [it for it in issues if it["code"] in wanted]
    if args.start_code:
        issues = [it for it in issues if it["code"] >= args.start_code]
    if args.end_code:
        issues = [it for it in issues if it["code"] <= args.end_code]
    if args.max_issues:
        issues = issues[: args.max_issues]
    return issues


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Recaptureaza revistele noi prin screenshot randat in Firefox.")
    p.add_argument("--start-code", default=DEFAULT_START_CODE, help="Cod de start, implicit 200912.")
    p.add_argument("--end-code", default="", help="Cod final optional, ex. 202606.")
    p.add_argument("--only-code", action="append", default=[], help="Proceseaza doar codul YYYYMM. Poate fi repetat.")
    p.add_argument("--only-pages", default="", help="Test: pagini/range-uri, ex. 8,9 sau 1-3.")
    p.add_argument("--max-issues", type=int, default=0, help="Test: primele N numere dupa filtrare.")
    p.add_argument("--max-pages", type=int, default=0, help="Test: primele N pagini din fiecare numar.")
    p.add_argument("--first-wait", type=float, default=DEFAULT_FIRST_WAIT, help="Asteptare dupa deschiderea numarului.")
    p.add_argument("--page-wait", type=float, default=DEFAULT_PAGE_WAIT, help="Asteptare dupa schimbarea paginii.")
    p.add_argument("--max-page-retries", type=int, default=6, help="Cate incercari fac pentru o pagina inainte sa sar numarul.")
    p.add_argument("--max-driver-restarts", type=int, default=2, help="Cate reporniri Firefox incerc pentru acelasi numar.")
    p.add_argument("--browser-start-retries", type=int, default=DEFAULT_BROWSER_START_RETRIES, help="Cate incercari fac la pornirea Firefox.")
    p.add_argument("--browser-restart-wait", type=float, default=DEFAULT_BROWSER_RESTART_WAIT, help="Pauza intre repornirile Firefox.")
    p.add_argument("--pdf-wait", type=float, default=2.0, help="Pauza dupa PDF.")
    p.add_argument("--window-width", type=int, default=DEFAULT_WIDTH)
    p.add_argument("--window-height", type=int, default=DEFAULT_HEIGHT)
    p.add_argument("--visible", action="store_true", help="Arata Firefox; implicit ruleaza headless.")
    p.add_argument("--force", action="store_true", help="Reproceseaza chiar daca state-rendered spune complet.")
    p.add_argument("--force-pages", action="store_true", help="Refa paginile PNG existente.")
    p.add_argument("--no-pdf", action="store_true", help="Nu construi PDF; util la teste.")
    p.add_argument("--username", default=os.environ.get(USER_ENV, DEFAULT_USERNAME))
    p.add_argument("--password", default=os.environ.get(PASS_ENV, DEFAULT_PASSWORD))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.headless = not args.visible
    args.skip_login = False
    args.require_login = False
    setup_console_and_logging()
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    mi = load_base_module()
    session = mi.make_session()
    mi.load_cookies(session)
    # Refolosim loginul HTTP ca sa improspatam cookies.json daca e nevoie.
    mi.ensure_login(session, args)

    state = load_state()
    issues = mi.enumerate_issues(session, mi.ARCHIVE_URLS)
    issues = filter_issues(issues, args)
    print(f"\nTotal numere rendered selectate: {len(issues)}")
    if not issues:
        return

    drv: Optional[webdriver.Firefox] = None
    try:
        drv = start_browser(args)
        load_driver_cookies(drv, mi.COOKIE_PATH)
        for issue in issues:
            driver_restarts = 0
            while True:
                try:
                    if drv is None:
                        drv = start_browser(args)
                        load_driver_cookies(drv, mi.COOKIE_PATH)
                    capture_issue(mi, drv, session, state, issue, args)
                    break
                except KeyboardInterrupt:
                    print("\n[oprit manual] progresul rendered este salvat.")
                    raise
                except Exception as e:
                    code = issue.get("code")
                    needs_restart = driver_needs_restart(e)
                    print(f"\n!! Eroare la {code}: {type(e).__name__}: {str(e)[:240]}")
                    if needs_restart and driver_restarts < max(0, int(args.max_driver_restarts)):
                        driver_restarts += 1
                        print(
                            "   Firefox/geckodriver pare blocat; "
                            f"repornesc browserul si reincerc numarul ({driver_restarts}/{args.max_driver_restarts})."
                        )
                        close_browser(drv, save_cookies=False, force=True)
                        drv = None
                        time.sleep(max(0.0, float(args.browser_restart_wait)))
                        continue
                    if needs_restart:
                        print("   driverul a ramas instabil pentru acest numar; pornesc browser nou la urmatorul.")
                        close_browser(drv, save_cookies=False, force=True)
                        drv = None
                    print("   continui cu urmatorul numar; progresul de pana acum este salvat.")
                    time.sleep(2)
                    break
    finally:
        close_browser(drv, mi.COOKIE_PATH, save_cookies=True, force=False)
    print("\nGATA rendered.")


if __name__ == "__main__":
    main()
