#!/usr/bin/env python3
"""
Automatizare descărcare PDF-uri din Arcanum (FIXED VERSION cu SORTARE CRONOLOGICĂ):
- FIXED: Scanează corect toate fișierele existente de pe disk
- FIXED: Păstrează progresul parțial între zile
- FIXED: Procesează și combină corect TOATE PDF-urile pentru fiecare issue
- FIXED: Resume logic corect pentru issue-urile parțiale
- FIXED: Detectează corect prefix-urile pentru fișiere
- FIXED: Verifică corect issue-urile complete pentru skip URLs
- FIXED: Elimină dublurile automat
- FIXED: Detectează mai bine numărul total de pagini
- FIXED: Sortare cronologică corectă în downloaded_issues
- FIXED: Detectează și oprește automat pentru CAPTCHA
- FIXED: Așteaptă automat pentru mentenanță (403 Forbidden)
- FIXED: Gestionează pop-up Windows de autentificare

DEPENDENȚE OPȚIONALE:
- pyautogui: Pentru gestionarea automată a pop-up-urilor Windows de autentificare
  Instalare: pip install pyautogui
  (Scriptul funcționează și fără, dar va aștepta intervenție manuală)
"""

import time
import os
import sys
import re
import json
import shutil
import subprocess
import glob
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.common.exceptions import WebDriverException, ElementClickInterceptedException

import logging
import sys

def setup_logging():
    """Configurează logging în timp real"""
    log_dir = r"E:\Carte\BB\17 - Site Leadership\alte\Ionel Balauta\Aryeht\Task 1 - Traduce tot site-ul\Doar Google Web\Andreea\Meditatii\2023\++Arcanum Download + Chrome\Ruleaza cand sunt plecat 3\Logs"
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"arcanum_download_{timestamp}.log")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, mode='w', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            handler.stream.reconfigure(line_buffering=True)

    print(f"📝 LOGGING ACTIVAT: {log_file}")
    return log_file


def _ps_get_process_count(name):
    """Returnează numărul de procese cu numele dat, folosind PowerShell (NU tasklist care se blochează)."""
    try:
        CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        ps_cmd = f"(Get-Process -Name {name} -ErrorAction SilentlyContinue).Count"
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_cmd],
                          capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW if sys.platform == 'win32' else 0, timeout=10)
        count_str = (r.stdout or '').strip()
        return int(count_str) if count_str.isdigit() else 0
    except Exception:
        return -1  # nu putem verifica


def _ps_stop_process(name, timeout_sec=20):
    """Oprește un proces folosind PowerShell Stop-Process. NU folosește taskkill (se blochează pe acest PC)."""
    try:
        CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        ps_cmd = f"Get-Process -Name {name} -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_cmd],
                      capture_output=True, creationflags=CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                      timeout=timeout_sec)
        return True
    except Exception as e:
        print(f"   ⚠️ PowerShell Stop-Process {name}: {e}")
        return False


def kill_firefox_and_geckodriver_at_start():
    """
    Închide orice instanță Firefox și geckodriver la ÎNCEPUTUL scriptului.
    IMPORTANT: Folosește EXCLUSIV PowerShell (tasklist și taskkill se BLOCHEAZĂ pe acest PC).
    """
    try:
        fox_count = _ps_get_process_count('firefox')
        gecko_count = _ps_get_process_count('geckodriver')
        print("🔄 [LA PORNIRE] Închid orice Firefox și geckodriver...")
        print(f"   [DEBUG] Procese detectate (PowerShell): firefox={fox_count}, geckodriver={gecko_count}")

        # Închide Firefox cu PowerShell Stop-Process (NU taskkill care se blochează!)
        if fox_count > 0:
            _ps_stop_process('firefox')
            time.sleep(3)
            fox_after = _ps_get_process_count('firefox')
            if fox_after > 0:
                print(f"   ⚠️ Mai sunt {fox_after} procese firefox - încerc din nou...")
                _ps_stop_process('firefox')
                time.sleep(2)
                fox_after2 = _ps_get_process_count('firefox')
                if fox_after2 > 0:
                    print(f"   ❌ {fox_after2} procese firefox NU s-au închis!")
                else:
                    print("   ✅ Firefox închis la a doua încercare.")
            else:
                print("   ✅ Firefox închis.")
        else:
            print("   ✅ Firefox nu rulează.")

        # Închide geckodriver cu PowerShell Stop-Process
        if gecko_count > 0:
            _ps_stop_process('geckodriver')
            time.sleep(2)
            print("   ✅ Geckodriver închis.")
        else:
            print("   ✅ Geckodriver nu rulează.")

        # Curăță fișierele de lock din profilurile Firefox
        try:
            profile_base = os.path.join(os.environ.get('APPDATA', ''), r"Mozilla\Firefox\Profiles")
            if os.path.isdir(profile_base):
                for profile_dir in os.listdir(profile_base):
                    profile_path = os.path.join(profile_base, profile_dir)
                    if os.path.isdir(profile_path):
                        for lock_file in ['parent.lock', '.parentlock', 'lock']:
                            lock_path = os.path.join(profile_path, lock_file)
                            if os.path.exists(lock_path):
                                try:
                                    os.remove(lock_path)
                                    print(f"   🔓 Lock șters: {lock_path}")
                                except Exception as e:
                                    print(f"   ⚠️ Nu am putut șterge {lock_path}: {e}")
        except Exception as e:
            print(f"   ⚠️ Eroare la curățarea lock-urilor: {e}")

        time.sleep(1)
        print("✅ [LA PORNIRE] Pregătire terminată – profilul Firefox este eliberat.")
    except Exception as e:
        print(f"⚠️ [LA PORNIRE] Eroare la închiderea Firefox/geckodriver: {e}")


# Colectie unica - GazetaMatematica (doar pentru acest script derivat)
ADDITIONAL_COLLECTIONS = [
    'https://adt.arcanum.com/ro/collection/GazetaMatematica/',
]

# URL-uri specifice de issue-uri (view) care trebuie descarcate din GazetaMatematica.
# Cand main_collection_url contine "GazetaMatematica", extract_issue_links_from_collection()
# returneaza aceasta lista in loc sa scaneze pagina colectiei.
FORCED_ISSUE_URLS_BY_COLLECTION = {
    'GazetaMatematica': [
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1945',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1944-45_Sup',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1945_1_sup',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1946-47',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1946_2_sup',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1947-48',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1947_1_sup',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1947_2_sup',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1948-49',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1948_1_sup',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1948_2_sup',
        'https://adt.arcanum.com/ro/view/GazetaMatematica_1949_1_sup',
    ],
}

# Skip URLs statice (hardcoded)
STATIC_SKIP_URLS = {
    "https://adt.arcanum.com/ro/view/Convietuirea_1997-1998"
}

DAILY_LIMIT = 1050
STATE_FILENAME = "state.json"
SKIP_URLS_FILENAME = "skip_urls.json"


