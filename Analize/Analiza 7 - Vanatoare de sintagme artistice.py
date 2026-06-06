# -*- coding: utf-8 -*-
"""
============================================================
 ANALIZA 7 — VANATOARE DE SINTAGME ARTISTICE
============================================================
SCOP: scaneaza toate textele dintr-un folder si extrage PROPOZITIILE intregi in
care apar termeni de critica de arta / estetica (perspectiva, viziune, tusa,
echilibru compozitional, linia orizontului...). Asa iti faci un catalog de
formulari sclipitoare ale unor autori uitati, din care te inspiri pe blog.

MAI COMPLEX decat varianta simpla:
  - lista de termeni editabila din fisierul "termeni_arta.txt" (unul pe linie);
    daca nu exista, scriptul foloseste o lista default si o si scrie pe disc.
  - cautare INSENSIBILA la diacritice (gaseste "viziune" si "vizíune", "tusa"/"tuşă").
  - prinde TOTI termenii dintr-o propozitie, nu doar primul.
  - CLASAMENT: propozitiile care combina MAI MULTI termeni (cele mai expresive)
    apar primele -> alea sunt bijuteriile.
  - index pe termen (in ce propozitii apare fiecare) + sursa fisierului.

UTILIZARE:
  python "Analiza 7 - Vanatoare de sintagme artistice.py" "cale\\folder_cu_txt"
  python "Analiza 7 - Vanatoare de sintagme artistice.py"      (implicit: folderul curent)
============================================================
"""
import os
import re
import sys
import glob
import unicodedata
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

TERMENI_DEFAULT = [
    "perspectiva", "profil", "viziune", "relevanta", "revelatie", "contraste", "imagine",
    "receptare", "orizont", "vizualizare", "intensitate", "proiectie", "unitate", "traire",
    "reper vizual", "expunere prelungita", "demers", "verosimil", "interventie", "context",
    "contur", "sugestivitate", "plasmuire", "creatie", "tusa", "elemente plastice",
    "echilibrul compozitional", "echilibru compozitional", "gradari de nuante", "prim-plan",
    "prim-planuri", "vibratie stilistica", "utilizarea luminii", "linia orizontului",
    "alteritate", "viziunea de ansamblu", "in planul indepartat", "planul apropiat",
    "catharsis", "epifanie", "tensiune", "manierei compozitionale", "gest", "lumina",
]


def strip_dia(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def load_terms():
    f = os.path.join(HERE, "termeni_arta.txt")
    if os.path.exists(f):
        terms = [l.strip() for l in open(f, encoding="utf-8") if l.strip() and not l.startswith("#")]
        if terms:
            return terms, f
    # scrie lista default ca template editabil
    with open(f, "w", encoding="utf-8") as out:
        out.write("# Lista de termeni artistici (unul pe linie). Editeaz-o cum vrei.\n")
        for t in TERMENI_DEFAULT:
            out.write(t + "\n")
    return TERMENI_DEFAULT, f


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if len(p.strip()) > 15]


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else HERE
    if not os.path.isdir(folder):
        print("Nu exista folderul:", folder); return

    terms, terms_file = load_terms()
    # pre-compilam regexuri pe forma fara diacritice
    patterns = [(t, re.compile(r"\b" + re.escape(strip_dia(t)) + r"\b")) for t in terms]

    files = glob.glob(os.path.join(folder, "*.txt"))
    files = [f for f in files if not os.path.basename(f).startswith(("_", "Analiza", "Caiet",
             "Rescriere", "Prompt", "termeni_arta", "catalog_"))]
    print("=" * 60)
    print("ANALIZA 7 — VANATOARE DE SINTAGME ARTISTICE")
    print(f"Folder: {folder} | {len(files)} fisiere | {len(terms)} termeni")
    print(f"Lista termeni: {terms_file}")
    print("=" * 60)

    rezultate = []          # (nr_termeni, propozitie, sursa, [termeni])
    index_termen = defaultdict(list)
    vazute = set()

    for cale in files:
        nume = os.path.basename(cale)
        text = open(cale, encoding="utf-8", errors="replace").read()
        for prop in sentences(text):
            norm = strip_dia(prop)
            gasiti = [t for t, pat in patterns if pat.search(norm)]
            if not gasiti:
                continue
            cheie = norm[:80]
            if cheie in vazute:
                continue
            vazute.add(cheie)
            rezultate.append((len(gasiti), prop, nume, gasiti))
            for t in gasiti:
                index_termen[t].append((nume, prop))

    rezultate.sort(key=lambda x: -x[0])   # cele cu mai multi termeni primele
    print(f"\nGasit {len(rezultate)} propozitii cu termeni artistici.\n")
    print("TOP 15 cele mai 'bogate' (combina mai multi termeni):")
    for nr, prop, sursa, gasiti in rezultate[:15]:
        print(f"\n  [{nr} termeni: {', '.join(gasiti)}]  ({sursa})")
        print("   -> " + (prop[:300] + ("..." if len(prop) > 300 else "")))

    out = os.path.join(HERE, "catalog_expresii_arta.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("=== CATALOG SINTAGME ARTISTICE (sortat: cele mai bogate primele) ===\n\n")
        for nr, prop, sursa, gasiti in rezultate:
            f.write(f"[{nr}] termeni: {', '.join(gasiti)} | sursa: {sursa}\n-> {prop}\n")
            f.write("-" * 50 + "\n")
        f.write("\n\n=== INDEX PE TERMEN ===\n")
        for t in sorted(index_termen, key=lambda k: -len(index_termen[k])):
            f.write(f"\n# {t.upper()} ({len(index_termen[t])} aparitii)\n")
            for sursa, prop in index_termen[t][:10]:
                f.write(f"  ({sursa}) {prop[:160]}\n")

    print("\nCatalog salvat:", out)
    if not rezultate:
        print("(Niciun termen gasit - normal daca textul nu e critica de arta. "
              "Editeaza termeni_arta.txt sau ruleaza pe articole culturale.)")


if __name__ == "__main__":
    main()
