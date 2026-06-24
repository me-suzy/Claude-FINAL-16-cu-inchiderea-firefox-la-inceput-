# -*- coding: utf-8 -*-
"""
magazin-ist.py
==============

Downloader pentru arhiva magazinistoric.ro.

Metoda este adaptata dupa "DOWNLOAD FULL - Metoda 1.py":
  - enumera arhiva si numerele revistei;
  - salveaza imaginea-sursa pentru fiecare pagina in staging;
  - construieste PDF-ul final din imaginile salvate;
  - pastreaza state.json pentru resume exact de unde s-a oprit.

Stocare:
  - PDF-uri finale:   G:\\Magazin Istoric\\Magazin Istoric - 196701 - ianuarie.pdf
  - imagini staging:  G:\\Magazin Istoric\\Temporare\\196701\\page0001.jpg
  - state/log/cookie: D:\\TEST\\Magazin Istoric\\

Credentiale:
  - username: --username sau MAGAZIN_ISTORIC_USERNAME
  - parola:   --password sau MAGAZIN_ISTORIC_PASSWORD sau prompt securizat

Parola nu este salvata in acest fisier. Cookie-urile de sesiune se salveaza separat,
in cookies.json, ca sa nu ceara login la fiecare pornire.
"""

from __future__ import annotations

import argparse
import getpass
import glob
import html as html_lib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover - depinde de versiunea locala urllib3
    Retry = None


BASE_URL = "https://magazinistoric.ro/"
WP_LOGIN_URL = urljoin(BASE_URL, "wp-login.php")
LOGIN_CHECK_URL = urljoin(BASE_URL, "revista/2026/202606/")
APP_ID = "magazin-istoric"

ARCHIVE_URLS = [
    "https://magazinistoric.ro/anii-1967-1969/",
    "https://magazinistoric.ro/anii-1970-1979/",
    "https://magazinistoric.ro/anii-1980-1989/",
    "https://magazinistoric.ro/anii-1990-1999/",
    "https://magazinistoric.ro/anii-2000-2009/",
    "https://magazinistoric.ro/anii-2010-2014/",
    "https://magazinistoric.ro/anii-2020-2029/",
]

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(r"G:\Magazin Istoric")
TEMP_ROOT = OUTPUT_ROOT / "Temporare"
STATE_PATH = SCRIPT_DIR / "state.json"
COOKIE_PATH = SCRIPT_DIR / "cookies.json"
LOG_DIR = SCRIPT_DIR / "Logs"
STATE_BACKUP_DIR = SCRIPT_DIR / "State_Backups"
COMPLETION_MARKER = "_magazin_ist_complete.json"

USER_ENV = "MAGAZIN_ISTORIC_USERNAME"
PASS_ENV = "MAGAZIN_ISTORIC_PASSWORD"

DEFAULT_PAGE_WAIT = 0.50
DEFAULT_PDF_WAIT = 2.0
DEFAULT_QUALITY = 3
DEFAULT_MAX_PROBE_PAGES = 260

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) "
    "Gecko/20100101 Firefox/115.0"
)

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
        path = LOG_DIR / f"magazin-ist_{datetime.now():%Y%m%d_%H%M%S}.log"
        RUN_LOG_FILE = open(path, "a", encoding="utf-8", buffering=1)
        sys.stdout = Tee(sys.stdout, RUN_LOG_FILE)
        sys.stderr = Tee(sys.stderr, RUN_LOG_FILE)
        print(f"Log rulare: {path}")
    except Exception as e:
        print(f"(nu pot activa logul: {e})")


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.7,en;q=0.5",
        }
    )
    if Retry is not None:
        try:
            retry = Retry(
                total=5,
                connect=5,
                read=5,
                status=5,
                backoff_factor=1.0,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(["GET", "HEAD", "POST"]),
                raise_on_status=False,
            )
        except TypeError:
            retry = Retry(
                total=5,
                connect=5,
                read=5,
                status=5,
                backoff_factor=1.0,
                status_forcelist=(429, 500, 502, 503, 504),
                method_whitelist=frozenset(["GET", "HEAD", "POST"]),
                raise_on_status=False,
            )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    return s


