# -*- coding: utf-8 -*-
"""
============================================================
 ANALIZA 6 — STILOMETRIE: AMPRENTA STILISTICA A UNUI AUTOR
============================================================
SCOP: izolezi "ADN-ul" literar al unui scriitor (din rubrica lui fixa intr-un ziar)
ca sa-l poti imprumuta organic in scrisul tau.

CUM: pui articolele DOAR ale acelui autor (.txt) intr-un folder (ex: stil_autor\\)
si scriptul masoara:
  - RITMUL FRAZEI: lungimea medie/mediana a propozitiei, % fraze scurte vs lungi
    (scurt&taios = cioranian; lung cu subordonate = calinescian).
  - PUNCTUATIA: virgule/fraza, puncte-virgula, paranteze, linii de pauza
    (multe = stil digresiv, eseistic).
  - DENSITATEA PARTILOR DE VORBIRE (POS, cu spaCy): multe verbe = dinamic;
    multe adjective/adverbe = descriptiv, plastic.
  - OBSESIILE LEXICALE (TF-IDF): cuvintele rare/metaforele pe care le repeta obsesiv.
  - SEMNATURA pe cuvinte functionale (cum foloseste "insa", "dar", "asadar"...).

LA FINAL: iti construieste un PROMPT few-shot (cu 2-3 fragmente reale ale autorului)
gata de dat unui LLM ca sa-ti infuzeze 30% din stilul lui in textul tau.

UTILIZARE:
  python "Analiza 6 - Stilometrie autor (amprenta).py" "cale\\catre\\folder_autor"
  python "Analiza 6 - Stilometrie autor (amprenta).py"        (implicit: .\\stil_autor)
============================================================
"""
import os
import re
import sys
import glob
import statistics as st
from collections import Counter

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
toti totul tu un una unde unei unele unor unul va vom vor voi zi ale catre că dacă și şi în să său
această aceasta acea acele după până fără însă către când cînd încă într întru astfel""".split()

# cuvinte functionale urmarite ca "semnatura" stilistica
FUNCTION_WORDS = ["insa", "dar", "asadar", "deci", "totusi", "asa", "iar", "ci", "caci",
                  "desi", "intrucat", "asadar", "prin urmare", "cu toate acestea", "de altfel"]


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 1]


def words(text):
    return re.findall(r"[A-Za-zĂăÂâÎîȘșŞşȚțŢţ]+", text.lower())


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "stil_autor")
    if not os.path.isdir(folder):
        print("Nu exista folderul:", folder)
        print("Creeaza-l si pune acolo .txt cu articolele DOAR ale autorului dorit.")
        return
    files = sorted(glob.glob(os.path.join(folder, "*.txt")))
    if not files:
        print("Niciun .txt in", folder); return

    texts = [open(f, encoding="utf-8", errors="replace").read() for f in files]
    full = "\n\n".join(texts)
    toks = words(full)
    sents = sentences(full)
    slen = [len(words(s)) for s in sents if s]

    print("=" * 60)
    print("ANALIZA 6 — AMPRENTA STILISTICA")
    print("Folder:", folder, f"| {len(files)} fisiere | {len(toks)} cuvinte | {len(sents)} fraze")
    print("=" * 60)

    # 1) ritmul frazei
    if slen:
        scurte = 100 * sum(1 for x in slen if x <= 8) / len(slen)
        lungi = 100 * sum(1 for x in slen if x >= 25) / len(slen)
        print("\n[RITMUL FRAZEI]")
        print(f"   lungime medie: {st.mean(slen):.1f} cuvinte | mediana: {st.median(slen):.0f}")
        print(f"   fraze scurte (<=8 cuv): {scurte:.0f}%   |   fraze lungi (>=25): {lungi:.0f}%")
        verdict = ("taios/axiomatic (tip cioranian)" if st.mean(slen) < 14
                   else "amplu/eseistic (tip calinescian)" if st.mean(slen) > 22
                   else "echilibrat")
        print(f"   => ritm: {verdict}")

    # 2) punctuatie
    n_sent = max(1, len(sents))
    print("\n[PUNCTUATIE]")
    for simbol, nume in [(",", "virgule"), (";", "punct-virgula"), ("—", "linie pauza"),
                         ("-", "cratima/pauza"), ("(", "paranteze"), (":", "doua puncte")]:
        print(f"   {nume:14}: {full.count(simbol)/n_sent:.2f} / fraza")
    print("   (multe virgule/paranteze/linii = stil digresiv, eseistic)")

    # 3) POS density cu spaCy
    try:
        import spacy
        nlp = spacy.load("ro_core_news_sm")
        if len(full) > nlp.max_length:
            nlp.max_length = len(full) + 1000
        doc = nlp(full)
        pos = Counter(t.pos_ for t in doc if t.is_alpha)
        tot = sum(pos.values()) or 1
        print("\n[DENSITATEA PARTILOR DE VORBIRE]")
        for p in ["NOUN", "VERB", "ADJ", "ADV", "PROPN"]:
            print(f"   {p:6}: {100*pos.get(p,0)/tot:5.1f}%")
        dinamic = pos.get("VERB", 0) >= pos.get("ADJ", 0) + pos.get("ADV", 0)
        print("   =>", "stil DINAMIC (multe verbe)" if dinamic else "stil DESCRIPTIV (multe adjective/adverbe)")
    except Exception as e:
        print("\n(POS spaCy indisponibil:", e, ")")

    # 4) obsesii lexicale (TF-IDF)
    docs = texts if len(texts) > 1 else re.split(r"\n\s*\n", full)
    docs = [d for d in docs if len(d.strip()) > 80] or [full]
    print("\n[OBSESII LEXICALE — cuvinte/metafore definitorii (TF-IDF)]")
    try:
        vec = TfidfVectorizer(stop_words=STOP_RO,
                              token_pattern=r"[A-Za-zĂăÂâÎîȘșŞşȚțŢţ]{4,}",
                              ngram_range=(1, 2), min_df=1)
        X = vec.fit_transform(docs)
        terms = vec.get_feature_names_out()
        import numpy as np
        sc = np.asarray(X.sum(axis=0)).ravel()
        for i in sc.argsort()[::-1][:20]:
            print(f"   {sc[i]:5.2f}  {terms[i]}")
    except Exception as e:
        print("   (TF-IDF a esuat:", e, ")")

    # 5) raport + prompt few-shot
    report = os.path.join(here, "Analiza 6 - amprenta.txt")
    with open(report, "w", encoding="utf-8") as f:
        f.write(f"AMPRENTA STILISTICA — {folder}\n")
        if slen:
            f.write(f"lungime medie fraza: {st.mean(slen):.1f}; mediana {st.median(slen):.0f}\n")
        f.write("\nVezi consola pentru detalii complete.\n")

    # prompt few-shot cu 2-3 fragmente reale
    fragmente = []
    for t in texts[:3]:
        frag = " ".join(t.split())[:500]
        if len(frag) > 100:
            fragmente.append(frag)
    prompt = os.path.join(here, "Analiza 6 - prompt few-shot autor.txt")
    with open(prompt, "w", encoding="utf-8") as f:
        f.write("SYSTEM: Esti expert in stilistica literara. Studiaza fragmentele de mai jos\n"
                "scrise de un anumit autor si deprinde-i topica, ironia, vocabularul si ritmul frazei.\n\n")
        for i, fr in enumerate(fragmente, 1):
            f.write(f"EXEMPLU {i} (autorul):\n{fr}\n\n")
        f.write("SARCINA: Reformuleaza textul MEU de mai jos pastrand 70% din stilul meu (modern, clar),\n"
                "dar infuzeaza 30% din ironia, conectorii si eleganta topicii autorului de mai sus.\n"
                "Pastreaza-mi ideile si argumentele intacte.\n\nTEXTUL MEU:\n[lipeste aici articolul tau]\n")
    print("\nRaport salvat:", report)
    print("Prompt few-shot (transfer de stil) salvat:", prompt)


if __name__ == "__main__":
    main()
