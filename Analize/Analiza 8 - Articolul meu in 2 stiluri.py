# -*- coding: utf-8 -*-
"""
============================================================
 ANALIZA 8 — ARTICOLUL MEU IN 2 STILURI (2 voci din corpus)
============================================================
SCOP: iei articolul TAU si il rescrii in DOUA voci/stiluri diferite descoperite
AUTOMAT intr-un text-corpus (ex: o pagina de ziar cu mai multi autori).

CUM:
  1. Citeste corpusul (default "Analiza 1.txt"; pune acolo text de la 2+ autori).
  2. Il taie in fragmente si le grupeaza in 2 STILURI (clustering stilometric:
     TF-IDF pe n-grame de caractere + KMeans). Fiecare grup = o "voce".
  3. Pentru fiecare voce ia mostre reprezentative + o amprenta scurta (ritmul frazei).
  4. Iti construieste 2 PROMPTURI few-shot: "rescrie articolul meu in vocea A / B".
  5. Daca ai Ollama -> rescrie automat ambele; daca nu -> salveaza prompturile,
     gata de lipit in Claude/ChatGPT.

IMPORTANT: ideile/argumentele articolului raman ALE TALE; se schimba doar "vocea"
(ritm, vocabular, topica) ~30%, ca sa ramana modern si clar.

UTILIZARE:
  python "Analiza 8 - Articolul meu in 2 stiluri.py"
  python "Analiza 8 - Articolul meu in 2 stiluri.py" --article articolul_meu.txt --corpus "Analiza 1.txt"
  python "Analiza 8 - Articolul meu in 2 stiluri.py" --model mistral
============================================================
"""
import os
import re
import sys
import json
import argparse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

HERE = os.path.dirname(os.path.abspath(__file__))
OLLAMA = "http://localhost:11434"


def read_first_existing(*names):
    for n in names:
        p = n if os.path.isabs(n) else os.path.join(HERE, n)
        if os.path.exists(p):
            return open(p, encoding="utf-8", errors="replace").read(), p
    return None, None


def chunks(text, min_len=160):
    raw = re.split(r"\n\s*\n", text)
    out, buf = [], ""
    for p in raw:
        p = re.sub(r"\s+", " ", p).strip()
        if not p:
            continue
        buf = (buf + " " + p).strip()
        if len(buf) >= min_len:
            out.append(buf); buf = ""
    if len(buf) > 80:
        out.append(buf)
    return out


def sent_len(text):
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    wl = [len(re.findall(r"\w+", s)) for s in sents]
    return sum(wl) / len(wl) if wl else 0


def amprenta(text):
    al = sent_len(text)
    eticheta = ("scurta/taioasa" if al < 14 else "ampla/eseistica" if al > 22 else "echilibrata")
    return f"fraza medie {al:.0f} cuvinte ({eticheta})"


def ollama_models():
    try:
        r = urllib.request.urlopen(OLLAMA + "/api/tags", timeout=3)
        return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return None