def load_cookies(session: requests.Session) -> None:
    if not COOKIE_PATH.exists():
        return
    try:
        data = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
        for item in data:
            session.cookies.set(
                item["name"],
                item["value"],
                domain=item.get("domain") or "magazinistoric.ro",
                path=item.get("path") or "/",
            )
        print(f"[login] cookies incarcate: {COOKIE_PATH}")
    except Exception as e:
        print(f"[login] nu pot citi cookies.json: {e}")


def save_cookies(session: requests.Session) -> None:
    try:
        data = []
        for c in session.cookies:
            data.append(
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                    "expires": c.expires,
                }
            )
        COOKIE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[login] cookies salvate: {COOKIE_PATH}")
    except Exception as e:
        print(f"[login] nu pot salva cookies.json: {e}")


def is_viewer_accessible(session: requests.Session) -> bool:
    try:
        r = session.get(LOGIN_CHECK_URL, timeout=30, allow_redirects=True)
        text = r.text or ""
        return "FBPublication" in text and "Abonamente la editia online" not in text
    except Exception:
        return False


def ensure_login(session: requests.Session, args: argparse.Namespace) -> bool:
    if args.skip_login:
        print("[login] sar peste login (--skip-login).")
        return False

    if is_viewer_accessible(session):
        print("[login] sesiune activa din cookies.json.")
        return True

    username = args.username or os.environ.get(USER_ENV) or ""
    if not username:
        username = input("Username Magazin Istoric: ").strip()

    password = args.password or os.environ.get(PASS_ENV) or ""
    if not password:
        try:
            password = getpass.getpass("Parola Magazin Istoric: ")
        except Exception:
            password = ""

    if not username or not password:
        print("[login] fara credentiale complete; continui cu acces direct la imaginile disponibile.")
        return False

    print("[login] autentificare WordPress...")
    data = {
        "log": username,
        "pwd": password,
        "wp-submit": "Log In",
        "redirect_to": BASE_URL,
        "testcookie": "1",
    }
    r = session.post(WP_LOGIN_URL, data=data, timeout=45, allow_redirects=True)
    if r.status_code >= 400:
        msg = f"login HTTP {r.status_code}"
        if args.require_login:
            raise RuntimeError(msg)
        print(f"[login] {msg}; continui cu fallback.")
        return False

    if is_viewer_accessible(session) or any(c.name.startswith("wordpress_logged_in") for c in session.cookies):
        print("[login] autentificare reusita.")
        save_cookies(session)
        return True

    msg = "login nereusit sau abonamentul nu este activ pentru viewer"
    if args.require_login:
        raise RuntimeError(msg)
    print(f"[login] {msg}; continui cu fallback pe URL-uri directe.")
    return False


def fetch_text(session: requests.Session, url: str, timeout: int = 45) -> Tuple[str, str]:
    r = session.get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    if not r.encoding:
        r.encoding = "utf-8"
    return r.text, r.url


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<script\b.*?</script>", " ", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<style\b.*?</style>", " ", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = html_lib.unescape(fragment)
    return re.sub(r"\s+", " ", fragment).strip()


def main_content_html(page_html: str) -> str:
    m = re.search(
        r"<div\b[^>]*\bid\s*=\s*(['\"])content\1[^>]*>(?P<body>.*?)</div>\s*<!--\s*#content\s*-->",
        page_html,
        flags=re.I | re.S,
    )
    return m.group("body") if m else page_html


def safe_filename(value: str, fallback: str = "document") -> str:
    value = html_lib.unescape(value or "")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or fallback


def unique_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def extract_anchor_tags(page_html: str) -> Iterable[Tuple[str, str]]:
    pat = re.compile(
        r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        flags=re.I | re.S,
    )
    href_pat = re.compile(r"\bhref\s*=\s*(['\"])(?P<href>.*?)\1", flags=re.I | re.S)
    for m in pat.finditer(page_html):
        h = href_pat.search(m.group("attrs"))
        if h:
            yield html_lib.unescape(h.group("href")), m.group("body")


def extract_year_urls(page_html: str, base_url: str) -> List[str]:
    candidates = []
    for href, _body in extract_anchor_tags(page_html):
        href = urljoin(base_url, href)
        if re.match(r"^https://magazinistoric\.ro/\d{4}(?:-\d+)?/$", href):
            candidates.append(href)
    return sorted(unique_keep_order(candidates), key=lambda u: int(re.search(r"/(\d{4})", u).group(1)))


