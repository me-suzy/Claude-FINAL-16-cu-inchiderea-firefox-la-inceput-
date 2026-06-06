# -*- coding: utf-8 -*-
"""
OCR pipeline pentru paginile descarcate din Arcanum (presa veche romaneasca).
  imagini pageNNNN.jpg  ->  text OCR curat (pageNNNN.txt) + corpus combinat (_full.txt)
                        ->  frecventa cuvintelor (_wordfreq.csv)

Foloseste Tesseract (limba 'ron') + curatare text (de-hyphenare, normalizare).
Resume: sare paginile care au deja .txt.

Utilizare:
  python ocr_pipeline.py "g:\\Temporare\\SzatmariMuzeumKiadvanyai_Evkonyv_ADT\\SatuMare_1969_studii"
  python ocr_pipeline.py <folder> --lang ron --max 5      (test pe primele 5 pagini)
  python ocr_pipeline.py <folder> --search "cinema"        (cauta in corpus, cu context)
"""

import os
import re
import sys
import csv
import glob
import argparse
from collections import Counter

# consola Windows e cp1252 -> textul cu diacritice (ț, ş) ar crapa la print
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pytesseract
from PIL import Image

# Tesseract 5.5 (modern) din Program Files + tessdata local cu ron/hun moderne (LSTM).
# (instalarea x86 e v3.02 din 2011 si crapa cu optiunile moderne --oem)
TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESS):
    pytesseract.pytesseract.tesseract_cmd = TESS
_LOCAL_TESSDATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata")
if os.path.isdir(_LOCAL_TESSDATA):
    os.environ["TESSDATA_PREFIX"] = _LOCAL_TESSDATA

# stopwords romanesti (lista compacta; suficienta pentru statistici)
STOP_RO = set("""
a ai al ale alta alte altul am ar are as asta astea acea aceasta aceasta aceea acel acele acest
aceasta acestea aceluiasi acolo acord acum adica ai aia aici al ale alta altceva altele altul am
anume apoiar are asa asemenea asta astazi astfel asupra atare atat atata atatea ati atunci au avea
avem aveti avut azi as ca care caror carei carii caut ce cea ceea cei cel cele ceva chiar ci cind
cine cit cita cite citi citiva ciuda cu cui cum cumva cind cit cita cite cu da daca dar dat date
de deci deja desi despre dintr dintre din doar doi doua drept dupa eu el ea ei ele este esti eram
era erau face fara fata fel fi fie fiecare fii fiind fost foarte i ia iar ii il imi in inca inainte
insa intr intre isi iti l la le li lor lui ma mai mare mea mei mele mi mie mine mod mult multa multe
multi ne nevoie ni nici nimic niste noastre noastra nostri nostru nou noi nu numai o or ori oricare
orice oricit oricum pai pana pe pentru peste pic poate pot prea prin printr putea putin r sa sai
sale sau se si sint sintem sint spre sub sunt suntem sunt si t ta tale te ti tine toata toate tot
toti totul totusi tu tuturor un una unde unei uneia unele uneori unii unor unul unele va vi voi vom
vor vostru vostra vreo vreun zi
""".split())


def ocr_image(path, lang="ron", psm=3):
    img = Image.open(path)
    cfg = f"--oem 1 --psm {psm}"   # oem 1 = motor LSTM (modern, calitate buna)
    return pytesseract.image_to_string(img, lang=lang, config=cfg)


def clean_text(t):
    t = t.replace("­", "")                       # soft hyphen
    t = re.sub(r"-\n([a-zaaiiststt])", r"\1", t, flags=re.I)  # cuvinte taiate la capat de rand
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def page_files(folder):
    fs = []
    for ext in ("jpg", "png", "webp"):
        fs += glob.glob(os.path.join(folder, f"page*.{ext}"))
    fs.sort(key=lambda p: os.path.basename(p))
    return fs


def tokenize_ro(text):
    words = re.findall(r"[a-zaaiiststtAAIISTTĂăÂâÎîŞşȘșŢţȚț]+", text.lower())
    return [w for w in words if len(w) >= 3 and w not in STOP_RO]


def run_ocr(folder, lang, max_pages, force):
    folder = folder.rstrip("\\/")
    out_dir = folder + "_txt"
    os.makedirs(out_dir, exist_ok=True)
    files = page_files(folder)
    if max_pages:
        files = files[:max_pages]
    if not files:
        print("Nu am gasit imagini page*.jpg in:", folder)
        return None
    print(f"OCR pe {len(files)} pagini (lang={lang}) -> {out_dir}")
    combined = []
    for i, f in enumerate(files):
        name = os.path.splitext(os.path.basename(f))[0]
        txt_path = os.path.join(out_dir, name + ".txt")
        if os.path.exists(txt_path) and not force:
            text = open(txt_path, encoding="utf-8").read()
            print(f"  {name}: exista deja, sar")
        else:
            try:
                text = clean_text(ocr_image(f, lang=lang))
            except Exception as e:
                print(f"  {name}: EROARE OCR ({e})")
                continue
            with open(txt_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"  {name}: OK ({len(text)} caractere)")
        combined.append(text)

    full = "\n\n".join(combined)
    full_path = os.path.join(out_dir, "_full.txt")
    with open(full_path, "w", encoding="utf-8") as fh:
        fh.write(full)
    print(f"\nCorpus combinat: {full_path} ({len(full)} caractere)")

    # frecventa cuvintelor
    toks = tokenize_ro(full)
    freq = Counter(toks)
    csv_path = os.path.join(out_dir, "_wordfreq.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["cuvant", "aparitii"])
        for word, n in freq.most_common(2000):
            w.writerow([word, n])
    print(f"Frecvente: {csv_path}  (cuvinte unice: {len(freq)}, total: {len(toks)})")
    print("\nTop 25 cuvinte:")
    for word, n in freq.most_common(25):
        print(f"   {word:20} {n}")
    return out_dir


def search_corpus(folder, term, ctx=60):
    out_dir = folder.rstrip("\\/") + "_txt"
    full_path = os.path.join(out_dir, "_full.txt")
    if not os.path.exists(full_path):
        print("Nu exista corpus inca. Ruleaza intai OCR pe folder.")
        return
    text = open(full_path, encoding="utf-8").read()
    hits = list(re.finditer(re.escape(term), text, flags=re.I))
    print(f"'{term}': {len(hits)} aparitii\n")
    for m in hits[:40]:
        a = max(0, m.start() - ctx); b = min(len(text), m.end() + ctx)
        snip = text[a:b].replace("\n", " ")
        print(f"  ...{snip}...")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="folderul cu page*.jpg")
    ap.add_argument("--lang", default="ron")
    ap.add_argument("--max", type=int, default=0, help="limiteaza la N pagini (test)")
    ap.add_argument("--force", action="store_true", help="re-OCR chiar daca exista .txt")
    ap.add_argument("--search", default=None, help="cauta un termen in corpus")
    args = ap.parse_args()

    if args.search:
        search_corpus(args.folder, args.search)
    else:
        run_ocr(args.folder, args.lang, args.max, args.force)


if __name__ == "__main__":
    main()
