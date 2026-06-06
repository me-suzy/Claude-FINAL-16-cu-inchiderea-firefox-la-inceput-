# -*- coding: utf-8 -*-
"""
============================================================
 ANALIZA 2 — EXPRESII SI COLOCATII (n-grame)
============================================================
CE FACE: gaseste GRUPURILE de cuvinte care apar des impreuna:
  - bigrame  = perechi de 2 cuvinte ("razboi mondial", "partidul comunist")
  - trigrame = grupuri de 3 cuvinte ("lupta de rezistenta")
Astea se numesc COLOCATII: cuvinte care "merg impreuna" natural in limba.

DE CE TE AJUTA LA SCRIS (NLP):
  - Cuvintele singure (Analiza 1) iti dau TEMA; expresiile iti dau STILUL si TOPICA.
  - Aici prinzi "tiparul de vorbire" al epocii: formulari, clisee, sintagme fixe.
  - Le poti folosi ca sa scrii autentic "in stilul anului 19xx" - exact ce voiai
    pentru asistentul de stil. Un model neuronal de scris devine mult mai bun daca
    ii dai astfel de expresii reale ca exemple/context.

CUM: pastram cuvintele goale in interiorul expresiei (ca sa sune natural), dar
cerem ca expresia sa NU inceapa/sfarseasca cu un cuvant gol (ca sa fie "intreaga").

UTILIZARE:
  python "Analiza 2 - Expresii si colocatii.py"
  python "Analiza 2 - Expresii si colocatii.py" "cale\\fisier.txt"
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

STOP_RO = set("""a ai al ale am ar are as asa au ca care cat ce cea cei cel cele ci cind cine cit cu
cui cum da daca dar de deci din doar dupa eu el ea ei ele este esti era erau fara fi fie fost i ia
iar ii il imi in inca insa intr intre isi iti l la le li lor lui ma mai mea mei mele mi mie mine
mod ne nici nu o or ori pai pana pe pentru peste sa sai sale sau se si sint spre sub sunt ta te ti
tot toti totul tu un una unde unei unor unul va vom vor voi ale catre""".split())
STOP_RO |= set("că dacă și şi în să său această aceasta acea acele după până fără însă dintre "
               "către când cînd încă într întru astfel".split())


def words(text):
    return re.findall(r"[A-Za-zĂăÂâÎîȘșŞşȚțŢţ]+", text.lower())


def ngrams(toks, n):
    return [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]


def good_phrase(gram):
    # expresia sa nu inceapa/sfarseasca cu cuvant gol; sa nu fie toata din cuvinte goale
    if gram[0] in STOP_RO or gram[-1] in STOP_RO:
        return False
    if all(w in STOP_RO for w in gram):
        return False
    if any(len(w) < 2 for w in gram):
        return False
    return True


def top_ngrams(toks, n, k=25, min_count=2):
    c = Counter(g for g in ngrams(toks, n) if good_phrase(g))
    return [(g, cnt) for g, cnt in c.most_common(k) if cnt >= min_count]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "corpus_exemplu.txt")
    if not os.path.exists(path):
        print("Nu gasesc fisierul:", path); return
    text = open(path, encoding="utf-8", errors="replace").read()
    toks = words(text)

    print("=" * 56)
    print("ANALIZA 2 — EXPRESII SI COLOCATII")
    print("Fisier:", os.path.basename(path), f"({len(toks)} cuvinte)")
    print("=" * 56)

    bi = top_ngrams(toks, 2, k=30)
    tri = top_ngrams(toks, 3, k=25)

    print("\nTop EXPRESII din 2 cuvinte (bigrame):")
    for g, n in bi:
        print(f"   {n:>3}  {' '.join(g)}")

    print("\nTop EXPRESII din 3 cuvinte (trigrame):")
    for g, n in tri:
        print(f"   {n:>3}  {' '.join(g)}")

    out = os.path.join(here, "Analiza 2 - rezultat.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"ANALIZA 2 — EXPRESII — {os.path.basename(path)}\n\n")
        f.write("BIGRAME (2 cuvinte):\n")
        for g, n in top_ngrams(toks, 2, k=100):
            f.write(f"{n}\t{' '.join(g)}\n")
        f.write("\nTRIGRAME (3 cuvinte):\n")
        for g, n in top_ngrams(toks, 3, k=100):
            f.write(f"{n}\t{' '.join(g)}\n")
    print("\nRaport salvat:", out)
    print("\nIDEE: ia expresiile astea si da-le unui model AI ca 'asa se scria atunci'.")


if __name__ == "__main__":
    main()