def issue_code_from_url(value: str) -> Optional[str]:
    m = re.search(r"/revista/(\d{4})/(\d{6})/", value or "")
    return m.group(2) if m else None


def extract_issues_from_year(page_html: str, year_url: str) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    img_pat = re.compile(r"<img\b[^>]*\bsrc\s*=\s*(['\"])(?P<src>.*?)\1", flags=re.I | re.S)
    for href, body in extract_anchor_tags(page_html):
        abs_href = urljoin(year_url, href)
        if "magazinistoric.ro" not in abs_href:
            continue
        img = img_pat.search(body)
        img_src = urljoin(year_url, html_lib.unescape(img.group("src"))) if img else ""
        code = issue_code_from_url(img_src) or issue_code_from_url(abs_href)
        if not code:
            continue
        label = strip_tags(body)
        # De obicei label = "ianuarie". Daca ramane gol, folosim codul.
        issues.append(
            {
                "code": code,
                "year": code[:4],
                "month": label or code,
                "issue_url": abs_href.split("#", 1)[0],
                "thumb_url": img_src,
                "year_url": year_url,
            }
        )

    by_code: Dict[str, Dict[str, str]] = {}
    for issue in issues:
        by_code.setdefault(issue["code"], issue)
    return [by_code[k] for k in sorted(by_code)]


def enumerate_issues(session: requests.Session, archive_urls: Sequence[str]) -> List[Dict[str, str]]:
    all_issues: Dict[str, Dict[str, str]] = {}
    for archive_url in archive_urls:
        print(f"\n[arhiva] {archive_url}")
        page_html, final_url = fetch_text(session, archive_url)
        year_urls = extract_year_urls(main_content_html(page_html), final_url)
        print(f"  ani gasiti: {len(year_urls)}")
        for year_url in year_urls:
            y_html, y_final = fetch_text(session, year_url)
            issues = extract_issues_from_year(main_content_html(y_html), y_final)
            print(f"  {year_url} -> {len(issues)} numere")
            for issue in issues:
                all_issues.setdefault(issue["code"], issue)
            time.sleep(0.10)
    return [all_issues[k] for k in sorted(all_issues)]


def issue_reader_base(issue: Dict[str, str]) -> str:
    return f"https://magazinistoric.ro/revista/{issue['year']}/{issue['code']}/"


def extract_reader_link_from_issue_page(session: requests.Session, issue: Dict[str, str]) -> Optional[str]:
    try:
        page_html, _final = fetch_text(session, issue["issue_url"])
    except Exception:
        return None
    m = re.search(
        r"""href\s*=\s*(['"])(?P<href>https://magazinistoric\.ro/revista/\d{4}/\d{6}/(?:1/)?index\.php\?[^'"]+)\1""",
        page_html,
        flags=re.I | re.S,
    )
    if m:
        return html_lib.unescape(m.group("href"))
    return None


def parse_viewer_metadata(session: requests.Session, issue: Dict[str, str]) -> Tuple[Optional[int], str, Optional[str]]:
    title = f"Magazin Istoric - {issue.get('month', '').strip()} {issue['year']}".strip()
    guid = None
    try:
        page_html, final_url = fetch_text(session, issue_reader_base(issue))
        if "FBPublication" not in page_html or "Abonamente la editia online" in page_html:
            return None, title, guid
        tm = re.search(r"<title>\s*(.*?)\s*</title>", page_html, flags=re.I | re.S)
        if tm:
            title = strip_tags(tm.group(1)) or title
        gm = re.search(r"FBInit\.GUID\s*=\s*['\"]([^'\"]+)['\"]", page_html)
        if gm:
            guid = gm.group(1)
        nums = []
        nums += [int(x) for x in re.findall(r"href\s*=\s*['\"]\./(\d+)/['\"]", page_html, flags=re.I)]
        nums += [int(x) for x in re.findall(r"title\s*=\s*['\"](\d+)['\"]", page_html, flags=re.I)]
        nums = [n for n in nums if n > 0]
        total = max(nums) if nums else None
        if total:
            print(f"  metadata viewer: {total} pagini ({final_url})")
        return total, title, guid
    except Exception as e:
        print(f"  metadata viewer indisponibila: {str(e).splitlines()[0][:120]}")
        return None, title, guid


