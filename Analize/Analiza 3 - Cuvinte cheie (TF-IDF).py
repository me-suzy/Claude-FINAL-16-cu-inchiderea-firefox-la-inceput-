# -*- coding: utf-8 -*-
"""
============================================================
 ANALIZA 3 — CUVINTE-CHEIE (TF-IDF)
============================================================
CE FACE: gaseste cuvintele IMPORTANTE, nu doar pe cele frecvente.

  Diferenta fata de Analiza 1:
   - Frecventa simpla scoate in fata cuvinte banale ("oameni", "ani").
   - TF-IDF scoate in fata cuvintele CARACTERISTICE: cele care apar des intr-o
     bucata de text, dar RAR in rest. Adica exact "despre ce" e fiecare parte.

  Cum: taiem textul in bucati (paragrafe) = mai multe "documente". Apoi TF-IDF
  (Term Frequency × Inverse Document Frequency) da fiecarui cuvant un scor de
  "cat de definitoriu" e. E un algoritm clasic NLP, baza motoarelor de cautare.

DE CE TE AJUTA LA SCRIS:
  - Iti da TEMELE reale ale unui numar de revista, automat -> idei de articole.
  - Poti eticheta/rezuma rapid un document ("despre ce e nr. 3 din 1969?").
  - E fix ce sta la baza unui sistem RAG: gasesti bucatile relevante dupa cuvinte-cheie.

UTILIZARE:
  python "Analiza 3 - Cuvinte cheie (TF-IDF).py"
  python "Analiza 3 - Cuvinte cheie (TF-IDF).py" "cale\\fisier.txt"
============================================================
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from sklearn.feature_extraction.text import TfidfVectorizer

STOP_RO = """a ai al ale am ar are as asa au ca care cat ce cea cei cel cele ci cind cine cit cu cui
cum da daca dar de deci din doar dupa eu el ea ei ele este esti era erau fara fi fie fost i ia iar
ii il imi in inca insa intr intre isi iti l la le li lor lui ma mai mare mea mei mele mi mie mine
mod mult multe multi ne nici nimic niste nostru nou noi nu o or ori pai pana pe pentru peste poate
pot prea prin sa sai sale sau se si sint sintem spre sub sunt suntem ta te ti tine toata toate tot
toti totul tu un una unde unei unele unor unul va vom vor voi zi ale catre fata fel cei dintre
că dacă și şi în să său această aceasta acea acele după până fără însă către când cînd încă într
întru astfel""".split()


def chunks_by_paragraph(text, min_len=200):
    raw = re.split(r"\n\s*\n", text)
    out, buf = [], ""
    for p in raw:
        p = p.strip()
        if not p:
            continue
        buf = (buf + " " + p).strip()
        if len(buf) >= min_len:
            out.append(buf); buf = ""
    if len(buf) > 50:
        out.append(buf)
    return out or [text]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "corpus_exemplu.txt")
    if not os.path.exists(path):
        print("Nu gasesc fisierul:", path); return
    text = open(path, encoding="utf-8", errors="replace").read()

    docs = chunks_by_paragraph(text)
    print("=" * 56)
    print("ANALIZA 3 — CUVINTE-CHEIE (TF-IDF)")
    print("Fisier:", os.path.basename(path), f"| {len(docs)} bucati de text analizate")
    print("=" * 56)

    vec = TfidfVectorizer(
        lowercase=True,
        stop_words=STOP_RO,
        token_pattern=r"[A-Za-zĂăÂâÎîȘșŞşȚțŢţ]{3,}",
        ngram_range=(1, 2),     # cuvinte simple + perechi
        min_df=1,
    )
    X = vec.fit_transform(docs)
    terms = vec.get_feature_names_out()

    # scor global = suma TF-IDF pe toate bucatile -> cuvintele cele mai definitorii
    import numpy as np
    scoruri = np.asarray(X.sum(axis=0)).ravel()
    top_idx = scoruri.argsort()[::-1][:30]

    print("\nTop 30 cuvinte/expresii-cheie (cele mai definitorii pentru text):")
    for i in top_idx:
        print(f"   {scoruri[i]:6.2f}  {terms[i]}")

    # si cate un cuvant-cheie pentru fiecare bucata (despre ce e fiecare paragraf)
    print("\nCuvantul-cheie principal al fiecarei bucati (primele 12):")
    for d in range(min(12, X.shape[0])):
        row = X.getrow(d).toarray().ravel()
        j = row.argmax()
        print(f"   bucata {d+1:>2}: {terms[j]:20}  (fragment: {docs[d][:50].strip()}...)")

    out = os.path.join(here, "Analiza 3 - rezultat.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"ANALIZA 3 — CUVINTE-CHEIE TF-IDF — {os.path.basename(path)}\n\n")
        for i in scoruri.argsort()[::-1][:100]:
            f.write(f"{scoruri[i]:.3f}\t{terms[i]}\n")
    print("\nRaport salvat:", out)


if __name__ == "__main__":
    main()