def ollama_chat(model, system, user):
    payload = json.dumps({"model": model,
                          "messages": [{"role": "system", "content": system},
                                       {"role": "user", "content": user}],
                          "stream": False, "options": {"temperature": 0.85}}).encode("utf-8")
    req = urllib.request.Request(OLLAMA + "/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=180))["message"]["content"].strip()


def build_prompt(samples, eticheta, article):
    s = ("Esti un editor stilistic. Mai jos sunt MOSTRE dintr-o anumita voce de scriitor "
         f"(amprenta: {eticheta}), extrase automat dintr-un ziar vechi. Studiaza-i ritmul "
         "frazei, vocabularul, topica si atitudinea.\n\n")
    for i, m in enumerate(samples, 1):
        s += f"MOSTRA {i}:\n{m[:600]}\n\n"
    s += ("SARCINA: Rescrie articolul MEU de mai jos. Pastreaza-mi IDEILE, argumentele si "
          "subiectul intacte (sunt ale mele), dar infuzeaza ~30% din aceasta voce (ritm, "
          "vocabular, topica). Pastreaza textul lizibil pentru un cititor de azi. "
          "Raspunde doar cu articolul rescris.")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article", default=None, help="fisierul cu articolul tau")
    ap.add_argument("--corpus", default=None, help="textul-corpus cu autori (default Analiza 1.txt)")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    article, ap_path = (None, None)
    if args.article:
        article, ap_path = read_first_existing(args.article)
    if article is None:
        article, ap_path = read_first_existing("articolul_meu.txt")
    if article is None:
        print("Nu gasesc articolul. Da --article cale.txt sau pune articolul_meu.txt in folder.")
        return

    corpus, c_path = read_first_existing(args.corpus or "Analiza 1.txt", "corpus_exemplu.txt")
    if corpus is None:
        print("Nu gasesc corpusul. Pune text (de la 2+ autori) in 'Analiza 1.txt'.")
        return

    print("=" * 60)
    print("ANALIZA 8 — ARTICOLUL MEU IN 2 STILURI")
    print("Articol:", os.path.basename(ap_path))
    print("Corpus :", os.path.basename(c_path))
    print("=" * 60)

    frag = chunks(corpus)
    if len(frag) < 4:
        # prea putine fragmente -> impartim in 2 jumatati
        h = len(corpus) // 2
        grupuri = [[corpus[:h]], [corpus[h:]]]
        reps = [corpus[:h], corpus[h:]]
        labels = None
        print("(corpus mic: impart in 2 jumatati ca 2 voci)")
    else:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1, max_features=4000)
        X = vec.fit_transform(frag)
        km = KMeans(n_clusters=2, n_init=10, random_state=42).fit(X)
        labels = km.labels_
        dist = km.transform(X)
        grupuri = [[], []]
        for i, lab in enumerate(labels):
            grupuri[lab].append(frag[i])
        # mostre reprezentative = cele mai apropiate de centru
        reps = []
        for c in range(2):
            idx = [i for i in range(len(frag)) if labels[i] == c]
            idx.sort(key=lambda i: dist[i, c])
            reps.append([frag[i] for i in idx[:3]])

    rezultate = []
    for c in range(2):
        sample_list = reps[c] if isinstance(reps[c], list) else [reps[c]]
        text_voce = " ".join(sample_list)
        et = amprenta(text_voce)
        n = len(grupuri[c]) if labels is not None else 1
        print(f"\n--- VOCEA {chr(65+c)} ({n} fragmente) | amprenta: {et} ---")
        print("  mostra:", (sample_list[0][:160] + "...").replace("\n", " "))
        rezultate.append((chr(65 + c), et, sample_list, text_voce))

    models = ollama_models() if not args.model or True else None
    have_ollama = models is not None
    model = (args.model or (models[0] if models else None)) if have_ollama else None

    for litera, et, samples, _ in rezultate:
        system = build_prompt(samples, et, article)
        if have_ollama and model:
            print(f"\n[Ollama:{model}] rescriu in VOCEA {litera}...")
            try:
                txt = ollama_chat(model, system, article)
            except Exception as e:
                print("  eroare Ollama:", e); txt = None
            if txt:
                out = os.path.join(HERE, f"Articol in stil - VOCEA {litera}.txt")
                open(out, "w", encoding="utf-8").write(txt)
                print("  salvat:", out)
        else:
            out = os.path.join(HERE, f"Prompt - Articol in VOCEA {litera}.txt")
            with open(out, "w", encoding="utf-8") as f:
                f.write("=== SYSTEM ===\n" + system + "\n\n=== ARTICOLUL MEU ===\n" + article)
            print(f"  (fara Ollama) prompt VOCEA {litera} salvat -> de lipit in chat: {out}")

    if not have_ollama:
        print("\nFara Ollama local: ai 2 prompturi gata de lipit in Claude/ChatGPT.")
        print("Pt rescriere automata: instaleaza Ollama + 'ollama pull llama3.1'.")


if __name__ == "__main__":
    main()