def quality_order(preferred: int) -> List[int]:
    preferred = max(1, min(3, int(preferred)))
    return unique_keep_order([preferred, 3, 2, 1])


def page_image_url(issue: Dict[str, str], page_no: int, quality: int, guid: Optional[str] = None) -> str:
    url = (
        f"https://magazinistoric.ro/revista/{issue['year']}/{issue['code']}/"
        f"files/assets/common/page-html5-substrates/page{page_no:04d}_{quality}.jpg"
    )
    # Query-ul uni nu este obligatoriu, dar il pastram daca l-am gasit in viewer.
    if guid:
        return f"{url}?uni={guid}"
    return url


def head_image(session: requests.Session, url: str) -> Tuple[bool, int, str]:
    try:
        r = session.head(url, timeout=25, allow_redirects=True)
        ct = (r.headers.get("Content-Type") or "").lower()
        length = int(r.headers.get("Content-Length") or 0)
        ok = r.status_code == 200 and "image/" in ct and length > 1024
        return ok, length, ct
    except Exception:
        return False, 0, ""


def existing_page_variant(
    session: requests.Session,
    issue: Dict[str, str],
    page_no: int,
    qualities: Sequence[int],
    guid: Optional[str] = None,
) -> Optional[Tuple[int, str, int]]:
    for q in qualities:
        url = page_image_url(issue, page_no, q, guid)
        ok, length, _ct = head_image(session, url)
        if ok:
            return q, url, length
    if guid:
        # Uneori query-ul uni poate fi invechit; incercam si URL-ul curat.
        for q in qualities:
            url = page_image_url(issue, page_no, q, None)
            ok, length, _ct = head_image(session, url)
            if ok:
                return q, url, length
    return None


def probe_page_count(
    session: requests.Session,
    issue: Dict[str, str],
    qualities: Sequence[int],
    max_probe_pages: int,
    guid: Optional[str] = None,
) -> int:
    print("  probez numarul de pagini dupa imaginile pageNNNN_Q.jpg...")

    def exists(n: int) -> bool:
        return existing_page_variant(session, issue, n, qualities, guid) is not None

    if not exists(1):
        return 0

    last = 1
    high = 2
    while high <= max_probe_pages and exists(high):
        last = high
        high *= 2

    if high > max_probe_pages:
        if exists(max_probe_pages):
            print(f"  !! am gasit pagina {max_probe_pages}; creste --max-probe-pages daca lipseste finalul")
            return max_probe_pages
        high = max_probe_pages

    lo = last + 1
    hi = high
    while lo < hi:
        mid = (lo + hi) // 2
        if exists(mid):
            lo = mid + 1
        else:
            hi = mid
    total = lo - 1
    print(f"  probe rezultat: {total} pagini")
    return total


def new_state() -> Dict:
    return {
        "version": 1,
        "app": APP_ID,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "downloaded_issues": [],
    }


def state_is_foreign(data: Dict) -> bool:
    app = data.get("app")
    if app and app != APP_ID:
        return True
    for item in data.get("downloaded_issues", [])[:20]:
        url = " ".join(
            str(item.get(k) or "")
            for k in ("url", "issue_url", "reader_url", "pdf", "stage_dir")
        )
        if url and "magazinistoric.ro" not in url and "Magazin Istoric" not in url:
            return True
    return False


def load_state() -> Dict:
    if not STATE_PATH.exists():
        return new_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state.json nu este obiect JSON")
        if state_is_foreign(data):
            STATE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            dst = STATE_BACKUP_DIR / f"state_foreign_{datetime.now():%Y%m%d_%H%M%S}.json"
            dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[state] state.json pare strain de Magazin Istoric; backup: {dst}")
            return new_state()
        data.setdefault("version", 1)
        data.setdefault("app", APP_ID)
        data.setdefault("downloaded_issues", [])
        return data
    except Exception as e:
        print(f"[state] nu pot citi state.json ({e}); pornesc state nou.")
        return new_state()


def backup_state() -> None:
    if not STATE_PATH.exists():
        return
    try:
        STATE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dst = STATE_BACKUP_DIR / f"state_{datetime.now():%Y%m%d_%H%M%S}.json"
        dst.write_bytes(STATE_PATH.read_bytes())
    except Exception:
        pass


