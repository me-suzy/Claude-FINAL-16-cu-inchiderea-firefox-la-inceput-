# -*- coding: utf-8 -*-
"""
============================================================
 ANALIZA 4 — ENTITATI (nume, locuri, organizatii) — NER
============================================================
CE FACE: gaseste automat PERSOANELE, LOCURILE si ORGANIZATIILE din text.
  Se numeste NER (Named Entity Recognition) si e facut de un model NEURONAL
  (spaCy 'ro_core_news_sm'), antrenat sa recunoasca tipurile de nume proprii.
  Daca modelul lipseste, folosim o metoda simpla de rezerva (cuvinte cu majuscula).

DE CE TE AJUTA LA SCRIS:
  - Iti scoate instant CINE si UNDE apare in presa de epoca -> materie prima pentru
    rubrica "Acum X ani", pentru biografii, pentru harti/cronologii.
  - Construiesti un "who's who": ce personaje/orase/institutii apareau cel mai des.
  - E pasul de la "text brut" la "date" cu care poti face articole structurate.

UTILIZARE:
  python "Analiza 4 - Entitati (nume, locuri, organizatii).py"
  python "Analiza 4 - Entitati (nume, locuri, organizatii).py" "cale\\fisier.txt"
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


def fallback_proper_nouns(text):
    """Daca nu avem model NER: candidati = secvente de cuvinte cu majuscula,
    fara cele de la inceput de propozitie (aproximativ)."""
    # secvente gen "Satu Mare", "Gheorghe Pop"
    cands = re.findall(r"\b([A-ZĂÂÎȘŞȚŢ][a-zăâîșşțţ]+(?:\s+[A-ZĂÂÎȘŞȚŢ][a-zăâîșşțţ]+){0,2})", text)
    # scoatem cele care urmeaza imediat dupa ". " (probabil doar inceput de fraza)
    c = Counter(x.strip() for x in cands if len(x.strip()) > 2)
    return c


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "corpus_exemplu.txt")
    if not os.path.exists(path):
        print("Nu gasesc fisierul:", path); return
    text = open(path, encoding="utf-8", errors="replace").read()

    print("=" * 56)
    print("ANALIZA 4 — ENTITATI (NER)")
    print("Fisier:", os.path.basename(path))
    print("=" * 56)

    nlp = None
    try:
        import spacy
        nlp = spacy.load("ro_core_news_sm")
        print("Model neuronal: ro_core_news_sm (spaCy)\n")
    except Exception as e:
        print(f"(model spaCy ro indisponibil: {e})")
        print("Folosesc metoda de rezerva (cuvinte cu majuscula).\n")

    out = os.path.join(here, "Analiza 4 - rezultat.txt")

    if nlp is not None:
        if len(text) > nlp.max_length:
            nlp.max_length = len(text) + 1000
        doc = nlp(text)
        by_label = {}
        for ent in doc.ents:
            by_label.setdefault(ent.label_, Counter())[ent.text.strip()] += 1
        # etichete utile + nume prietenoase
        nice = {"PERSON": "PERSOANE", "PER": "PERSOANE", "GPE": "LOCURI (geo-politic)",
                "LOC": "LOCURI", "ORG": "ORGANIZATII", "NAT_REL_POL": "natiune/religie/politic",
                "EVENT": "EVENIMENTE", "DATETIME": "DATE", "PERIOD": "PERIOADE"}
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"ANALIZA 4 — ENTITATI — {os.path.basename(path)}\n\n")
            for label, counter in sorted(by_label.items(), key=lambda kv: -sum(kv[1].values())):
                titlu = nice.get(label, label)
                print(f"--- {titlu} ({label}) — {sum(counter.values())} aparitii ---")
                f.write(f"\n=== {titlu} ({label}) ===\n")
                for name, n in counter.most_common(15):
                    print(f"   {n:>3}  {name}")
                    f.write(f"{n}\t{name}\n")
                print()
    else:
        c = fallback_proper_nouns(text)
        print("--- Candidati nume proprii (top 30) ---")
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"ANALIZA 4 (rezerva) — {os.path.basename(path)}\n\n")
            for name, n in c.most_common(30):
                print(f"   {n:>3}  {name}")
                f.write(f"{n}\t{name}\n")

    print("Raport salvat:", out)


if __name__ == "__main__":
    main()
