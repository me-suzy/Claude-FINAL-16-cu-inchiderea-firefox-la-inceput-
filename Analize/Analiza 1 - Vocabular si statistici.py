# -*- coding: utf-8 -*-
"""
============================================================
 ANALIZA 1 — VOCABULAR SI STATISTICI DE BAZA
============================================================
CE FACE: citeste un fisier .txt si masoara "din ce e facut" textul:
  - cate cuvinte / propozitii are
  - lungimea medie a propozitiei
  - bogatia vocabularului (cate cuvinte DIFERITE / total) = "diversitate lexicala"
  - cele mai folosite cuvinte de continut (fara cuvinte goale gen "si", "de", "la")
  - cuvinte folosite o SINGURA data (hapax) = vocabular rar/special al epocii

DE CE TE AJUTA LA SCRIS (limbaj "neuronal" / NLP):
  - Vezi REGISTRUL si densitatea scrisului de epoca (propozitii lungi, formale?).
  - Iti dai seama ce vocabular dominant avea presa atunci -> il poti imita.
  - Hapax-urile sunt mina de aur: cuvinte/expresii rare pe care le poti reintroduce
    in articolele tale ca sa sune autentic "de epoca".
  - E baza oricarei analize: intai intelegi materialul, apoi il folosesti.

UTILIZARE:
  python "Analiza 1 - Vocabular si statistici.py"                  (foloseste corpus_exemplu.txt)
  python "Analiza 1 - Vocabular si statistici.py" "cale\\fisier.txt"
============================================================
"""
import os
import re
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# cuvinte "goale" (functionale) pe care le ignoram cand cautam cuvinte de CONTINUT
STOP_RO = set("""a ai al ale am ar are as asta asa au avea ca care cat ce cea cei cel cele ci cind
cine cit cu cui cum da daca dar de deci din doar doi doua dupa eu el ea ei ele este esti era erau
fara fi fie fost foarte i ia iar ii il imi in inca insa intr intre isi iti l la le li lor lui ma
mai mare mea mei mele mi mie mine mod mult multe multi ne nici nimic niste nostru nou noi nu o or
ori pai pana pe pentru peste poate pot prea prin sa sai sale sau se si sint sintem spre sub sunt
suntem ta te ti tine toata toate tot toti totul tu un una unde unei unele unor unul va vom vor voi
zi al ale catre fata fel cei""".split())
# variante cu diacritice (OCR-ul le pastreaza: în, şi, după, până, fără...)
STOP_RO |= set("că dacă și şi în să său această aceasta acea acele după până fără însă dintre "
               "către când cînd încă într întru astfel ţării său şia".split())


def read_txt(path):
    return open(path, encoding="utf-8", errors="replace").read()


def words(text):
    # cuvinte = siruri de litere (inclusiv diacritice romanesti)
    return re.findall(r"[A-Za-zĂăÂâÎîȘșŞşȚțŢţ]+", text.lower())


def sentences(text):
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if len(p.strip()) > 0]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "corpus_exemplu.txt")
    if not os.path.exists(path):
        print("Nu gasesc fisierul:", path); return
    text = read_txt(path)

    toks = words(text)
    sents = sentences(text)
    content = [w for w in toks if len(w) >= 3 and w not in STOP_RO]
    freq = Counter(content)
    unique = set(toks)
    hapax = [w for w, n in Counter(content).items() if n == 1]

    print("=" * 56)
    print("ANALIZA 1 — VOCABULAR SI STATISTICI")
    print("Fisier:", os.path.basename(path))
    print("=" * 56)
    print(f"Caractere:                 {len(text):>8}")
    print(f"Cuvinte (total):           {len(toks):>8}")
    print(f"Cuvinte diferite (unice):  {len(unique):>8}")
    print(f"Propozitii:                {len(sents):>8}")
    if sents:
        avg = len(toks) / len(sents)
        print(f"Lungime medie propozitie:  {avg:>8.1f} cuvinte")
    if toks:
        ttr = len(unique) / len(toks)
        print(f"Diversitate lexicala (TTR):{ttr:>8.3f}  (1.0 = nicio repetare; mic = repetitiv)")
    print()
    print("Top 30 cuvinte de CONTINUT (ce 'vorbeste' textul):")
    for w, n in freq.most_common(30):
        print(f"   {w:22} {n}")
    print()
    print(f"Cuvinte folosite o SINGURA data (hapax): {len(hapax)}")
    print("  Exemple (vocabular rar/de epoca, bun de reciclat in scris):")
    print("   " + ", ".join(sorted(hapax)[:40]))

    # salvam un raport
    out = os.path.join(here, "Analiza 1 - rezultat.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"ANALIZA 1 — {os.path.basename(path)}\n")
        f.write(f"cuvinte={len(toks)} unice={len(unique)} propozitii={len(sents)}\n\n")
        f.write("TOP 100 cuvinte de continut:\n")
        for w, n in freq.most_common(100):
            f.write(f"{w}\t{n}\n")
        f.write("\nHAPAX (cuvinte folosite o singura data):\n")
        f.write(", ".join(sorted(hapax)))
    print("\nRaport salvat:", out)


if __name__ == "__main__":
    main()