def save_state(state: Dict) -> None:
    state["app"] = APP_ID
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state["count"] = sum(int(it.get("pages") or 0) for it in state.get("downloaded_issues", []))
    try:
        if STATE_PATH.exists():
            old = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            old_items = old.get("downloaded_issues", []) if isinstance(old, dict) else []
            new_items = state.get("downloaded_issues", [])
            if len(new_items) + 5 < len(old_items):
                print(f"[state] protectie: state-ul nou pare mai mic ({len(new_items)} < {len(old_items)}), fac backup.")
                backup_state()
    except Exception:
        pass

    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def get_entry(state: Dict, code: str) -> Optional[Dict]:
    for it in state.setdefault("downloaded_issues", []):
        if it.get("code") == code:
            return it
    return None


def upsert_issue(
    state: Dict,
    issue: Dict[str, str],
    title: str,
    pages_done: int,
    total_pages: int,
    last_page: int,
    stage_dir: Path,
    completed: bool = False,
    pdf: Optional[Path] = None,
    reader_url: Optional[str] = None,
) -> Dict:
    entry = get_entry(state, issue["code"])
    if entry is None:
        entry = {"code": issue["code"]}
        state.setdefault("downloaded_issues", []).append(entry)
    entry.update(
        {
            "url": issue_reader_base(issue),
            "issue_url": issue.get("issue_url"),
            "reader_url": reader_url or entry.get("reader_url"),
            "title": title,
            "year": issue["year"],
            "month": issue.get("month"),
            "pages": int(pages_done),
            "total_pages": int(total_pages),
            "last_successful_page": int(last_page),
            "stage_dir": str(stage_dir),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    if completed:
        entry["completed_at"] = datetime.now().isoformat(timespec="seconds")
    if pdf:
        entry["pdf"] = str(pdf)
    state["downloaded_issues"].sort(key=lambda x: x.get("code", ""))
    save_state(state)
    return entry


def issue_is_complete(entry: Optional[Dict]) -> bool:
    return bool(entry and entry.get("completed_at") and entry.get("pdf"))


def pdf_path_for_issue(issue: Dict[str, str]) -> Path:
    month = safe_filename(issue.get("month") or "")
    name = f"Magazin Istoric - {issue['code']}"
    if month and month != issue["code"]:
        name += f" - {month}"
    return OUTPUT_ROOT / f"{name}.pdf"


def stage_dir_for_issue(issue: Dict[str, str]) -> Path:
    return TEMP_ROOT / issue["code"]


def existing_page_file(stage_dir: Path, page_no: int) -> Optional[Path]:
    p = stage_dir / f"page{page_no:04d}.jpg"
    if p.exists() and p.stat().st_size > 1024:
        return p
    return None


def collect_page_files(stage_dir: Path) -> List[Path]:
    files = [Path(p) for p in glob.glob(str(stage_dir / "page*.jpg"))]
    files.sort(key=lambda p: p.name)
    return files


def count_stage_pages(stage_dir: Path) -> Tuple[int, int]:
    last = 0
    files = collect_page_files(stage_dir)
    for p in files:
        m = re.search(r"page(\d+)\.jpg$", p.name)
        if m:
            last = max(last, int(m.group(1)))
    return len(files), last


def write_completion_marker(entry: Dict, stage_dir: Path) -> None:
    try:
        marker = stage_dir / COMPLETION_MARKER
        marker.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  [state] nu pot scrie markerul de finalizare: {e}")


def download_page_image(
    session: requests.Session,
    issue: Dict[str, str],
    page_no: int,
    stage_dir: Path,
    qualities: Sequence[int],
    guid: Optional[str] = None,
) -> Optional[Path]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    out = stage_dir / f"page{page_no:04d}.jpg"
    tmp = out.with_suffix(".jpg.part")

    variants = []
    if guid:
        variants.extend(page_image_url(issue, page_no, q, guid) for q in qualities)
    variants.extend(page_image_url(issue, page_no, q, None) for q in qualities)
    variants = unique_keep_order(variants)

    last_error = ""
    for url in variants:
        try:
            r = session.get(url, timeout=60, stream=True, allow_redirects=True)
            ct = (r.headers.get("Content-Type") or "").lower()
            if r.status_code != 200 or "image/" not in ct:
                last_error = f"HTTP {r.status_code} {ct}"
                continue
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)
            if tmp.stat().st_size <= 1024:
                last_error = f"fisier prea mic ({tmp.stat().st_size} bytes)"
                try:
                    tmp.unlink()
                except Exception:
                    pass
                continue
            os.replace(tmp, out)
            return out
        except Exception as e:
            last_error = str(e).splitlines()[0][:120]
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            time.sleep(1.0)

    print(f"  pg {page_no:04d}: ESEC download ({last_error})")
    return None


def build_pdf(image_paths: Sequence[Path], pdf_path: Path, total_pages: int) -> bool:
    if total_pages and len(image_paths) < total_pages:
        print(f"  (PDF amanat: doar {len(image_paths)}/{total_pages} pagini pe disc)")
        return False
    if not image_paths:
        print("  (fara imagini, nu fac PDF)")
        return False
    for p in image_paths:
        if not p.exists() or p.stat().st_size < 1024:
            print(f"  !! pagina lipsa/mica: {p.name}; nu fac PDF acum")
            return False

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = pdf_path.with_suffix(pdf_path.suffix + ".part")
    if tmp.exists():
        try:
            tmp.unlink()
        except Exception:
            pass

    total_mb = sum(p.stat().st_size for p in image_paths) / (1024 * 1024)
    print(f"  construiesc PDF: {len(image_paths)} pagini, imagini {total_mb:.1f} MB -> {pdf_path}")

    try:
        import img2pdf

        layout = None
        try:
            layout = img2pdf.get_fixed_dpi_layout_fun((200, 200))
        except Exception:
            pass

        for attempt in range(1, 4):
            try:
                with open(tmp, "wb") as fh:
                    kwargs = {"outputstream": fh}
                    engine = getattr(getattr(img2pdf, "Engine", None), "pikepdf", None)
                    if engine is not None:
                        kwargs["engine"] = engine
                    if layout is not None:
                        kwargs["layout_fun"] = layout
                    img2pdf.convert([str(p) for p in image_paths], **kwargs)
                if tmp.stat().st_size < 1024:
                    raise RuntimeError(f"PDF .part prea mic ({tmp.stat().st_size} bytes)")
                os.replace(tmp, pdf_path)
                print(f"  PDF salvat: {pdf_path}")
                return True
            except Exception as e:
                print(f"  img2pdf incercare {attempt}/3 esuata: {type(e).__name__}: {str(e)[:160]}")
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass
                time.sleep(2)
    except Exception as e:
        print(f"  img2pdf indisponibil ({e}); incerc fallback PIL daca documentul e mic.")

    if len(image_paths) > 120 or total_mb > 250:
        print("  !! fallback PIL oprit pentru document mare; se reincearca la urmatoarea rulare.")
        return False

    imgs = []
    try:
        from PIL import Image

        for p in image_paths:
            im = Image.open(p)
            im.load()
            imgs.append(im.convert("RGB"))
        imgs[0].save(tmp, "PDF", resolution=200.0, save_all=True, append_images=imgs[1:])
        if tmp.stat().st_size < 1024:
            raise RuntimeError(f"PDF .part prea mic ({tmp.stat().st_size} bytes)")
        os.replace(tmp, pdf_path)
        print(f"  PDF salvat cu PIL: {pdf_path}")
        return True
    except Exception as e:
        print(f"  !! PDF PIL esuat: {type(e).__name__}: {str(e)[:160]}")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False
    finally:
        for im in imgs:
            try:
                im.close()
            except Exception:
                pass


def finalize_pending_pdfs(state: Dict) -> None:
    pending = []
    for e in state.get("downloaded_issues", []):
        if e.get("completed_at") or not e.get("stage_dir") or not e.get("total_pages"):
            continue
        stage = Path(e["stage_dir"])
        total = int(e.get("total_pages") or 0)
        files = collect_page_files(stage)
        if total and len(files) >= total:
            pending.append((e, stage, files, total))
    if not pending:
        return
    print(f"\n[finalize] PDF-uri restante: {len(pending)}")
    for e, stage, files, total in pending:
        issue = {
            "code": e["code"],
            "year": e.get("year") or e["code"][:4],
            "month": e.get("month") or e["code"],
        }
        pdf_path = Path(e.get("pdf") or pdf_path_for_issue(issue))
        if pdf_path.exists() and pdf_path.stat().st_size > 1024:
            e["completed_at"] = e.get("completed_at") or datetime.now().isoformat(timespec="seconds")
            e["pdf"] = str(pdf_path)
            save_state(state)
            continue
        if build_pdf(files, pdf_path, total):
            e["completed_at"] = datetime.now().isoformat(timespec="seconds")
            e["pdf"] = str(pdf_path)
            write_completion_marker(e, stage)
            save_state(state)


def discover_issue_total_and_title(
    session: requests.Session,
    issue: Dict[str, str],
    entry: Optional[Dict],
    qualities: Sequence[int],
    max_probe_pages: int,
) -> Tuple[int, str, Optional[str], Optional[str]]:
    title = entry.get("title") if entry else ""
    total = int(entry.get("total_pages") or 0) if entry else 0
    guid = None
    reader_link = entry.get("reader_url") if entry else None

    if not reader_link:
        reader_link = extract_reader_link_from_issue_page(session, issue)

    meta_total, meta_title, guid = parse_viewer_metadata(session, issue)
    if meta_title:
        title = meta_title
    if meta_total:
        total = meta_total

    if not title:
        title = f"Magazin Istoric - {issue.get('month', '').strip()} {issue['year']}".strip()

    if not total:
        total = probe_page_count(session, issue, qualities, max_probe_pages, guid)

    return total, title, guid, reader_link


def process_issue(
    session: requests.Session,
    state: Dict,
    issue: Dict[str, str],
    args: argparse.Namespace,
) -> None:
    code = issue["code"]
    stage_dir = stage_dir_for_issue(issue)
    pdf_path = pdf_path_for_issue(issue)
    entry = get_entry(state, code)

    if pdf_path.exists() and pdf_path.stat().st_size > 1024 and not args.force:
        print(f"\n=== {code}: PDF existent, marchez complet si sar ===")
        pages, last_page = count_stage_pages(stage_dir)
        total = pages or int(entry.get("total_pages") if entry else 0) or pages
        upsert_issue(
            state,
            issue,
            entry.get("title") if entry else f"Magazin Istoric {code}",
            pages,
            total,
            last_page,
            stage_dir,
            completed=True,
            pdf=pdf_path,
        )
        return

    if issue_is_complete(entry) and not args.force:
        print(f"\n=== {code}: deja complet in state.json, sar ===")
        return

    qualities = quality_order(args.quality)
    print(f"\n=== NUMAR: {code}  {issue.get('month', '')} ===")
    total, title, guid, reader_link = discover_issue_total_and_title(
        session, issue, entry, qualities, args.max_probe_pages
    )
    if not total:
        print(f"  !! nu am putut afla numarul de pagini pentru {code}; sar.")
        return
    print(f"  titlu: {title}")
    print(f"  pagini: {total}")

    capture_total = min(total, args.max_pages) if args.max_pages else total
    if args.max_pages:
        print(f"  [TEST] descarc doar primele {capture_total}/{total} pagini")

    pages_done = 0
    last_page = 0
    for page_no in range(1, capture_total + 1):
        ex = None if args.force_pages else existing_page_file(stage_dir, page_no)
        if ex:
            pages_done += 1
            last_page = page_no
            print(f"  pg {page_no:04d}: exista, sar")
            upsert_issue(
                state,
                issue,
                title,
                pages_done,
                total,
                last_page,
                stage_dir,
                reader_url=reader_link,
            )
            continue

        img = None
        for attempt in range(1, 4):
            img = download_page_image(session, issue, page_no, stage_dir, qualities, guid)
            if img:
                break
            print(f"  pg {page_no:04d}: reincerc ({attempt}/3)...")
            time.sleep(2)

        if not img:
            print(f"  pg {page_no:04d}: ramas neterminat; se reia la urmatoarea rulare.")
            upsert_issue(
                state,
                issue,
                title,
                pages_done,
                total,
                last_page,
                stage_dir,
                reader_url=reader_link,
            )
            continue

        pages_done += 1
        last_page = page_no
        print(f"  pg {page_no:04d}: OK -> {img.name}")
        upsert_issue(
            state,
            issue,
            title,
            pages_done,
            total,
            last_page,
            stage_dir,
            reader_url=reader_link,
        )
        time.sleep(args.page_wait)

    files = collect_page_files(stage_dir)
    if len(files) >= total and not args.max_pages:
        if build_pdf(files, pdf_path, total):
            entry = upsert_issue(
                state,
                issue,
                title,
                total,
                total,
                total,
                stage_dir,
                completed=True,
                pdf=pdf_path,
                reader_url=reader_link,
            )
            write_completion_marker(entry, stage_dir)
            print(f"  [state] COMPLET {total}/{total} PDF OK")
            if args.pdf_wait:
                time.sleep(args.pdf_wait)
    else:
        print(f"  document incomplet pe disc: {len(files)}/{total}; PDF-ul se face cand e gata.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Descarca arhiva Magazin Istoric ca imagini + PDF, cu resume."
    )
    p.add_argument("--username", default=os.environ.get(USER_ENV, ""), help=f"Username sau env {USER_ENV}.")
    p.add_argument("--password", default=os.environ.get(PASS_ENV, ""), help=f"Parola sau env {PASS_ENV}.")
    p.add_argument("--skip-login", action="store_true", help="Nu face login; foloseste doar URL-urile directe.")
    p.add_argument("--require-login", action="store_true", help="Opreste scriptul daca loginul esueaza.")
    p.add_argument("--list-only", action="store_true", help="Doar enumera numerele gasite, fara download.")
    p.add_argument("--quality", type=int, default=DEFAULT_QUALITY, choices=[1, 2, 3], help="Calitate preferata: 3=max.")
    p.add_argument("--page-wait", type=float, default=DEFAULT_PAGE_WAIT, help="Pauza intre pagini, in secunde.")
    p.add_argument("--pdf-wait", type=float, default=DEFAULT_PDF_WAIT, help="Pauza dupa fiecare PDF, in secunde.")
    p.add_argument("--max-probe-pages", type=int, default=DEFAULT_MAX_PROBE_PAGES, help="Limita pentru detectarea paginilor.")
    p.add_argument("--max-issues", type=int, default=0, help="Test: proceseaza doar primele N numere.")
    p.add_argument("--max-pages", type=int, default=0, help="Test: descarca doar primele N pagini din fiecare numar.")
    p.add_argument("--only-code", action="append", default=[], help="Proceseaza doar codul YYYYMM dat. Poate fi repetat.")
    p.add_argument("--start-code", default="", help="Sari peste numerele mai mici decat codul YYYYMM.")
    p.add_argument("--end-code", default="", help="Sari peste numerele mai mari decat codul YYYYMM.")
    p.add_argument("--force", action="store_true", help="Reproceseaza si daca state/PDF spune complet.")
    p.add_argument("--force-pages", action="store_true", help="Redescarca paginile existente in Temporare.")
    p.add_argument("--archive-url", action="append", default=[], help="Adauga/foloseste un URL de arhiva custom.")
    return p.parse_args()


def apply_filters(issues: List[Dict[str, str]], args: argparse.Namespace) -> List[Dict[str, str]]:
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


def main() -> None:
    args = parse_args()
    setup_console_and_logging()

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    session = make_session()
    load_cookies(session)
    ensure_login(session, args)

    state = load_state()
    finalize_pending_pdfs(state)

    archive_urls = args.archive_url or ARCHIVE_URLS
    issues = enumerate_issues(session, archive_urls)
    issues = apply_filters(issues, args)

    print(f"\nTotal numere selectate: {len(issues)}")
    if args.list_only:
        for it in issues:
            print(f"{it['code']} | {it.get('month','')} | {it.get('issue_url','')}")
        return

    for issue in issues:
        try:
            process_issue(session, state, issue, args)
        except KeyboardInterrupt:
            print("\n[oprit manual] progresul este salvat in state.json.")
            raise
        except Exception as e:
            print(f"\n!! Eroare la {issue.get('code')}: {type(e).__name__}: {str(e)[:240]}")
            print("   continui cu urmatorul numar; progresul de pana acum este salvat.")
            time.sleep(2)

    print("\nGATA.")


if __name__ == "__main__":
    main()
