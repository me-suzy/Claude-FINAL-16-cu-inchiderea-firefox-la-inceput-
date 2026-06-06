# -*- coding: utf-8 -*-
"""
============================================================
 RESCRIERE IN STIL 1932 (interbelic) — cu LLM
============================================================
CE FACE: iei o propozitie/paragraf modern si il rescrie in stilul presei
interbelice, folosind CONTEXTUL extras de Analiza 5 (epitete, conectori, verbe).

  - Daca ai OLLAMA pornit local -> rescrie automat (model llama3 / mistral / etc).
  - Daca NU ai Ollama -> iti asambleaza prompt-ul complet intr-un fisier, gata de
    lipit in Claude / ChatGPT (merge imediat, fara nicio instalare).

UTILIZARE:
  python "Rescriere stil 1932.py" "Am citit o carte buna ieri si merita cumparata."
  python "Rescriere stil 1932.py" --file articol.txt
  python "Rescriere stil 1932.py" "..." --model mistral        (alege modelul Ollama)
  python "Rescriere stil 1932.py" "..." --prompt-only           (doar prompt, fara LLM)

CA SA MEARGA LOCAL (o singura data):
  1) instaleaza Ollama de pe https://ollama.com
  2) in terminal:  ollama pull llama3.1     (sau: ollama pull mistral)
  3) ruleaza scriptul normal -> va folosi Ollama automat.
============================================================
"""
import os
import sys
import json
import argparse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
OLLAMA = "http://localhost:11434"


def load_context():
    """Ia epitete/conectori/verbe din fisierul produs de Analiza 5, daca exista."""
    f = os.path.join(HERE, "Prompt stil interbelic + context.txt")
    if os.path.exists(f):
        return open(f, encoding="utf-8", errors="replace").read()
    return ""


def build_system_prompt():
    ctx = load_context()
    base = (
        "Esti un editor stilistic din perioada interbelica romaneasca (anii 1930). "
        "Primesti o propozitie sau un paragraf modern si il rescrii PASTRAND SENSUL, "
        "dar folosind topica, vocabularul, conectorii eleganti si formele de exprimare "
        "ale presei romanesti din acea epoca. Pastreaza textul lizibil pentru un cititor "
        "de azi (regula de 10-30%: infuzezi stil, nu ingreunezi). Raspunde DOAR cu textul rescris."
    )
    if ctx:
        base += "\n\nFoloseste, unde se potriveste firesc, materialul EXTRAS din presa de epoca:\n" + ctx
    return base


def ollama_models():
    try:
        r = urllib.request.urlopen(OLLAMA + "/api/tags", timeout=3)
        return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return None


def ollama_chat(model, system, user):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": False,
        "options": {"temperature": 0.8},
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA + "/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=120)
    return json.load(r)["message"]["content"].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="textul de rescris")
    ap.add_argument("--file", help="citeste textul dintr-un fisier")
    ap.add_argument("--model", default=None, help="model Ollama (ex: llama3.1, mistral)")
    ap.add_argument("--prompt-only", action="store_true", help="doar asambleaza prompt-ul")
    args = ap.parse_args()

    if args.file:
        text = open(args.file, encoding="utf-8", errors="replace").read()
    elif args.text:
        text = args.text
    else:
        print("Da-mi un text: python \"Rescriere stil 1932.py\" \"propozitia ta\"")
        return

    system = build_system_prompt()

    # mod doar-prompt sau Ollama lipsa -> salvam prompt-ul complet pentru chat LLM
    models = None if args.prompt_only else ollama_models()
    if args.prompt_only or models is None:
        out = os.path.join(HERE, "Rescriere - prompt de lipit in chat.txt")
        with open(out, "w", encoding="utf-8") as f:
            f.write("=== SYSTEM ===\n" + system + "\n\n=== TEXTUL MEU (de rescris) ===\n" + text + "\n")
        if models is None and not args.prompt_only:
            print("Ollama nu ruleaza local. Am salvat prompt-ul complet, gata de lipit in")
            print("Claude / ChatGPT:\n  ", out)
            print("\nSau instaleaza Ollama (https://ollama.com), 'ollama pull llama3.1', si reruleaza.")
        else:
            print("Prompt salvat:", out)
        return

    if not models:
        print("Ollama ruleaza dar n-ai niciun model. Ruleaza:  ollama pull llama3.1")
        return
    model = args.model or models[0]
    print(f"Rescriu cu Ollama (model: {model})...\n")
    try:
        rezultat = ollama_chat(model, system, text)
    except Exception as e:
        print("Eroare la Ollama:", e); return

    print("--- ORIGINAL ---\n" + text.strip())
    print("\n--- IN STIL 1932 ---\n" + rezultat)
    out = os.path.join(HERE, "Rescriere - rezultat.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("ORIGINAL:\n" + text + "\n\nIN STIL 1932:\n" + rezultat + "\n")
    print("\nSalvat:", out)


if __name__ == "__main__":
    main()