class ChromePDFDownloader:
    def __init__(self, main_collection_url, download_dir=None, batch_size=50, timeout=15):
        self.main_collection_url = main_collection_url
        self.batch_size = batch_size
        self.timeout = timeout
        self.download_dir = download_dir or os.getcwd()
        self.driver = None
        self.wait = None
        self.attached_existing = False
        self.state_path = os.path.join(self.download_dir, STATE_FILENAME)
        self.skip_urls_path = os.path.join(self.download_dir, SKIP_URLS_FILENAME)
        self.current_issue_url = None
        self.dynamic_skip_urls = set()

        # Tracking pentru retry-uri după CAPTCHA
        self.captcha_retry_count = {}  # {segment_key: retry_count}
        self.captcha_wait_minutes = 7  # Timpul de așteptare după CAPTCHA (crescut la 7 minute)
        self.captcha_max_retries = 2  # Număr maxim de retry-uri înainte de oprire (0, 1, 2 = 3 încercări total)
        self.captcha_retry_needed = False  # Flag pentru retry după CAPTCHA

        # Calea pentru loguri zilnice
        self.daily_log_dir = os.path.join(self.download_dir, "daily_logs")
        os.makedirs(self.daily_log_dir, exist_ok=True)

        # Crează backup zilnic ÎNAINTE de a încărca state-ul
        self._create_daily_backup()

        self._load_skip_urls()
        self._load_state()
        self.fix_existing_json()

    def _load_skip_urls(self):
        """Încarcă skip URLs din fișierul separat"""
        self.dynamic_skip_urls = set(STATIC_SKIP_URLS)  # Începe cu cele statice

        if os.path.exists(self.skip_urls_path):
            try:
                # REPARĂ JSON-ul dacă are virgulă lipsă
                self._repair_json_missing_comma(self.skip_urls_path)

                with open(self.skip_urls_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    completed_urls = data.get("completed_urls", [])
                    completed_collections = data.get("completed_collections", [])

                    self.dynamic_skip_urls.update(url.rstrip('/') for url in completed_urls)
                    self.dynamic_skip_urls.update(url.rstrip('/') for url in completed_collections)

                    print(f"📋 Încărcat {len(completed_urls)} URL-uri complet descărcate din {SKIP_URLS_FILENAME}")
                    print(f"📋 Încărcat {len(completed_collections)} colecții complet procesate din {SKIP_URLS_FILENAME}")
            except Exception as e:
                print(f"⚠ Eroare la citirea {SKIP_URLS_FILENAME}: {e}")
                print(f"🔄 Recreez {SKIP_URLS_FILENAME} de la zero...")
                # Dacă JSON-ul e prea corupt, resetează-l
                self._save_skip_urls()

        print(f"🚫 Total URL-uri de skip: {len(self.dynamic_skip_urls)}")

    def _save_skip_urls(self):
        """FIXED: Verifică corect dacă un issue este complet - FOLOSEȘTE last_successful_segment_end!"""
        try:
            completed_urls = []
            for item in self.state.get("downloaded_issues", []):
                # VERIFICARE CORECTĂ: folosește last_successful_segment_end, NU pages!
                completed_at = item.get("completed_at")
                total_pages = item.get("total_pages")
                last_segment = item.get("last_successful_segment_end", 0)
                pages = item.get("pages", 0)  # Pentru debug

                # CONDIȚIE FIXATĂ: verifică progresul REAL (last_segment), nu pages!
                if (completed_at and  # Marcat ca terminat
                    total_pages and  # Are total_pages setat
                    total_pages > 0 and  # Total valid
                    last_segment >= total_pages):  # Progresul REAL este complet

                    completed_urls.append(item["url"])
                    print(f"✅ Issue complet pentru skip: {item['url']} ({last_segment}/{total_pages})")

                    # DEBUG: Afișează discrepanțele
                    if pages != last_segment:
                        print(f"   ⚠ DISCREPANȚĂ: pages={pages}, last_segment={last_segment}")
                else:
                    # DEBUG: Afișează de ce nu e considerat complet
                    if item.get("url"):  # Doar dacă are URL valid
                        print(f"🔄 Issue incomplet: {item.get('url', 'NO_URL')}")
                        print(f"   completed_at: {bool(completed_at)}")
                        print(f"   total_pages: {total_pages}")
                        print(f"   last_segment: {last_segment}")
                        print(f"   pages: {pages}")

                        # Verifică fiecare condiție individual
                        if not completed_at:
                            print(f"   → Lipsește completed_at")
                        elif not total_pages or total_pages <= 0:
                            print(f"   → total_pages invalid")
                        elif last_segment < total_pages:
                            print(f"   → Progres incomplet: {last_segment}/{total_pages}")

            # Adaugă și cele statice
            all_completed = list(STATIC_SKIP_URLS) + completed_urls

            # Păstrează și colecțiile complete dacă există
            existing_data = {}
            if os.path.exists(self.skip_urls_path):
                with open(self.skip_urls_path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)

            data = {
                "last_updated": datetime.now().isoformat(),
                "completed_urls": sorted(list(set(all_completed))),
                "completed_collections": existing_data.get("completed_collections", [])
            }

            with open(self.skip_urls_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            print(f"💾 Salvat {len(data['completed_urls'])} URL-uri CORECT VERIFICATE în {SKIP_URLS_FILENAME}")

            # RAPORT FINAL pentru debugging
            print(f"📋 ISSUES COMPLETE în skip_urls:")
            for url in sorted(completed_urls):
                year = url.split('_')[-1] if '_' in url else 'UNKNOWN'
                print(f"   ✅ {year}")

        except Exception as e:
            print(f"⚠ Eroare la salvarea {SKIP_URLS_FILENAME}: {e}")

    def _safe_folder_name(self, name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    def _decode_unicode_escapes(self, obj):
        """Decodifică secvențele unicode din JSON"""
        if isinstance(obj, dict):
            return {key: self._decode_unicode_escapes(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._decode_unicode_escapes(item) for item in obj]
        elif isinstance(obj, str):
            # Decodifică secvențele unicode ca \u0103, \u0219
            try:
                return obj.encode('utf-8').decode('unicode_escape').encode('latin-1').decode('utf-8') if '\\u' in obj else obj
            except:
                return obj
        else:
            return obj

    def is_issue_complete_by_end_page(self, end_page):
        """FIXED: Determină dacă un issue e complet pe baza ultimei pagini"""
        # VERIFICARE CRITICĂ: Dacă e doar 1 pagină, probabil e o eroare de detectare
        if end_page <= 1:
            print(f"⚠ ALERTĂ: end_page={end_page} pare să fie o eroare de detectare!")
            return False  # NU considera complet dacă e doar 1 pagină

        # Pentru issue-uri normale, verifică dacă ultima pagină nu e multiplu rotund
        return not ((end_page + 1) % 50 == 0 or (end_page + 1) % 100 == 0)

    def extract_issue_id_from_filename(self, filename):
        """FIXED: Extrage ID-ul issue-ului din numele fișierului (cu sau fără timestamp)"""

        # Încearcă primul pattern: cu timestamp (PrefixIssue-TIMESTAMP__pages)
        match = re.search(r'([^-]+(?:-[^-]+)*)-\d+__pages', filename)
        if match:
            return match.group(1)

        # Încearcă al doilea pattern: fără timestamp (PrefixIssue__pages)
        match = re.search(r'(.+?)__pages\d+-\d+\.pdf', filename)
        if match:
            return match.group(1)

        return None

    def extract_issue_url_from_filename(self, filename):
        """FIXED: Extrage URL-ul issue-ului din numele fișierului"""
        issue_id = self.extract_issue_id_from_filename(filename)
        if not issue_id:
            return None

        if "Convietuirea" in issue_id:
            return f"https://adt.arcanum.com/ro/view/{issue_id}"
        elif "GazetaMatematica" in issue_id:
            return f"https://adt.arcanum.com/en/view/{issue_id}"
        else:
            return f"https://adt.arcanum.com/ro/view/{issue_id}"

    def get_all_pdf_segments_for_issue(self, issue_url):
        """FIXED: Scanează toate fișierele PDF pentru un issue specific"""
        issue_id = issue_url.rstrip('/').split('/')[-1]
        segments = []

        try:
            for filename in os.listdir(self.download_dir):
                if not filename.lower().endswith('.pdf'):
                    continue

                file_issue_id = self.extract_issue_id_from_filename(filename)
                if file_issue_id == issue_id:
                    # Extrage intervalul de pagini
                    match = re.search(r'__pages(\d+)-(\d+)\.pdf', filename)
                    if match:
                        start_page = int(match.group(1))
                        end_page = int(match.group(2))
                        segments.append({
                            'filename': filename,
                            'start': start_page,
                            'end': end_page,
                            'path': os.path.join(self.download_dir, filename)
                        })

        except Exception as e:
            print(f"⚠ Eroare la scanarea fișierelor pentru {issue_url}: {e}")

        # Sortează după pagina de început
        segments.sort(key=lambda x: x['start'])
        return segments

    def get_existing_pdf_segments(self, issue_url):
        """FIXED: Scanează toate segmentele existente și returnează ultima pagină"""
        segments = self.get_all_pdf_segments_for_issue(issue_url)

        if not segments:
            return 0

        # Găsește cea mai mare pagină finală
        max_page = max(seg['end'] for seg in segments)

        print(f"📊 Fișiere PDF existente pentru {issue_url}:")
        for seg in segments:
            print(f"   📄 {seg['filename']} (pagini {seg['start']}-{seg['end']})")

        return max_page

    def calculate_expected_segments(self, total_pages):
        """
        NOUĂ FUNCȚIE: Calculează toate segmentele așteptate bazat pe total_pages
        Returns: List of tuples (start_page, end_page)
        """
        if not total_pages or total_pages <= 0:
            return []

        bs = self.batch_size  # 50
        expected_segments = []

        # Primul segment: 1 până la (bs-1), adică 1-49
        first_end = min(bs - 1, total_pages)
        if first_end >= 1:
            expected_segments.append((1, first_end))

        # Segmentele următoare: bs până la final
        current_start = bs
        while current_start < total_pages:
            current_end = min(current_start + bs - 1, total_pages)
            expected_segments.append((current_start, current_end))
            current_start += bs

        return expected_segments

    def verify_physical_segments(self, issue_url, total_pages):
        """
        NOUĂ FUNCȚIE CRITICĂ: Verifică că TOATE segmentele fizice există pe disk
        Returns: (is_complete, missing_segments, existing_segments)
        """
        if not total_pages or total_pages <= 0:
            return False, [], []

        # Calculează segmentele așteptate
        expected_segments = self.calculate_expected_segments(total_pages)

        # Obține segmentele existente pe disk
        existing_segments = self.get_all_pdf_segments_for_issue(issue_url)

        # Creează set-uri pentru comparație
        expected_set = set(expected_segments)
        existing_set = set((seg['start'], seg['end']) for seg in existing_segments)

        # Identifică segmentele lipsă
        missing_set = expected_set - existing_set
        missing_segments = sorted(list(missing_set))

        is_complete = len(missing_segments) == 0

        return is_complete, missing_segments, existing_segments

    def verify_and_report_missing_segments(self, issue_url, total_pages, item=None):
        """
        NOUĂ FUNCȚIE: Verifică completitudinea și raportează segmentele lipsă
        Returns: True dacă colecția este completă, False dacă lipsesc segmente
        """
        is_complete, missing_segments, existing_segments = self.verify_physical_segments(issue_url, total_pages)

        if is_complete:
            print(f"✅ VERIFICARE FIZICĂ: Toate {len(existing_segments)} segmente există pe disk")
            return True
        else:
            print(f"❌ VERIFICARE FIZICĂ: LIPSESC {len(missing_segments)} SEGMENTE!")
            print(f"   📊 Existente: {len(existing_segments)} segmente")
            print(f"   📊 Așteptate: {len(missing_segments) + len(existing_segments)} segmente")
            print(f"   🔍 Segmente LIPSĂ:")
            for start, end in missing_segments:
                print(f"      ❌ pages{start}-{end}.pdf")

            # Dacă avem item din state.json, marchează-l ca incomplet
            if item:
                if item.get("completed_at"):
                    print(f"   🔧 CORECTEZ: Șterg completed_at pentru a relua descărcarea")
                    item["completed_at"] = ""
                if item.get("pages") == total_pages:
                    print(f"   🔧 CORECTEZ: Resetez pages la 0 pentru reluare")
                    item["pages"] = 0

            return False

    def reconstruct_all_issues_from_disk(self):
        """FIXED: Reconstruiește complet progresul din fișierele de pe disk"""
        print("🔍 SCANEZ COMPLET toate fișierele PDF de pe disk...")

        # Grupează fișierele după issue ID
        issues_on_disk = {}

        try:
            for filename in os.listdir(self.download_dir):
                if not filename.lower().endswith('.pdf'):
                    continue

                issue_id = self.extract_issue_id_from_filename(filename)
                if not issue_id:
                    continue

                # Extrage intervalul de pagini
                match = re.search(r'__pages(\d+)-(\d+)\.pdf', filename)
                if not match:
                    continue

                start_page = int(match.group(1))
                end_page = int(match.group(2))

                if issue_id not in issues_on_disk:
                    issues_on_disk[issue_id] = {
                        'segments': [],
                        'max_page': 0,
                        'url': self.extract_issue_url_from_filename(filename)
                    }

                issues_on_disk[issue_id]['segments'].append({
                    'filename': filename,
                    'start': start_page,
                    'end': end_page
                })

                if end_page > issues_on_disk[issue_id]['max_page']:
                    issues_on_disk[issue_id]['max_page'] = end_page

        except Exception as e:
            print(f"⚠ Eroare la scanarea disk-ului: {e}")
            return {}

        # Afișează rezultatele scanării
        print(f"📊 Găsite {len(issues_on_disk)} issue-uri pe disk:")
        for issue_id, data in issues_on_disk.items():
            segments_count = len(data['segments'])
            max_page = data['max_page']
            url = data['url']

            print(f"   📁 {issue_id}: {segments_count} segmente, max pagina {max_page}")
            print(f"      🔗 URL: {url}")

            # Afișează segmentele sortate
            data['segments'].sort(key=lambda x: x['start'])
            for seg in data['segments'][:3]:  # Primele 3
                print(f"      📄 {seg['filename']} ({seg['start']}-{seg['end']})")
            if segments_count > 3:
                print(f"      📄 ... și încă {segments_count - 3} segmente")

        return issues_on_disk

    def sync_json_with_disk_files(self):
        """SAFE: Îmbogățește informațiile din JSON cu cele de pe disk, ZERO pierderi + SORTARE CRONOLOGICĂ CORECTĂ"""
        print("🔄 MERGE SAFE - combinez informațiile din JSON cu cele de pe disk...")

        # PASUL 1: Scanează complet disk-ul
        issues_on_disk = self.reconstruct_all_issues_from_disk()

        # PASUL 2: PĂSTREAZĂ TOATE issue-urile existente din JSON (ZERO pierderi)
        existing_issues_by_url = {}
        for item in self.state.get("downloaded_issues", []):
            url = item.get("url", "").rstrip('/')
            existing_issues_by_url[url] = item.copy()  # DEEP COPY pentru siguranță

        print(f"📋 PĂSTREZ {len(existing_issues_by_url)} issue-uri din JSON existent")

        # PASUL 3: MERGE cu datele de pe disk (doar îmbogățește, nu șterge)
        enriched_count = 0
        new_from_disk_count = 0

        for issue_id, disk_data in issues_on_disk.items():
            url = disk_data['url']
            if not url:
                continue

            max_page = disk_data['max_page']
            segments_count = len(disk_data['segments'])
            is_complete = self.is_issue_complete_by_end_page(max_page)

            if url in existing_issues_by_url:
                # ÎMBOGĂȚEȘTE issue-ul existent (doar dacă progresul e mai mare)
                existing_issue = existing_issues_by_url[url]
                current_progress = existing_issue.get("last_successful_segment_end", 0)

                if max_page > current_progress:
                    # ÎMBOGĂȚEȘTE doar câmpurile necesare, păstrează restul
                    existing_issue["last_successful_segment_end"] = max_page
                    if not existing_issue.get("total_pages"):
                        existing_issue["total_pages"] = max_page
                    enriched_count += 1
                    print(f"🔄 ÎMBOGĂȚIT: {url} - progres {current_progress} → {max_page}")

                # Marchează ca complet DOAR dacă nu era deja marcat
                if is_complete and not existing_issue.get("completed_at"):
                    existing_issue["completed_at"] = datetime.now().isoformat(timespec="seconds")
                    existing_issue["pages"] = max_page
                    existing_issue["total_pages"] = max_page
                    print(f"✅ MARCAT ca complet: {url} ({max_page} pagini)")

            else:
                # Issue complet nou găsit doar pe disk - ADAUGĂ
                new_issue = {
                    "url": url,
                    "title": issue_id.replace("-", " ").replace("_", " "),
                    "subtitle": "",
                    "pages": max_page if is_complete else 0,
                    "completed_at": datetime.now().isoformat(timespec="seconds") if is_complete else "",
                    "last_successful_segment_end": max_page,
                    "total_pages": max_page if is_complete else None
                }
                existing_issues_by_url[url] = new_issue
                new_from_disk_count += 1
                print(f"➕ ADĂUGAT nou din disk: {url} ({max_page} pagini, {segments_count} segmente)")

        # PASUL 4: Reconstruiește lista finală (TOATE issue-urile păstrate)
        all_issues_list = list(existing_issues_by_url.values())

        # PASUL 5: SORTARE CRONOLOGICĂ CORECTĂ
        partial_issues = []
        complete_issues = []

        for issue in all_issues_list:
            is_partial = (issue.get("last_successful_segment_end", 0) > 0 and
                         not issue.get("completed_at") and
                         issue.get("total_pages") and
                         issue.get("last_successful_segment_end", 0) < issue.get("total_pages", 0))

            if is_partial:
                partial_issues.append(issue)
                print(f"🔄 Issue parțial: {issue['url']} ({issue.get('last_successful_segment_end', 0)}/{issue.get('total_pages', 0)} pagini)")
            else:
                complete_issues.append(issue)

        # SORTARE CRONOLOGICĂ PENTRU COMPLETE ISSUES
        # Sortează issue-urile complete după completed_at (cel mai recent primul)
        def sort_key_for_complete(issue):
            completed_at = issue.get("completed_at", "")
            if completed_at:
                try:
                    # Convertește la datetime pentru sortare corectă
                    return datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                except:
                    return datetime.min
            else:
                # Issue-urile fără completed_at merg la sfârșit
                return datetime.min

        # Sortează: parțiale după progres (desc), complete după data (desc - cel mai recent primul)
        partial_issues.sort(key=lambda x: x.get("last_successful_segment_end", 0), reverse=True)
        complete_issues.sort(key=sort_key_for_complete, reverse=True)  # Cel mai recent primul

        print(f"\n📊 SORTARE CRONOLOGICĂ APLICATĂ:")
        print(f"   🔄 Issue-uri parțiale: {len(partial_issues)} (sortate după progres)")

        if complete_issues:
            print(f"   ✅ Issue-uri complete: {len(complete_issues)} (sortate cronologic)")
            print(f"      📅 Cel mai recent: {complete_issues[0].get('completed_at', 'N/A')}")
            print(f"      📅 Cel mai vechi: {complete_issues[-1].get('completed_at', 'N/A')}")

            # Afișează primele 5 pentru verificare
            print(f"      🔍 Ordinea cronologică (primele 5):")
            for i, issue in enumerate(complete_issues[:5]):
                url = issue.get('url', '').split('/')[-1]
                completed_at = issue.get('completed_at', 'N/A')
                print(f"         {i+1}. {url} - {completed_at}")

        # PASUL 6: Actualizează starea SAFE (păstrează tot ce nu modificăm)
        original_count = self.state.get("count", 0)
        final_issues = partial_issues + complete_issues  # Parțiale primul, apoi complete cronologic
        actual_complete_count = len([i for i in final_issues if i.get("completed_at")])

        # PĂSTREAZĂ toate câmpurile existente, actualizează doar ce e necesar
        self.state["downloaded_issues"] = final_issues
        self.state["count"] = max(original_count, actual_complete_count)  # Nu scade niciodată

        self._save_state_safe()

        print(f"✅ MERGE COMPLET cu SORTARE CRONOLOGICĂ CORECTĂ - ZERO pierderi:")
        print(f"   📊 Total issues: {len(final_issues)} (înainte: {len(existing_issues_by_url) - new_from_disk_count})")
        print(f"   🔄 Îmbogățite: {enriched_count}")
        print(f"   ➕ Adăugate din disk: {new_from_disk_count}")
        print(f"   🔄 Parțiale: {len(partial_issues)}")
        print(f"   ✅ Complete: {len(complete_issues)}")
        print(f"   🎯 Count păstrat/actualizat: {original_count} → {self.state['count']}")

        if partial_issues:
            print("🎯 Issue-urile parțiale vor fi procesate primele!")

        print("📅 Issue-urile complete sunt acum sortate cronologic (cel mai recent primul)!")

    def process_completed_but_unfinalized_issues(self):
        """
        Procesează issues care sunt complet descărcate dar nu au fost finalizate
        (au last_successful_segment_end == total_pages dar pages=0 și completed_at="")
        """
        print("\n🔍 VERIFICARE: Caut issues complet descărcate dar nefinalizate...")

        issues_to_finalize = []

        for issue in self.state.get("downloaded_issues", []):
            url = issue.get("url", "")
            last_segment = issue.get("last_successful_segment_end", 0)
            total_pages = issue.get("total_pages", 0) or 0  # Ensure it's never None
            completed_at = issue.get("completed_at", "")
            pages = issue.get("pages", 0)
            title = issue.get("title", "")
            subtitle = issue.get("subtitle", "")

            # Verifică dacă e complet descărcat dar nefinalizat
            if (last_segment > 0 and
                total_pages is not None and total_pages > 0 and
                last_segment >= total_pages and
                not completed_at and
                pages == 0):

                issues_to_finalize.append({
                    'url': url,
                    'title': title,
                    'subtitle': subtitle,
                    'last_segment': last_segment,
                    'total_pages': total_pages
                })

                print(f"\n📋 GĂSIT issue nefinalizat: {url}")
                print(f"   📊 Progres: {last_segment}/{total_pages} (100% descărcat)")
                print(f"   ❌ Status: pages=0, completed_at=empty")

        if not issues_to_finalize:
            print("✅ Nu am găsit issues nefinalizate - toate sunt OK!")
            return

        print(f"\n🎯 FINALIZARE AUTOMATĂ: {len(issues_to_finalize)} issues vor fi procesate...")

        for issue_data in issues_to_finalize:
            url = issue_data['url']
            title = issue_data['title']
            subtitle = issue_data['subtitle']
            total_pages = issue_data['total_pages']

            try:
                print(f"\n{'='*60}")
                print(f"🔄 PROCESEZ: {url}")
                print(f"{'='*60}")

                # VERIFICARE CRITICĂ: Verifică că TOATE segmentele fizice există pe disk
                print(f"🔍 VERIFICARE FIZICĂ: Verific că toate segmentele există pe disk...")
                is_physically_complete = self.verify_and_report_missing_segments(url, total_pages)

                if not is_physically_complete:
                    print(f"⚠ SKIP: Colecția NU este completă pe disk - lipsesc segmente!")
                    print(f"   🔄 Issue-ul va fi reluat pentru a descărca segmentele lipsă")

                    # Găsește issue-ul în state și marchează-l ca incomplet
                    for state_issue in self.state.get("downloaded_issues", []):
                        if state_issue.get("url") == url:
                            state_issue["completed_at"] = ""
                            state_issue["pages"] = 0
                            state_issue["last_successful_segment_end"] = 0
                            self._save_state_safe()
                            print(f"   ✅ Issue resetat în state.json pentru reluare")
                            break
                    continue

                # Verifică din nou pe disk că toate fișierele sunt prezente
                final_segments = self.get_all_pdf_segments_for_issue(url)

                if not final_segments:
                    print(f"⚠ SKIP: Nu am găsit fișiere PDF pe disk pentru {url}")
                    continue

                # Calculează progresul real
                real_final_page = max(seg['end'] for seg in final_segments)
                real_completion_percent = (real_final_page / total_pages) * 100

                print(f"📊 Verificare disk: {real_final_page}/{total_pages} ({real_completion_percent:.1f}%)")

                if real_completion_percent < 95:
                    print(f"⚠ SKIP: Progresul real < 95% - nu finalizez")
                    continue

                # PASUL 1: Marchează ca terminat în JSON
                print(f"📝 Marchez ca terminat în JSON...")
                self.mark_issue_done(url, real_final_page, title=title, subtitle=subtitle, total_pages=total_pages)
                print(f"✅ Marcat ca terminat în JSON")

                # Așteaptă salvarea JSON
                time.sleep(2)

                # PASUL 2: Procesează PDF-urile (backup + merge + mutare)
                print(f"📦 Procesez PDF-urile (backup + merge + mutare)...")
                self.copy_and_combine_issue_pdfs(url, title or url.split('/')[-1])
                print(f"✅ PDF-urile procesate cu succes!")

                # Așteaptă finalizarea procesării
                time.sleep(3)

                print(f"{'='*60}")
                print(f"🎉 FINALIZAT CU SUCCES: {url}")
                print(f"{'='*60}\n")

            except Exception as e:
                print(f"❌ EROARE la finalizarea {url}: {e}")
                import traceback
                traceback.print_exc()
                continue

        print(f"\n✅ FINALIZARE AUTOMATĂ COMPLETĂ: {len(issues_to_finalize)} issues procesate")

    def cleanup_duplicate_issues(self):
        """NOUĂ FUNCȚIE: Elimină dublurile din state.json"""
        print("🧹 CURĂȚARE: Verific și elimin dublurile din state.json...")

        issues = self.state.get("downloaded_issues", [])
        if not issues:
            return

        # Grupează după URL normalizat
        url_groups = {}
        for i, item in enumerate(issues):
            url = item.get("url", "").rstrip('/').lower()
            if not url:
                continue

            if url not in url_groups:
                url_groups[url] = []
            url_groups[url].append((i, item))

        # Găsește și rezolvă dublurile
        duplicates_found = 0
        clean_issues = []
        processed_urls = set()

        for original_url, group in url_groups.items():
            if len(group) > 1:
                duplicates_found += 1
                print(f"🔍 DUBLURĂ găsită pentru {original_url}: {len(group)} intrări")

                # Găsește cea mai completă versiune
                best_item = None
                best_score = -1

                for idx, item in group:
                    score = 0
                    if item.get("completed_at"): score += 100
                    if item.get("total_pages"): score += 50
                    if item.get("title"): score += 10
                    if item.get("last_successful_segment_end", 0) > 0: score += 20

                    print(f"   📊 Index {idx}: score {score}, completed: {bool(item.get('completed_at'))}")

                    if score > best_score:
                        best_score = score
                        best_item = item

                print(f"   ✅ Păstrez cea mai completă versiune (score: {best_score})")
                clean_issues.append(best_item)
            else:
                # Nu e dublură, păstrează-l
                clean_issues.append(group[0][1])

            processed_urls.add(original_url)

        if duplicates_found > 0:
            print(f"🧹 ELIMINAT {duplicates_found} dubluri din {len(issues)} issues")
            print(f"📊 Rămas cu {len(clean_issues)} issues unice")

            self.state["downloaded_issues"] = clean_issues
            self._save_state_safe()
        else:
            print("✅ Nu am găsit dubluri în state.json")

    def is_issue_really_complete(self, item, verify_physical=True):
        """
        FIXED: Nu verifica fizic issue-urile deja procesate complet
        """
        completed_at = item.get("completed_at")
        last_segment = item.get("last_successful_segment_end", 0)
        total_pages = item.get("total_pages")
        pages = item.get("pages", 0)
        url = item.get("url", "")

        # VERIFICARE 1: State.json verificare standard
        json_complete = (
            completed_at and
            total_pages and
            total_pages > 0 and
            last_segment >= total_pages and
            pages > 0
        )

        if not json_complete:
            return False

        # ✅ FIX CRUCIAL: Dacă pages == total_pages, issue-ul e PROCESAT!
        # PDF-ul final există, segmentele au fost șterse
        # NU mai verificăm fizic pe disk!
        if pages == total_pages:
            return True

        # VERIFICARE 2: Verificare FIZICĂ - DOAR pentru issues parțiale
        if verify_physical and total_pages and total_pages > 0:
            is_physically_complete, missing_segments, _ = self.verify_physical_segments(url, total_pages)

            if not is_physically_complete:
                print(f"⚠️ ATENȚIE: {url}")
                print(f"   ✅ În state.json: marcat COMPLET")
                print(f"   ❌ Pe disk: LIPSESC {len(missing_segments)} segmente!")
                return False

        return True

    def fix_incorrectly_marked_complete_issues(self):
        """
        FIXED: Nu resetează issue-urile deja procesate complet
        """
        print("🔧 CORECTEZ issue-urile marcate GREȘIT ca complete...")

        # ⚡ VERIFICARE PRIORITATE: Există issues incomplete de procesat?
        incomplete_issues_exist = False
        for item in self.state.get("downloaded_issues", []):
            total_pages_check = item.get("total_pages", 0) or 0  # Ensure it's never None
            if (item.get("pages", 0) == 0 and
                not item.get("completed_at") and
                total_pages_check > 0):
                incomplete_issues_exist = True
                break

        if incomplete_issues_exist:
            print("⚡ PRIORITATE: Există issues incomplete de procesat")
            print("   ⏭️ SKIP verificarea fizică a issues complete (CAZUL 3)")
            print("   ✅ Focusez pe finalizarea issues incomplete mai întâi!")

        fixes_applied = 0

        for item in self.state.get("downloaded_issues", []):
            completed_at = item.get("completed_at")
            last_segment = item.get("last_successful_segment_end", 0)
            total_pages = item.get("total_pages")
            pages = item.get("pages", 0)
            url = item.get("url", "")

            # ✅ FIX CRUCIAL: SKIP issue-uri PROCESATE complet
            # Dacă pages == total_pages, PDF-ul final există, segmentele au fost șterse
            if completed_at and pages > 0 and total_pages and pages == total_pages:
                # Issue PROCESAT complet - NU verificăm fizic!
                continue

            # CAZUL 1 & 2: Verificare state.json standard
            if (completed_at and
                pages == 0 and
                total_pages and
                last_segment < total_pages):

                print(f"🚨 CORECTEZ issue marcat GREȘIT ca complet: {url}")
                item["completed_at"] = ""
                item["pages"] = 0
                fixes_applied += 1
                continue

            # CAZUL 3: Verificare FIZICĂ - DOAR pentru issues NEPROCESSATE
            # (completed_at există dar pages == 0 sau pages < total_pages)
            if (completed_at and
                total_pages and
                total_pages > 0 and
                pages < total_pages and  # ✅ NU verifică dacă pages == total_pages
                not incomplete_issues_exist):

                is_physically_complete = self.verify_and_report_missing_segments(url, total_pages, item)

                if not is_physically_complete:
                    print(f"🚨 CORECTEZ issue marcat complet în JSON dar INCOMPLET pe disk: {url}")
                    item["completed_at"] = ""
                    item["pages"] = 0
                    fixes_applied += 1

        if fixes_applied > 0:
            print(f"🔧 CORECTAT {fixes_applied} issue-uri marcate greșit ca complete")
            self._save_state_safe()
            self._save_skip_urls()
        else:
            print("✅ Nu am găsit issue-uri marcate greșit ca complete")

        return fixes_applied

    def fix_progress_based_on_disk(self):
        """NOUĂ FUNCȚIE: Corectează last_successful_segment_end bazat pe ce există EFECTIV pe disk
           PROTECTED: Protecție împotriva resetărilor masive dacă disk-ul e gol
        """
        print("🔍 SCANEZ disk-ul și corectez progresul în JSON...")

        # 🛡️ PROTECȚIE: Verifică dacă disk-ul are CEVA fișiere PDF
        # Dacă disk-ul e complet gol sau aproape gol, NU reseta nimic!
        try:
            pdf_files_on_disk = [f for f in os.listdir(self.download_dir) if f.lower().endswith('.pdf')]
            pdf_count = len(pdf_files_on_disk)

            if pdf_count < 10:
                print(f"\n{'='*70}")
                print(f"🚨 ATENȚIE: PROTECȚIE DISK GOL ACTIVATĂ!")
                print(f"{'='*70}")
                print(f"⚠️  Disk-ul are doar {pdf_count} fișiere PDF.")
                print(f"   Acesta pare a fi prea puțin comparativ cu issues din state.json.")
                print(f"   POATE fișierele au fost mutate/șterse temporar?")
                print(f"\n🛡️  PROTECȚIE: NU voi reseta progresul pentru a preveni pierderea datelor!")
                print(f"   Verifică dacă fișierele PDF există pe disk și încearcă din nou.")
                print(f"{'='*70}\n")
                return  # NU continua!

        except Exception as e:
            print(f"⚠️  Nu am putut verifica disk-ul: {e}")
            print(f"   Pentru siguranță, NU voi modifica progresul.")
            return

        corrections = 0
        resets_to_zero = 0  # Contorizează câte issues vor fi resetate la 0

        for item in self.state.get("downloaded_issues", []):
            url = item.get("url", "")
            if not url:
                continue

            # Obține progresul din JSON
            json_progress = item.get("last_successful_segment_end", 0)
            total_pages = item.get("total_pages") or 0
            completed_at = item.get("completed_at", "")
            pages = item.get("pages", 0)

            # ⭐ IMPORTANT: SKIP issue-urile deja finalizate complet!
            # După procesare, segmentele individuale sunt șterse/mutate, rămâne doar PDF-ul final
            # DAR: Verificăm dacă PDF-ul final combinat există efectiv pe disk!
            if completed_at and pages > 0 and pages == total_pages:
                # Verifică dacă există PDF-ul FINAL combinat (nu segmente)
                try:
                    # Extrage ID-ul din URL (ex: Farmacia_1972-1673578372)
                    normalized_url = self._normalize_url(url)
                    issue_identifier = None

                    # Caută fișiere care NU sunt segmente (fără __pages în nume)
                    for filename in os.listdir(self.download_dir):
                        if filename.lower().endswith('.pdf') and '__pages' not in filename:
                            # Acest e un PDF final combinat
                            if normalized_url.lower() in filename.lower():
                                issue_identifier = filename
                                break

                    if issue_identifier:
                        # Există PDF-ul final combinat - Issue complet și procesat - NU îl atingem!
                        continue
                    else:
                        # NU există PDF final, doar segmente - TREBUIE verificat!
                        print(f"\n⚠️ ATENȚIE: {url} marcat complet dar lipsește PDF-ul final!")
                        print(f"   Verific segmentele individuale...")
                except Exception as e:
                    # Eroare la verificare - mai bine verificăm segmentele
                    pass

            # Scanează disk-ul pentru acest issue (doar pentru parțiale/incomplete)
            actual_segments = self.get_all_pdf_segments_for_issue(url)

            if actual_segments:
                # === CALCUL CORECT: Găsește progresul REAL CONSECUTIV de pe disk ===
                # Nu folosim max(seg['end']), ci găsim ultimul segment consecutiv de la pagina 1

                actual_segments.sort(key=lambda x: x['start'])

                # Calculează segmentele așteptate
                bs = self.batch_size  # 50
                all_segments_expected = []

                # Primul segment: 1-49
                if total_pages > 0:
                    first_end = min(bs - 1, total_pages)
                    if first_end >= 1:
                        all_segments_expected.append((1, first_end))

                    # Segmentele următoare: 50-99, 100-149, etc.
                    current = bs
                    while current <= total_pages:
                        end = min(current + bs - 1, total_pages)
                        all_segments_expected.append((current, end))
                        current += bs

                # Găsește ultimul segment consecutiv de la început
                real_progress = 0
                for expected_start, expected_end in all_segments_expected:
                    found = False
                    for disk_seg in actual_segments:
                        if disk_seg['start'] <= expected_start and disk_seg['end'] >= expected_end:
                            found = True
                            real_progress = expected_end  # Actualizează progresul
                            break

                    # Dacă lipsește un segment, OPREȘTE
                    if not found:
                        break

                # Dacă progresul din JSON diferă de cel real
                if json_progress != real_progress:
                    print(f"\n⚠️ DISCREPANȚĂ pentru {url}:")
                    print(f"   JSON zicea: {json_progress} pagini")
                    print(f"   Disk-ul arată CONSECUTIV: {real_progress} pagini")
                    print(f"   Segmente pe disk: {len(actual_segments)}")

                    # Afișează segmentele găsite
                    for seg in sorted(actual_segments, key=lambda x: x['start'])[:5]:
                        print(f"      📄 {seg['filename']} ({seg['start']}-{seg['end']})")

                    # CORECTEAZĂ cu progresul real CONSECUTIV
                    item["last_successful_segment_end"] = real_progress

                    # Dacă era marcat ca terminat dar nu e complet, demarchez
                    if completed_at and real_progress < total_pages:
                        print(f"   🔄 DEMARCHEZ ca terminat - progres incomplet!")
                        item["completed_at"] = ""
                        item["pages"] = 0

                    corrections += 1
                    print(f"   ✅ CORECTAT: {json_progress} → {real_progress} (CONSECUTIV)")
            elif json_progress > 0 and not completed_at:
                # JSON arată progres dar disk-ul e gol - DAR DOAR pentru issue-uri NEFINALIZATE!
                print(f"\n🚨 PROBLEMĂ GRAVĂ pentru {url}:")
                print(f"   JSON arată {json_progress} pagini, dar disk-ul e GOL!")
                print(f"   🔄 RESETEZ progresul la 0")

                item["last_successful_segment_end"] = 0
                item["completed_at"] = ""
                item["pages"] = 0

                corrections += 1
                resets_to_zero += 1

        # 🛡️ PROTECȚIE FINALĂ: Nu permite resetări masive
        if resets_to_zero > 20:
            print(f"\n{'='*70}")
            print(f"🚨 ALERTĂ CRITICĂ: PROTECȚIE RESETĂRI MASIVE ACTIVATĂ!")
            print(f"{'='*70}")
            print(f"❌ Funcția fix_progress_based_on_disk() vrea să reseteze {resets_to_zero} issues la 0!")
            print(f"   Acesta pare a fi un număr suspect de mare.")
            print(f"   POATE fișierele PDF au fost mutate temporar sau disk-ul e inaccesibil?")
            print(f"\n🛡️  PROTECȚIE: NU voi salva aceste modificări pentru a preveni pierderea datelor!")
            print(f"   Verifică că fișierele PDF există pe disk și încearcă din nou.")
            print(f"{'='*70}\n")
            return  # NU salva!

        if corrections > 0:
            print(f"\n✅ CORECTAT progresul pentru {corrections} issues")
            if resets_to_zero > 0:
                print(f"   ⚠️  Dintre care {resets_to_zero} au fost resetate la 0 (disk gol)")
            self._save_state_safe()
            self._save_skip_urls()
        else:
            print("✅ Progresul din JSON corespunde cu disk-ul")

    def get_pending_partial_issues(self):
        """IMPROVED: Găsește TOATE issue-urile parțiale din TOATE colecțiile"""
        pending_partials = []

        for item in self.state.get("downloaded_issues", []):
            url = item.get("url", "").rstrip('/')
            last_segment = item.get("last_successful_segment_end", 0)
            total_pages = item.get("total_pages")
            completed_at = item.get("completed_at", "")
            pages = item.get("pages", 0)

            # Skip URL-urile complet descărcate
            if url in self.dynamic_skip_urls:
                continue

            # CONDIȚIE PRECISĂ pentru parțiale
            is_partial = (
                last_segment > 0 and  # Are progres
                total_pages and total_pages > 0 and  # Are total valid
                last_segment < total_pages and  # Nu e complet
                not completed_at and  # Nu e marcat terminat
                pages == 0  # NU e finalizat (pages = 0)
            )

            if is_partial:
                completion_percent = (last_segment / total_pages) * 100
                item_with_priority = item.copy()
                item_with_priority['completion_percent'] = completion_percent
                item_with_priority['remaining_pages'] = total_pages - last_segment

                pending_partials.append(item_with_priority)

                print(f"🔄 PARȚIAL: {url}")
                print(f"   Progres: {last_segment}/{total_pages} ({completion_percent:.1f}%)")
                print(f"   Rămân: {total_pages - last_segment} pagini")

        # SORTARE: prioritizează după completitudine (aproape finalizate = prioritate)
        pending_partials.sort(key=lambda x: x['completion_percent'], reverse=True)

        if pending_partials:
            print(f"\n📋 ORDINEA DE PROCESARE ({len(pending_partials)} parțiale):")
            for i, item in enumerate(pending_partials[:10]):  # Primele 10
                url_short = item['url'].split('/')[-1]
                percent = item['completion_percent']
                remaining = item['remaining_pages']
                print(f"   {i+1}. {url_short}: {percent:.1f}% complet, {remaining} pagini")

            if len(pending_partials) > 10:
                print(f"   ... și încă {len(pending_partials) - 10} parțiale")

        return pending_partials

    def _normalize_downloaded_issues(self, raw):
        normalized = []
        for item in raw:
            if isinstance(item, str):
                normalized.append({
                    "url": item.rstrip('/'),
                    "title": "",
                    "subtitle": "",
                    "pages": 0,
                    "completed_at": "",
                    "last_successful_segment_end": 0,
                    "total_pages": None
                })
            elif isinstance(item, dict):
                normalized.append({
                    "url": item.get("url", "").rstrip('/'),
                    "title": item.get("title", ""),
                    "subtitle": item.get("subtitle", ""),
                    "pages": item.get("pages", 0),
                    "completed_at": item.get("completed_at", ""),
                    "last_successful_segment_end": item.get("last_successful_segment_end", 0),
                    "total_pages": item.get("total_pages")
                })
        return normalized

    def _repair_json_missing_comma(self, file_path):
        """
        Repară JSON-ul când lipsește virgula după câmpul 'pages'
        Pattern: "pages": <număr>\n      "completed_at" → "pages": <număr>,\n      "completed_at"
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Detectează pattern-ul: "pages": număr urmat direct de "completed_at" (fără virgulă)
            import re
            pattern = r'("pages"\s*:\s*\d+)\s*\n(\s*"completed_at")'

            # Verifică dacă există problema
            if re.search(pattern, content):
                print(f"🔧 REPARARE JSON: Detectată virgulă lipsă după 'pages' în {file_path}")

                # Adaugă virgula lipsă
                fixed_content = re.sub(pattern, r'\1,\n\2', content)

                # Salvează fișierul reparat
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(fixed_content)

                print(f"✅ JSON reparat automat: virgulă adăugată după 'pages'")
                return True

            return False

        except Exception as e:
            print(f"⚠ Eroare la repararea JSON: {e}")
            return False

    def _load_state(self):
        """ULTRA SAFE: Nu șterge NICIODATĂ datele existente"""
        today = datetime.now().strftime("%Y-%m-%d")

        if os.path.exists(self.state_path):
            try:
                # REPARĂ JSON-ul dacă are virgulă lipsă după 'pages'
                self._repair_json_missing_comma(self.state_path)

                with open(self.state_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    loaded = self._decode_unicode_escapes(loaded)

                # PĂSTREAZĂ TOATE issue-urile existente - ZERO ȘTERS
                existing_issues = self._normalize_downloaded_issues(loaded.get("downloaded_issues", []))

                print(f"📋 ÎNCĂRCAT {len(existing_issues)} issue-uri din state.json")

                # Găsește issue-urile parțiale
                partial_issues = []
                for issue in existing_issues:
                    last_segment = issue.get("last_successful_segment_end", 0)
                    total_pages = issue.get("total_pages")
                    completed_at = issue.get("completed_at", "")

                    if (last_segment > 0 and not completed_at and total_pages and last_segment < total_pages):
                        partial_issues.append(issue)
                        print(f"🔄 PARȚIAL: {issue['url']} - {last_segment}/{total_pages} pagini")

                complete_count = len([i for i in existing_issues if i.get("completed_at")])

                # PĂSTREAZĂ TOT - doar actualizează data
                self.state = {
                    "date": today,
                    "count": loaded.get("count", complete_count),
                    "downloaded_issues": existing_issues,  # TOATE PĂSTRATE
                    "pages_downloaded": loaded.get("pages_downloaded", 0),
                    "recent_links": loaded.get("recent_links", []),
                    "daily_limit_hit": False,
                    "main_collection_completed": loaded.get("main_collection_completed", False),
                    "current_additional_collection_index": loaded.get("current_additional_collection_index", 0)
                }

                print(f"✅ PĂSTRAT TOT: {complete_count} complete, {len(partial_issues)} parțiale")

            except Exception as e:
                print(f"❌ JSON CORRUPT: {e}")
                print(f"🛠️ RECUPEREZ din backup sau disk...")

                # Încearcă backup
                backup_path = self.state_path + ".backup"
                if os.path.exists(backup_path):
                    print(f"🔄 Restabilesc din backup...")

                    # REPARĂ backup-ul înainte de a-l copia
                    print(f"🔧 Verific și repar backup-ul dacă e necesar...")
                    self._repair_json_missing_comma(backup_path)

                    shutil.copy2(backup_path, self.state_path)
                    return self._load_state()  # Recursiv cu backup

                # Altfel începe gol dar SCANEAZĂ DISK-UL
                print(f"🔍 SCANEZ DISK-UL pentru recuperare...")
                self.state = {
                    "date": today,
                    "count": 0,
                    "downloaded_issues": [],
                    "pages_downloaded": 0,
                    "recent_links": [],
                    "daily_limit_hit": False,
                    "main_collection_completed": False,
                    "current_additional_collection_index": 0
                }
        else:
            print(f"📄 Nu există state.json")
            self.state = {
                "date": today,
                "count": 0,
                "downloaded_issues": [],
                "pages_downloaded": 0,
                "recent_links": [],
                "daily_limit_hit": False,
                "main_collection_completed": False,
                "current_additional_collection_index": 0
            }

        self._save_state()

    def _create_daily_backup(self):
        """Creează backup zilnic al state.json (o singură dată pe zi)"""
        if not os.path.exists(self.state_path):
            print("📄 Nu există state.json pentru backup")
            return

        today = datetime.now().strftime("%Y-%m-%d")
        backup_path = self.state_path + ".backup"

        # Verifică dacă backup-ul există și dacă e din ziua de azi
        backup_is_today = False
        if os.path.exists(backup_path):
            backup_time = datetime.fromtimestamp(os.path.getmtime(backup_path))
            backup_date = backup_time.strftime("%Y-%m-%d")
            if backup_date == today:
                backup_is_today = True
                print(f"✅ Backup zilnic deja existent pentru {today}")

        # Creează backup doar dacă nu există sau e din altă zi
        if not backup_is_today:
            try:
                shutil.copy2(self.state_path, backup_path)
                print(f"💾 BACKUP ZILNIC creat: {backup_path}")
                print(f"📅 Data backup: {today}")
            except Exception as e:
                print(f"⚠ Nu am putut crea backup zilnic: {e}")

    def _log_completed_issue(self, issue_url, title, subtitle, pages_count):
        """Înregistrează în log zilnic issue-urile finalizate"""
        today = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now().strftime("%H:%M:%S")
        log_file = os.path.join(self.daily_log_dir, f"completed_{today}.log")

        try:
            # Verifică dacă issue-ul e deja în log-ul de azi
            issue_already_logged = False
            if os.path.exists(log_file):
                with open(log_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    if issue_url in content:
                        issue_already_logged = True

            if not issue_already_logged:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"\n{'='*80}\n")
                    f.write(f"⏰ Ora finalizării: {current_time}\n")
                    f.write(f"📋 URL: {issue_url}\n")
                    f.write(f"📖 Titlu: {title}\n")
                    if subtitle:
                        f.write(f"📑 Subtitlu: {subtitle}\n")
                    f.write(f"📄 Pagini: {pages_count}\n")
                    f.write(f"{'='*80}\n")

                print(f"📝 Log zilnic actualizat: {log_file}")
        except Exception as e:
            print(f"⚠ Nu am putut scrie în log zilnic: {e}")

    def _log_state_changes(self, old_state, new_state, caller_function="Unknown"):
        """Loghează modificările făcute în state.json pentru debugging"""
        try:
            log_dir = os.path.join(os.path.dirname(self.state_path), "State_Change_Logs")
            os.makedirs(log_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = os.path.join(log_dir, f"state_changes_{timestamp}.log")

            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"{'='*70}\n")
                f.write(f"STATE.JSON CHANGE LOG\n")
                f.write(f"{'='*70}\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Called by: {caller_function}\n")
                f.write(f"{'='*70}\n\n")

                # Compară numărul total de issues
                old_count = len(old_state.get("downloaded_issues", []))
                new_count = len(new_state.get("downloaded_issues", []))
                f.write(f"Total issues: {old_count} → {new_count}\n\n")

                # Detectează modificări masive suspecte (ALERTĂ!)
                pages_reset_count = 0
                completed_at_reset_count = 0

                old_issues = {item.get("url"): item for item in old_state.get("downloaded_issues", [])}
                new_issues = {item.get("url"): item for item in new_state.get("downloaded_issues", [])}

                for url, old_item in old_issues.items():
                    if url in new_issues:
                        new_item = new_issues[url]
                        old_pages = old_item.get("pages", 0)
                        new_pages = new_item.get("pages", 0)
                        old_completed = old_item.get("completed_at", "")
                        new_completed = new_item.get("completed_at", "")

                        # Detectează resetări
                        if old_pages > 0 and new_pages == 0:
                            pages_reset_count += 1
                        if old_completed and not new_completed:
                            completed_at_reset_count += 1

                # ALERTĂ MODIFICĂRI MASIVE
                if pages_reset_count > 10 or completed_at_reset_count > 10:
                    f.write(f"🚨 ALERTĂ: MODIFICARE MASIVĂ DETECTATĂ!\n")
                    f.write(f"   - Issues cu pages resetat la 0: {pages_reset_count}\n")
                    f.write(f"   - Issues cu completed_at șters: {completed_at_reset_count}\n")
                    f.write(f"   - Funcție responsabilă: {caller_function}\n")
                    f.write(f"{'='*70}\n\n")

                # Înregistrează modificările detaliate
                f.write(f"MODIFICĂRI DETECTATE:\n")
                f.write(f"{'='*70}\n\n")

                changes_found = False
                for url, old_item in old_issues.items():
                    if url in new_issues:
                        new_item = new_issues[url]
                        changes = []

                        # Verifică fiecare câmp important
                        for key in ["pages", "completed_at", "last_successful_segment_end", "total_pages"]:
                            old_val = old_item.get(key)
                            new_val = new_item.get(key)
                            if old_val != new_val:
                                changes.append(f"  {key}: {old_val} → {new_val}")

                        if changes:
                            changes_found = True
                            f.write(f"URL: {url}\n")
                            f.write(f"  Title: {old_item.get('title', 'N/A')}\n")
                            for change in changes:
                                f.write(f"{change}\n")
                            f.write(f"\n")

                if not changes_found:
                    f.write("Nu s-au detectat modificări în issues existente.\n")

                # Înregistrează issues noi
                new_urls = set(new_issues.keys()) - set(old_issues.keys())
                if new_urls:
                    f.write(f"\n{'='*70}\n")
                    f.write(f"ISSUES NOI ADĂUGATE: {len(new_urls)}\n")
                    f.write(f"{'='*70}\n\n")
                    for url in new_urls:
                        item = new_issues[url]
                        f.write(f"URL: {url}\n")
                        f.write(f"  Title: {item.get('title', 'N/A')}\n")
                        f.write(f"  Pages: {item.get('pages', 0)}\n")
                        f.write(f"  Progress: {item.get('last_successful_segment_end', 0)}/{item.get('total_pages', 0)}\n\n")

            # Păstrează doar ultimele 50 de log-uri
            log_files = sorted(os.listdir(log_dir))
            if len(log_files) > 50:
                for old_log in log_files[:-50]:
                    os.remove(os.path.join(log_dir, old_log))

        except Exception as e:
            print(f"⚠ Nu am putut crea log pentru modificări: {e}")

    def _save_state_safe(self):
        """SAFE: Salvează starea cu backup timestamped și logging detaliat"""
        try:
            # PASUL 1: Citește starea VECHE pentru comparație
            old_state = {}
            if os.path.exists(self.state_path):
                try:
                    with open(self.state_path, "r", encoding="utf-8") as f:
                        old_state = json.load(f)
                except:
                    old_state = {}

            # PASUL 2: PROTECȚIE ÎMPOTRIVA RESETĂRILOR MASIVE
            # Verifică dacă se încearcă resetarea masivă a pages la 0
            if old_state.get("downloaded_issues"):
                old_completed_count = sum(1 for item in old_state.get("downloaded_issues", [])
                                         if item.get("pages", 0) > 0 and item.get("completed_at"))
                new_completed_count = sum(1 for item in self.state.get("downloaded_issues", [])
                                         if item.get("pages", 0) > 0 and item.get("completed_at"))

                # Dacă se pierd mai mult de 10 issues complete, STOP!
                if old_completed_count - new_completed_count > 10:
                    print(f"\n{'='*70}")
                    print(f"🚨 ALERTĂ CRITICĂ: PROTECȚIE ANTI-CORUPȚIE ACTIVATĂ!")
                    print(f"{'='*70}")
                    print(f"❌ Încercare de resetare masivă detectată:")
                    print(f"   Issues complete ÎNAINTE: {old_completed_count}")
                    print(f"   Issues complete DUPĂ: {new_completed_count}")
                    print(f"   Issues PIERDUTE: {old_completed_count - new_completed_count}")
                    print(f"\n⚠️  SALVAREA A FOST BLOCATĂ pentru a preveni corupția datelor!")
                    print(f"   State.json NU a fost modificat.")
                    print(f"{'='*70}\n")
                    return  # NU salva!

            # PASUL 3: Creează backup timestamped ÎNAINTE de salvare
            backup_dir = os.path.join(os.path.dirname(self.state_path), "State_Backups")
            os.makedirs(backup_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"state_{timestamp}.json")

            if os.path.exists(self.state_path):
                shutil.copy2(self.state_path, backup_path)

            # Păstrează doar ultimele 100 de backup-uri
            backup_files = sorted(os.listdir(backup_dir))
            if len(backup_files) > 100:
                for old_backup in backup_files[:-100]:
                    os.remove(os.path.join(backup_dir, old_backup))

            # PASUL 4: Loghează modificările (cu stack trace pentru debugging)
            import inspect
            caller_function = "Unknown"
            try:
                stack = inspect.stack()
                if len(stack) > 2:
                    caller_function = f"{stack[2].function} (line {stack[2].lineno})"
            except:
                pass

            self._log_state_changes(old_state, self.state, caller_function)

            # PASUL 5: Salvează starea nouă
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"⚠ Nu am putut salva state-ul: {e}")
            import traceback
            traceback.print_exc()

            # Încearcă să restabilească din backup zilnic
            backup_path = self.state_path + ".backup"
            if os.path.exists(backup_path):
                print(f"🔄 Încerc să restabilesc din backup...")
                try:
                    shutil.copy2(backup_path, self.state_path)
                    print(f"✅ State restabilit din backup")
                except:
                    print(f"❌ Nu am putut restabili din backup")

    def _save_state(self):
        """WRAPPER: Folosește salvarea safe"""
        self._save_state_safe()

    def fix_existing_json(self):
        """Funcție temporară pentru a repara caracterele din JSON existent"""
        if os.path.exists(self.state_path):
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            data = self._decode_unicode_escapes(data)

            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            print("✅ JSON reparat cu caractere românești")

    def remaining_quota(self):
        return 99999  # Dezactivează limita artificială

    def _update_partial_issue_progress(self, issue_url, last_successful_segment_end, total_pages=None, title=None, subtitle=None):
        """FIXED: Previne dublurile - verifică și după title dacă URL-ul nu se potrivește"""
        normalized = issue_url.rstrip('/')
        updated = False

        # STEP 1: Caută după URL exact
        for i, item in enumerate(self.state.setdefault("downloaded_issues", [])):
            if item["url"] == normalized:
                # ACTUALIZEAZĂ issue-ul existent
                if last_successful_segment_end > item.get("last_successful_segment_end", 0):
                    item["last_successful_segment_end"] = last_successful_segment_end

                if total_pages is not None and not item.get("total_pages"):
                    item["total_pages"] = total_pages

                if title and not item.get("title"):
                    item["title"] = title

                if subtitle and not item.get("subtitle"):
                    item["subtitle"] = subtitle

                # Mută la început pentru prioritate
                updated_item = self.state["downloaded_issues"].pop(i)
                self.state["downloaded_issues"].insert(0, updated_item)
                updated = True
                print(f"🔄 ACTUALIZAT progres pentru: {normalized} → {last_successful_segment_end} pagini")
                break

        # STEP 2: Dacă nu găsești după URL, caută după title (prevenire dubluri)
        if not updated and title:
            for i, item in enumerate(self.state["downloaded_issues"]):
                if item.get("title") == title and not item["url"].startswith("http"):
                    # GĂSIT dublu cu title ca URL - șterge-l!
                    print(f"🗑️ ȘTERG DUBLU GREȘIT: {item['url']} (era title în loc de URL)")
                    self.state["downloaded_issues"].pop(i)
                    break

        # STEP 3: Doar dacă nu există deloc, creează nou
        if not updated:
            # VALIDEAZĂ că URL-ul e corect
            if not normalized.startswith("https://"):
                print(f"❌ URL INVALID: {normalized} - nu creez issue nou!")
                return

            new_issue = {
                "url": normalized,
                "title": title or "",
                "subtitle": subtitle or "",
                "pages": 0,
                "completed_at": "",
                "last_successful_segment_end": last_successful_segment_end,
                "total_pages": total_pages
            }
            self.state["downloaded_issues"].insert(0, new_issue)
            print(f"➕ ADĂUGAT issue nou în progres: {normalized}")

        self._save_state_safe()
        print(f"💾 Progres salvat SAFE: {normalized} - pagini {last_successful_segment_end}/{total_pages or '?'}")

    def mark_issue_done(self, issue_url, pages_count, title=None, subtitle=None, total_pages=None):
        """ULTRA SAFE: Verificări stricte înainte de a marca ca terminat + DETECTARE MAGHIARĂ"""
        normalized = issue_url.rstrip('/')
        now_iso = datetime.now().isoformat(timespec="seconds")

        print(f"🔒 VERIFICĂRI ULTRA SAFE pentru marcarea ca terminat: {normalized}")

        # VERIFICARE 0: Detectează posibila problemă cu maghiara
        if total_pages == 1 and pages_count == 1:
            print(f"🚨 ALERTĂ CRITICĂ: total_pages=1 și pages_count=1")
            print(f"🔍 Posibilă problemă de detectare pentru interfața maghiară!")
            print(f"🛡️ REFUZ să marchez ca terminat - probabil e o eroare!")

            # Încearcă să re-detecteze numărul corect de pagini
            print(f"🔄 Încerc re-detectarea numărului total de pagini...")
            try:
                if self.driver and self.current_issue_url == normalized:
                    real_total = self.get_total_pages(max_attempts=3)
                    if real_total > 1:
                        print(f"✅ RE-DETECTAT: {real_total} pagini în loc de 1!")
                        # Marchează ca parțial cu progresul real
                        self._update_partial_issue_progress(
                            normalized, pages_count, total_pages=real_total, title=title, subtitle=subtitle
                        )
                        return
            except:
                pass

            print(f"🛡️ BLOCARE SAFETY: NU marchez issue-uri cu 1 pagină ca terminate!")
            return

        # VERIFICARE 2: pages_count trebuie să fie aproape de total_pages
        completion_percentage = (pages_count / total_pages) * 100

        if completion_percentage < 95:  # Trebuie să fie cel puțin 95% complet
            print(f"❌ BLOCARE SAFETY: Progres insuficient pentru {normalized}")
            print(f"📊 Progres: {pages_count}/{total_pages} ({completion_percentage:.1f}%)")
            print(f"🛡️ Trebuie cel puțin 95% pentru a marca ca terminat!")
            print(f"🔄 Marchează ca parțial în loc de terminat")

            # Marchează ca parțial, NU ca terminat
            self._update_partial_issue_progress(
                normalized, pages_count, total_pages=total_pages, title=title, subtitle=subtitle
            )
            return

        # VERIFICARE 3: Detectează batch size suspicious
        if pages_count < 100 and total_pages > 500:
            print(f"❌ BLOCARE SAFETY: Progres suspect de mic pentru {normalized}")
            print(f"📊 {pages_count} pagini par să fie doar primul batch din {total_pages}")
            print(f"🛡️ Probabil s-a oprit prematur, NU marchez ca terminat")

            # Marchează ca parțial
            self._update_partial_issue_progress(
                normalized, pages_count, total_pages=total_pages, title=title, subtitle=subtitle
            )
            return

        # VERIFICARE 4: Verifică dacă pages_count pare să fie doar primul segment
        if total_pages >= 1000 and pages_count < 100:
            print(f"❌ BLOCARE SAFETY: {pages_count} pagini din {total_pages} pare primul segment")
            print(f"🛡️ NU marchez issues mari ca terminate cu progres atât de mic")

            # Marchează ca parțial
            self._update_partial_issue_progress(
                normalized, pages_count, total_pages=total_pages, title=title, subtitle=subtitle
            )
            return

        # ===== TOATE VERIFICĂRILE AU TRECUT - SAFE SĂ MARCHEZ CA TERMINAT =====

        print(f"✅ TOATE VERIFICĂRILE ULTRA SAFE trecute pentru {normalized}")
        print(f"📊 Progres: {pages_count}/{total_pages} ({completion_percentage:.1f}%)")
        print(f"🎯 Marchez ca TERMINAT")

        # Continuă cu logica originală de marcare ca terminat...
        existing = None
        existing_index = -1

        # CĂUTARE ÎMBUNĂTĂȚITĂ: încearcă mai multe variante de URL
        search_variants = [
            normalized,
            normalized + '/',
            normalized.replace('https://', 'http://'),
            normalized.replace('http://', 'https://')
        ]

        for i, item in enumerate(self.state.setdefault("downloaded_issues", [])):
            item_url = item.get("url", "").rstrip('/')
            if item_url in search_variants or normalized in [item_url, item_url + '/']:
                existing = item
                existing_index = i
                print(f"🔍 GĂSIT issue existent la index {i}: {item_url}")
                break

        # Creează record-ul de completare
        completion_data = {
            "pages": pages_count,
            "completed_at": now_iso,
            "last_successful_segment_end": pages_count,
            "total_pages": total_pages  # SETEAZĂ ÎNTOTDEAUNA!
        }

        # Adaugă title/subtitle doar dacă nu există sau sunt goale
        if title:
            completion_data["title"] = title
        if subtitle:
            completion_data["subtitle"] = subtitle

        if existing:
            # ÎMBOGĂȚEȘTE issue-ul existent
            for key, value in completion_data.items():
                if key in ["title", "subtitle"]:
                    if not existing.get(key):
                        existing[key] = value
                else:
                    existing[key] = value

            # SCOATE din poziția curentă
            updated_issue = self.state["downloaded_issues"].pop(existing_index)
            print(f"✅ ACTUALIZAT și SCOS din poziția {existing_index}: {normalized}")
        else:
            # Creează issue nou complet
            updated_issue = {
                "url": normalized,
                "title": title or "",
                "subtitle": subtitle or "",
                **completion_data
            }
            print(f"➕ CREAT issue nou: {normalized}")

        # INSEREAZĂ ÎN POZIȚIA CRONOLOGICĂ CORECTĂ
        # Găsește primul issue cu completed_at mai vechi decât cel curent
        insert_position = 0

        # Sari peste issue-urile parțiale (care sunt mereu primele)
        while (insert_position < len(self.state["downloaded_issues"]) and
               not self.state["downloaded_issues"][insert_position].get("completed_at")):
            insert_position += 1

        # Găsește poziția corectă între issue-urile complete (sortate cronologic descendent)
        while insert_position < len(self.state["downloaded_issues"]):
            other_completed_at = self.state["downloaded_issues"][insert_position].get("completed_at", "")
            if other_completed_at and other_completed_at < now_iso:
                break
            insert_position += 1

        # Inserează în poziția cronologică corectă
        self.state["downloaded_issues"].insert(insert_position, updated_issue)
        print(f"📅 INSERAT în poziția CRONOLOGICĂ {insert_position} (după issue-urile parțiale și în ordine de completed_at)")

        # Actualizează contoarele SAFE
        completed_count = len([i for i in self.state["downloaded_issues"] if i.get("completed_at")])
        self.state["count"] = max(self.state.get("count", 0), completed_count)

        # Actualizează pages_downloaded SAFE
        current_pages = self.state.get("pages_downloaded", 0)
        self.state["pages_downloaded"] = current_pages + pages_count

        # Adaugă în recent_links (păstrează max 10)
        recent_entry = {
            "url": normalized,
            "title": (existing and existing.get("title")) or title or "",
            "subtitle": (existing and existing.get("subtitle")) or subtitle or "",
            "pages": pages_count,
            "timestamp": now_iso
        }
        recent_links = self.state.setdefault("recent_links", [])
        recent_links.insert(0, recent_entry)
        self.state["recent_links"] = recent_links[:10]

        # Resetează flag-ul de limită
        self.state["daily_limit_hit"] = False

        # Adaugă în skip URLs
        self.dynamic_skip_urls.add(normalized)

        # Adaugă în log zilnic
        self._log_completed_issue(normalized, title or "", subtitle or "", pages_count)

        self._save_state_safe()
        self._save_skip_urls()

        print(f"✅ Issue marcat ca terminat cu SORTARE CRONOLOGICĂ CORECTĂ: {normalized}")
        print(f"📊 Detalii: {pages_count} pagini, total_pages: {total_pages}")
        print(f"📊 Total complet: {self.state['count']}, Total pagini: {self.state['pages_downloaded']}")
        print(f"📅 Plasat în poziția cronologică {insert_position} din {len(self.state['downloaded_issues'])}")

    def mark_collection_complete(self, collection_url):
        """Marchează o colecție ca fiind complet procesată în skip_urls.json"""
        try:
            normalized_collection = collection_url.rstrip('/')

            # Adaugă în dynamic skip URLs
            self.dynamic_skip_urls.add(normalized_collection)

            # Salvează în skip_urls.json cu un marker special pentru colecții
            skip_data = {}
            if os.path.exists(self.skip_urls_path):
                with open(self.skip_urls_path, "r", encoding="utf-8") as f:
                    skip_data = json.load(f)

            completed_collections = skip_data.get("completed_collections", [])
            if normalized_collection not in completed_collections:
                completed_collections.append(normalized_collection)
                skip_data["completed_collections"] = completed_collections
                skip_data["last_updated"] = datetime.now().isoformat()

                with open(self.skip_urls_path, "w", encoding="utf-8") as f:
                    json.dump(skip_data, f, indent=2, ensure_ascii=False)

                print(f"✅ Colecția marcată ca completă: {normalized_collection}")
        except Exception as e:
            print(f"⚠ Eroare la marcarea colecției complete: {e}")

    def setup_chrome_driver(self, browser="firefox"):
        """
        Inițializează WebDriver pentru Chrome sau Firefox
        browser: "chrome" sau "firefox" (default: "firefox")
        """
        if browser.lower() == "firefox":
            return self.setup_firefox_driver()

        # Calea către scriptul batch care pornește Chrome în debug mode
        CHROME_DEBUG_SCRIPT = r"e:\Carte\BB\17 - Site Leadership\alte\Ionel Balauta\Aryeht\Task 1 - Traduce tot site-ul\Doar Google Web\Andreea\Meditatii\2023\++Arcanum Download + Chrome\Ruleaza cand sunt plecat 3\start_chrome_debug.bat"

        try:
            print("🔧 Inițializare WebDriver – încerc conectare la instanța Chrome existentă via remote debugging...")
            chrome_options = ChromeOptions()
            chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
            prefs = {
                "download.default_directory": os.path.abspath(self.download_dir),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True,
            }
            chrome_options.add_experimental_option("prefs", prefs)
            try:
                self.driver = webdriver.Chrome(options=chrome_options)
                self.wait = WebDriverWait(self.driver, self.timeout)
                self.attached_existing = True
                print("✅ Conectat la instanța Chrome existentă cu succes.")
                return True
            except WebDriverException as e:
                print(f"⚠ Conexiune la Chrome existent eșuat: {e}")
                print(f"🔄 Încerc să pornesc Chrome prin scriptul debug...")

                # Verifică dacă scriptul batch există
                if not os.path.exists(CHROME_DEBUG_SCRIPT):
                    print(f"❌ EROARE: Scriptul Chrome debug nu există: {CHROME_DEBUG_SCRIPT}")
                    print(f"⚠️  Chrome trebuie pornit MANUAL prin scriptul debug!")
                    print(f"⏳ Așteaptă 30 secunde pentru pornire manuală...")
                    time.sleep(30)

                    # Reîncearcă conectarea
                    try:
                        self.driver = webdriver.Chrome(options=chrome_options)
                        self.wait = WebDriverWait(self.driver, self.timeout)
                        self.attached_existing = True
                        print("✅ Conectat la Chrome după așteptare.")
                        return True
                    except:
                        print("❌ Încă nu pot conecta la Chrome - opresc scriptul")
                        return False

                # Pornește scriptul batch
                try:
                    print(f"🚀 Pornesc Chrome prin: {CHROME_DEBUG_SCRIPT}")

                    # Pornește scriptul în background (nu așteaptă finalizarea)
                    subprocess.Popen([CHROME_DEBUG_SCRIPT], shell=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)

                    print(f"⏳ Aștept 10 secunde pentru pornirea Chrome...")
                    time.sleep(5)

                    # Încearcă să se conecteze (cu retry)
                    for attempt in range(1, 6):  # 5 încercări
                        print(f"🔄 Încercare conectare {attempt}/5...")
                        try:
                            self.driver = webdriver.Chrome(options=chrome_options)
                            self.wait = WebDriverWait(self.driver, self.timeout)
                            self.attached_existing = True
                            print("✅ Conectat la Chrome după repornire cu succes!")
                            return True
                        except WebDriverException as retry_e:
                            if attempt < 5:
                                print(f"⚠️  Încercare {attempt} eșuată, reîncerc în 5 secunde...")
                                time.sleep(3)
                            else:
                                print(f"❌ Nu am putut conecta după 5 încercări: {retry_e}")
                                return False

                except Exception as script_error:
                    print(f"❌ Eroare la pornirea scriptului Chrome: {script_error}")
                    print(f"⚠️  Pornește MANUAL Chrome prin scriptul debug!")
                    return False

        except WebDriverException as e:
            print(f"❌ Eroare la inițializarea WebDriver-ului: {e}")
            return False

    def kill_existing_firefox(self):
        """
        Închide toate instanțele Firefox și geckodriver existente pentru a elibera profilul.
        Curăță și fișierele de lock din profil după terminare.
        IMPORTANT: Folosește PowerShell Get-Process (NU tasklist care se blochează pe acest PC).
        """
        try:
            CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

            # Verifică dacă Firefox rulează cu PowerShell (NU tasklist!)
            fox_count = _ps_get_process_count('firefox')

            if fox_count > 0:
                print(f"🔄 Închid Firefox-ul existent ({fox_count} procese) pentru a elibera profilul...")

                # Folosește EXCLUSIV PowerShell (taskkill se BLOCHEAZĂ pe acest PC!)
                _ps_stop_process('firefox')
                time.sleep(3)

                # Verifică dacă mai rulează
                fox_count2 = _ps_get_process_count('firefox')
                if fox_count2 > 0:
                    print(f"⚠️ Firefox nu s-a închis ({fox_count2} procese) - încerc din nou...")
                    _ps_stop_process('firefox')
                    time.sleep(2)

                print("✅ Firefox închis - profilul este eliberat")
            else:
                print("✅ Firefox nu rulează - profilul este liber")

            # Închide și procesele geckodriver rămase
            gecko_count = _ps_get_process_count('geckodriver')
            if gecko_count > 0:
                print("🔄 Geckodriver detectat - forțez închiderea...")
                _ps_stop_process('geckodriver')
                time.sleep(2)

            # Curăță fișierele de lock din profilurile Firefox
            try:
                profile_base = os.path.join(os.environ['APPDATA'], r"Mozilla\Firefox\Profiles")
                if os.path.isdir(profile_base):
                    for profile_dir in os.listdir(profile_base):
                        profile_path = os.path.join(profile_base, profile_dir)
                        if os.path.isdir(profile_path):
                            for lock_file in ['parent.lock', '.parentlock', 'lock']:
                                lock_path = os.path.join(profile_path, lock_file)
                                if os.path.exists(lock_path):
                                    try:
                                        os.remove(lock_path)
                                        print(f"🔓 Fișier lock șters: {lock_path}")
                                    except Exception as le:
                                        print(f"⚠️ Nu am putut șterge lock-ul {lock_path}: {le}")
            except Exception as le:
                print(f"⚠️ Eroare la curățarea lock-urilor: {le}")

            time.sleep(1)
            return True

        except Exception as e:
            print(f"⚠️ Eroare la închiderea Firefox: {e}")
            return False

    def setup_firefox_driver(self):
        """
        Pornește o instanță Firefox pentru automatizare folosind același profil.
        Firefox-ul de automatizare este SEPARAT de Firefox-ul normal (fără banner "remote control" în cel normal).
        """
        try:
            print("🚀 Pornesc Firefox pentru automatizare...")

            # === ÎNCHIDE FIREFOX EXISTENT PENTRU A ELIBERA PROFILUL ===
            # Necesar pentru că nu putem avea 2 instanțe Firefox cu același profil
            self.kill_existing_firefox()

            # Găsește profilul Firefox
            profile_base = os.path.join(os.environ['APPDATA'], r"Mozilla\Firefox\Profiles")
            profiles = glob.glob(os.path.join(profile_base, "*.default-release"))
            if not profiles:
                profiles = glob.glob(os.path.join(profile_base, "*.default"))
            if not profiles:
                profiles = [p for p in glob.glob(os.path.join(profile_base, "*")) if os.path.isdir(p)]

            selected_profile = profiles[0] if profiles else None

            # === CONFIGURARE OPȚIUNI FIREFOX ===
            firefox_options = FirefoxOptions()
            firefox_options.add_argument("--no-remote")

            if selected_profile:
                firefox_options.add_argument("-profile")
                firefox_options.add_argument(selected_profile)
                print(f"✅ Profil folosit: {selected_profile}")
            else:
                print("⚠ Nu am găsit niciun profil Firefox - folosesc profil temporar")

            # Setări descărcare
            firefox_options.set_preference("browser.download.folderList", 2)
            firefox_options.set_preference("browser.download.dir", os.path.abspath(self.download_dir))
            firefox_options.set_preference("browser.download.useDownloadDir", True)
            firefox_options.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/pdf")
            firefox_options.set_preference("pdfjs.disabled", True)

            # Setări Marionette (pentru automatizare)
            firefox_options.set_preference("marionette.logging", False)

            # User agent
            firefox_options.set_preference("general.useragent.override",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0")

            # Păstrează Firefox deschis după ce scriptul se oprește
            firefox_options.set_preference("browser.tabs.remote.autostart", False)

            # === PORNIRE FIREFOX ===
            firefox_service = FirefoxService()

            self.driver = webdriver.Firefox(options=firefox_options, service=firefox_service)
            self.wait = WebDriverWait(self.driver, self.timeout)
            self.attached_existing = False
            self.keep_firefox_open = True

            print("✅ Firefox pentru automatizare pornit cu succes!")
            print("📝 Folosește același profil = aceleași bookmark-uri, istoric și parole")
            return True

        except Exception as e:
            print(f"❌ Eroare Firefox: {e}")
            import traceback
            traceback.print_exc()
            return False

    def safe_get_current_url(self):
        """
        Obține URL-ul curent gestionând erorile fără să creeze instanțe noi Firefox
        Returnează URL-ul sau None dacă apare o eroare
        """
        try:
            if not hasattr(self, 'driver') or not self.driver:
                return None
            return self.driver.current_url
        except Exception as e:
            error_str = str(e)
            # Erori comune care nu necesită crearea unei instanțe noi
            if "discarded" in error_str or "NoSuchWindow" in error_str or "Process unexpectedly closed" in error_str:
                # Context browser închis - nu crea instanță nouă
                return None
            # Alte erori - returnează None
            return None

    def navigate_to_page(self, url):
        try:
            # VERIFICĂ ÎNTÂI DACĂ BROWSER-UL MAI EXISTĂ
            try:
                # Verifică dacă driver-ul există și funcționează
                if not hasattr(self, 'driver') or not self.driver:
                    raise Exception("Driver nu există")
                _ = self.driver.current_url
            except Exception as e:
                # Browser-ul s-a închis sau nu funcționează
                print(f"⚠ Browser închis sau nefuncțional ({e}), încerc reconectare...")

                # Reîncearcă să creeze driver-ul
                # setup_firefox_driver() va închide automat orice Firefox existent
                print("🔄 Repornesc Firefox pentru reconectare...")
                if not self.setup_chrome_driver(browser="firefox"):
                    print("❌ Nu pot reconecta browser-ul")
                    return False
                print("✅ Firefox repornit cu succes!")

            print(f"🌐 Navighez către: {url}")
            self.driver.get(url)
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'body')))
            print("✅ Pagina încărcată.")

            # Așteaptă ca pagina să se stabilizeze (delay pentru securitate site)
            print("⏳ Aștept 3 secunde pentru stabilizarea paginii...")
            time.sleep(3)

            # 🔧 VERIFICARE 1: MENTENANȚĂ (403 Forbidden)
            if self.detect_403_maintenance():
                print(f"⚠️ Detectat 403 Forbidden - Arcanum în mentenanță")

                # Așteaptă finalul mentenanței (10 min x 3 încercări = 30 min max)
                if self.wait_for_maintenance(wait_minutes=10, max_retries=3):
                    print(f"✅ Mentenanță finalizată - continuăm")
                    # Site-ul e online, continuă
                else:
                    print(f"❌ Mentenanță prea lungă - opresc scriptul")
                    return False

            # 🚨 VERIFICARE 2: CAPTCHA
            if self.detect_captcha():
                print(f"\n{'='*60}")
                print(f"🚨🚨🚨 CAPTCHA DETECTAT - OPRIRE COMPLETĂ! 🚨🚨🚨")
                print(f"{'='*60}")
                print(f"❌ Sistemul Arcanum necesită verificare umană (CAPTCHA)")
                print(f"❌ Scriptul NU poate rezolva CAPTCHA automat")
                print(f"💾 Salvez progresul curent și opresc scriptul...")
                self.state["captcha_detected"] = True
                self.state["captcha_url"] = self.driver.current_url
                self._save_state()
                print(f"\n🛑 SCRIPTUL A FOST OPRIT DIN CAUZA CAPTCHA")
                print(f"📋 URL CAPTCHA: {self.driver.current_url}")
                print(f"📋 Progresul a fost salvat în state.json")
                print(f"⚠️  ACȚIUNE NECESARĂ: Rezolvă CAPTCHA manual în browser")
                print(f"{'='*60}\n")
                raise SystemExit("🚨 OPRIRE CAPTCHA - Verificare umană necesară!")

            return True
        except SystemExit:
            # Re-ridică SystemExit pentru a opri scriptul complet
            raise
        except Exception as e:
            print(f"❌ Eroare la navigare sau încărcare: {e}")
            # ÎNCEARCĂ O RECONECTARE CA ULTIM RESORT
            try:
                print("🔄 Încerc reconectare de urgență...")
                if self.setup_chrome_driver(browser="firefox"):
                    self.driver.get(url)
                    self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'body')))
                    print("✅ Reconectat și navigat cu succes!")

                    time.sleep(2)

                    # 🔧 VERIFICARE 403 DUPĂ RECONECTARE
                    if self.detect_403_maintenance():
                        print(f"⚠️ 403 după reconectare")
                        if self.wait_for_maintenance(wait_minutes=10, max_retries=3):
                            print(f"✅ Mentenanță finalizată după reconectare")
                        else:
                            print(f"❌ Mentenanță prea lungă după reconectare")
                            return False

                    # 🚨 VERIFICARE CAPTCHA DUPĂ RECONECTARE
                    if self.detect_captcha():
                        print(f"\n🚨 CAPTCHA DETECTAT DUPĂ RECONECTARE - OPRIRE!")
                        self.state["captcha_detected"] = True
                        self.state["captcha_url"] = self.driver.current_url
                        self._save_state()
                        raise SystemExit("🚨 OPRIRE CAPTCHA - Verificare umană necesară!")

                    return True
            except SystemExit:
                raise
            except:
                pass
            return False

    def get_issue_metadata(self):
        title = ""
        subtitle = ""
        try:
            breadcrumb = self.driver.find_element(By.CSS_SELECTOR, "li.breadcrumb-item.active")
            try:
                sub_elem = breadcrumb.find_element(By.CSS_SELECTOR, "#pdfview-pdfcontents span")
                subtitle = sub_elem.text.strip()
            except Exception:
                subtitle = ""
            raw = breadcrumb.text.strip()
            if subtitle and subtitle in raw:
                title = raw.replace(subtitle, "").strip()
            else:
                title = raw
        except Exception:
            pass
        return title, subtitle

    def get_total_pages(self, max_attempts=5, delay_between=1.0):
        """FIXED: Detectează corect numărul total de pagini INCLUSIV pentru limba maghiară"""
        for attempt in range(1, max_attempts + 1):
            try:
                # Metoda 1: Caută pattern-uri specifice pentru maghiară ȘI alte limbi
                page_patterns = [
                    r'(\d+)\s*/\s*(\d+)',           # "1 / 146" (română/engleză)
                    r'/\s*(\d+)',                   # "/ 146" (maghiară - PRINCIPAL)
                    r'of\s+(\d+)',                  # "of 146" (engleză)
                    r'din\s+(\d+)',                 # "din 146" (română)
                    r'(\d+)\s*oldal',               # "146 oldal" (maghiară)
                    r'összesen\s+(\d+)',            # "összesen 146" (maghiară)
                ]

                # PRIORITATE: Caută mai întâi în clasa CSS specifică maghiară
                try:
                    # Pattern specific pentru interfața maghiară din screenshot
                    adornment_divs = self.driver.find_elements(By.CSS_SELECTOR,
                        'div.MuiInputAdornment-root.MuiInputAdornment-positionEnd')

                    for div in adornment_divs:
                        text = div.text.strip()
                        print(f"🔍 Verific div adornment: '{text}'")

                        # Caută pattern-ul "/ 146"
                        match = re.search(r'/\s*(\d+)', text)
                        if match:
                            total = int(match.group(1))
                            print(f"✅ TOTAL PAGINI detectat din adornment maghiar: {total}")
                            return total
                except Exception as e:
                    print(f"⚠ Eroare în detectare maghiară: {e}")

                # Metoda 2: Caută în toate elementele cu text (backup)
                all_texts = self.driver.find_elements(By.XPATH,
                    "//*[contains(text(), '/') or contains(text(), 'of') or contains(text(), 'din') or contains(text(), 'oldal')]")

                for el in all_texts:
                    text = el.text.strip()
                    print(f"🔍 Verific text element: '{text}'")

                    for pattern in page_patterns:
                        matches = re.findall(pattern, text)
                        if matches:
                            if pattern == page_patterns[0]:  # "număr / total"
                                current, total = matches[0]
                                total = int(total)
                                print(f"✅ TOTAL PAGINI detectat din '{text}': {total} (curent: {current})")
                                return total
                            else:  # "/ total", "of total", etc.
                                total = int(matches[0])
                                print(f"✅ TOTAL PAGINI detectat din '{text}': {total}")
                                return total

                # Metoda 3: JavaScript mai robust pentru maghiară
                js_result = self.driver.execute_script(r"""
                    const patterns = [
                        /\/\s*(\d+)/g,                    // / 146 (PRIORITATE pentru maghiară)
                        /(\d+)\s*\/\s*(\d+)/g,           // 1 / 146
                        /of\s+(\d+)/g,                   // of 146
                        /din\s+(\d+)/g,                  // din 146
                        /(\d+)\s*oldal/g,                // 146 oldal
                        /összesen\s+(\d+)/g              // összesen 146
                    ];

                    // Caută în toate nodurile text
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    const results = [];

                    while(walker.nextNode()) {
                        const text = walker.currentNode.nodeValue;
                        if (!text || text.trim().length < 2) continue;

                        for (let pattern of patterns) {
                            const matches = [...text.matchAll(pattern)];
                            if (matches.length > 0) {
                                const match = matches[0];
                                let total, current = 0;

                                if (match.length === 3) {  // "număr / total"
                                    current = parseInt(match[1]);
                                    total = parseInt(match[2]);
                                } else {  // "/ total"
                                    total = parseInt(match[1]);
                                }

                                if (total && total > 0) {
                                    results.push({
                                        text: text.trim(),
                                        total: total,
                                        current: current,
                                        pattern: pattern.source
                                    });
                                }
                            }
                        }
                    }

                    // Sortează după total (cel mai mare primul) și returnează primul
                    results.sort((a, b) => b.total - a.total);
                    return results.length > 0 ? results[0] : null;
                """)

                if js_result:
                    total = js_result['total']
                    current = js_result.get('current', 0)
                    text = js_result['text']
                    pattern = js_result['pattern']
                    print(f"✅ TOTAL PAGINI detectat prin JS: {total} din '{text}' (pattern: {pattern})")
                    return total

                print(f"⚠ ({attempt}) Nu am găsit încă numărul total de pagini, reîncerc în {delay_between}s...")
                time.sleep(delay_between)

            except Exception as e:
                print(f"⚠ ({attempt}) Eroare în get_total_pages: {e}")
                time.sleep(delay_between)

        print("❌ Nu s-a reușit extragerea numărului total de pagini după multiple încercări.")
        return 0

    def debug_page_detection(self):
        """Funcție de debugging pentru a vedea ce detectează în interfața maghiară"""
        try:
            print("🔍 DEBUG: Analizez interfața pentru detectarea paginilor...")

            # 1. Verifică adornment-urile
            adornments = self.driver.find_elements(By.CSS_SELECTOR,
                'div.MuiInputAdornment-root')
            print(f"📊 Găsite {len(adornments)} adornment-uri:")
            for i, div in enumerate(adornments):
                text = div.text.strip()
                html = div.get_attribute('outerHTML')[:100]
                print(f"   {i+1}. Text: '{text}' | HTML: {html}...")

            # 2. Caută toate elementele cu "/"
            slash_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), '/')]")
            print(f"📊 Găsite {len(slash_elements)} elemente cu '/':")
            for i, el in enumerate(slash_elements[:5]):  # Primele 5
                text = el.text.strip()
                tag = el.tag_name
                print(f"   {i+1}. <{tag}>: '{text}'")

            # 3. JavaScript debug
            js_result = self.driver.execute_script("""
                const allText = document.body.innerText;
                const lines = allText.split('\\n');
                const relevantLines = lines.filter(line =>
                    line.includes('/') ||
                    line.includes('oldal') ||
                    line.includes('összesen')
                );
                return relevantLines.slice(0, 10);
            """)

            print(f"📊 Linii relevante din JS:")
            for i, line in enumerate(js_result):
                print(f"   {i+1}. '{line.strip()}'")

        except Exception as e:
            print(f"❌ Eroare în debug: {e}")

    def open_save_popup(self):
        try:
            # PASUL 1: Așteaptă ca orice dialog existent să dispară
            try:
                self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, 'div.MuiDialog-container')))
            except Exception:
                self.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
                time.sleep(0.5)

            # PASUL 2: Așteaptă ca pagina să se încarce complet (delay pentru securitate site)
            print("⏳ Aștept 2 secunde pentru încărcarea completă a paginii...")
            time.sleep(2)

            # PASUL 3: Așteaptă ca elementul să fie vizibil, stabil și clickable
            print("🔍 Caut butonul de salvare (SaveAltIcon)...")
            try:
                # Așteaptă mai întâi ca elementul să fie prezent
                svg = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'svg[data-testid="SaveAltIcon"]'))
                )
                # Apoi așteaptă ca elementul să fie vizibil
                WebDriverWait(self.driver, 10).until(
                    EC.visibility_of(svg)
                )
                # Apoi așteaptă ca elementul să fie clickable
                svg = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'svg[data-testid="SaveAltIcon"]'))
                )
                print("✅ Butonul de salvare găsit și pregătit")
            except Exception as e:
                print(f"⚠ Eroare la găsirea butonului: {e}")
                # Reîncearcă cu un delay suplimentar
                print("⏳ Aștept încă 2 secunde și reîncerc...")
                time.sleep(2)
                svg = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'svg[data-testid="SaveAltIcon"]')))

            # PASUL 4: Găsește butonul părinte dacă e SVG
            button = svg
            if svg.tag_name.lower() == "svg":
                try:
                    button = svg.find_element(By.XPATH, "./ancestor::button")
                except Exception:
                    pass

            # PASUL 5: Încearcă click-ul cu retry-uri
            for attempt in range(1, 5):
                try:
                    # Scroll în viewport dacă e necesar
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                    time.sleep(0.5)

                    # Folosește JavaScript pentru click pentru a declanșa corect event-urile
                    print(f"🖱️ Încerc click pe butonul de salvare (încercarea {attempt})...")

                    # Încearcă mai întâi cu JavaScript pentru a declanșa corect event-urile
                    try:
                        # Folosește JavaScript pentru a declanșa click-ul și toate event-urile
                        self.driver.execute_script("""
                            var button = arguments[0];
                            // Declanșează mouseover, mousedown, mouseup, click
                            var events = ['mouseover', 'mousedown', 'mouseup', 'click'];
                            events.forEach(function(eventType) {
                                var event = new MouseEvent(eventType, {
                                    view: window,
                                    bubbles: true,
                                    cancelable: true
                                });
                                button.dispatchEvent(event);
                            });
                        """, button)
                        print(f"✅ Click efectuat prin JavaScript cu event-uri (încercarea {attempt})")
                    except Exception as js_error:
                        print(f"⚠ JavaScript click eșuat: {js_error}, încerc click normal...")
                        try:
                            button.click()
                            print(f"✅ Click efectuat normal (încercarea {attempt})")
                        except Exception as normal_error:
                            print(f"⚠ Click normal eșuat: {normal_error}")
                            # Reîncearcă cu JavaScript simplu
                            self.driver.execute_script("arguments[0].click();", button)
                            print(f"✅ Click efectuat prin JavaScript simplu (încercarea {attempt})")

                    # Așteaptă mai mult după click pentru ca popup-ul să apară complet
                    print("⏳ Aștept 4 secunde pentru apariția completă a popup-ului...")
                    time.sleep(4)

                    # VERIFICARE RAPIDĂ: Verifică dacă popup-ul a apărut efectiv folosind JavaScript
                    try:
                        # Folosește JavaScript pentru a verifica dacă popup-ul există în DOM
                        popup_exists = self.driver.execute_script("""
                            // Verifică multiple moduri de a detecta popup-ul
                            var dialog = document.querySelector('div.MuiDialog-container') ||
                                        document.querySelector('div[role="dialog"]') ||
                                        document.querySelector('div.MuiDialog-root') ||
                                        document.querySelector('.MuiDialog-container');

                            if (dialog) {
                                var style = window.getComputedStyle(dialog);
                                var isVisible = style.display !== 'none' &&
                                               style.visibility !== 'hidden' &&
                                               dialog.offsetParent !== null;
                                return isVisible;
                            }

                            // Verifică dacă input-urile există (indică că popup-ul este deschis)
                            var firstInput = document.getElementById('first page');
                            if (firstInput) {
                                return firstInput.offsetParent !== null;
                            }

                            return false;
                        """)

                        if popup_exists:
                            print("✅ Popup-ul a apărut și este vizibil (detectat prin JavaScript)")
                            return True
                        else:
                            # Așteaptă puțin mai mult și verifică din nou
                            print("⏳ Popup-ul nu este încă vizibil, aștept încă 3 secunde...")
                            time.sleep(3)

                            # Verifică din nou cu mai multe încercări
                            for check_attempt in range(3):
                                popup_exists = self.driver.execute_script("""
                                    var dialog = document.querySelector('div.MuiDialog-container') ||
                                                document.querySelector('div[role="dialog"]') ||
                                                document.querySelector('div.MuiDialog-root');
                                    if (dialog) {
                                        var style = window.getComputedStyle(dialog);
                                        return style.display !== 'none' && dialog.offsetParent !== null;
                                    }
                                    var firstInput = document.getElementById('first page');
                                    return firstInput && firstInput.offsetParent !== null;
                                """)

                                if popup_exists:
                                    print(f"✅ Popup-ul a apărut la verificarea {check_attempt + 1}")
                                    return True

                                if check_attempt < 2:
                                    time.sleep(1)

                            # Verifică dacă input-urile există direct (popup-ul poate fi deschis dar nu detectat)
                            try:
                                first_input = WebDriverWait(self.driver, 5).until(
                                    EC.presence_of_element_located((By.ID, "first page"))
                                )
                                if first_input.is_displayed():
                                    print("✅ Input-urile sunt disponibile - popup-ul este deschis")
                                    return True
                            except:
                                pass

                            print(f"⚠ Popup-ul nu este detectat după click (încercarea {attempt}), reîncerc...")
                            if attempt < 4:
                                time.sleep(2)
                                # Reîncarcă butonul pentru următoarea încercare
                                try:
                                    svg = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'svg[data-testid="SaveAltIcon"]')))
                                    button = svg
                                    if svg.tag_name.lower() == "svg":
                                        try:
                                            button = svg.find_element(By.XPATH, "./ancestor::button")
                                        except:
                                            pass
                                except:
                                    pass
                                continue
                            else:
                                print("⚠ Popup-ul nu apare după multiple încercări")
                                return False  # Returnează False pentru a opri procesarea
                    except Exception as e:
                        print(f"⚠ Verificare popup: {e}")
                        if attempt < 4:
                            time.sleep(2)
                            continue
                        else:
                            return True  # Continuă oricum

                except ElementClickInterceptedException:
                    print(f"⚠ Click interceptat (încercarea {attempt}), trimit ESC și reiau...")
                    self.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
                    time.sleep(2)
                    continue
                except Exception as e:
                    print(f"⚠ Eroare la click (încercarea {attempt}): {e}")
                    if attempt < 4:
                        time.sleep(2)
                        continue
                    else:
                        raise

            print("❌ Nu am reușit să dau click pe butonul de deschidere a popup-ului după retry-uri.")
            return False
        except Exception as e:
            print(f"❌ Nu am reușit să deschid popup-ul de salvare: {e}")
            return False

    def detect_save_button_multilingual(self):
        """
        Detectează butonul de salvare în orice limbă suportată de Arcanum
        """
        # Lista cu toate variantele de text pentru butonul de salvare
        save_button_texts = [
            "Salvați",    # Română
            "Save",       # Engleză
            "Mentés",     # Maghiară
            "Uložiť",     # Slovacă/Cehă
            "Speichern",  # Germană
            "Salvar",     # Spaniolă (dacă e cazul)
            "Sauvegarder" # Franceză (dacă e cazul)
        ]

        for text in save_button_texts:
            try:
                save_btn = self.driver.find_element(By.XPATH,
                    f'//button[.//text()[contains(normalize-space(.), "{text}")]]')
                if save_btn and save_btn.is_enabled():
                    print(f"✅ Buton de salvare găsit cu textul: '{text}'")
                    return save_btn
            except:
                continue

        # Dacă nu găsește cu textul, încearcă după clasele CSS (backup method)
        try:
            buttons = self.driver.find_elements(By.CSS_SELECTOR,
                'button[class*="MuiButton"][class*="Primary"]')
            for btn in buttons:
                text = btn.text.strip().lower()
                # Verifică dacă conține cuvinte cheie în orice limbă
                if any(keyword in text for keyword in ['salv', 'save', 'ment', 'ulož', 'speich']):
                    print(f"✅ Buton de salvare găsit prin CSS cu textul: '{btn.text}'")
                    return btn
        except:
            pass

        return None

    def fill_and_save_range(self, start, end):
        try:
            # PASUL 1: Verifică că popup-ul există și este vizibil folosind JavaScript
            print("🔍 Verific dacă popup-ul este deschis...")

            # Așteaptă mai mult pentru ca popup-ul să apară
            time.sleep(2)

            # Folosește JavaScript pentru verificare rapidă
            try:
                popup_visible = self.driver.execute_script("""
                    var dialog = document.querySelector('div.MuiDialog-container') ||
                                document.querySelector('div[role="dialog"]') ||
                                document.querySelector('div.MuiDialog-root');

                    if (dialog) {
                        var style = window.getComputedStyle(dialog);
                        return style.display !== 'none' && style.visibility !== 'hidden' && dialog.offsetParent !== null;
                    }

                    // Verifică dacă input-urile există (indică că popup-ul este deschis)
                    var firstInput = document.getElementById('first page');
                    return firstInput && firstInput.offsetParent !== null;
                """)

                if popup_visible:
                    print("✅ Popup-ul este deschis și vizibil (detectat prin JavaScript)")
                else:
                    print("⏳ Popup-ul nu este încă vizibil, aștept încă 2 secunde...")
                    time.sleep(2)

                    # Verifică din nou
                    popup_visible = self.driver.execute_script("""
                        var dialog = document.querySelector('div.MuiDialog-container') ||
                                    document.querySelector('div[role="dialog"]') ||
                                    document.querySelector('div.MuiDialog-root');
                        if (dialog) {
                            var style = window.getComputedStyle(dialog);
                            return style.display !== 'none' && dialog.offsetParent !== null;
                        }
                        var firstInput = document.getElementById('first page');
                        return firstInput && firstInput.offsetParent !== null;
                    """)

                    if popup_visible:
                        print("✅ Popup-ul este acum vizibil")
                    else:
                        # Încearcă să găsească input-urile direct cu WebDriverWait
                        try:
                            first_input = WebDriverWait(self.driver, 5).until(
                                EC.presence_of_element_located((By.ID, "first page"))
                            )
                            if first_input.is_displayed():
                                print("✅ Input-urile sunt disponibile - popup-ul este deschis")
                            else:
                                print("⚠ Popup-ul nu este detectat, dar continuăm (poate apare în timpul completării)")
                        except:
                            print("⚠ Popup-ul nu este detectat, dar continuăm (poate apare în timpul completării)")
            except Exception as e:
                print(f"⚠ Verificare popup prin JavaScript: {e}")
                # Continuă oricum

            # Verifică că suntem încă pe pagina corectă
            try:
                current_url = self.driver.current_url
                if self.current_issue_url not in current_url and not current_url.startswith('chrome://'):
                    print(f"⚠ ATENȚIE: URL s-a schimbat în timpul așteptării popup: {current_url}")
                    # Nu returnăm False aici, continuăm să încercăm
            except:
                pass

            # PASUL 2: Găsește și completează primul input cu verificări multiple și retry-uri
            print("🔍 Caut primul input (first page)...")
            first_input = None
            max_retries = 5

            for retry in range(max_retries):
                try:
                    # Încearcă mai multe metode de găsire
                    selectors = [
                        (By.ID, "first page"),
                        (By.NAME, "first page"),
                        (By.CSS_SELECTOR, 'input[id="first page"]'),
                        (By.CSS_SELECTOR, 'input[name="first page"]'),
                        (By.XPATH, '//input[@id="first page"]'),
                        (By.XPATH, '//input[contains(@placeholder, "first") or contains(@placeholder, "început")]'),
                    ]

                    for selector_type, selector_value in selectors:
                        try:
                            first_input = WebDriverWait(self.driver, 10).until(
                                EC.presence_of_element_located((selector_type, selector_value))
                            )
                            # Verifică că este vizibil și enabled
                            WebDriverWait(self.driver, 10).until(
                                lambda d: first_input.is_displayed() and first_input.is_enabled()
                            )
                            print(f"✅ Primul input găsit folosind {selector_type}: {selector_value}")
                            break
                        except:
                            continue

                    if first_input and first_input.is_displayed() and first_input.is_enabled():
                        break
                    else:
                        raise Exception("Input-ul nu este disponibil")

                except Exception as e:
                    if retry < max_retries - 1:
                        wait_time = (retry + 1) * 1
                        print(f"⚠ Nu am găsit primul input (încercarea {retry + 1}/{max_retries}), aștept {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        print(f"❌ Nu am putut găsi primul input după {max_retries} încercări: {e}")
                        # Debug: afișează structura paginii
                        try:
                            page_source_snippet = self.driver.page_source[:2000]
                            print(f"🔍 Fragment din pagina (primele 2000 caractere):\n{page_source_snippet}")
                        except:
                            pass
                        return False

            if not first_input:
                print("❌ Primul input nu a fost găsit")
                return False

            print("⏳ Aștept 1s înainte de a completa primul input...")
            time.sleep(1)

            # Verifică din nou că input-ul este disponibil
            try:
                if not first_input.is_displayed() or not first_input.is_enabled():
                    print("⚠ Input-ul nu mai este disponibil, reîncerc găsirea...")
                    first_input = self.wait.until(EC.element_to_be_clickable((By.ID, "first page")))
            except:
                print("❌ Nu pot re-găsi primul input")
                return False

            # Completează primul input
            try:
                first_input.click()  # Click pentru a activa input-ul
                time.sleep(0.5)
                first_input.send_keys(Keys.CONTROL + "a")
                time.sleep(0.5)
                first_input.send_keys(str(start))
                time.sleep(0.5)
                print(f"✏️ Am introdus primul număr: {start}")
            except Exception as e:
                print(f"❌ Eroare la completarea primului input: {e}")
                return False

            # PASUL 3: Găsește și completează al doilea input
            print("⏳ Aștept 1s înainte de a completa al doilea input...")
            time.sleep(1)

            print("🔍 Caut al doilea input (last page)...")
            try:
                # Așteaptă mai întâi ca elementul să fie prezent
                last_input = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.ID, "last page"))
                )
                # Apoi așteaptă ca elementul să fie vizibil
                WebDriverWait(self.driver, 15).until(
                    EC.visibility_of(last_input)
                )
                # Apoi așteaptă ca elementul să fie interactiv
                WebDriverWait(self.driver, 15).until(
                    lambda d: last_input.is_enabled() and last_input.is_displayed()
                )
                print("✅ Al doilea input găsit și pregătit")
            except Exception as e:
                print(f"❌ Nu am putut găsi al doilea input: {e}")
                return False

            # Completează al doilea input
            try:
                last_input.click()  # Click pentru a activa input-ul
                time.sleep(0.5)
                last_input.send_keys(Keys.CONTROL + "a")
                time.sleep(0.5)
                last_input.send_keys(str(end))
                time.sleep(0.5)
                print(f"✏️ Am introdus al doilea număr: {end}")
            except Exception as e:
                print(f"❌ Eroare la completarea celui de-al doilea input: {e}")
                return False

            # PASUL 4: Așteaptă înainte de a apăsa butonul de salvare (delay pentru securitate)
            print("⏳ Aștept 3 secunde înainte de a apăsa butonul de salvare (delay securitate)...")
            time.sleep(3)

            # PASUL 5: Găsește și apasă butonul de salvare
            print("🔍 Caut butonul de salvare...")
            save_btn = self.detect_save_button_multilingual()

            if save_btn:
                try:
                    # Așteaptă ca butonul să fie clickable
                    WebDriverWait(self.driver, 15).until(
                        EC.element_to_be_clickable(save_btn)
                    )
                    # Scroll în viewport
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", save_btn)
                    time.sleep(1)

                    save_btn.click()
                    print(f"✅ Segmentul {start}-{end} salvat.")

                    # PASUL 6: Așteaptă după click pentru ca descărcarea să înceapă
                    print("⏳ Aștept 2 secunde pentru inițierea descărcării...")
                    time.sleep(2)

                    return True
                except Exception as e:
                    print(f"❌ Eroare la click pe butonul de salvare: {e}")
                    return False
            else:
                print(f"❌ Nu am găsit butonul de salvare în nicio limbă pentru segmentul {start}-{end}")
                return False

        except Exception as e:
            print(f"❌ Eroare la completarea/salvarea intervalului {start}-{end}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def check_daily_limit_in_all_windows(self, set_flag=True):
        # return False  # Add this line at the top to disable detection
        """Verifică mesajul de limită zilnică în toate ferestrele deschise"""
        current_window = self.driver.current_window_handle
        limit_reached = False

        try:
            all_handles = self.driver.window_handles
            for handle in all_handles:
                try:
                    self.driver.switch_to.window(handle)
                    body_text = self.driver.find_element(By.TAG_NAME, "body").text

                    if ("Daily download limit reached" in body_text or
                        "Terms and conditions" in body_text):
                        print(f"⚠ Limita zilnică detectată în fereastra: {handle}")
                        limit_reached = True

                        if handle != current_window and len(all_handles) > 1:
                            print(f"🗙 Închid fereastra cu limita zilnică: {handle}")
                            self.driver.close()
                        break

                except Exception as e:
                    continue

            try:
                if current_window in self.driver.window_handles:
                    self.driver.switch_to.window(current_window)
                elif self.driver.window_handles:
                    self.driver.switch_to.window(self.driver.window_handles[0])
            except Exception:
                pass

        except Exception as e:
            print(f"⚠ Eroare la verificarea ferestrelor: {e}")

        if limit_reached and set_flag:
            self.state["daily_limit_hit"] = True
            self._save_state()

        return limit_reached

    def detect_captcha(self):
        """
        🚨 FUNCȚIE CRITICĂ: Detectează CAPTCHA Arcanum și oprește scriptul complet

        Detectează 3 tipuri de CAPTCHA:
        1. Textul "Let's confirm you are human" + butonul "amzn-captcha-verify-button"
        2. Pagina "Human Verification" cu "JavaScript is disabled"
        3. Butonul "amzn-captcha-verify-button" (backup)

        Returns: True dacă CAPTCHA detectat, False altfel
        """
        try:
            current_url = self.driver.current_url

            # Detectare 1: Verifică conținutul paginii (HTML și text)
            try:
                page_source = self.driver.page_source
                body_text = self.driver.find_element(By.TAG_NAME, "body").text

                # CAPTCHA Tip 1: "Let's confirm you are human"
                if (('<h1 style="font-weight: normal; color: rgb(221, 107, 16);">Let\'s confirm you are human</h1>' in page_source or
                     'Let\'s confirm you are human' in body_text) and
                    'Complete the security check before continuing' in body_text):
                    print(f"\n{'='*60}")
                    print(f"🚨 CAPTCHA DETECTAT (Tip 1) - VERIFICARE UMANĂ!")
                    print(f"{'='*60}")
                    print(f"URL: {current_url}")
                    print(f"🛑 CAPTCHA detectat: 'Let's confirm you are human'")
                    return True

                # CAPTCHA Tip 2: "Human Verification" cu JavaScript disabled message
                if ('<title>Human Verification</title>' in page_source and
                    'JavaScript is disabled' in page_source and
                    'you need to verify that you\'re not a robot by solving a CAPTCHA puzzle' in page_source):
                    print(f"\n{'='*60}")
                    print(f"🚨 CAPTCHA DETECTAT (Tip 2) - HUMAN VERIFICATION!")
                    print(f"{'='*60}")
                    print(f"URL: {current_url}")
                    print(f"🛑 CAPTCHA detectat: 'Human Verification' page")
                    return True

            except Exception:
                pass

            # Detectare 3: Verifică butonul CAPTCHA
            try:
                captcha_button = self.driver.find_element(By.ID, "amzn-captcha-verify-button")
                if captcha_button:
                    print(f"\n{'='*60}")
                    print(f"🚨 CAPTCHA DETECTAT (Tip 3) - BUTON CAPTCHA!")
                    print(f"{'='*60}")
                    print(f"URL: {current_url}")
                    print(f"🛑 CAPTCHA detectat - buton de verificare găsit!")
                    return True
            except Exception:
                pass

            return False

        except Exception as e:
            print(f"⚠ Eroare la detectarea CAPTCHA: {e}")
            return False

    def detect_403_maintenance(self):
        """
        🔧 Detectează mentenanța Arcanum (403 Forbidden)

        Când apare 403, înseamnă că Arcanum face mentenanță ~10 minute
        Scriptul va aștepta automat și va reîncerca

        IMPORTANT: Detectarea trebuie să fie STRICTĂ pentru a evita false pozitive!
        O pagină cu "403" în conținut normal (ex: anul 1403) NU e mentenanță.

        Returns: True dacă 403 detectat, False altfel
        """
        try:
            # Verifică titlul paginii - dacă titlul e explicit "403 Forbidden"
            try:
                page_title = self.driver.title.strip().lower()
                # Titlul trebuie să fie EXACT sau să înceapă cu 403
                if page_title in ["403 forbidden", "403", "forbidden"] or page_title.startswith("403"):
                    print(f"⚠️ DETECTAT: 403 Forbidden în titlu: '{self.driver.title}'")
                    return True
            except Exception:
                pass

            # Verifică conținutul paginii - dar DOAR dacă e o pagină de eroare scurtă
            try:
                body_text = self.driver.find_element(By.TAG_NAME, "body").text.strip()

                # Pagina de eroare 403 e FOARTE scurtă (sub 500 caractere de obicei)
                # și conține EXACT "403 Forbidden" ca text principal
                if len(body_text) < 500:
                    # Verifică dacă e o pagină de eroare nginx/apache
                    body_lower = body_text.lower()
                    if ("403 forbidden" in body_lower and
                        ("nginx" in body_lower or "apache" in body_lower or len(body_text) < 100)):
                        print(f"⚠️ DETECTAT: Pagină de eroare 403 (server)")
                        return True

                    # Verifică dacă body-ul e aproape DOAR "403 Forbidden"
                    if body_text.strip() in ["403 Forbidden", "403", "Forbidden", "Access Denied"]:
                        print(f"⚠️ DETECTAT: Pagină de eroare 403 simplă")
                        return True
            except Exception:
                pass

            # Verifică h1 cu 403 - dar DOAR dacă e exact "403 Forbidden" sau similar
            try:
                h1_elements = self.driver.find_elements(By.TAG_NAME, "h1")
                for h1 in h1_elements:
                    h1_text = h1.text.strip().lower()
                    # Verifică EXACT match pentru erori 403
                    if h1_text in ["403 forbidden", "403", "forbidden", "access denied"]:
                        print(f"⚠️ DETECTAT: 403 Forbidden în header H1")
                        return True
            except Exception:
                pass

            return False

        except Exception as e:
            print(f"⚠ Eroare la detectarea 403: {e}")
            return False

    def wait_for_maintenance(self, wait_minutes=10, max_retries=3):
        """
        🔧 Așteaptă finalul mentenanței Arcanum și reîncearcă

        Args:
            wait_minutes: Minute de așteptat între încercări (default: 10)
            max_retries: Număr maxim de reîncercări (default: 3)

        Returns: True dacă site-ul revine online, False dacă depășește max_retries
        """
        print(f"\n{'='*60}")
        print(f"🔧 MENTENANȚĂ ARCANUM DETECTATĂ (403 Forbidden)")
        print(f"{'='*60}")
        print(f"⚠️  Site-ul Arcanum este în mentenanță")
        print(f"⏳ Aștept {wait_minutes} minute și reîncerc automat")
        print(f"📊 Reîncercări rămase: {max_retries}")

        for retry in range(1, max_retries + 1):
            print(f"\n🔄 ÎNCERCARE {retry}/{max_retries}")
            print(f"⏳ Aștept {wait_minutes} minute pentru finalizarea mentenanței...")

            # Așteptare cu afișare progress
            wait_seconds = wait_minutes * 60
            interval = 60  # Afișează progress la fiecare minut

            for elapsed in range(0, wait_seconds, interval):
                remaining = wait_seconds - elapsed
                print(f"   ⏱️  Aștept: {remaining // 60} minute rămase...")
                time.sleep(min(interval, remaining))

            print(f"✅ Așteptare finalizată - încerc refresh...")

            # Dă refresh la pagină
            try:
                print(f"🔄 Dau refresh la pagină...")
                self.driver.refresh()
                time.sleep(3)  # Așteaptă încărcarea

                # Verifică dacă 403 a dispărut
                if not self.detect_403_maintenance():
                    print(f"\n{'='*60}")
                    print(f"✅ MENTENANȚA S-A TERMINAT!")
                    print(f"{'='*60}")
                    print(f"✅ Site-ul Arcanum este din nou online")
                    print(f"🔄 Reiau descărcarea de unde am rămas...")
                    return True
                else:
                    print(f"❌ Încă 403 - mentenanța continuă...")
                    if retry < max_retries:
                        print(f"🔄 Mai încerc încă {max_retries - retry} ori...")

            except Exception as e:
                print(f"⚠ Eroare la refresh: {e}")

        # Depășit numărul maxim de reîncercări
        print(f"\n{'='*60}")
        print(f"❌ MENTENANȚA DEPĂȘEȘTE TIMPUL AȘTEPTAT")
        print(f"{'='*60}")
        print(f"❌ Am așteptat {wait_minutes * max_retries} minute total")
        print(f"❌ Site-ul încă returnează 403 Forbidden")
        print(f"💾 Salvez progresul și opresc scriptul COMPLET")
        print(f"🔄 Repornește scriptul mai târziu când mentenanța se termină")

        # 🛑 SETEAZĂ FLAG PENTRU OPRIRE COMPLETĂ A SCRIPTULUI
        self.state["maintenance_stop"] = True
        self._save_state()
        print(f"🛑 FLAG MAINTENANCE_STOP SETAT - Scriptul se va opri complet!")

        return False

    def check_for_daily_limit_popup(self):
        """
        FIXED: Verifică dacă s-a deschis o filă nouă cu mesajul de limită zilnică după descărcare.
        EXCLUDERE EXPLICITĂ pentru about:blank și alte file normale de browser
        """
        try:
            current_handles = set(self.driver.window_handles)

            print(f"🔍 Verific {len(current_handles)} file deschise pentru limita zilnică...")

            # Verifică toate filele deschise pentru mesajul de limită
            for handle in current_handles:
                try:
                    self.driver.switch_to.window(handle)

                    # Obține URL-ul pentru debugging
                    current_url = self.driver.current_url

                    # SKIP EXPLICIT pentru about:blank și alte file normale de browser
                    if (current_url == "about:blank" or
                        current_url.startswith("chrome://") or
                        current_url.startswith("chrome-extension://") or
                        current_url.startswith("data:") or
                        not current_url or current_url.strip() == ""):
                        print(f"✅ Skip filă normală de browser: {current_url}")
                        continue

                    # Obține textul complet al paginii
                    body_text = self.driver.find_element(By.TAG_NAME, "body").text.strip()

                    # Obține sursa HTML pentru verificarea structurii
                    try:
                        page_source = self.driver.page_source
                    except:
                        page_source = ""

                    # DETECTOARE MULTIPLE pentru limita zilnică
                    limit_detected = False
                    detection_reason = ""

                    # 1. NOUA PAGINĂ: "Vezi Termeni de utilizare"
                    if ("Vezi" in body_text and
                        ("Termeni de utilizare" in body_text or "conditii-de-utilizare" in current_url)):
                        limit_detected = True
                        detection_reason = "NOUĂ PAGINĂ - Vezi Termeni de utilizare"

                    # 2. VECHEA PAGINĂ: "Daily download limit reached"
                    elif "Daily download limit reached" in body_text:
                        limit_detected = True
                        detection_reason = "VECHE PAGINĂ - Daily download limit reached"

                    # 3. DETECTARE PRIN URL: dacă URL-ul conține "conditii-de-utilizare"
                    elif "conditii-de-utilizare" in current_url:
                        limit_detected = True
                        detection_reason = "URL DETECTARE - conditii-de-utilizare"

                    # 4. DETECTARE PRIN LINK: caută linkul specific
                    elif "www.arcanum.com/ro/adt/conditii-de-utilizare" in body_text:
                        limit_detected = True
                        detection_reason = "LINK DETECTARE - arcanum.com conditii"

                    # 4. DETECTARE PRIN LINK: caută linkul specific
                    elif "www.arcanum.com/en/adt/terms-and-conditions" in body_text:
                        limit_detected = True
                        detection_reason = "LINK DETECTARE - arcanum.com conditii"

                    # 4. DETECTARE PRIN LINK: caută linkul specific
                    elif "www.arcanum.com/hu/adt/felhasznalasi-feltetelek" in body_text:
                        limit_detected = True
                        detection_reason = "LINK DETECTARE - arcanum.com conditii"

                    # 5. **NOUĂ DETECTARE**: Verifică structura HTML normală
                    elif page_source and not self._has_normal_html_structure(page_source):
                        # Verifică dacă e o pagină anormală (fără structura HTML standard)
                        # și dacă conținutul e suspect de mic sau conține cuvinte cheie
                        # DOAR dacă nu e about:blank (deja verificat mai sus)
                        if (len(body_text.strip()) < 500 and
                            (any(keyword in body_text.lower() for keyword in
                                ['limit', 'vezi', 'termeni', 'utilizare', 'download', 'reached', 'Download-Limit']) or
                             len(body_text.strip()) < 100)):
                            limit_detected = True
                            detection_reason = "STRUCTURĂ HTML ANORMALĂ - probabil pagină de limită"

                    # 6. DETECTARE GENERALĂ: pagină suspicioasă cu puțin conținut și "Vezi"
                    elif (len(body_text.strip()) < 200 and
                          "Vezi" in body_text and
                          len(body_text.split()) < 20):
                        limit_detected = True
                        detection_reason = "DETECTARE GENERALĂ - pagină suspicioasă cu 'Vezi'"

                    # DEBUGGING: Afișează conținutul suspicios
                    if (self._is_suspicious_page(body_text, current_url, page_source)):
                        html_structure_ok = self._has_normal_html_structure(page_source)
                        print(f"🔍 FILĂ SUSPICIOASĂ {handle}:")
                        print(f"   📄 URL: {current_url}")
                        print(f"   📝 Conținut ({len(body_text)} chars): '{body_text[:200]}{'...' if len(body_text) > 200 else ''}'")
                        print(f"   🏗️ Structură HTML normală: {html_structure_ok}")
                        print(f"   🎯 Detectat limit: {limit_detected} ({detection_reason})")

                    # ACȚIUNE: Dacă limita a fost detectată
                    if limit_detected:
                        print(f"🛑 LIMITĂ ZILNICĂ DETECTATĂ în filă: {handle}")
                        print(f"🔍 MOTIV: {detection_reason}")
                        print(f"📄 URL complet: {current_url}")
                        print(f"📝 Conținut complet filă:")
                        print(f"   '{body_text}'")
                        print(f"🏗️ Structură HTML: {self._has_normal_html_structure(page_source)}")

                        # Închide fila cu limita (dar doar dacă nu e singura filă)
                        if len(current_handles) > 1:
                            print(f"🗙 Închid fila cu limita: {handle}")
                            self.driver.close()

                            # Revine la prima filă disponibilă
                            if self.driver.window_handles:
                                self.driver.switch_to.window(self.driver.window_handles[0])
                                print(f"↩️ Revin la fila principală")
                        else:
                            print(f"⚠ Nu închid fila - este singura rămasă")

                        # Setează flag-ul și oprește procesarea
                        self.state["daily_limit_hit"] = True
                        self._save_state()
                        print(f"🛑 Flag daily_limit_hit setat în state.json")

                        return True

                except Exception as e:
                    print(f"⚠ Eroare la verificarea filei {handle}: {e}")
                    continue

            print(f"✅ Nu am detectat limita zilnică în {len(current_handles)} file")
            return False

        except Exception as e:
            print(f"❌ Eroare fatală în verificarea popup-ului de limită: {e}")
            import traceback
            traceback.print_exc()
            return False

    def detect_login_required(self):
        """Detectează dacă este necesară autentificarea"""
        try:
            page_source = self.driver.page_source
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            current_url = self.driver.current_url

            # Verifică dacă există mesajul de login required
            if "Accesarea documentelor necesită abonament" in body_text or "Accesarea documentelor necesită abonament" in page_source:
                print("🔐 Detectat: Este necesară autentificarea (mesaj)")
                return True

            # Verifică și prin URL
            if "/accounts/login/" in current_url:
                print("🔐 Detectat: Pagină de login (URL)")
                return True

            # Verifică dacă există input-urile de login în pagină (cazul când apare pagina de login în timpul download-ului)
            try:
                # Verifică dacă există input-ul pentru username
                username_input = self.driver.find_elements(By.CSS_SELECTOR, 
                    "input[type='text'][name='username'][id='id_username'], "
                    "input[type='text'][name='username'][placeholder*='E-mail sau nume utilizator'], "
                    "input[type='text'][name='username'][aria-label*='E-mail sau nume utilizator']")
                
                # Verifică dacă există input-ul pentru password
                password_input = self.driver.find_elements(By.CSS_SELECTOR,
                    "input[type='password'][name='password'][id='id_password'], "
                    "input[type='password'][name='password'][placeholder*='Parolă'], "
                    "input[type='password'][name='password'][aria-label*='Parolă']")
                
                # Verifică dacă există butonul de submit "Conectare"
                submit_button = self.driver.find_elements(By.CSS_SELECTOR,
                    "input.btn.btn-primary[type='submit'][value='Conectare'], "
                    "input[type='submit'][value='Conectare']")
                
                # Dacă toate cele trei elemente sunt prezente, înseamnă că suntem pe pagina de login
                if username_input and password_input and submit_button:
                    print("🔐 Detectat: Pagină de login (input-uri de autentificare)")
                    return True
                    
            except Exception:
                pass  # Dacă nu găsește elementele, continuă cu alte verificări

            # Verifică și în page_source pentru cazurile când elementele nu sunt încă în DOM
            if ('id="id_username"' in page_source or 'name="username"' in page_source) and \
               ('id="id_password"' in page_source or 'name="password"' in page_source) and \
               ('value="Conectare"' in page_source or 'Conectare' in page_source):
                print("🔐 Detectat: Pagină de login (detectată în page_source)")
                return True

            return False

        except Exception as e:
            print(f"⚠ Eroare la detectarea login page: {e}")
            return False

    def handle_windows_auth_popup(self):
        """
        🔐 Gestionează pop-up-ul de autentificare Windows/Chrome

        Uneori Chrome cere autentificare Windows înainte de login.
        Avem 2 opțiuni:
        1. Închide pop-up-ul (ESC) și continuă cu login normal
        2. Completează parola Windows și continuă

        Returns: True dacă a reușit, False altfel
        """
        try:
            print("\n🔍 Verific dacă apare pop-up Windows de autentificare...")
            time.sleep(5)  # Așteaptă 2 secunde să apară eventualul pop-up

            # Încercăm să importăm pyautogui pentru interacțiunea cu Windows
            try:
                import pyautogui

                # OPȚIUNEA 1: Încearcă să închidă pop-up-ul cu ESC
                print("🔄 OPȚIUNEA 1: Încerc să închid pop-up-ul Windows cu ESC...")
                pyautogui.press('esc')
                time.sleep(1)

                # Verifică dacă pagina s-a încărcat normal
                try:
                    self.driver.find_element(By.TAG_NAME, "body")
                    print("✅ Pop-up închis cu succes - pagina accesibilă!")
                    return True
                except:
                    pass

                # OPȚIUNEA 2: Dacă ESC nu a funcționat, completează parola Windows
                print("🔄 OPȚIUNEA 2: Completez parola Windows...")
                print("⚠️  Dacă apare pop-up de autentificare Windows, completez automat...")

                # Așteaptă puțin
                time.sleep(1)

                # Scrie parola Windows
                windows_password = "_bebe@123##"
                pyautogui.write(windows_password, interval=0.1)
                time.sleep(0.5)

                # Apasă Enter pentru a confirma
                pyautogui.press('enter')
                time.sleep(2)

                print("✅ Parolă Windows introdusă și confirmată")
                return True

            except ImportError:
                print("⚠️  pyautogui nu este instalat - nu pot gestiona pop-up Windows automat")
                print("📋 Instalează cu: pip install pyautogui")
                print("⚠️  Dacă apare pop-up, închide-l manual sau introdu parola: _bebe@123##")
                time.sleep(3)  # Dă timp utilizatorului să intervină manual
                return True

        except Exception as e:
            print(f"⚠️  Eroare la gestionarea pop-up Windows: {e}")
            print("🔄 Continui oricum cu login-ul normal...")
            return True

    def perform_auto_login(self):
        """Efectuează login automat când este detectată pagina de autentificare"""
        try:
            print("\n" + "="*60)
            print("🔐 ÎNCEPUT LOGIN AUTOMAT")
            print("="*60)

            # PASUL 0: Gestionează pop-up-ul Windows de autentificare (dacă apare)
            print("\n🔐 PASUL 0: Verific pop-up Windows de autentificare...")
            self.handle_windows_auth_popup()

            current_url = self.driver.current_url
            page_source = self.driver.page_source

            # PASUL 1: Dacă suntem pe pagina cu mesaj, găsește linkul "Conectare" SAU navighează direct
            if "Accesarea documentelor necesită abonament" in page_source:
                print("📄 Detectat mesaj: 'Accesarea documentelor necesită abonament'")
                print("🔍 Caut linkul 'Conectare' sau navighez direct la pagina de login...")

                try:
                    # Extrage linkul din regex
                    import re
                    match = re.search(r'<a[^>]*href="(/ro/accounts/login/\?next=.*?)"[^>]*>Conectare</a>', page_source)

                    if match:
                        login_path = match.group(1)
                        # Decodifică URL-ul HTML
                        from html import unescape
                        login_path = unescape(login_path)
                        login_url = f"https://adt.arcanum.com{login_path}"
                        print(f"✅ Găsit link de conectare: {login_url}")
                    else:
                        # Fallback: caută elementul direct
                        try:
                            login_link = self.driver.find_element(By.XPATH,
                                "//a[contains(text(), 'Conectare') and contains(@href, '/accounts/login/')]")
                            login_url = login_link.get_attribute("href")
                            print(f"✅ Găsit link prin XPath: {login_url}")
                        except:
                            # Dacă nu găsește linkul, folosește URL-ul standard
                            login_url = "https://adt.arcanum.com/ro/accounts/login/?next=/ro/"
                            print(f"⚠ Nu am găsit link specific, folosesc URL standard: {login_url}")

                    # Navighează la pagina de login
                    self.driver.get(login_url)
                    print("✅ Navigat la pagina de login")
                    time.sleep(2)

                except Exception as e:
                    print(f"⚠ Eroare la găsirea linkului, încerc navigare directă: {e}")
                    self.driver.get("https://adt.arcanum.com/ro/accounts/login/?next=/ro/")
                    time.sleep(2)

            # PASUL 2: Verifică că suntem pe pagina de login SAU dacă deja avem input-urile de login
            current_url = self.driver.current_url
            page_source = self.driver.page_source
            
            # Verifică dacă suntem pe pagina de login sau dacă avem input-urile de login în pagină
            is_login_page = "/accounts/login/" in current_url
            has_login_inputs = ('id="id_username"' in page_source or 'name="username"' in page_source) and \
                              ('id="id_password"' in page_source or 'name="password"' in page_source)
            
            if not is_login_page and not has_login_inputs:
                print(f"❌ Nu sunt pe pagina de login! URL curent: {current_url}")
                print("🔄 Navighez explicit la pagina de login...")
                self.driver.get("https://adt.arcanum.com/ro/accounts/login/?next=/ro/")
                time.sleep(2)
                current_url = self.driver.current_url

            print(f"✅ Sunt pe pagina de login: {current_url}")

            # PASUL 3: AȘTEAPTĂ 5 SECUNDE pentru autocomplete
            print("⏳ Aștept 5 secunde pentru încărcarea automată a datelor salvate...")
            time.sleep(5)

            # PASUL 4: Găsește și completează câmpurile
            print("🔍 Caut câmpurile de autentificare...")

            try:
                username_field = self.wait.until(
                    EC.presence_of_element_located((By.ID, "id_username"))
                )
                password_field = self.driver.find_element(By.ID, "id_password")

                print("✅ Găsite câmpurile de login")

                # Verifică dacă sunt populate automat
                current_username = username_field.get_attribute("value")
                current_password = password_field.get_attribute("value")

                if current_username and current_password:
                    print(f"✅ Câmpurile sunt deja populate automat!")
                    print(f"   Username: {current_username}")
                    print(f"   Parolă: {'*' * len(current_password)} ({len(current_password)} caractere)")
                else:
                    print("📝 Completez manual credențialele...")

                    if not current_username:
                        username_field.clear()
                        username_field.send_keys("vascaraus@gmail.com")
                        print("✅ Username completat")

                    if not current_password:
                        password_field.clear()
                        password_field.send_keys("ZCf8Z2Fx54L9v!L")
                        print("✅ Parolă completată")

                # PASUL 5: Așteaptă puțin și apoi submit
                time.sleep(1)

                print("🔍 Caut butonul de 'Conectare'...")
                submit_button = self.driver.find_element(
                    By.CSS_SELECTOR,
                    "input.btn.btn-primary[type='submit'][value='Conectare']"
                )

                print("✅ Găsit butonul de Conectare")
                print("🔐 Trimit formularul de login...")

                submit_button.click()

                # PASUL 6: Așteaptă finalizarea login-ului
                print("⏳ Aștept finalizarea login-ului (10 secunde conform cerințelor)...")
                time.sleep(10)

                # PASUL 7: Verifică succesul login-ului
                final_url = self.driver.current_url

                if "/accounts/login/" not in final_url:
                    print("="*60)
                    print("✅ LOGIN REUȘIT!")
                    print(f"🔗 Redirecționat către: {final_url}")
                    print("⏳ Aștept 10 secunde înainte de a reia download-ul...")
                    time.sleep(10)
                    print("="*60 + "\n")
                    return True
                else:
                    # Verifică mesaje de eroare
                    body_text = self.driver.find_element(By.TAG_NAME, "body").text
                    print("="*60)
                    print("❌ LOGIN EȘUAT - Încă pe pagina de login")

                    if "utilizator" in body_text.lower() or "password" in body_text.lower() or "parolă" in body_text.lower():
                        print("⚠ Posibil mesaj de eroare în pagină")
                        print(f"📄 Fragment din pagină: {body_text[:200]}")

                    print("="*60 + "\n")
                    return False

            except Exception as e:
                print("="*60)
                print(f"❌ Eroare la completarea formularului: {e}")
                print("="*60 + "\n")
                import traceback
                traceback.print_exc()
                return False

        except Exception as e:
            print("="*60)
            print(f"❌ Eroare generală în perform_auto_login: {e}")
            print("="*60 + "\n")
            import traceback
            traceback.print_exc()
            return False

    def close_security_popups(self):
        """Închide automat pop-up-urile de securitate, DAR NU pagina de limită zilnică"""
        try:
            print("🔍 Verific dacă s-au deschis pop-up-uri de securitate...")

            # Salvează handle-ul ferestrei principale
            main_window = self.driver.current_window_handle
            all_windows = self.driver.window_handles

            # Verifică dacă s-au deschis ferestre noi
            if len(all_windows) > 1:
                for window in all_windows:
                    if window != main_window:
                        try:
                            # Comută la fereastra nouă
                            self.driver.switch_to.window(window)

                            # Verifică dacă e pop-up de securitate
                            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
                            current_url = self.driver.current_url

                            # VERIFICĂ PRIMA DATĂ DACĂ E PAGINA DE LIMITĂ ZILNICĂ - NU O ÎNCHIDE!
                            daily_limit_indicators = [
                                "vezi termeni de utilizare",
                                "daily download limit reached",
                                "conditii-de-utilizare",
                                "terms and conditions"
                            ]

                            is_daily_limit = any(indicator in page_text for indicator in daily_limit_indicators)
                            is_daily_limit_url = "conditii-de-utilizare" in current_url

                            if is_daily_limit or is_daily_limit_url:
                                print(f"🛑 DETECTAT PAGINA DE LIMITĂ ZILNICĂ - NU O ÎNCHID!")
                                print(f"📄 URL: {current_url}")
                                print(f"📝 Conținut: {page_text[:100]}...")
                                # NU închide această pagină - lasă scriptul să o detecteze
                                continue

                            # Detectează DOAR pop-up-uri de securitate normale (nu limita zilnică)
                            security_indicators = [
                                "let's confirm you are human",
                                "complete the security check",
                                "verify that you are not a bot",
                                "security check",
                                "javascript is disabled",
                                "human verification"
                            ]

                            # Verifică conținutul pentru pop-up-uri de securitate (dar nu limită zilnică)
                            is_security_popup = any(indicator in page_text for indicator in security_indicators)

                            if is_security_popup:
                                print(f"🔒 Detectat pop-up de securitate în fereastra: {window}")
                                print(f"📄 URL: {current_url}")

                                # 🚨 VERIFICARE CRITICĂ: Este CAPTCHA REAL?
                                # Detectează 2 tipuri de CAPTCHA:
                                # Tip 1: "Let's confirm you are human" + butonul "amzn-captcha-verify-button"
                                # Tip 2: "Human Verification" cu "JavaScript is disabled"
                                try:
                                    page_source = self.driver.page_source

                                    # CAPTCHA Tip 1: Text + Buton
                                    has_captcha_text = (
                                        '<h1 style="font-weight: normal; color: rgb(221, 107, 16);">Let\'s confirm you are human</h1>' in page_source or
                                        'Let\'s confirm you are human' in page_source
                                    ) and ('Complete the security check before continuing' in page_source)

                                    has_captcha_button = False
                                    try:
                                        captcha_button = self.driver.find_element(By.ID, "amzn-captcha-verify-button")
                                        if captcha_button:
                                            has_captcha_button = True
                                    except:
                                        pass

                                    # CAPTCHA Tip 2: Human Verification
                                    has_human_verification = (
                                        '<title>Human Verification</title>' in page_source and
                                        'JavaScript is disabled' in page_source and
                                        'you need to verify that you\'re not a robot by solving a CAPTCHA puzzle' in page_source
                                    )

                                    # CAPTCHA REAL detectat?
                                    if (has_captcha_text and has_captcha_button) or has_human_verification:
                                        captcha_type = ""
                                        if has_captcha_text and has_captcha_button:
                                            captcha_type = "Tip 1: Text + Buton CAPTCHA"
                                        elif has_human_verification:
                                            captcha_type = "Tip 2: Human Verification"

                                        # Determină segment key pentru tracking retry
                                        segment_key = f"{self.current_issue_url}_current_segment"
                                        retry_count = self.captcha_retry_count.get(segment_key, 0)

                                        print(f"\n{'='*60}")
                                        print(f"🚨 CAPTCHA DETECTAT ÎN POP-UP!")
                                        print(f"{'='*60}")
                                        print(f"📋 URL CAPTCHA: {current_url}")
                                        print(f"✅ Tip: {captcha_type}")
                                        print(f"🔢 Detectare #: {retry_count + 1}/{self.captcha_max_retries + 1}")

                                        if retry_count < self.captcha_max_retries:
                                            # DETECTARE cu RETRY - Pauză și reîncearcă
                                            print(f"\n⏸️ DETECTARE CAPTCHA #{retry_count + 1} - PAUZĂ TEMPORARĂ")
                                            print(f"🔄 Strategie: Aștept {self.captcha_wait_minutes} minute și reîncerc")
                                            print(f"💡 Motivație: CAPTCHA expiră după ~{self.captcha_wait_minutes} minute")
                                            print(f"📊 Încercări rămase: {self.captcha_max_retries - retry_count}")

                                            # Marchează retry (incrementează counter-ul)
                                            self.captcha_retry_count[segment_key] = retry_count + 1

                                            # Închide fereastra cu CAPTCHA
                                            try:
                                                print(f"🚪 Închid fereastra cu CAPTCHA...")
                                                self.driver.close()
                                                if self.driver.window_handles:
                                                    self.driver.switch_to.window(self.driver.window_handles[0])
                                                print(f"✅ Fereastră închisă")
                                            except Exception as e:
                                                print(f"⚠ Eroare la închidere fereastră: {e}")

                                            # Așteaptă 4 minute
                                            wait_seconds = self.captcha_wait_minutes * 60
                                            print(f"\n⏳ Aștept {self.captcha_wait_minutes} minute ({wait_seconds} secunde)...")
                                            print(f"⏰ Timpul curent: {datetime.now().strftime('%H:%M:%S')}")

                                            for remaining in range(wait_seconds, 0, -30):
                                                mins = remaining // 60
                                                secs = remaining % 60
                                                print(f"⏳ Timp rămas: {mins}m {secs}s...")
                                                time.sleep(30)

                                            print(f"⏰ Timpul final: {datetime.now().strftime('%H:%M:%S')}")
                                            print(f"✅ Așteptare completă! Reîncerc segmentul...")
                                            print(f"{'='*60}\n")

                                            # Setează flag pentru retry
                                            self.captcha_retry_needed = True
                                            return  # Iese din close_security_popups()

                                        else:
                                            # ULTIMA DETECTARE - Oprește definitiv
                                            print(f"\n🛑 DETECTARE CAPTCHA #{retry_count + 1} - OPRIRE DEFINITIVĂ")
                                            print(f"⚠️ CAPTCHA persistă după {retry_count} retry-uri")
                                            print(f"⚠️ Am așteptat {retry_count * self.captcha_wait_minutes} minute total")
                                            print(f"⚠️ Trebuie intervenție manuală obligatorie!")

                                            # Reset counter
                                            self.captcha_retry_count[segment_key] = 0

                                            # Salvează starea
                                            print(f"💾 Salvez progresul...")
                                            self.state["captcha_detected"] = True
                                            self.state["captcha_url"] = current_url
                                            self._save_state()

                                            print(f"\n🛑 SCRIPTUL A FOST OPRIT DEFINITIV")
                                            print(f"📋 URL CAPTCHA: {current_url}")
                                            print(f"📋 Progresul salvat în state.json")
                                            print(f"⚠️ ACȚIUNE NECESARĂ: Rezolvă CAPTCHA manual în browser")
                                            print(f"{'='*60}\n")
                                            raise SystemExit("🚨 OPRIRE DEFINITIVĂ - CAPTCHA persistent, intervenție manuală necesară!")
                                    elif has_captcha_text and not has_captcha_button:
                                        print(f"ℹ️ Pop-up cu text similar CAPTCHA dar FĂRĂ butonul CAPTCHA")
                                        print(f"ℹ️ Probabil pagină de download (check-access-save) - nu e CAPTCHA real")
                                except Exception as e:
                                    print(f"⚠ Eroare la verificarea conținutului CAPTCHA: {e}")

                                print("⏳ Aștept 2 secunde apoi îl închid...")
                                time.sleep(3)

                                # Închide pop-up-ul normal de securitate (non-CAPTCHA)
                                self.driver.close()
                                print("✅ Pop-up de securitate închis automat")
                            else:
                                print(f"ℹ️ Fereastră nouă detectată dar nu e pop-up de securitate sau e pagină importantă")

                        except Exception as e:
                            print(f"⚠ Eroare la verificarea ferestrei {window}: {e}")

            # Revine la fereastra principală
            try:
                self.driver.switch_to.window(main_window)
            except:
                if self.driver.window_handles:
                    self.driver.switch_to.window(self.driver.window_handles[0])

        except Exception as e:
            print(f"⚠ Eroare în close_security_popups: {e}")


    def _has_normal_html_structure(self, page_source):
        """
        FIXED: Verifică dacă pagina are structura HTML normală specifică site-ului Arcanum.
        IMPORTANT: Chrome page_source nu întotdeauna include DOCTYPE, deci nu ne bazăm pe el!
        """
        if not page_source:
            return False

        # Normalizează spațiile și new lines pentru verificare
        normalized_source = ' '.join(page_source.strip().split())
        normalized_start = normalized_source[:500].lower()

        # INDICATORI POZITIVI pentru pagini normale Arcanum
        normal_indicators = [
            'html lang="ro"',                    # Toate paginile Arcanum au asta
            '<title>',                           # Toate au titlu
            '<head>',                           # Toate au head
            'ziarele arcanum',                  # În titlu
            'meta charset="utf-8"',             # Meta charset standard
            'meta name="viewport"'              # Meta viewport standard
        ]

        # INDICATORI NEGATIVI pentru pagini de limită/eroare
        limit_indicators = [
            'vezi',                             # "Vezi Termeni de utilizare"
            'conditii-de-utilizare',            # URL sau link către condiții
            'daily download limit',             # Vechiul mesaj
            'terms and conditions'              # Versiunea engleză
        ]

        # Contorizează indicatorii pozitivi
        positive_count = sum(1 for indicator in normal_indicators
                            if indicator in normalized_start)

        # Contorizează indicatorii negativi
        negative_count = sum(1 for indicator in limit_indicators
                            if indicator in normalized_start)

        # Verifică dimensiunea - paginile de limită sunt foarte mici
        is_too_small = len(normalized_source) < 300

        # LOGICA DE DECIZIE:
        # 1. Dacă are indicatori negativi ȘI e mică → pagină de limită
        if negative_count > 0 and is_too_small:
            print(f"🚨 PAGINĂ DE LIMITĂ detectată:")
            print(f"   Indicatori negativi: {negative_count}")
            print(f"   Dimensiune: {len(normalized_source)} chars")
            print(f"   Conținut: '{normalized_source[:200]}'")
            return False

        # 2. Dacă are suficienți indicatori pozitivi → pagină normală
        if positive_count >= 4:  # Cel puțin 4 din 6 indicatori pozitivi
            return True

        # 3. Dacă e foarte mică și fără indicatori pozitivi → suspicioasă
        if is_too_small and positive_count < 2:
            print(f"🔍 PAGINĂ SUSPICIOASĂ (prea mică și fără indicatori):")
            print(f"   Indicatori pozitivi: {positive_count}/6")
            print(f"   Dimensiune: {len(normalized_source)} chars")
            print(f"   Conținut: '{normalized_source[:200]}'")
            return False

        # 4. În toate celelalte cazuri → consideră normală
        return True

    def _is_suspicious_page(self, body_text, url, page_source):
        """
        FIXED: Helper mai inteligent pentru a determina dacă o pagină merită debugging
        EXCLUDERE EXPLICITĂ pentru about:blank și alte file normale de browser
        """

        # EXCLUDERE EXPLICITĂ pentru about:blank și alte file normale de browser
        if url == "about:blank" or "about:blank" in url:
            return False  # Nu e suspicioasă - e pagină normală de browser

        # Exclude și alte URL-uri normale de Chrome
        if url.startswith("chrome://") or url.startswith("chrome-extension://"):
            return False

        # Exclude URL-urile goale sau None
        if not url or url.strip() == "":
            return False

        # Indicatori clari de pagini problematice
        clear_limit_signs = [
            "Vezi" in body_text and len(body_text) < 200,
            "conditii" in body_text.lower(),
            "limit" in body_text.lower() and len(body_text) < 500,
            "daily download" in body_text.lower()
        ]

        # Pagini foarte mici sunt întotdeauna suspicioase DOAR dacă nu sunt about:blank
        too_small = len(body_text.strip()) < 100

        # NU detecta ca suspicioase paginile normale mari
        is_normal_arcanum = (
            len(body_text) > 500 and
            "Analele" in body_text and
            ("Universității" in body_text or "Matematică" in body_text)
        )

        if is_normal_arcanum:
            return False  # Nu e suspicioasă - e pagină normală Arcanum

        return any(clear_limit_signs) or too_small

    def save_page_range(self, start, end, retries=1):
        """FIXED: Verifică URL-ul + verifică limita zilnică + verifică login + închide pop-up-urile automat + retry după CAPTCHA"""
        for attempt in range(1, retries + 2):
            print(f"🔄 Încep segmentul {start}-{end}, încercarea {attempt}")

            # Așteaptă ca pagina să fie complet încărcată înainte de a începe (delay pentru securitate site)
            if attempt == 1:
                print("⏳ Aștept 2 secunde pentru încărcarea completă a paginii înainte de descărcare...")
                time.sleep(2)
            else:
                # Pentru retry-uri, așteaptă mai mult
                print("⏳ Aștept 3 secunde înainte de retry...")
                time.sleep(3)

            # VERIFICARE 1: Suntem pe documentul corect?
            try:
                current_url = self.driver.current_url
                # Verifică dacă URL-ul e valid (nu e chrome:// sau about:)
                if current_url.startswith('chrome://') or current_url.startswith('about:'):
                    print(f"🚨 EROARE: Browser-ul este pe o pagină internă Chrome!")
                    print(f"   Actual: {current_url}")
                    print(f"🔄 Renavigez la documentul corect...")
                    if not self.navigate_to_page(self.current_issue_url):
                        print(f"❌ Nu pot renaviga la {self.current_issue_url}")
                        if attempt < retries + 1:
                            continue  # Reîncearcă
                        return False
                    time.sleep(3)
                    print(f"✅ Renavigat cu succes la documentul corect")
                elif self.current_issue_url not in current_url:
                    print(f"🚨 EROARE: Browser-ul a navigat la URL greșit!")
                    print(f"   Așteptat: {self.current_issue_url}")
                    print(f"   Actual: {current_url}")
                    print(f"🔄 Renavigez la documentul corect...")

                    if not self.navigate_to_page(self.current_issue_url):
                        print(f"❌ Nu pot renaviga la {self.current_issue_url}")
                        if attempt < retries + 1:
                            continue  # Reîncearcă
                        return False

                    time.sleep(3)  # Delay mărit după renavigare
                    print(f"✅ Renavigat cu succes la documentul corect")
            except Exception as e:
                print(f"⚠ Eroare la verificarea URL-ului: {e}")
                # Încercă renavigare preventivă
                if attempt < retries + 1:
                    print("🔄 Încerc renavigare preventivă...")
                    try:
                        if self.navigate_to_page(self.current_issue_url):
                            time.sleep(3)
                            continue
                    except:
                        pass

            # VERIFICARE 2: Este nevoie de login?
            if self.detect_login_required():
                print("🔐 DETECTAT: Este necesară autentificarea!")
                print("🔄 Încerc login automat...")

                login_success = self.perform_auto_login()

                if not login_success:
                    print("❌ LOGIN EȘUAT - Opresc descărcarea")
                    print("⏸️ PAUZĂ NECESARĂ - Verifică manual credențialele!")
                    return False

                print("✅ Login reușit - aștept 10 secunde înainte de a reia download-ul...")
                time.sleep(10)
                print("🔄 Renavigez la document...")

                # După login, renavigăm la documentul original
                if not self.navigate_to_page(self.current_issue_url):
                    print(f"❌ Nu pot renaviga la {self.current_issue_url} după login")
                    return False

                time.sleep(3)
                print("✅ Renavigat cu succes după login")

            # 🔧 VERIFICARE 1: MENTENANȚĂ (403 Forbidden)
            if self.detect_403_maintenance():
                print(f"⚠️ Detectat 403 la segmentul {start}-{end} - Arcanum în mentenanță")

                # Așteaptă finalul mentenanței
                if self.wait_for_maintenance(wait_minutes=10, max_retries=3):
                    print(f"✅ Mentenanță finalizată - reîncerc segmentul {start}-{end}")
                    # Renavigăm la documentul corect după mentenanță
                    if not self.navigate_to_page(self.current_issue_url):
                        print(f"❌ Nu pot renaviga după mentenanță")
                        return False
                    time.sleep(3)
                    # Continuă cu încercarea curentă
                else:
                    print(f"❌ Mentenanță prea lungă - abandonez segmentul {start}-{end}")
                    return False

            # 🚨 VERIFICARE 2: CAPTCHA
            if self.detect_captcha():
                print(f"\n{'='*60}")
                print(f"🚨🚨🚨 CAPTCHA DETECTAT ÎN TIMPUL DESCĂRCĂRII! 🚨🚨🚨")
                print(f"{'='*60}")
                print(f"❌ CAPTCHA detectat la segmentul {start}-{end}")
                print(f"💾 Salvez progresul și opresc scriptul...")
                self.state["captcha_detected"] = True
                self.state["captcha_url"] = self.driver.current_url
                self._save_state()
                raise SystemExit("🚨 OPRIRE CAPTCHA - Verificare umană necesară!")

            # Continuă cu logica existentă...
            if not self.open_save_popup():
                print(f"⚠ Eșec la deschiderea popup-ului pentru {start}-{end}")
                time.sleep(2)
                continue

            success = self.fill_and_save_range(start, end)
            if success:
                print("⏳ Aștept 4 secunde pentru inițierea descărcării (delay securitate site)...")
                time.sleep(4)

                # Închide automat pop-up-urile de securitate
                self.captcha_retry_needed = False  # Reset flag
                self.close_security_popups()

                # Verifică dacă trebuie retry după CAPTCHA
                if self.captcha_retry_needed:
                    print(f"🔄 CAPTCHA retry flag detectat - reîncerc segmentul {start}-{end}")
                    continue  # Reîncearcă segmentul

                print("⏳ Aștept 5 secunde pentru finalizarea descărcării segmentului (delay securitate site)...")
                time.sleep(3)

                # Verifică limita zilnică IMEDIAT DUPĂ descărcare
                if self.check_for_daily_limit_popup():
                    print(f"🛑 OPRIRE INSTANT - Limită zilnică detectată după segmentul {start}-{end}")
                    return False

                print(f"✅ Segmentul {start}-{end} descărcat cu succes")

                # Resetează counter-ul CAPTCHA pentru acest segment (dacă exista)
                segment_key = f"{self.current_issue_url}_current_segment"
                if segment_key in self.captcha_retry_count:
                    print(f"✅ Reset counter CAPTCHA pentru segment (era la {self.captcha_retry_count[segment_key]})")
                    self.captcha_retry_count[segment_key] = 0

                # VERIFICARE CRITICĂ: Asigură-te că rămânem pe URL-ul corect după descărcare
                try:
                    time.sleep(2)  # Așteaptă puțin pentru ca pagina să se stabilizeze
                    try:
                        current_url = self.driver.current_url
                    except Exception as url_error:
                        # Eroare "Browsing context has been discarded" - nu crea instanță nouă
                        if "discarded" in str(url_error) or "NoSuchWindow" in str(type(url_error).__name__):
                            print(f"⚠ Context browser închis - aștept stabilizare...")
                            time.sleep(3)
                            # Încearcă să recreeze driver-ul fără să pornească Firefox nou
                            try:
                                if hasattr(self, 'driver') and self.driver:
                                    # Verifică dacă Firefox procesul încă rulează
                                    import psutil
                                    firefox_running = False
                                    for proc in psutil.process_iter(['pid', 'name']):
                                        try:
                                            if 'firefox' in proc.info['name'].lower():
                                                firefox_running = True
                                                break
                                        except:
                                            continue

                                    if firefox_running:
                                        print("✅ Firefox încă rulează - aștept stabilizare...")
                                        time.sleep(5)
                                        # Nu crea instanță nouă - doar așteaptă
                                        return True
                            except:
                                pass
                        print(f"⚠ Eroare la verificarea URL-ului după descărcare: {url_error}")
                        return True  # Continuă oricum

                    if self.current_issue_url not in current_url or current_url.startswith('chrome://') or '?pg=' in current_url:
                        print(f"⚠ URL s-a schimbat după descărcare: {current_url}")
                        print(f"🔄 Renavigez la URL-ul corect...")
                        if not self.navigate_to_page(self.current_issue_url):
                            print(f"❌ Nu pot renaviga după descărcare - va eșua la următorul segment")
                            # Return True oricum pentru că descărcarea a reușit
                        else:
                            print(f"✅ Renavigat după descărcare - aștept stabilizare...")
                            time.sleep(5)  # Delay mărit după renavigare pentru stabilizare completă

                            # Verifică din nou că suntem pe URL-ul corect
                            try:
                                final_url = self.driver.current_url
                                if self.current_issue_url not in final_url:
                                    print(f"⚠ URL încă greșit după renavigare: {final_url}")
                                    print(f"🔄 Reîncerc renavigarea...")
                                    self.navigate_to_page(self.current_issue_url)
                                    time.sleep(3)
                            except Exception:
                                # Ignoră eroarea - continuă oricum
                                pass
                except Exception as e:
                    print(f"⚠ Eroare la verificarea URL-ului după descărcare: {e}")

                return True
            else:
                print(f"⚠ Retry pentru segmentul {start}-{end}")
                time.sleep(2)

        print(f"❌ Renunț la segmentul {start}-{end} după {retries+1} încercări.")
        return False

    def save_all_pages_in_batches(self, resume_from=1):
        """FIXED: Refă segmentele incomplete în loc să continue din mijloc"""
        total = self.get_total_pages()
        if total <= 0:
            print("⚠ Nu am obținut numărul total de pagini; nu pot continua.")
            return 0, False

        print(f"🎯 TOTAL PAGINI DETECTAT: {total}")

        bs = self.batch_size  # 50

        # PASUL 1: Calculează segmentele standard
        all_segments = []

        # Primul segment: 1 până la bs-1 (1-49)
        first_end = min(bs - 1, total)
        if first_end >= 1:
            all_segments.append((1, first_end))

        # Segmentele următoare: bs, bs*2-1, etc. (50-99, 100-149, etc.)
        current = bs
        while current <= total:
            end = min(current + bs - 1, total)
            all_segments.append((current, end))
            current += bs

        print(f"📊 SEGMENTE STANDARD CALCULATE: {len(all_segments)}")
        for i, (start, end) in enumerate(all_segments):
            print(f"   {i+1}. Segment {start}-{end}")

        # PASUL 2: Verifică ce segmente sunt COMPLET descărcate pe disk
        completed_segments = []

        for i, (seg_start, seg_end) in enumerate(all_segments):
            # Verifică dacă există un fișier care acoperă COMPLET segmentul
            segments_on_disk = self.get_all_pdf_segments_for_issue(self.current_issue_url)

            segment_complete = False
            for disk_seg in segments_on_disk:
                disk_start = disk_seg['start']
                disk_end = disk_seg['end']

                # Verifică dacă segmentul de pe disk acoperă COMPLET segmentul standard
                if disk_start <= seg_start and disk_end >= seg_end:
                    segment_complete = True
                    print(f"✅ Segment {i+1} ({seg_start}-{seg_end}) COMPLET pe disk: {disk_seg['filename']}")
                    break

            if segment_complete:
                completed_segments.append(i)
            else:
                # Verifică dacă există fișiere parțiale pentru acest segment
                partial_files = [seg for seg in segments_on_disk
                               if seg['start'] >= seg_start and seg['end'] <= seg_end]
                if partial_files:
                    print(f"⚠ Segment {i+1} ({seg_start}-{seg_end}) PARȚIAL pe disk:")
                    for pf in partial_files:
                        print(f"   📄 {pf['filename']} (pagini {pf['start']}-{pf['end']}) - VA FI REFĂCUT")
                else:
                    print(f"🆕 Segment {i+1} ({seg_start}-{seg_end}) lipsește complet")

        # PASUL 3: Începe cu primul segment incomplet
        start_segment_index = 0
        for i in range(len(all_segments)):
            if i not in completed_segments:
                start_segment_index = i
                break
        else:
            # Toate segmentele sunt complete
            print("✅ Toate segmentele sunt complete pe disk!")
            return total, False

        print(f"🎯 ÎNCEP cu segmentul {start_segment_index + 1} (primul incomplet)")

        # PASUL 4: Procesează segmentele începând cu primul incomplet
        segments_to_process = all_segments[start_segment_index:]

        print(f"🎯 PROCESEZ {len(segments_to_process)} segmente începând cu segmentul {start_segment_index + 1}")

        # PASUL 5: ȘTERGE fișierele parțiale pentru segmentele care vor fi refăcute
        for i, (seg_start, seg_end) in enumerate(segments_to_process):
            actual_index = start_segment_index + i
            if actual_index not in completed_segments:
                # Șterge fișierele parțiale pentru acest segment
                segments_on_disk = self.get_all_pdf_segments_for_issue(self.current_issue_url)
                for disk_seg in segments_on_disk:
                    if disk_seg['start'] >= seg_start and disk_seg['end'] <= seg_end:
                        try:
                            os.remove(disk_seg['path'])
                            print(f"🗑️ ȘTERG fișier parțial: {disk_seg['filename']}")
                        except Exception as e:
                            print(f"⚠ Nu am putut șterge {disk_seg['filename']}: {e}")

        # PASUL 5.5: RE-SCANEAZĂ disk-ul DUPĂ ștergere pentru a vedea ce există ACUM
        print(f"\n🔍 RE-SCANEZ disk-ul după ștergerea fișierelor parțiale...")
        segments_on_disk_now = self.get_all_pdf_segments_for_issue(self.current_issue_url)

        # Re-calculează segmentele complete ACUM (după ștergere)
        completed_segments_now = []
        for i, (seg_start, seg_end) in enumerate(all_segments):
            segment_complete = False
            for disk_seg in segments_on_disk_now:
                disk_start = disk_seg['start']
                disk_end = disk_seg['end']

                if disk_start <= seg_start and disk_end >= seg_end:
                    segment_complete = True
                    completed_segments_now.append(i)
                    print(f"✅ Segment {i+1} ({seg_start}-{seg_end}) EXISTĂ ACUM pe disk: {disk_seg['filename']}")
                    break

            if not segment_complete:
                print(f"❌ Segment {i+1} ({seg_start}-{seg_end}) LIPSEȘTE - va fi descărcat")

        # Re-calculează segments_to_process bazat pe ce există ACUM
        actual_segments_to_download = []
        for i in range(len(all_segments)):
            if i not in completed_segments_now:
                actual_segments_to_download.append(all_segments[i])

        if not actual_segments_to_download:
            print("✅ Toate segmentele sunt complete după re-scanare!")
            return total, False

        print(f"\n🎯 După re-scanare: trebuie să descarc {len(actual_segments_to_download)} segmente lipsă")
        for seg_start, seg_end in actual_segments_to_download[:5]:  # Afișează primele 5
            print(f"   📥 Segment de descărcat: {seg_start}-{seg_end}")
        if len(actual_segments_to_download) > 5:
            print(f"   ... și încă {len(actual_segments_to_download) - 5} segmente")

        # Calculează last_successful_page bazat pe ultimul segment complet
        last_successful_page = 0
        if completed_segments_now:
            max_completed_index = max(completed_segments_now)
            last_successful_page = all_segments[max_completed_index][1]
            print(f"📊 Ultimul segment complet: index {max_completed_index}, pagina {last_successful_page}")

        # PASUL 6: Descarcă DOAR segmentele care lipsesc ACUM
        failed_segments = []
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 3

        for i, (start, end) in enumerate(actual_segments_to_download):
            print(f"📦 Procesez segmentul LIPSĂ {start}-{end} ({i+1}/{len(actual_segments_to_download)})")

            # VERIFICARE CRITICĂ: Asigură-te că suntem pe URL-ul corect înainte de fiecare segment
            if i > 0:  # Nu e nevoie pentru primul segment
                try:
                    current_url = self.safe_get_current_url()
                    if current_url is None:
                        # Context browser închis - așteaptă stabilizare fără să creeze instanță nouă
                        print(f"⚠ Context browser închis înainte de segment {start}-{end} - aștept stabilizare...")
                        time.sleep(5)
                        # Încearcă să renavigheze fără să creeze instanță nouă
                        try:
                            if hasattr(self, 'driver') and self.driver:
                                self.driver.get(self.current_issue_url)
                                time.sleep(3)
                        except:
                            # Dacă nu funcționează, continuă oricum
                            pass
                        current_url = self.safe_get_current_url()

                    # Verifică dacă URL-ul e greșit sau conține parametri care indică o pagină diferită
                    if current_url and (self.current_issue_url not in current_url or
                        current_url.startswith('chrome://') or
                        '?pg=' in current_url or
                        '/?layout=' in current_url):
                        print(f"⚠ URL greșit detectat înainte de segment {start}-{end}: {current_url}")
                        print(f"🔄 Renavigez la URL-ul corect...")
                        if not self.navigate_to_page(self.current_issue_url):
                            print(f"❌ Nu pot renaviga la {self.current_issue_url}")
                            failed_segments.append((start, end))
                            consecutive_failures += 1
                            continue
                        print(f"✅ Renavigat cu succes - aștept stabilizare...")
                        time.sleep(5)  # Delay mărit după renavigare pentru stabilizare completă

                        # Verifică din nou că suntem pe URL-ul corect
                        verify_url = self.safe_get_current_url()
                        if verify_url and self.current_issue_url not in verify_url:
                            print(f"⚠ URL încă greșit după renavigare: {verify_url}")
                            print(f"🔄 Reîncerc renavigarea...")
                            self.navigate_to_page(self.current_issue_url)
                            time.sleep(3)
                except Exception as e:
                    print(f"⚠ Eroare la verificarea URL-ului: {e}")
                    # Nu crea instanță nouă - doar așteaptă și continuă
                    time.sleep(3)
                    # Încearcă renavigare preventivă fără să creeze instanță nouă
                    try:
                        if hasattr(self, 'driver') and self.driver:
                            self.driver.get(self.current_issue_url)
                            time.sleep(3)
                    except:
                        pass

            # Încercă să descarce segmentul cu retry
            result = self.save_page_range(start, end, retries=3)

            if result:
                # SUCCES: Adaug delay mai mare între segmente pentru stabilizare
                print(f"✅ Segmentul {start}-{end} descărcat cu succes")
                consecutive_failures = 0  # Reset counter la succes

                # Delay critic între segmente pentru ca site-ul să se stabilizeze
                if i < len(actual_segments_to_download) - 1:  # Nu e ultimul segment
                    print(f"⏳ Aștept 8 secunde între segmente pentru stabilizare (delay securitate site)...")
                    time.sleep(8)

                    # Verifică din nou URL-ul după delay
                    try:
                        current_url = self.driver.current_url
                        if (self.current_issue_url not in current_url or
                            current_url.startswith('chrome://') or
                            '?pg=' in current_url or
                            '/?layout=' in current_url):
                            print(f"⚠ URL s-a schimbat după delay: {current_url}")
                            print(f"🔄 Renavigez la URL-ul corect...")
                            if not self.navigate_to_page(self.current_issue_url):
                                print(f"❌ Nu pot renaviga după delay")
                                # Continuă oricum, dar va eșua la următorul segment
                            else:
                                print(f"✅ Renavigat după delay - aștept stabilizare...")
                                time.sleep(5)  # Delay mărit pentru stabilizare completă

                                # Verifică din nou că suntem pe URL-ul corect
                                verify_url = self.driver.current_url
                                if self.current_issue_url not in verify_url:
                                    print(f"⚠ URL încă greșit după renavigare: {verify_url}")
                                    print(f"🔄 Reîncerc renavigarea...")
                                    self.navigate_to_page(self.current_issue_url)
                                    time.sleep(3)
                    except Exception as e:
                        print(f"⚠ Eroare la verificarea URL-ului după delay: {e}")
            else:
                if self.state.get("daily_limit_hit", False):
                    print(f"🛑 OPRIRE - Limită zilnică atinsă la segmentul {start}-{end}")
                    return last_successful_page, True

                print(f"❌ SEGMENT EȘUAT: {start}-{end}")
                failed_segments.append((start, end))
                consecutive_failures += 1

                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"🚨 PREA MULTE EȘECURI CONSECUTIVE ({consecutive_failures})")
                    print(f"🔄 ÎNCERC RECOVERY COMPLET...")

                    try:
                        # Recovery: Repornește Firefox complet
                        # setup_firefox_driver() va închide automat orice Firefox existent
                        print(f"🔄 Recovery: Repornesc Firefox...")
                        if not self.setup_chrome_driver(browser="firefox"):
                            print(f"❌ Recovery eșuat - opresc procesarea")
                            break
                        print(f"✅ Firefox repornit pentru recovery")

                        if not self.navigate_to_page(self.current_issue_url):
                            print(f"❌ Nu pot renaviga după recovery")
                            break

                        consecutive_failures = 0
                        print(f"✅ Recovery reușit - REÎNCERC segmentul eșuat {start}-{end}")
                        time.sleep(3)

                        # 🔥 REÎNCEARCĂ SEGMENTUL EȘUAT în loc să sară peste el
                        print(f"🔄 REÎNCERC: Segmentul {start}-{end} după recovery...")
                        retry_result = self.save_page_range(start, end, retries=3)

                        if retry_result:
                            print(f"✅ SUCCESS după recovery: Segmentul {start}-{end}")
                            # Elimină din failed_segments dacă reușește
                            if (start, end) in failed_segments:
                                failed_segments.remove((start, end))
                            # Actualizează progresul
                            last_successful_page = end
                            self._update_partial_issue_progress(self.current_issue_url, end, total_pages=total)
                            print(f"✅ Progres salvat: pagini până la {end}")
                        else:
                            print(f"❌ Segmentul {start}-{end} a eșuat din nou după recovery")
                            print(f"⏭️ Continui cu următorul segment...")

                    except Exception as e:
                        print(f"❌ Eroare în recovery: {e}")
                        break
                else:
                    print(f"🔄 Eșecuri consecutive: {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")
                    print(f"⏳ Continui cu următorul segment după pauză...")
                    time.sleep(2)

            # Actualizează progresul pentru segmentele reușite
            if result:
                last_successful_page = end
                self._update_partial_issue_progress(self.current_issue_url, end, total_pages=total)

            time.sleep(1)

        # RAPORTARE FINALĂ
        successful_segments = len(actual_segments_to_download) - len(failed_segments)
        print(f"📊 PROGRES FINAL: {last_successful_page}/{total} pagini")
        print(f"📊 SEGMENTE: {successful_segments}/{len(actual_segments_to_download)} reușite")

        if failed_segments:
            print(f"📊 SEGMENTE EȘUATE: {len(failed_segments)}")
            for start, end in failed_segments:
                print(f"   ❌ {start}-{end}")

        # === VERIFICARE CRITICĂ FINALĂ: SCANEAZĂ DISK-UL PENTRU PROGRES REAL ===
        print(f"\n🔍 VERIFICARE CRITICĂ: Scanez disk-ul pentru progres REAL...")

        actual_segments_on_disk = self.get_all_pdf_segments_for_issue(self.current_issue_url)

        if actual_segments_on_disk:
            print(f"📄 Segmente găsite pe disk: {len(actual_segments_on_disk)}")

            # Sortează segmentele după pagina de început
            actual_segments_on_disk.sort(key=lambda x: x['start'])

            # Afișează segmentele găsite
            for seg in actual_segments_on_disk:
                print(f"   ✅ {seg['filename']} (pagini {seg['start']}-{seg['end']})")

            # === CALCUL CORECT: Găsește ultimul segment CONSECUTIV de la început ===
            real_last_page = 0

            # Verifică fiecare segment așteptat în ordine
            for i, (expected_start, expected_end) in enumerate(all_segments):
                # Caută dacă acest segment există pe disk
                found = False
                for disk_seg in actual_segments_on_disk:
                    if disk_seg['start'] <= expected_start and disk_seg['end'] >= expected_end:
                        found = True
                        real_last_page = expected_end  # Actualizează progresul
                        break

                # Dacă lipsește un segment, OPREȘTE numărarea
                if not found:
                    print(f"⚠️ OPRIT LA SEGMENT: {expected_start}-{expected_end} (LIPSEȘTE)")
                    break

            print(f"📊 PROGRES REAL CONSECUTIV DE PE DISK: {real_last_page}/{total} pagini")

            # Identifică TOATE găurile (nu doar până la primul lipsă)
            missing_ranges = []
            for i, (expected_start, expected_end) in enumerate(all_segments):
                found = False
                for disk_seg in actual_segments_on_disk:
                    if disk_seg['start'] <= expected_start and disk_seg['end'] >= expected_end:
                        found = True
                        break
                if not found:
                    missing_ranges.append((expected_start, expected_end))

            if missing_ranges:
                print(f"\n⚠️ GĂURI DETECTATE: {len(missing_ranges)} segmente lipsă pe disk!")
                for start, end in missing_ranges[:10]:  # Primele 10
                    print(f"   ❌ LIPSEȘTE: pages{start}-{end}")
                if len(missing_ranges) > 10:
                    print(f"   ... și încă {len(missing_ranges) - 10} segmente lipsă")

            # FOLOSEȘTE PROGRESUL REAL CONSECUTIV DE PE DISK
            last_successful_page = real_last_page

            print(f"\n✅ PROGRES FINAL CORECTAT (CONSECUTIV): {last_successful_page}/{total}")
        else:
            print(f"⚠️ Nu am găsit NICIUN segment pe disk pentru acest issue!")
            last_successful_page = 0

        completion_rate = (last_successful_page / total) * 100 if total > 0 else 0
        is_complete = completion_rate >= 98 and len(failed_segments) == 0

        return last_successful_page, False

    def verify_all_segments_present(self, issue_url, total_pages):
        """
        CRITICAL: Verifică că TOATE segmentele sunt prezente și consecutive
        Returns: (bool: all_present, list: missing_segments)
        """
        print(f"🔍 VERIFICARE CRITICĂ: Scanez completitudinea segmentelor pentru {issue_url}")

        # PASUL 1: Obține toate segmentele de pe disk
        all_segments = self.get_all_pdf_segments_for_issue(issue_url)

        if not all_segments:
            print(f"❌ Nu am găsit niciun segment!")
            return False, []

        # PASUL 2: Calculează segmentele așteptate
        bs = self.batch_size  # 50
        expected_segments = []

        # Primul segment: 1-49
        first_end = min(bs - 1, total_pages)
        if first_end >= 1:
            expected_segments.append((1, first_end))

        # Segmentele următoare: 50-99, 100-149, etc.
        current = bs
        while current <= total_pages:
            end = min(current + bs - 1, total_pages)
            expected_segments.append((current, end))
            current += bs

        print(f"📊 Segmente așteptate: {len(expected_segments)}")

        # PASUL 3: Verifică fiecare segment așteptat
        missing_segments = []

        for expected_start, expected_end in expected_segments:
            # Caută un segment care acoperă complet intervalul așteptat
            found = False

            for disk_seg in all_segments:
                disk_start = disk_seg['start']
                disk_end = disk_seg['end']

                # Verifică dacă segmentul de pe disk acoperă complet intervalul așteptat
                if disk_start <= expected_start and disk_end >= expected_end:
                    found = True
                    print(f"   ✅ Segment {expected_start}-{expected_end}: găsit ({disk_seg['filename']})")
                    break

            if not found:
                missing_segments.append((expected_start, expected_end))
                print(f"   ❌ Segment {expected_start}-{expected_end}: LIPSEȘTE!")

        # PASUL 4: Raport final
        if missing_segments:
            print(f"🚨 PROBLEMA DETECTATĂ: {len(missing_segments)} segmente lipsă!")
            for start, end in missing_segments:
                print(f"   📄 Lipsește: pages{start}-{end}")
            return False, missing_segments
        else:
            print(f"✅ TOATE {len(expected_segments)} segmente sunt prezente și complete!")
            return True, []

    def download_missing_segments(self, issue_url, missing_segments):
        """
        Descarcă segmentele lipsă pentru un issue incomplet
        """
        if not missing_segments:
            return True

        print(f"🔄 RECUPERARE: Descarc {len(missing_segments)} segmente lipsă pentru {issue_url}")

        # PASUL 1: Navigă la issue
        if not self.navigate_to_page(issue_url):
            print(f"❌ Nu pot naviga la {issue_url}")
            return False

        # Așteaptă ca pagina să se încarce complet (delay pentru securitate site)
        print("⏳ Aștept 3 secunde pentru încărcarea completă a paginii...")
        time.sleep(3)

        # PASUL 2: Descarcă fiecare segment lipsă
        success_count = 0

        for start, end in missing_segments:
            print(f"📥 Descarc segmentul lipsă: pages{start}-{end}")

            result = self.save_page_range(start, end, retries=3)

            if result:
                success_count += 1
                print(f"✅ Segment recuperat: pages{start}-{end}")
            else:
                print(f"❌ Nu am putut recupera segmentul: pages{start}-{end}")

                # Verifică limita zilnică
                if self.state.get("daily_limit_hit", False):
                    print(f"🛑 Limită zilnică atinsă în timpul recuperării")
                    return False

            time.sleep(2)

        print(f"📊 Recuperare finalizată: {success_count}/{len(missing_segments)} segmente descărcate")

        return success_count == len(missing_segments)

    def extract_issue_links_from_collection(self):
        """
        FIXED: Extrage toate linkurile de issue din colecție, inclusiv pentru limba ungară
        Folosește selector generic pentru a detecta orice limbă (/view/, /ro/view/, /en/view/, /hu/view/)

        OVERRIDE pentru script-ul derivat: dacă main_collection_url se potrivește cu o cheie
        din FORCED_ISSUE_URLS_BY_COLLECTION, returnează direct lista hardcodată de view URL-uri
        în loc să scaneze pagina colecției (utilă pentru descărcare selectivă).
        """
        # === OVERRIDE: lista forțată de issue-uri pentru GazetaMatematica ===
        try:
            collection_url = getattr(self, 'main_collection_url', '') or ''
            for key, forced_list in FORCED_ISSUE_URLS_BY_COLLECTION.items():
                if key in collection_url:
                    # Normalizează URL-urile (fără parametri, fără trailing slash)
                    normalized = []
                    seen = set()
                    for u in forced_list:
                        n = u.split('?')[0].rstrip('/')
                        if n not in seen:
                            seen.add(n)
                            normalized.append(n)
                    print(f"🎯 FORCED ISSUE LIST activă pentru '{key}': {len(normalized)} URL-uri")
                    for i, link in enumerate(normalized):
                        print(f"   {i+1}. 🔗 {link}")
                    return normalized
        except Exception as e:
            print(f"⚠ Eroare la verificarea listei forțate: {e} - continui cu scanarea normală")

        try:
            # Așteaptă ca lista să se încarce
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'ul.list-group')))

            # SELECTOR GENERIC: orice link care conține '/view/' în href
            anchors = self.driver.find_elements(By.CSS_SELECTOR, 'li.list-group-item a[href*="/view/"]')

            print(f"🔍 Am găsit {len(anchors)} linkuri brute cu '/view/' în colecție")

            links = []
            for a in anchors:
                href = a.get_attribute("href")
                if href and '/view/' in href:
                    # Normalizează URL-ul (elimină parametrii și slash-ul final)
                    normalized = href.split('?')[0].rstrip('/')
                    links.append(normalized)

            # Elimină dublurile păstrând ordinea
            unique = []
            seen = set()
            for l in links:
                if l not in seen:
                    seen.add(l)
                    unique.append(l)

            print(f"🔗 Am găsit {len(unique)} linkuri UNICE de issue în colecție")

            # DEBUGGING pentru colecțiile problematice
            if len(unique) == 0:
                print(f"🔍 DEBUG - Nu am găsit linkuri. Analizez structura paginii...")

                # Verifică dacă există lista de grupuri
                try:
                    list_groups = self.driver.find_elements(By.CSS_SELECTOR, 'ul.list-group')
                    print(f"🔍 Liste grup găsite: {len(list_groups)}")

                    list_items = self.driver.find_elements(By.CSS_SELECTOR, 'li.list-group-item')
                    print(f"🔍 Elemente listă găsite: {len(list_items)}")

                    # Verifică toate linkurile din pagină
                    all_links = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/view/"]')
                    print(f"🔍 TOATE linkurile cu '/view/' din pagină: {len(all_links)}")

                    for i, link in enumerate(all_links[:10]):  # Primele 10 pentru debugging
                        href = link.get_attribute("href")
                        text = link.text.strip()[:50]
                        print(f"   {i+1}. 🔗 {href}")
                        print(f"      📝 Text: '{text}'")

                    # Verifică structura HTML a primelor elemente
                    if list_items:
                        print(f"🔍 Primul element listă HTML:")
                        print(f"   {list_items[0].get_attribute('outerHTML')[:200]}...")

                except Exception as debug_e:
                    print(f"⚠ Eroare în debugging: {debug_e}")
            else:
                # Afișează primele câteva linkuri găsite pentru verificare
                print(f"📋 Primele linkuri găsite:")
                for i, link in enumerate(unique[:5]):
                    # Extrage anul sau identificatorul din URL
                    parts = link.split('/')[-1].split('_')
                    identifier = parts[-1] if len(parts) > 1 else "N/A"
                    print(f"   {i+1}. 🔗 {identifier}: {link}")

                if len(unique) > 5:
                    print(f"   📊 ... și încă {len(unique) - 5} linkuri")

            return unique

        except Exception as e:
            print(f"❌ Eroare la extragerea linkurilor din colecție: {e}")

            # Debugging suplimentar în caz de eroare
            try:
                current_url = self.driver.current_url
                page_title = self.driver.title
                print(f"🔍 URL curent: {current_url}")
                print(f"🔍 Titlu pagină: {page_title}")

                # Verifică dacă pagina s-a încărcat corect
                body_text = self.driver.find_element(By.TAG_NAME, "body").text[:200]
                print(f"🔍 Început conținut: '{body_text}...'")

            except Exception as debug_e:
                print(f"⚠ Eroare în debugging după eroare: {debug_e}")

            return []

    def extract_page_range_from_filename(self, filename):
        """Extrage range-ul de pagini din numele fișierului pentru sortare corectă"""
        match = re.search(r'__pages(\d+)-(\d+)\.pdf', filename)
        if match:
            start_page = int(match.group(1))
            end_page = int(match.group(2))
            return (start_page, end_page)
        return (0, 0)

    def copy_and_combine_issue_pdfs(self, issue_url: str, issue_title: str):
        """
        FIXED: MUTĂ fișierele în folder și le combină (nu mai păstrează pe D:)
        ADDED: Face backup în g:Temporare înainte de procesare
        """
        issue_id = issue_url.rstrip('/').split('/')[-1]
        folder_name = self._safe_folder_name(issue_title or issue_id)
        dest_dir = os.path.join(self.download_dir, folder_name)
        os.makedirs(dest_dir, exist_ok=True)

        # DIRECTORUL DE BACKUP
        backup_base_dir = r"g:\Temporare"
        backup_dir = os.path.join(backup_base_dir, folder_name)

        print(f"📁 Procesez PDF-urile pentru '{issue_title}' cu ID '{issue_id}'")

        # ⏳ AȘTEAPTĂ CA TOATE FIȘIERELE SĂ FIE COMPLET DESCĂRCATE
        print("⏳ Aștept 10 secunde ca toate fișierele să se termine de descărcat...")
        time.sleep(20)

        # PASUL 1: Găsește TOATE fișierele pentru acest issue
        all_segments = self.get_all_pdf_segments_for_issue(issue_url)

        if not all_segments:
            print(f"ℹ️ Nu am găsit fișiere PDF pentru '{issue_title}' cu ID '{issue_id}'.")
            return

        print(f"🔍 Am găsit {len(all_segments)} fișiere PDF pentru '{issue_id}':")
        for seg in all_segments:
            print(f"   📄 {seg['filename']} (pagini {seg['start']}-{seg['end']})")

        # PASUL 1.5: CREEAZĂ BACKUP-UL ÎNAINTE DE PROCESARE
        print(f"💾 Creez backup în: {backup_dir}")
        try:
            os.makedirs(backup_dir, exist_ok=True)
            backup_success = True
            backup_size_total = 0

            for seg in all_segments:
                src = seg['path']
                backup_dst = os.path.join(backup_dir, seg['filename'])

                try:
                    shutil.copy2(src, backup_dst)  # copy2 păstrează și metadata
                    file_size = os.path.getsize(backup_dst)
                    backup_size_total += file_size
                    print(f"💾 BACKUP: {seg['filename']} → g:\\Temporare\\{folder_name}\\")
                except Exception as e:
                    print(f"⚠ EROARE backup pentru {seg['filename']}: {e}")
                    backup_success = False

            backup_size_mb = backup_size_total / (1024 * 1024)
            if backup_success:
                print(f"✅ BACKUP COMPLET: {len(all_segments)} fișiere ({backup_size_mb:.2f} MB) în {backup_dir}")
            else:
                print(f"⚠ BACKUP PARȚIAL: Unele fișiere nu au putut fi copiate în backup")

        except Exception as e:
            print(f"❌ EROARE la crearea backup-ului: {e}")
            print(f"🛡️ OPRESC PROCESAREA pentru siguranță - fișierele rămân pe G:\\")
            return

        # PASUL 2: MUTĂ (nu copiază) TOATE fișierele în folder (DOAR DUPĂ backup SUCCESS)
        moved_files = []
        for seg in all_segments:
            src = seg['path']
            dst = os.path.join(dest_dir, seg['filename'])
            try:
                shutil.move(src, dst)  # MOVE în loc de COPY
                moved_files.append(dst)
                print(f"📄 MUTAT: {seg['filename']} → {folder_name}/")
            except Exception as e:
                print(f"⚠ Nu am reușit să mut {seg['filename']}: {e}")

        if not moved_files:
            print(f"❌ Nu am reușit să mut niciun fișier pentru '{issue_title}'.")
            return

        print(f"📁 Toate {len(moved_files)} PDF-urile pentru '{issue_title}' au fost MUTATE în '{dest_dir}'.")
        print(f"💾 BACKUP SIGUR găsit în: {backup_dir}")

        # PASUL 3: Combină PDF-urile în ordinea corectă
        output_file = os.path.join(dest_dir, f"{folder_name}.pdf")

        try:
            if len(moved_files) > 1:
                print(f"🔗 Combinez {len(moved_files)} fișiere PDF în ordinea corectă...")

                # Sortează fișierele după range-ul de pagini
                files_with_ranges = []
                for file_path in moved_files:
                    filename = os.path.basename(file_path)
                    start_page, end_page = self.extract_page_range_from_filename(filename)
                    files_with_ranges.append((start_page, end_page, file_path))

                # Sortează după pagina de început
                files_with_ranges.sort(key=lambda x: x[0])
                sorted_files = [x[2] for x in files_with_ranges]

                # Afișează ordinea de combinare
                print("📋 Ordinea de combinare:")
                for start, end, path in files_with_ranges:
                    filename = os.path.basename(path)
                    print(f"   📄 {filename} (pagini {start}-{end})")

                from PyPDF2 import PdfMerger
                merger = PdfMerger()

                for pdf_path in sorted_files:
                    try:
                        merger.append(pdf_path)
                        filename = os.path.basename(pdf_path)
                        print(f"   ✅ Adăugat în ordine: {filename}")
                    except Exception as e:
                        print(f"   ⚠ Eroare la adăugarea {pdf_path}: {e}")

                # Scrie fișierul combinat
                merger.write(output_file)
                merger.close()

                # Verifică că fișierul combinat a fost creat cu succes
                if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
                    print(f"✅ Fișierul combinat creat cu succes: {file_size_mb:.2f} MB")

                    # ȘTERGE SEGMENTELE DIN FOLDER (nu mai sunt copii, sunt originalele mutate)
                    deleted_count = 0
                    total_deleted_size = 0

                    for file_to_delete in moved_files:
                        try:
                            file_size = os.path.getsize(file_to_delete)
                            os.remove(file_to_delete)
                            deleted_count += 1
                            total_deleted_size += file_size
                            print(f"   🗑️ Șters segment: {os.path.basename(file_to_delete)}")
                        except Exception as e:
                            print(f"   ⚠ Nu am putut șterge {file_to_delete}: {e}")

                    deleted_size_mb = total_deleted_size / (1024 * 1024)
                    print(f"🎉 FINALIZAT: Păstrat doar fișierul combinat '{os.path.basename(output_file)}'")
                    print(f"🗑️ Șterse {deleted_count} segmente originale ({deleted_size_mb:.2f} MB)")
                    print(f"💾 BACKUP SIGUR: Segmentele originale păstrate în {backup_dir}")

                else:
                    print(f"❌ EROARE: Fișierul combinat nu a fost creat corect!")
                    print(f"🛡️ SIGURANȚĂ: Păstrez segmentele pentru siguranță")
                    print(f"💾 BACKUP DISPONIBIL: {backup_dir}")

            elif len(moved_files) == 1:
                # Un singur fișier - doar redenumește
                original_file = moved_files[0]
                original_size_mb = os.path.getsize(original_file) / (1024 * 1024)

                try:
                    os.replace(original_file, output_file)
                    print(f"✅ Fișierul redenumit în: {os.path.basename(output_file)} ({original_size_mb:.2f} MB)")
                    print(f"💾 BACKUP SIGUR: Originalul păstrat în {backup_dir}")
                except Exception as e:
                    print(f"⚠ Nu am putut redenumi {original_file}: {e}")

            else:
                print(f"ℹ️ Nu există fișiere PDF de combinat în '{dest_dir}'.")

        except Exception as e:
            print(f"❌ EROARE la combinarea PDF-urilor: {e}")
            print(f"🛡️ SIGURANȚĂ: Păstrez segmentele din cauza erorii")
            print(f"💾 BACKUP DISPONIBIL: {backup_dir}")
            return

        # PASUL 4: Raport final
        try:
            if os.path.exists(output_file):
                final_size_mb = os.path.getsize(output_file) / (1024 * 1024)

                print(f"\n📋 RAPORT FINAL pentru '{issue_title}':")
                print(f"   📁 Folder destinație: {dest_dir}")
                print(f"   📄 Fișier final: {os.path.basename(output_file)} ({final_size_mb:.2f} MB)")
                print(f"   🔍 Combinat din {len(all_segments)} segmente")
                print(f"   💾 BACKUP SIGUR: {backup_dir} ({backup_size_mb:.2f} MB)")
                print(f"   ✅ STATUS: SUCCES - fișier complet creat, backup realizat, segmente șterse de pe G:\\")
            else:
                print(f"⚠ Nu s-a putut crea fișierul final pentru '{issue_title}'")
                print(f"💾 BACKUP DISPONIBIL: {backup_dir}")
        except Exception as e:
            print(f"⚠ Eroare la raportul final: {e}")

        print(f"=" * 60)


    def find_next_issue_in_collection_order(self, collection_links, last_completed_url):
        """
        FIXED: Găsește următorul issue de procesat în ordinea din HTML, nu primul din listă
        """
        if not last_completed_url:
            # Dacă nu avem istoric, începe cu primul din listă
            return collection_links[0] if collection_links else None

        try:
            last_index = collection_links.index(last_completed_url.rstrip('/'))
            # Returnează următorul din listă după cel completat
            next_index = last_index + 1
            if next_index < len(collection_links):
                next_url = collection_links[next_index]
                print(f"🎯 Următorul issue după '{last_completed_url}' este: '{next_url}'")
                return next_url
            else:
                print(f"✅ Toate issue-urile din colecție au fost procesate!")
                return None
        except ValueError:
            # Dacă last_completed_url nu e în lista curentă, începe cu primul
            print(f"⚠ URL-ul '{last_completed_url}' nu e în colecția curentă, încep cu primul din listă")
            return collection_links[0] if collection_links else None

    def get_last_completed_issue_from_collection(self, collection_links):
            """FIXED: Găsește ultimul issue REAL complet descărcat din colecția curentă"""
            for item in self.state.get("downloaded_issues", []):
                url = item.get("url", "").rstrip('/')
                if url in [link.rstrip('/') for link in collection_links]:

                    # VERIFICARE CORECTĂ: Issue-ul trebuie să fie REAL complet
                    if self.is_issue_really_complete(item):
                        print(f"🏁 Ultimul issue REAL complet din colecție: {url}")
                        return url
                    elif item.get("completed_at"):
                        last_segment = item.get("last_successful_segment_end", 0)
                        total_pages = item.get("total_pages")
                        pages = item.get("pages", 0)
                        print(f"⚠ Issue marcat ca complet dar INCOMPLET: {url} ({last_segment}/{total_pages}, pages: {pages})")

            print("🆕 Niciun issue REAL complet găsit în colecția curentă")
            return None



    def open_new_tab_and_download(self, url):
        """FIXED: Verificare simplă din JSON - fără verificare fizică"""
        normalized_url = url.rstrip('/')

        # Skip URLs din lista statică
        if normalized_url in self.dynamic_skip_urls:
            print(f"⏭️ Sar peste {url} (în skip list).")
            return False

        # ✅ VERIFICARE SIMPLIFICATĂ - doar din JSON
        # Dacă are completed_at ȘI pages > 0, e complet și procesat!
        already_done = any(
            item.get("url") == normalized_url and
            item.get("completed_at") and
            item.get("pages", 0) > 0 and
            item.get("total_pages") and
            item.get("pages") == item.get("total_pages")
            for item in self.state.get("downloaded_issues", [])
        )

        if already_done:
            print(f"⏭️ Sar peste {url} (deja descărcat și procesat complet în JSON).")
            return False





        print(f"\n🎯 ÎNCEP FOCUSAREA PE: {url}")
        print("=" * 60)

        try:
            # IMPORTANT: Redeschide Firefox dacă nu este deschis (după închiderea de la issue-ul anterior)
            if not hasattr(self, 'driver') or not self.driver:
                print("🔄 Firefox nu este deschis - redeschid Firefox pentru noul issue...")
                if not self.setup_chrome_driver(browser="firefox"):
                    print("❌ Nu pot redeschide Firefox")
                    return False
                print("✅ Firefox redeschis cu succes")

            if not self.attached_existing:
                self.ensure_alive_fallback()

            # Deschide fila nouă
            prev_handles = set(self.driver.window_handles)
            self.driver.execute_script("window.open('');")
            new_handles = set(self.driver.window_handles)
            diff = new_handles - prev_handles
            new_handle = diff.pop() if diff else self.driver.window_handles[-1]
            self.driver.switch_to.window(new_handle)

            if not self.navigate_to_page(url):
                print(f"❌ Nu am putut naviga la {url}")
                return False

            time.sleep(2)

            # VERIFICARE NOUĂ: Este nevoie de login?
            if self.detect_login_required():
                print("🔐 DETECTAT: Este necesară autentificarea!")
                print("🔄 Încerc login automat...")

                login_success = self.perform_auto_login()

                if not login_success:
                    print("❌ LOGIN EȘUAT - Opresc procesarea acestui issue")
                    return False

                print("✅ Login reușit - renavigez la issue...")

                # După login, renavigăm la issue-ul original
                if not self.navigate_to_page(url):
                    print(f"❌ Nu pot renaviga la {url} după login")
                    return False

                time.sleep(3)
                print("✅ Renavigat cu succes după login")

            # Verifică DOAR o dată la început pentru limită
            if self.check_daily_limit_in_all_windows(set_flag=False):
                print("⚠ Pagină cu limită zilnică detectată - opresc aici.")
                self.state["daily_limit_hit"] = True
                self._save_state()
                return False

            print("✅ Pagina e OK, încep extragerea metadatelor...")
            title, subtitle = self.get_issue_metadata()

            # FIXED: Scanează corect fișierele existente pentru acest issue specific
            existing_pages = self.get_existing_pdf_segments(url)
            print(f"📊 Pagini existente pe disk: {existing_pages}")

            resume_from = 1
            json_progress = 0
            total_pages_json = 0
            for item in self.state.get("downloaded_issues", []):
                if item.get("url") == normalized_url:
                    json_progress = item.get("last_successful_segment_end", 0)
                    total_pages_json = item.get("total_pages", 0)
                    break

            # === VERIFICARE CRITICĂ: DISK vs JSON ===
            # Dacă disk-ul arată 0 sau foarte puțin, dar JSON zice complet → JSON e greșit!
            if existing_pages == 0 and json_progress > 0:
                print(f"⚠️ DISCREPANȚĂ CRITICĂ: JSON zice {json_progress} pagini, dar disk-ul arată {existing_pages}!")
                print(f"🔄 Ignor JSON-ul greșit - încep descărcarea de la 0!")
                resume_from = 1
                # Resetează progresul în JSON
                for item in self.state.get("downloaded_issues", []):
                    if item.get("url") == normalized_url:
                        item["last_successful_segment_end"] = 0
                        item["completed_at"] = ""
                        item["pages"] = 0
                        self._save_state()
                        print(f"✅ JSON resetat pentru {url}")
                        break
            elif json_progress and total_pages_json and json_progress >= total_pages_json and existing_pages >= total_pages_json * 0.9:
                # Doar dacă JSON zice complet ȘI disk-ul confirmă (>90% din pagini)
                print(f"⏭️ Issue-ul {url} este deja complet (JSON: {json_progress}, Disk: {existing_pages}, Total: {total_pages_json}).")
                return False
            else:
                # Reiau de unde am rămas (folosind maximul dintre JSON și disk)
                actual_progress = max(json_progress, existing_pages)
                if actual_progress > 0:
                    resume_from = actual_progress + 1
                    print(f"📄 Reiau de la pagina {resume_from} (JSON: {json_progress}, Disk: {existing_pages})")

            self.current_issue_url = normalized_url

            # FIXED: Obține total_pages și actualizează progresul
            total_pages = self.get_total_pages()
            if total_pages > 0:
                self._update_partial_issue_progress(normalized_url, actual_progress, total_pages=total_pages, title=title, subtitle=subtitle)
            else:
                print("⚠ Nu am putut obține numărul total de pagini!")

            print(f"🔒 INTRÂND ÎN MODUL FOCUS - nu mai fac alte verificări până nu termin!")

# ==================== DESCĂRCAREA PROPRIU-ZISĂ ====================
            print(f"📥 ÎNCEPE DESCĂRCAREA pentru {url}...")
            pages_done, limit_hit = self.save_all_pages_in_batches(resume_from=resume_from)

            print(f"📊 REZULTAT DESCĂRCARE:")
            print(f"   📄 Pagini descărcate: {pages_done}")
            print(f"   📄 Total necesar: {total_pages}")
            print(f"   🛑 Limită zilnică: {limit_hit}")

            if pages_done == 0 and not limit_hit:
                print(f"⚠ Descărcarea pentru {url} a eșuat complet.")
                return False

            # ==================== VERIFICARE SEGMENTE LIPSĂ ====================
            # 🔥 VERIFICARE OBLIGATORIE - chiar dacă a fost limită/CAPTCHA
            if total_pages > 0:
                print(f"\n🔍 VERIFICARE COMPLETITUDINE: Scanez după segmente lipsă...")
                print(f"   (Această verificare se face ÎNTOTDEAUNA, indiferent de limită/CAPTCHA)")

                all_present, missing_segments = self.verify_all_segments_present(normalized_url, total_pages)

                if not all_present:
                    print(f"🚨 GĂURI DETECTATE: {len(missing_segments)} segmente lipsă!")
                    for start, end in missing_segments:
                        print(f"   📄 LIPSEȘTE: pages{start}-{end}")

                    # Dacă a fost limită zilnică, NU încerca să recuperezi acum
                    if limit_hit:
                        print(f"⚠️ LIMITĂ ZILNICĂ atinsă - nu pot recupera segmentele lipsă ACUM")
                        print(f"🔄 Segmentele lipsă vor fi re-descărcate la următoarea rulare")
                        print(f"🛡️ BLOCHEZ marcarea ca terminat - issue rămâne PARȚIAL")

                        # Actualizează progresul ca parțial
                        self._update_partial_issue_progress(
                            normalized_url, pages_done, total_pages=total_pages, title=title, subtitle=subtitle
                        )
                        return False

                    print(f"🔄 RECUPERARE AUTOMATĂ: Descarc segmentele lipsă...")
                    recovery_success = self.download_missing_segments(normalized_url, missing_segments)

                    if recovery_success:
                        print(f"✅ RECUPERARE REUȘITĂ!")

                        # Re-verifică
                        all_present_2, missing_2 = self.verify_all_segments_present(normalized_url, total_pages)
                        if not all_present_2:
                            print(f"❌ Încă lipsesc {len(missing_2)} segmente după recuperare!")
                            for start, end in missing_2[:5]:  # Afișează primele 5
                                print(f"   📄 LIPSEȘTE: pages{start}-{end}")
                            print(f"🛡️ BLOCHEZ marcarea ca terminat")

                            # Marchează ca parțial pentru reluare
                            self._update_partial_issue_progress(
                                normalized_url, pages_done, total_pages=total_pages, title=title, subtitle=subtitle
                            )
                            return False

                        # 🔥 CRITICAL FIX: Actualizează pages_done cu progresul REAL de pe disk după recuperare!
                        print(f"🔄 ACTUALIZARE: Scanez disk-ul pentru progres REAL după recuperare...")
                        final_segments_after_recovery = self.get_all_pdf_segments_for_issue(normalized_url)
                        if final_segments_after_recovery:
                            real_progress_after_recovery = max(seg['end'] for seg in final_segments_after_recovery)
                            print(f"📊 Progres REAL după recuperare: {real_progress_after_recovery}/{total_pages}")

                            # 🔥 ACTUALIZEAZĂ pages_done cu valoarea REALĂ!
                            pages_done = real_progress_after_recovery
                            print(f"✅ pages_done actualizat: {pages_done} pagini")
                        else:
                            print(f"⚠️ Nu am găsit segmente pe disk după recuperare!")
                            return False
                    else:
                        print(f"❌ RECUPERARE EȘUATĂ")
                        print(f"🛡️ BLOCHEZ marcarea ca terminat")

                        # Marchează ca parțial pentru reluare
                        self._update_partial_issue_progress(
                            normalized_url, pages_done, total_pages=total_pages, title=title, subtitle=subtitle
                        )
                        return False
                else:
                    print(f"✅ TOATE segmentele sunt prezente - nicio gaură!")

            if limit_hit:
                print(f"⚠ Limită zilnică atinsă în timpul descărcării pentru {url}; progresul parțial a fost salvat.")
                return False

            # ==================== VERIFICĂRI ULTRA SAFE ÎNAINTE DE FINALIZARE ====================

            print(f"🔍 VERIFICĂRI FINALE ULTRA SAFE pentru {url}...")
            print(f"📊 Rezultat descărcare: {pages_done} pagini din {total_pages}")

            # Verifică dacă total_pages a fost detectat corect
            if total_pages <= 0:
                print(f"❌ OPRIRE SAFETY: total_pages nu a fost detectat corect ({total_pages})")
                print(f"🛡️ NU marchez ca terminat fără total_pages valid")
                print(f"🔄 Păstrez ca parțial cu progres {pages_done}")

                self._update_partial_issue_progress(
                    normalized_url, pages_done, total_pages=None, title=title, subtitle=subtitle
                )
                return True  # Succes parțial

            # VERIFICARE CRITICĂ: Progresul trebuie să fie aproape complet
            completion_percent = (pages_done / total_pages) * 100
            print(f"📊 Completitudine calculată: {completion_percent:.1f}%")

            if completion_percent < 95:  # Cel puțin 95%
                print(f"❌ BLOCARE SAFETY: Progres insuficient pentru marcare ca terminat")
                print(f"📊 Progres: {pages_done}/{total_pages} ({completion_percent:.1f}%)")
                print(f"🛡️ Trebuie cel puțin 95% pentru a marca ca terminat!")
                print(f"🔄 Păstrez ca PARȚIAL pentru continuare ulterioară")

                # Marchează ca parțial, NU ca terminat
                self._update_partial_issue_progress(
                    normalized_url, pages_done, total_pages=total_pages, title=title, subtitle=subtitle
                )

                print(f"💾 Issue {url} păstrat ca parțial: {pages_done}/{total_pages}")
                print(f"🔄 Va fi continuat automat la următoarea rulare")
                return True  # Succes parțial - va continua mai târziu

            # VERIFICARE SUPLIMENTARĂ: Issues mari cu progres mic
            if total_pages >= 500 and pages_done < 200:
                print(f"❌ BLOCARE SPECIALĂ: Issue mare cu progres suspect de mic")
                print(f"📊 {pages_done} pagini din {total_pages} pare eșec de descărcare!")
                print(f"🛡️ Probabil eroare tehnică sau limită - NU marchez terminat")

                self._update_partial_issue_progress(
                    normalized_url, pages_done, total_pages=total_pages, title=title, subtitle=subtitle
                )
                return True  # Succes parțial

            # ===== VERIFICARE ULTRA-CRITICĂ FINALĂ: SCANEAZĂ DISK-UL ÎNAINTE DE MARCARE =====

            print(f"\n🔍 VERIFICARE ULTRA-CRITICĂ FINALĂ: Scanez disk-ul pentru progres EFECTIV ÎNAINTE de marcare...")
            print("⏳ SINCRONIZARE: Aștept 30 secunde ca toate fișierele să fie complet salvate pe disk...")
            time.sleep(30)

            final_segments_check = self.get_all_pdf_segments_for_issue(url)

            if not final_segments_check:
                print(f"❌ PROBLEMĂ GRAVĂ: Nu am găsit NICIUN segment pe disk!")
                print(f"🛡️ BLOCHEZ marcarea ca terminat - ceva s-a întâmplat grav!")
                return False

            # Calculează progresul REAL de pe disk
            real_final_page = max(seg['end'] for seg in final_segments_check)

            print(f"📊 PROGRES REAL DE PE DISK: {real_final_page}/{total_pages}")
            print(f"📄 Segmente găsite: {len(final_segments_check)}")

            # Verifică dacă progresul REAL este suficient
            real_completion_percent = (real_final_page / total_pages) * 100 if total_pages > 0 else 0

            if real_completion_percent < 95:
                print(f"❌ BLOCARE SAFETY: Progresul REAL de pe disk este prea mic!")
                print(f"📊 Progres REAL: {real_final_page}/{total_pages} ({real_completion_percent:.1f}%)")
                print(f"🛡️ pages_done din descărcare zicea {pages_done}, dar disk-ul arată {real_final_page}")
                print(f"🔄 Marchează ca PARȚIAL pentru continuare ulterioară")

                # Actualizează cu progresul REAL
                self._update_partial_issue_progress(
                    normalized_url, real_final_page, total_pages=total_pages, title=title, subtitle=subtitle
                )

                print(f"💾 Issue {url} păstrat ca parțial cu progres REAL: {real_final_page}/{total_pages}")
                return True  # Succes parțial

            # Identifică și afișează găurile
            all_segments_expected = []
            bs = self.batch_size
            first_end = min(bs - 1, total_pages)
            if first_end >= 1:
                all_segments_expected.append((1, first_end))
            current = bs
            while current <= total_pages:
                end = min(current + bs - 1, total_pages)
                all_segments_expected.append((current, end))
                current += bs

            missing_segments_final = []
            for expected_start, expected_end in all_segments_expected:
                found = False
                for disk_seg in final_segments_check:
                    if disk_seg['start'] <= expected_start and disk_seg['end'] >= expected_end:
                        found = True
                        break
                if not found:
                    missing_segments_final.append((expected_start, expected_end))

            if missing_segments_final:
                print(f"⚠️ GĂURI DETECTATE în verificarea finală: {len(missing_segments_final)} segmente!")
                for start, end in missing_segments_final[:5]:
                    print(f"   ❌ LIPSEȘTE: pages{start}-{end}")
                if len(missing_segments_final) > 5:
                    print(f"   ... și încă {len(missing_segments_final) - 5} segmente")

                print(f"🛡️ BLOCHEZ marcarea ca terminat din cauza găurilor!")

                # Marchează ca parțial cu progresul real
                self._update_partial_issue_progress(
                    normalized_url, real_final_page, total_pages=total_pages, title=title, subtitle=subtitle
                )

                return True  # Succes parțial

            # ACTUALIZEAZĂ pages_done cu valoarea REALĂ de pe disk
            pages_done = real_final_page

            print(f"✅ VERIFICARE OK: Toate segmentele sunt prezente pe disk!")
            print(f"📊 Progres CONFIRMAT: {pages_done}/{total_pages} ({real_completion_percent:.1f}%)")

            # ===== TOATE VERIFICĂRILE AU TRECUT - MARCHEAZĂ CA TERMINAT =====
            print(f"\n✅ TOATE VERIFICĂRILE AU TRECUT pentru {url}")
            print(f"🎯 Progres verificat pe disk: {pages_done}/{total_pages} ({real_completion_percent:.1f}%)")
            print(f"🎯 MARCHEZ CA TERMINAT COMPLET în JSON")

            # MARCHEAZĂ ISSUE CA TERMINAT
            self.mark_issue_done(url, pages_done, title=title, subtitle=subtitle, total_pages=total_pages)
            print(f"✅ Issue marcat ca terminat în JSON: {url} ({pages_done} pagini)")

            # PAUZĂ: Așteaptă ca JSON să fie salvat
            print("⏳ SINCRONIZARE: Aștept 3 secunde pentru salvarea JSON...")
            time.sleep(5)

            # ==================== PROCESAREA PDF-URILOR ====================
            print(f"\n🔄 ÎNCEPE PROCESAREA PDF-URILOR pentru {url}...")

            # Verifică din nou că toate fișierele sunt pe disk
            final_segments = self.get_all_pdf_segments_for_issue(url)
            print(f"🔍 VERIFICARE: Am găsit {len(final_segments)} fișiere PDF pentru acest issue")

            if len(final_segments) == 0:
                print(f"⚠ PROBLEMĂ: Nu am găsit fișiere PDF pentru {url}!")
                return False

            # Copiază și combină PDF-urile
            print(f"📦 Copiez și combin toate PDF-urile...")
            self.copy_and_combine_issue_pdfs(url, title or normalized_url)
            print(f"✅ PDF-urile au fost copiate și combinate cu succes!")

            # PAUZĂ CRITICĂ 3: Așteaptă ca procesarea PDF să fie completă
            print("⏳ SINCRONIZARE: Aștept 8 secunde după procesarea PDF-urilor...")
            time.sleep(8)

            # ==================== FINALIZARE COMPLETĂ ====================
            print("=" * 60)
            print(f"🎉 FOCUSAREA COMPLETĂ PE {url} FINALIZATĂ CU SUCCES!")
            print(f"📊 REZULTAT: {pages_done} pagini descărcate și procesate")
            print("=" * 60)

            # IMPORTANT: Închide Firefox după finalizarea issue-ului pentru a evita pop-up-uri
            print("🔄 Închid Firefox după finalizarea issue-ului pentru a evita pop-up-uri...")
            try:
                if hasattr(self, 'driver') and self.driver:
                    self.driver.quit()
                    self.driver = None
                    self.wait = None
                    print("✅ Firefox închis cu succes")
                    time.sleep(2)
            except Exception as e:
                print(f"⚠ Eroare la închiderea Firefox: {e}")

            # PAUZĂ FINALĂ: Înainte să treacă la următorul issue
            print("⏳ PAUZĂ FINALĂ: 5 secunde înainte de următorul issue...")
            time.sleep(5)

            return True

        except WebDriverException as e:
            print(f"❌ Eroare WebDriver pentru {url}: {e}")
            return False
        except Exception as e:
            print(f"❌ Eroare în open_new_tab_and_download pentru {url}: {e}")
            return False
        finally:
            try:
                # NU ÎNCHIDE DACĂ E ULTIMA FEREASTRĂ
                if len(self.driver.window_handles) > 1:
                    self.driver.close()
                    self.driver.switch_to.window(self.driver.window_handles[0])
                else:
                    # Doar revine la prima fereastră fără să închidă
                    if self.driver.window_handles:
                        self.driver.switch_to.window(self.driver.window_handles[0])
            except Exception as e:
                print(f"⚠ Eroare în finally: {e}")
                pass

    def ensure_alive_fallback(self):
        """Verifică dacă conexiunea WebDriver e activă, dacă nu - repornește Firefox"""
        try:
            _ = self.driver.title
        except Exception as e:
            print(f"⚠ Conexiune WebDriver moartă ({e}), repornesc Firefox...")
            # Folosește aceeași metodă ca setup_firefox_driver() pentru consistență
            if not self.setup_firefox_driver():
                print("❌ Nu am putut reporni Firefox în ensure_alive_fallback!")
                raise Exception("Firefox nu poate fi repornit")

    def run_collection(self, collection_url):
        """FIXED: Verifică TOATE issue-urile înainte să marcheze colecția ca completă"""
        print(f"🌐 Încep procesarea colecției: {collection_url}")

        # === REINIȚIALIZARE AUTOMATĂ FIREFOX DACĂ E ÎNCHIS ===
        if not self.driver:
            print("⚠️ Driver neinițializat - reinițializez Firefox automat...")
            if not self.setup_firefox_driver():
                print("❌ Nu am putut reinițializa Firefox!")
                return False
            print("✅ Firefox reinițializat cu succes!")

        if not self.navigate_to_page(collection_url):
            return False

        # Verifică limita DOAR la început
        if self.state.get("daily_limit_hit", False):
            print("⚠ Nu mai pot continua din cauza limitei zilnice setate anterior.")
            return False  # SCHIMBAT din True în False

        if self.remaining_quota() <= 0:
            print(f"⚠ Limita zilnică de {DAILY_LIMIT} issue-uri atinsă.")
            return False  # SCHIMBAT din True în False

        issue_links = self.extract_issue_links_from_collection()
        if not issue_links:
            print("⚠ Nu s-au găsit issue-uri în colecție.")
            return False

        # === VERIFICARE CRITICĂ: Scanează TOATE issue-urile din colecție (SILENȚIOS pentru skip) ===
        print(f"\n🔍 VERIFICARE COMPLETITUDINE COLECȚIE:")

        incomplete_issues = []
        complete_count = 0
        skipped_count = 0

        for link in issue_links:
            normalized = link.rstrip('/')

            # SKIP SILENȚIOS dacă e în skip list
            if normalized in self.dynamic_skip_urls:
                skipped_count += 1
                continue

            # Verifică în state.json
            issue_item = next(
                (i for i in self.state.get("downloaded_issues", [])
                 if i.get("url") == normalized),
                None
            )

            if not issue_item:
                # Issue nou - trebuie descărcat
                incomplete_issues.append(link)
                print(f"   🆕 NOU: {link}")
                continue

            # Verifică dacă e REAL complet
            is_really_complete = self.is_issue_really_complete(issue_item)

            if is_really_complete:
                complete_count += 1
                # NU mai afișa pentru fiecare - doar contorizează
            else:
                incomplete_issues.append(link)
                last_segment = issue_item.get("last_successful_segment_end", 0)
                total_pages = issue_item.get("total_pages", "?")
                pages = issue_item.get("pages", 0)

                print(f"   ❌ INCOMPLET: {link}")
                print(f"      pages: {pages}, last_segment: {last_segment}, total: {total_pages}")

        # === RAPORT COLECȚIE (DUPĂ SCANAREA TUTUROR ISSUE-URILOR) ===
        print(f"\n📊 RAPORT COLECȚIE:")
        print(f"   Total issues: {len(issue_links)}")
        print(f"   ⏭️ Skip (în skip_urls.json): {skipped_count}")
        print(f"   ✅ Complete: {complete_count}")
        print(f"   ❌ Incomplete: {len(incomplete_issues)}")

        # === DACĂ NU E NIMIC DE PROCESAT, COLECȚIA E COMPLETĂ ===
        if len(incomplete_issues) == 0:
            print(f"✅ COLECȚIA {collection_url} ESTE COMPLETĂ!")
            print(f"   Toate {len(issue_links)} issue-uri sunt complete")
            return True

        # === ÎNAINTE DE A PROCESA ISSUE-URI INCOMPLETE: Finalizează issue-uri complet descărcate dar nefinalizate ===
        print(f"\n🔍 VERIFICARE PRIORITARĂ: Caut issue-uri complet descărcate dar nefinalizate din această colecție...")

        # Apelează procesarea issue-urilor nefinalizate pentru această colecție
        self.process_completed_but_unfinalized_issues()

        print(f"✅ Verificare completă - continuez cu issue-urile incomplete")

        # === PROCESEAZĂ ISSUE-URILE INCOMPLETE ===
        print(f"\n🎯 PROCESEZ {len(incomplete_issues)} issue-uri incomplete:")

        processed_any = False
        for i, link in enumerate(incomplete_issues):
            print(f"\n🔢 ISSUE {i+1}/{len(incomplete_issues)}: {link}")

            # Verifică cota
            if self.remaining_quota() <= 0:
                print(f"⚠ Limită zilnică atinsă - opresc procesarea")
                return False  # Returnează FALSE ca să nu marcheze colecția ca completă

            if self.state.get("daily_limit_hit", False):
                print("⚠ Flag daily_limit_hit setat - opresc procesarea")
                return False

            # Procesează issue-ul
            result = self.open_new_tab_and_download(link)

            if result:
                processed_any = True
                print(f"✅ Issue-ul {link} procesat cu succes!")
            else:
                print(f"⚠ Issue-ul {link} nu a fost procesat")

            # Verifică din nou cota
            if self.remaining_quota() <= 0 or self.state.get("daily_limit_hit", False):
                print("⚠ Limită zilnică atinsă - opresc procesarea")
                return False

            # Pauză între issue-uri
            if i < len(incomplete_issues) - 1:
                print("⏳ Pauză de 2s între issue-uri...")
                time.sleep(2)

        # === RE-VERIFICARE FINALĂ ===
        print(f"\n🔍 RE-VERIFICARE FINALĂ după procesare:")

        still_incomplete = []
        for link in issue_links:
            normalized = link.rstrip('/')
            issue_item = next(
                (i for i in self.state.get("downloaded_issues", [])
                 if i.get("url") == normalized),
                None
            )

            if not issue_item or not self.is_issue_really_complete(issue_item):
                still_incomplete.append(link)

        if len(still_incomplete) == 0:
            print(f"✅ COLECȚIA {collection_url} ESTE ACUM COMPLETĂ!")
            return True
        else:
            print(f"⚠ COLECȚIA {collection_url} ÎNCĂ ARE {len(still_incomplete)} issue-uri incomplete")
            print(f"   Va fi reluată la următoarea rulare")
            return False

    def process_pending_partials_first(self):
        """FIXED: Procesează mai întâi issue-urile parțiale, indiferent de colecție"""
        pending_partials = self.get_pending_partial_issues()

        if not pending_partials:
            print("✅ Nu există issue-uri parțiale de procesat.")
            return True

        print(f"\n🎯 PRIORITATE: Procesez {len(pending_partials)} issue-uri parțiale:")
        for item in pending_partials:
            url = item.get("url")
            progress = item.get("last_successful_segment_end", 0)
            total = item.get("total_pages", 0)
            print(f"   🔄 {url} - pagini {progress}/{total}")

        # Procesează issue-urile parțiale
        processed_any = False
        for item in pending_partials:
            if self.remaining_quota() <= 0 or self.state.get("daily_limit_hit", False):
                print(f"⚠ Limita zilnică atinsă în timpul issue-urilor parțiale.")
                break

            url = item.get("url")
            result = self.open_new_tab_and_download(url)
            if result:
                processed_any = True
            time.sleep(1)

        return processed_any

    def run_additional_collections(self):
        """FIXED: Nu sare la următoarea colecție dacă cea curentă nu e completă"""
        start_index = self.state.get("current_additional_collection_index", 0)

        if start_index >= len(ADDITIONAL_COLLECTIONS):
            print("✅ TOATE colecțiile adiționale au fost procesate!")
            return True

        print(f"🔄 Continuez cu colecțiile adiționale de la indexul {start_index}")

        for i in range(start_index, len(ADDITIONAL_COLLECTIONS)):
            collection_url = ADDITIONAL_COLLECTIONS[i]

            print(f"\n📚 COLECȚIA {i+1}/{len(ADDITIONAL_COLLECTIONS)}: {collection_url}")

            if collection_url.rstrip('/') in self.dynamic_skip_urls:
                print(f"⏭️ Skip colecția (deja completă)")
                self.state["current_additional_collection_index"] = i + 1
                self._save_state()
                continue

            if self.remaining_quota() <= 0 or self.state.get("daily_limit_hit", False):
                print(f"⚠ Limită zilnică - opresc procesarea")
                return False  # SCHIMBAT

            # Setează indexul ÎNAINTE de procesare
            self.state["current_additional_collection_index"] = i
            self._save_state()

            # Procesează colecția
            collection_completed = self.run_collection(collection_url)

            if collection_completed:
                # DOAR dacă e REAL completă
                print(f"✅ Colecția {i+1} COMPLETĂ - trec la următoarea")
                self.mark_collection_complete(collection_url)
                self.state["current_additional_collection_index"] = i + 1
                self._save_state()
            else:
                # NU e completă - oprește aici
                print(f"⚠ Colecția {i+1} NU e completă - rămân aici")
                print(f"🔄 Va continua cu aceeași colecție la următoarea rulare")
                return False  # OPREȘTE - nu trece la următoarea

            if self.state.get("daily_limit_hit", False):
                return False

        print("🎉 TOATE colecțiile au fost procesate!")
        return True

    def run(self):
        print("🧪 Încep executarea Chrome PDF Downloader FIXED")
        print("=" * 60)

        try:
            if not self.setup_chrome_driver():
                return False

            # 🚨 VERIFICARE CAPTCHA DIN RULAREA ANTERIOARĂ
            if self.state.get("captcha_detected", False):
                print(f"\n{'='*60}")
                print(f"🚨 CAPTCHA DETECTAT ÎN RULAREA ANTERIOARĂ!")
                print(f"{'='*60}")
                print(f"❌ Scriptul a fost oprit anterior din cauza CAPTCHA")
                print(f"📋 URL CAPTCHA: {self.state.get('captcha_url', 'necunoscut')}")
                print(f"⚠️  ACȚIUNE NECESARĂ:")
                print(f"   1. Rezolvă CAPTCHA manual în browser")
                print(f"   2. Șterge flag-ul din state.json:")
                print(f"      \"captcha_detected\": false")
                print(f"   3. Repornește scriptul")
                print(f"{'='*60}\n")
                return False

            # 🛑 VERIFICARE MAINTENANCE_STOP DIN RULAREA ANTERIOARĂ
            if self.state.get("maintenance_stop", False):
                print(f"\n{'='*60}")
                print(f"🔧 VERIFICARE MAINTENANCE_STOP FLAG")
                print(f"{'='*60}")
                print(f"⚠️ Scriptul a fost oprit anterior din cauza mentenanței")
                print(f"🔍 Verific dacă site-ul Arcanum este din nou disponibil...")

                # Încearcă să acceseze site-ul
                try:
                    self.driver.get("https://adt.arcanum.com/ro/")
                    time.sleep(3)

                    if self.detect_403_maintenance():
                        print(f"❌ Site-ul încă returnează 403 Forbidden")
                        print(f"🛑 Mentenanța continuă - opresc scriptul")
                        print(f"🔄 Repornește mai târziu când mentenanța se termină")
                        return False
                    else:
                        print(f"✅ Site-ul Arcanum este din nou ONLINE!")
                        print(f"🔄 Resetez flag-ul maintenance_stop și continui...")
                        self.state["maintenance_stop"] = False
                        self._save_state()
                except Exception as e:
                    print(f"❌ Eroare la verificarea site-ului: {e}")
                    print(f"🛑 Opresc scriptul pentru siguranță")
                    return False

            print("🔄 Resetez flag-ul de limită zilnică...")
            self.state["daily_limit_hit"] = False
            self._save_state()

            # Sincronizare și cleanup
            self.sync_json_with_disk_files()

            # Procesează issues complet descărcate dar nefinalizate
            self.process_completed_but_unfinalized_issues()

            self.cleanup_duplicate_issues()
            self.fix_incorrectly_marked_complete_issues()

            # === NOUĂ VERIFICARE: Corectează progresul bazat pe disk ===
            print("\n🔍 VERIFICARE: Sincronizez progresul din JSON cu fișierele de pe disk...")
            self.fix_progress_based_on_disk()

            if self.check_daily_limit_in_all_windows(set_flag=False):
                print("⚠ Am găsit ferestre cu limita deschise - le închid...")

            # === BUCLĂ PRINCIPALĂ: Verifică MEREU issue-uri parțiale ===
            max_iterations = 100  # Prevenire buclă infinită
            iteration = 0

            while iteration < max_iterations:
                iteration += 1
                print(f"\n{'='*60}")
                print(f"🔄 ITERAȚIE {iteration}: Verificare priorități")
                print(f"{'='*60}")

                # 🛑 VERIFICARE FLAG MAINTENANCE_STOP - OPRIRE COMPLETĂ
                if self.state.get("maintenance_stop", False):
                    print(f"\n{'='*60}")
                    print(f"🛑 MAINTENANCE_STOP FLAG DETECTAT!")
                    print(f"{'='*60}")
                    print(f"❌ Scriptul a fost oprit din cauza mentenanței prelungite")
                    print(f"⚠️  Site-ul Arcanum era în mentenanță > 30 minute")
                    print(f"🔄 Repornește scriptul mai târziu")
                    print(f"💡 Pentru a reseta flag-ul, șterge 'maintenance_stop' din state.json")
                    # NU resetăm flag-ul automat - utilizatorul trebuie să îl reseteze manual
                    # sau scriptul îl va reseta la următoarea pornire dacă site-ul e OK
                    return False

                # === PRIORITATE 0: Issue-uri complet descărcate dar nefinalizate (PRIORITATE MAXIMĂ!) ===
                print(f"\n🔍 PRIORITATE 0: Verific issue-uri complet descărcate dar nefinalizate...")
                self.process_completed_but_unfinalized_issues()
                print(f"✅ Verificare issue-uri nefinalizate completă")

                # === PRIORITATE 1: Issue-uri parțiale (din ORICE colecție) ===
                pending_partials = self.get_pending_partial_issues()

                if pending_partials:
                    print(f"\n🎯 PRIORITATE ABSOLUTĂ: {len(pending_partials)} issue-uri parțiale găsite")

                    for idx, item in enumerate(pending_partials):
                        if self.remaining_quota() <= 0 or self.state.get("daily_limit_hit", False):
                            print("⚠ Limită zilnică atinsă")
                            return True

                        url = item.get("url")
                        progress = item.get("last_successful_segment_end", 0)
                        total = item.get("total_pages", 0)

                        print(f"\n🔄 PARȚIAL {idx+1}/{len(pending_partials)}: {url}")
                        print(f"   Progres: {progress}/{total} pagini")

                        result = self.open_new_tab_and_download(url)

                        if result:
                            print(f"✅ Issue parțial finalizat")
                        else:
                            print(f"⚠ Issue parțial nu s-a finalizat")

                        time.sleep(2)

                    # După ce procesezi parțiale, revino la început pentru re-verificare
                    continue

                print("✅ Nu există issue-uri parțiale - continui cu colecțiile")

                # === PRIORITATE 2: Colecția principală ===
                if not self.state.get("main_collection_completed", False):
                    print(f"\n📚 Procesez colecția principală: {self.main_collection_url}")

                    main_completed = self.run_collection(self.main_collection_url)

                    if self.state.get("daily_limit_hit", False):
                        print("⚠ Limită zilnică în colecția principală")
                        return True

                    if main_completed:
                        print("✅ Colecția principală completă!")
                        self.state["main_collection_completed"] = True
                        self._save_state()
                        # Revino la început pentru a verifica parțiale
                        continue
                    else:
                        print("🔄 Colecția principală incompletă - reiau mai târziu")
                        # Revino la început pentru a verifica parțiale
                        continue

                print("✅ Colecția principală completă - trec la adiționale")

                # === PRIORITATE 3: Colecții adiționale ===
                if self.remaining_quota() > 0 and not self.state.get("daily_limit_hit", False):
                    print(f"\n📚 Procesez colecții adiționale")

                    all_additional_complete = self.run_additional_collections()

                    if all_additional_complete:
                        print("🎉 TOATE colecțiile procesate!")
                        return True
                    else:
                        print("🔄 Mai sunt colecții de procesat")
                        # Revino la început pentru a verifica parțiale
                        continue

                # Dacă ajungi aici, verifică o ultimă dată
                final_partials = self.get_pending_partial_issues()
                if not final_partials:
                    print("✅ Nu mai există issue-uri parțiale - terminat!")
                    break

            if iteration >= max_iterations:
                print("⚠ Limită iterații atinsă - posibilă buclă infinită")

            print("✅ Toate operațiunile finalizate")
            self._finalize_session()
            return True

        except KeyboardInterrupt:
            print("\n\n⚠ Intervenție manuală")
            return False
        except Exception as e:
            print(f"\n❌ Eroare: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            # NU închide Firefox - lasă-l deschis pentru utilizator
            if not self.attached_existing and self.driver:
                try:
                    # IMPORTANT: Pentru a păstra Firefox deschis, trebuie să folosim un workaround
                    # Firefox se închide automat când geckodriver se oprește (proces copil)
                    # Soluția: Nu apelăm quit() și lăsăm procesul Firefox să continue
                    print("✅ Firefox rămâne deschis după oprirea scriptului")
                    print("💡 NOTĂ: Dacă Firefox se închide, pornește-l manual cu start_firefox.bat")

                    # Workaround: Nu apelăm quit() - doar setăm driver-ul la None
                    # Firefox va continua să ruleze chiar dacă geckodriver se oprește
                    # Dacă Firefox se închide automat, este din cauza modului în care geckodriver
                    # controlează procesul Firefox (proces copil)

                    # Nu apelăm quit() sau close() - doar deconectăm WebDriver
                    # Setăm driver-ul la None pentru a permite garbage collection
                    # dar Firefox procesul ar trebui să rămână activ
                    self.driver = None
                except Exception as e:
                    print(f"⚠ Eroare la deconectarea WebDriver: {e}")
                    # Chiar dacă apare o eroare, nu închidem Firefox
                    pass

    def _finalize_session(self):
        if self.driver:
            if self.attached_existing:
                print("🔖 Am păstrat sesiunea Firefox existentă deschisă (nu fac quit).")
            else:
                # NU închide Firefox - lasă-l deschis pentru utilizator
                print("✅ Firefox rămâne deschis după oprirea scriptului")
                # try:
                #     self.driver.quit()  # COMENTAT - Firefox rămâne deschis
                # except Exception:
                #     pass


def main():
    """
    MAIN FUNCTION - Script derivat pentru GazetaMatematica (lista fixa de view URL-uri).
    Foloseste FORCED_ISSUE_URLS_BY_COLLECTION pentru a descarca doar issue-urile specificate.
    """

    log_file = setup_logging()  # ADĂUGAT - PRIMA LINIE

    # LA ÎNCEPUT: închide orice Firefox și geckodriver (ca „End task" din Task Manager)
    # ca la rulare din Task Scheduler profilul să fie liber înainte de a deschide instanța nouă
    kill_firefox_and_geckodriver_at_start()

    print("🚀 PORNIRE SCRIPT - ANALIZA INIȚIALĂ")
    print("=" * 70)

    # PASUL 1: Creează downloader temporar pentru analiza stării
    temp_downloader = ChromePDFDownloader("temp", download_dir="G:\\", batch_size=50)

    # PASUL 2: Analizează starea curentă
    print("🔍 ANALIZA STĂRII CURENTE:")
    current_state = temp_downloader.state

    main_completed = current_state.get("main_collection_completed", False)
    current_index = current_state.get("current_additional_collection_index", 0)
    total_issues = len(current_state.get("downloaded_issues", []))

    print(f"   📊 Total issues în state: {total_issues}")
    print(f"   🏁 Main collection completed: {main_completed}")
    print(f"   🔢 Current additional index: {current_index}")

    # PASUL 3: Verifică issue-urile parțiale (PRIORITATE ABSOLUTĂ)
    print(f"\n🎯 VERIFICARE ISSUE-URI PARȚIALE:")
    pending_partials = temp_downloader.get_pending_partial_issues()

    if pending_partials:
        print(f"🚨 GĂSITE {len(pending_partials)} ISSUE-URI PARȚIALE!")
        print(f"🔥 PRIORITATE ABSOLUTĂ - acestea trebuie continuate:")

        for item in pending_partials:
            url = item.get("url", "")
            progress = item.get("last_successful_segment_end", 0)
            total = item.get("total_pages", 0)
            title = item.get("title", "")
            print(f"   🔄 {title}")
            print(f"      📍 {url}")
            print(f"      🎯 CONTINUĂ de la pagina {progress + 1} (progres: {progress}/{total})")

        print(f"\n✅ VA PROCESA AUTOMAT issue-urile parțiale primul!")
    else:
        print(f"✅ Nu există issue-uri parțiale de procesat")

    # PASUL 4: Analizeaza progresul GazetaMatematica (din lista FORCED_ISSUE_URLS_BY_COLLECTION)
    print(f"\n📚 ANALIZA COLECȚIEI GazetaMatematica (lista fixă de issue-uri):")

    forced_urls = FORCED_ISSUE_URLS_BY_COLLECTION.get('GazetaMatematica', [])
    expected_urls = []
    seen_norm = set()
    for u in forced_urls:
        n = u.split('?')[0].rstrip('/')
        if n not in seen_norm:
            seen_norm.add(n)
            expected_urls.append(n)

    downloaded_urls = []
    partial_urls = []
    for item in current_state.get("downloaded_issues", []):
        url = (item.get("url") or "").split('?')[0].rstrip('/')
        if url in seen_norm:
            if item.get("completed_at"):
                downloaded_urls.append(url)
            else:
                partial_urls.append(url)

    missing_urls = [u for u in expected_urls if u not in downloaded_urls and u not in partial_urls]

    print(f"   📋 Issue-uri țintă: {len(expected_urls)}")
    print(f"   ✅ Complete: {len(downloaded_urls)}")
    print(f"   🔄 Parțiale: {len(partial_urls)}")
    print(f"   ❌ Lipsă: {len(missing_urls)}")

    # PASUL 5: Determina strategia
    total_remaining = len(partial_urls) + len(missing_urls)

    if total_remaining > 0:
        print(f"\n🎯 STRATEGIA DE PROCESARE:")
        print(f"   🔥 RĂMÂN {total_remaining} issue-uri de procesat din GazetaMatematica")
        print(f"   📈 Progres: {len(downloaded_urls)}/{len(expected_urls)} ({(len(downloaded_urls)/max(1,len(expected_urls)))*100:.1f}%)")
    else:
        print(f"\n✅ GazetaMatematica (lista forțată) este COMPLET!")

    # PASUL 6: Reseteaza starea pentru a continua cu GazetaMatematica (index 0 - singura colectie)
    if total_remaining > 0:
        print(f"\n🔧 RESETEZ STAREA pentru a continua cu GazetaMatematica:")

        if main_completed:
            print(f"   🔄 Resetez main_collection_completed: True → False")
            temp_downloader.state["main_collection_completed"] = False

        if current_index != 0:
            print(f"   🔄 Resetez current_additional_collection_index: {current_index} → 0")
            temp_downloader.state["current_additional_collection_index"] = 0

        temp_downloader._save_state()
        print(f"   ✅ Starea resetată pentru GazetaMatematica")

    # PASUL 7: Seteaza URL-ul colectiei principale
    print(f"\n🎯 SELECTARE COLECȚIE PRINCIPALĂ:")

    # Găsește prima colecție din ADDITIONAL_COLLECTIONS care NU e în skip list
    main_collection_url = None
    for collection_url in ADDITIONAL_COLLECTIONS:
        normalized = collection_url.rstrip('/')
        if normalized not in temp_downloader.dynamic_skip_urls:
            main_collection_url = collection_url
            print(f"✅ SELECTAT: {collection_url}")
            break
        else:
            print(f"⏭️ SKIP (complet descărcat): {collection_url}")

    if not main_collection_url:
        print("❌ TOATE colecțiile au fost descărcate!")
        sys.exit(0)

    print(f"\n🚀 ÎNCEPE PROCESAREA:")
    print(f"📍 URL principal: {main_collection_url}")
    print(f"📁 Director descărcare: G:\\")
    print(f"📦 Batch size: 50 pagini per segment")

    if pending_partials:
        print(f"⚡ Va începe cu {len(pending_partials)} issue-uri parțiale")

    print("=" * 70)

    # PASUL 8: Creează downloader-ul principal și pornește procesarea
    try:
        downloader = ChromePDFDownloader(
            main_collection_url=main_collection_url,
            download_dir="G:\\",
            batch_size=50
        )

        print("🎯 ÎNCEPE EXECUȚIA PRINCIPALĂ...")
        success = downloader.run()

        if success:
            print("\n✅ EXECUȚIE FINALIZATĂ CU SUCCES!")
        else:
            print("\n⚠ EXECUȚIE FINALIZATĂ CU PROBLEME!")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n⚠ OPRIRE MANUALĂ - Progresul a fost salvat")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ EROARE FATALĂ în main(): {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def kill_all_firefox_instances():
    """
    Inchide TOATE instantele Firefox si geckodriver INAINTE de a rula scriptul.
    IMPORTANT: Foloseste EXCLUSIV PowerShell (tasklist si taskkill se BLOCHEAZA pe acest PC).
    """
    try:
        fox_count = _ps_get_process_count('firefox')

        if fox_count > 0:
            print(f"🔄 Firefox detectat rulând ({fox_count} procese). Închid TOATE instanțele Firefox...")

            _ps_stop_process('firefox')
            time.sleep(3)

            fox_count2 = _ps_get_process_count('firefox')
            if fox_count2 > 0:
                print(f"⚠️ Firefox nu s-a închis ({fox_count2} procese) - încerc din nou...")
                _ps_stop_process('firefox')
                time.sleep(2)

                fox_count3 = _ps_get_process_count('firefox')
                if fox_count3 > 0:
                    print(f"❌ ATENȚIE: Firefox NU s-a putut închide complet ({fox_count3} procese)! Se continuă oricum...")
                else:
                    print("✅ Firefox închis forțat cu succes.")
            else:
                print("✅ Toate instanțele Firefox au fost închise cu succes.")
        else:
            print("✅ Nicio instanță Firefox activă - se poate porni direct.")

        gecko_count = _ps_get_process_count('geckodriver')
        if gecko_count > 0:
            print("🔄 Geckodriver detectat rulând - forțez închiderea...")
            _ps_stop_process('geckodriver')
            time.sleep(2)
            print("✅ Geckodriver închis.")

        # Curăță fișierele de lock din profilurile Firefox
        try:
            profile_base = os.path.join(os.environ['APPDATA'], r"Mozilla\Firefox\Profiles")
            if os.path.isdir(profile_base):
                for profile_dir in os.listdir(profile_base):
                    profile_path = os.path.join(profile_base, profile_dir)
                    if os.path.isdir(profile_path):
                        for lock_file in ['parent.lock', '.parentlock', 'lock']:
                            lock_path = os.path.join(profile_path, lock_file)
                            if os.path.exists(lock_path):
                                try:
                                    os.remove(lock_path)
                                    print(f"🔓 Fișier lock șters: {lock_path}")
                                except Exception as le:
                                    print(f"⚠️ Nu am putut șterge lock-ul {lock_path}: {le}")
        except Exception as le:
            print(f"⚠️ Eroare la curățarea lock-urilor: {le}")

        time.sleep(2)
        print("✅ Curățare completă - Firefox poate porni fără conflicte.")

    except Exception as e:
        print(f"⚠️ Eroare la închiderea Firefox: {e} - se continuă oricum...")


if __name__ == "__main__":
    try:
        # PASUL 0: Închide ORICE instanță Firefox existentă ÎNAINTE de orice altceva
        print("=" * 60)
        print("🔧 PASUL 0: Verificare și închidere Firefox existent...")
        print("=" * 60)
        kill_all_firefox_instances()
        print("=" * 60)
        print()

        # PASUL 1: Rulează scriptul principal
        main()
    except Exception as e:
        print(f"❌ Eroare fatală în __main__: {e}")
        sys.exit(1)