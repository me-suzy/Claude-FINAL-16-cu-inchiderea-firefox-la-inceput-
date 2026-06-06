# -*- coding: utf-8 -*-
"""
============================================================
 ANALIZA 5 — MINERIT STILISTIC (epitete, expresii, conectori, verbe)
============================================================
SCOP: sa-ti faci un "Caiet de schite stilistice" din presa veche, ca sa scrii mai
frumos pe blog. Extrage automat formele de exprimare elegante de epoca:

  A. EXPRESII (n-grame): combinatii de 3-4 cuvinte tipice epocii.
  B. CONECTORI ELEGANTI: "cu toate acestea", "drept urmare", "pe de o parte"...
     (cauta o lista de tranzitii fine si numara unde apar).
  C. EPITETE (adjectiv + substantiv) cu spaCy: "nepretuitul ajutor", "trista adunare".
     - lista frecventa + lista RARA (asocierile neobisnuite, cele mai expresive).
  D. TOPICA INVERSATA: adjectivul pus INAINTEA substantivului (solemn, de epoca).
  E. VERBE de epoca: cele mai folosite verbe (la radacina/lema).

  + Pregateste un PROMPT de "editor stilistic interbelic" + un pachet de context
    (epitete/conectori/verbe extrase) pe care il dai oricarui LLM (Ollama, Claude,
    ChatGPT) ca sa-ti rescrie propozitii moderne in stilul anilor 1930.

CUM TE AJUTA: in loc sa citesti manual mii de pagini, ai instant un dictionar de
figuri de stil. Regula de 10%: presari putin din ele in textul tau modern si suna
imediat mai muzical si mai ingrijit.

UTILIZARE:
  python "Analiza 5 - Minerit stilistic (epitete, expresii, conectori).py"
  python "Analiza 5 - Minerit stilistic (epitete, expresii, conectori).py" "cale\\fisier.txt"
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

# conectori / formule de tranzitie elegante (cu si fara diacritice)
CONECTORI = [
    "cu toate acestea", "cu toate ca", "cu toate că", "drept urmare", "prin urmare",
    "asadar", "așadar", "de altfel", "de altă parte", "de alta parte",
    "pe de o parte", "pe de alta parte", "pe de altă parte", "vazand acestea",
    "văzând acestea", "intrucat", "întrucât", "de buna seama", "de bună seamă",
    "in consecinta", "în consecință", "cu atat mai mult", "cu atât mai mult",
    "totodata", "totodată", "negresit", "negreșit", "fara indoiala", "fără îndoială",
    "spre deosebire", "dimpotriva", "dimpotrivă", "bunaoara", "bunăoară",
    "asijderea", "așijderea", "indeosebi", "îndeosebi", "de bunaseama",
    "in pofida", "în pofida", "cu prilejul", "spre pilda", "spre pildă",
]

STOP_RO = set("""a ai al ale am ar are as asa au ca care cat ce cea cei cel cele ci cind cine cit cu
cui cum da daca dar de deci din doar dupa eu el ea ei ele este esti era erau fara fi fie fost i ia
iar ii il imi in inca insa intr intre isi iti l la le li lor lui ma mai mea mei mele mi mie mine
mod ne nici nu o or ori pai pana pe pentru peste sa sai sale sau se si sint spre sub sunt ta te ti
tot toti totul tu un una unde unei unor unul va vom vor voi ale catre că dacă și şi în să său
această aceasta acea acele după până fără însă către când cînd încă într întru astfel""".split())


def words(text):
    return re.findall(r"[A-Za-zĂăÂâÎîȘșŞşȚțŢţ]+", text.lower())


def ngrams(toks, n):
    return [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]


def good_phrase(g):
    return g[0] not in STOP_RO and g[-1] not in STOP_RO and not all(w in STOP_RO for w in g)


def top_ngrams(toks, n, k, min_count=2):
    c = Counter(g for g in ngrams(toks, n) if good_phrase(g))
    return [(g, m) for g, m in c.most_common(k) if m >= min_count]


def find_connectors(text):
    low = text.lower()
    hits = []
    for c in CONECTORI:
        n = low.count(c.lower())
        if n:
            hits.append((c, n))
    # dedup variante diacritice/ne-diacritice care arata la fel
    return sorted(hits, key=lambda x: -x[1])


def context_of(text, phrase, ctx=45):
    m = re.search(re.escape(phrase), text, flags=re.I)
    if not m:
        return ""
    a = max(0, m.start() - ctx); b = min(len(text), m.end() + ctx)
    return "..." + text[a:b].replace("\n", " ").strip() + "..."


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "corpus_exemplu.txt")
    if not os.path.exists(path):
        print("Nu gasesc fisierul:", path); return
    text = open(path, encoding="utf-8", errors="replace").read()
    toks = words(text)

    print("=" * 60)
    print("ANALIZA 5 — MINERIT STILISTIC")
    print("Fisier:", os.path.basename(path), f"({len(toks)} cuvinte)")
    print("=" * 60)

    # A. expresii
    tri = top_ngrams(toks, 3, 20)
    quad = top_ngrams(toks, 4, 12)
    print("\n[A] EXPRESII tipice (3 cuvinte):")
    for g, n in tri:
        print(f"   {n:>3}  {' '.join(g)}")
    print("\n[A] EXPRESII tipice (4 cuvinte):")
    for g, n in quad:
        print(f"   {n:>3}  {' '.join(g)}")

    # B. conectori
    conn = find_connectors(text)
    print("\n[B] CONECTORI ELEGANTI gasiti in text:")
    if conn:
        for c, n in conn:
            print(f"   {n:>3}  {c:22} ex: {context_of(text, c)}")
    else:
        print("   (niciunul din lista in acest text - normal la texte scurte)")

    # C/D/E cu spaCy
    epitete = Counter()
    epitete_rare = []
    inversate = Counter()
    verbe = Counter()
    nlp = None
    try:
        import spacy
        nlp = spacy.load("ro_core_news_sm")
    except Exception as e:
        print(f"\n(!) spaCy ro indisponibil ({e}) - sar peste epitete/verbe. "
              f"Instaleaza: python -m spacy download ro_core_news_sm")

    if nlp is not None:
        if len(text) > nlp.max_length:
            nlp.max_length = len(text) + 1000
        doc = nlp(text)
        for tok in doc:
            if tok.pos_ == "VERB" and tok.is_alpha and len(tok.lemma_) > 2:
                verbe[tok.lemma_.lower()] += 1
            # epitet: adjectiv care determina un substantiv (relatia amod)
            if tok.pos_ == "ADJ" and tok.head.pos_ == "NOUN":
                adj, noun = tok, tok.head
                pair = " ".join(t.text for t in sorted([adj, noun], key=lambda t: t.i)).lower()
                epitete[pair] += 1
                if adj.i < noun.i:                     # adjectiv INAINTEA substantivului
                    inversate[pair] += 1

        epitete_rare = [p for p, n in epitete.items() if n == 1]

        print("\n[C] EPITETE frecvente (adjectiv + substantiv):")
        for p, n in epitete.most_common(20):
            print(f"   {n:>3}  {p}")
        print("\n[C] EPITETE RARE / neobisnuite (cele mai expresive, apar o data):")
        print("   " + " | ".join(sorted(epitete_rare)[:30]))
        print("\n[D] TOPICA INVERSATA (adjectiv inaintea substantivului - solemn):")
        for p, n in inversate.most_common(20):
            print(f"   {n:>3}  {p}")
        print("\n[E] VERBE de epoca (cele mai folosite, la radacina):")
        for v, n in verbe.most_common(25):
            print(f"   {n:>3}  {v}")

    # --- salvare Caiet de schite ---
    caiet = os.path.join(here, "Caiet de schite stilistice.txt")
    with open(caiet, "w", encoding="utf-8") as f:
        f.write(f"CAIET DE SCHITE STILISTICE — din {os.path.basename(path)}\n")
        f.write("=" * 50 + "\n\nEXPRESII (3-4 cuvinte):\n")
        for g, n in top_ngrams(toks, 3, 60) + top_ngrams(toks, 4, 40):
            f.write(f"{n}\t{' '.join(g)}\n")
        f.write("\nCONECTORI ELEGANTI:\n")
        for c, n in conn:
            f.write(f"{n}\t{c}\n")
        if nlp is not None:
            f.write("\nEPITETE (adjectiv+substantiv):\n")
            for p, n in epitete.most_common(150):
                f.write(f"{n}\t{p}\n")
            f.write("\nVERBE:\n")
            for v, n in verbe.most_common(150):
                f.write(f"{n}\t{v}\n")
    print("\nCaiet salvat:", caiet)

    # --- pachet de PROMPT pentru LLM (rescriere stil interbelic) ---
    top_ep = ", ".join(p for p, _ in epitete.most_common(25)) if nlp else ""
    top_co = ", ".join(c for c, _ in conn[:15])
    top_vb = ", ".join(v for v, _ in verbe.most_common(25)) if nlp else ""
    prompt_path = os.path.join(here, "Prompt stil interbelic + context.txt")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(
            "SYSTEM PROMPT (lipeste-l in Ollama / Claude / ChatGPT):\n"
            "---------------------------------------------------------\n"
            "Esti un editor stilistic din perioada interbelica romaneasca. Iti voi da o\n"
            "propozitie simpla si moderna, iar tu o vei rescrie pastrand sensul, dar folosind\n"
            "topica, vocabularul si formele de exprimare elegante din presa anilor 1930.\n"
            "Foloseste, unde se potriveste firesc, din urmatorul material EXTRAS din presa de epoca:\n\n"
            f"EPITETE: {top_ep}\n\n"
            f"CONECTORI: {top_co}\n\n"
            f"VERBE: {top_vb}\n\n"
            "Nu exagera: pastreaza textul lizibil pentru un cititor modern (regula de 10%).\n"
            "---------------------------------------------------------\n\n"
            "Exemplu de folosire:\n"
            "  Modern: \"Am citit o carte foarte buna ieri si cred ca merita cumparata.\"\n"
            "  Interbelic: \"Rasfoind in cursul zilei de ieri un volum de o rara valoare literara,\n"
            "  am dobandit convingerea ca achizitionarea sa este o datorie pentru orice spirit cultivat.\"\n\n"
            "Cum rulezi local cu Ollama (daca il ai instalat):\n"
            "  ollama run llama3  (apoi lipesti system prompt-ul de mai sus + propozitia ta)\n"
        )
    print("Prompt LLM + context salvat:", prompt_path)
    print("\nGATA. Ai acum 'Caiet de schite stilistice.txt' + 'Prompt stil interbelic + context.txt'.")


if __name__ == "__main__":
    main()
