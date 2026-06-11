# -*- coding: utf-8 -*-
"""
adauga-folder-in-repository.py

Adauga toate fisierele dintr-un folder local intr-un repository de pe GitHub.

Flux:
  Fereastra 1 -> intreaba in ce repo de pe GitHub sa adaugi fisierele (URL repo).
  Fereastra 2 -> intreaba calea folderului local pe care vrei sa-l copiezi in repo,
                 cu un checkbox: "Copiaza si subfolderele" (recursiv) sau doar fisierele din folder.
  Apoi: cloneaza repo-ul, copiaza fisierele, face commit si push.

Necesita: git instalat si configurat (cu credentiale/token pentru push).
"""

import os
import sys
import shutil
import tempfile
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


# ----------------------------------------------------------------------------
# FEREASTRA 1: alegerea repo-ului de pe GitHub
# ----------------------------------------------------------------------------
def cere_repo():
    """Afiseaza prima fereastra si intoarce URL-ul repo-ului ales (sau None)."""
    rezultat = {"url": None}

    win = tk.Tk()
    win.title("Pasul 1/2 - Alege repository-ul GitHub")
    win.geometry("680x230")
    win.resizable(False, False)

    tk.Label(
        win,
        text="In ce repository de pe GitHub vrei sa adaugi fisierele?",
        font=("Segoe UI", 11, "bold"),
    ).pack(pady=(18, 4))

    tk.Label(
        win,
        text="Lipeste aici URL-ul complet al repo-ului (ex: https://github.com/me-suzy/NumeRepo)",
        font=("Segoe UI", 9),
        fg="#555",
    ).pack(pady=(0, 8))

    entry = tk.Entry(win, width=80, font=("Consolas", 10))
    entry.pack(pady=6, padx=20)
    entry.insert(0, "https://github.com/me-suzy/")
    entry.focus_set()

    def confirma():
        url = entry.get().strip()
        if not url:
            messagebox.showwarning("Atentie", "Trebuie sa introduci un URL de repository.")
            return
        if "github.com" not in url:
            if not messagebox.askyesno(
                "Confirmare",
                "URL-ul nu pare a fi de pe github.com.\nVrei sa continui oricum?",
            ):
                return
        rezultat["url"] = url
        win.destroy()

    btn = tk.Frame(win)
    btn.pack(pady=18)
    tk.Button(btn, text="Continua  ->", width=16, command=confirma,
              bg="#2e7d32", fg="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)
    tk.Button(btn, text="Anuleaza", width=12, command=win.destroy).pack(side="left", padx=6)

    win.bind("<Return>", lambda e: confirma())
    win.mainloop()
    return rezultat["url"]


# ----------------------------------------------------------------------------
# FEREASTRA 2: alegerea folderului local + checkbox subfoldere
# ----------------------------------------------------------------------------
def cere_folder():
    """Afiseaza a doua fereastra si intoarce (cale_folder, include_subfoldere) sau (None, None)."""
    rezultat = {"folder": None, "recursiv": None}

    win = tk.Tk()
    win.title("Pasul 2/2 - Alege folderul de copiat")
    win.geometry("680x260")
    win.resizable(False, False)

    tk.Label(
        win,
        text="Ce folder local vrei sa copiezi complet in repo?",
        font=("Segoe UI", 11, "bold"),
    ).pack(pady=(18, 8))

    rand = tk.Frame(win)
    rand.pack(pady=6, padx=20, fill="x")

    entry = tk.Entry(rand, width=62, font=("Consolas", 10))
    entry.pack(side="left", fill="x", expand=True)
    entry.insert(0, r"d:\TEST\arcanum_capture\\")

    def rasfoieste():
        cale = filedialog.askdirectory(title="Alege folderul de copiat")
        if cale:
            entry.delete(0, tk.END)
            entry.insert(0, cale)

    tk.Button(rand, text="Rasfoieste...", command=rasfoieste).pack(side="left", padx=(8, 0))

    var_recursiv = tk.BooleanVar(value=True)
    tk.Checkbutton(
        win,
        text="Copiaza si subfolderele (recursiv), nu doar fisierele din folder",
        variable=var_recursiv,
        font=("Segoe UI", 10),
    ).pack(pady=(14, 4), anchor="w", padx=22)

    def confirma():
        folder = entry.get().strip().strip('"')
        if not folder:
            messagebox.showwarning("Atentie", "Trebuie sa alegi un folder.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Eroare", f"Folderul nu exista:\n{folder}")
            return
        rezultat["folder"] = folder
        rezultat["recursiv"] = var_recursiv.get()
        win.destroy()

    btn = tk.Frame(win)
    btn.pack(pady=18)
    tk.Button(btn, text="Adauga in repo  ->", width=18, command=confirma,
              bg="#2e7d32", fg="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)
    tk.Button(btn, text="Anuleaza", width=12, command=win.destroy).pack(side="left", padx=6)

    win.bind("<Return>", lambda e: confirma())
    win.mainloop()
    return rezultat["folder"], rezultat["recursiv"]


# ----------------------------------------------------------------------------
# FEREASTRA 3: log / progres
# ----------------------------------------------------------------------------
class FereastraLog:
    def __init__(self):
        self.win = tk.Tk()
        self.win.title("Adaugare fisiere in repository - progres")
        self.win.geometry("760x460")
        self.txt = scrolledtext.ScrolledText(self.win, font=("Consolas", 9), wrap="word")
        self.txt.pack(fill="both", expand=True, padx=8, pady=8)
        self.btn = tk.Button(self.win, text="Inchide", width=14,
                             command=self.win.destroy, state="disabled")
        self.btn.pack(pady=(0, 10))
        self.win.update()

    def log(self, mesaj):
        self.txt.insert(tk.END, mesaj + "\n")
        self.txt.see(tk.END)
        self.win.update()

    def gata(self):
        self.btn.config(state="normal")
        self.win.mainloop()


# ----------------------------------------------------------------------------
# Operatii git + copiere
# ----------------------------------------------------------------------------
def ruleaza(comanda, cwd, log):
    """Ruleaza o comanda si trimite output-ul in log. Intoarce codul de iesire."""
    log("> " + " ".join(comanda))
    proc = subprocess.Popen(
        comanda, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for linie in proc.stdout:
        log(linie.rstrip())
    proc.wait()
    return proc.returncode


def copiaza_fisiere(sursa, destinatie, recursiv, log):
    """Copiaza continutul folderului sursa in destinatie."""
    nr = 0
    if recursiv:
        for radacina, _dirs, fisiere in os.walk(sursa):
            rel = os.path.relpath(radacina, sursa)
            dest_dir = destinatie if rel == "." else os.path.join(destinatie, rel)
            os.makedirs(dest_dir, exist_ok=True)
            for f in fisiere:
                shutil.copy2(os.path.join(radacina, f), os.path.join(dest_dir, f))
                nr += 1
    else:
        for nume in os.listdir(sursa):
            cale = os.path.join(sursa, nume)
            if os.path.isfile(cale):
                shutil.copy2(cale, os.path.join(destinatie, nume))
                nr += 1
    log(f"Copiate {nr} fisiere ({'cu subfoldere' if recursiv else 'doar fisierele din folder'}).")
    return nr


def proceseaza(repo_url, folder, recursiv):
    log_win = FereastraLog()
    L = log_win.log

    L("=" * 60)
    L(f"Repository : {repo_url}")
    L(f"Folder     : {folder}")
    L(f"Recursiv   : {'DA (cu subfoldere)' if recursiv else 'NU (doar fisierele)'}")
    L("=" * 60)

    # verifica git
    if shutil.which("git") is None:
        L("EROARE: git nu este instalat sau nu este in PATH.")
        log_win.gata()
        return

    temp = tempfile.mkdtemp(prefix="repo_upload_")
    nume_repo = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    clona = os.path.join(temp, nume_repo or "repo")

    try:
        L("\n[1/5] Clonez repository-ul...")
        if ruleaza(["git", "clone", repo_url, clona], temp, L) != 0:
            L("\nEROARE la clonare. Verifica URL-ul si accesul (token/credentiale).")
            log_win.gata()
            return

        L("\n[2/5] Copiez fisierele in repository...")
        nr = copiaza_fisiere(folder, clona, recursiv, L)
        if nr == 0:
            L("Nu am gasit fisiere de copiat. Ma opresc.")
            log_win.gata()
            return

        L("\n[3/5] git add ...")
        ruleaza(["git", "add", "-A"], clona, L)

        # verifica daca exista modificari
        rez = subprocess.run(["git", "status", "--porcelain"], cwd=clona,
                             capture_output=True, text=True)
        if not rez.stdout.strip():
            L("\nNu exista modificari noi fata de repo (fisierele exista deja identice).")
            log_win.gata()
            return

        L("\n[4/5] git commit ...")
        mesaj = f"Adauga fisiere din folderul {os.path.basename(folder.rstrip(os.sep))}"
        ruleaza(["git", "commit", "-m", mesaj], clona, L)

        L("\n[5/5] git push ...")
        if ruleaza(["git", "push"], clona, L) != 0:
            L("\nEROARE la push. Verifica autentificarea GitHub (token / git credential manager).")
            log_win.gata()
            return

        L("\n" + "=" * 60)
        L("GATA! Fisierele au fost adaugate si trimise pe GitHub.")
        L(repo_url)
        L("=" * 60)

    finally:
        # curata folderul temporar
        try:
            shutil.rmtree(temp, ignore_errors=True)
        except Exception:
            pass
        log_win.gata()


# ----------------------------------------------------------------------------
def main():
    repo_url = cere_repo()
    if not repo_url:
        return
    folder, recursiv = cere_folder()
    if not folder:
        return
    proceseaza(repo_url, folder, recursiv)


if __name__ == "__main__":
    main()
