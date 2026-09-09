#!/usr/bin/env python3
"""Synchroniser le publicateur Facebook cloud avec le contenu local.

Depuis que la publication réelle sur la Page tourne sur GitHub Actions
({{DEPOT_SITE}}/automatisation/facebook/), pas ici — voir
LISEZ-MOI_Publicateur.md — deux copies existent forcément :

  - LOCALE (Campagne_BG/Contenus/) : là où le lot se rédige. Fait foi pour
    le TEXTE et les VISUELS.
  - DÉPÔT ({{DEPOT_SITE}}/automatisation/facebook/) : là où le
    workflow publie pour de vrai. Fait foi pour ce qui est déjà PARTI
    (STATUT, PUBLIE_LE, POST_ID).

Ce script réconcilie les deux à chaque passage :

  1. Clone jetable de {{DEPOT_SITE}} dans un dossier temporaire — jamais la
     copie locale du dépôt, qui peut appartenir à une session interactive en
     cours et ne doit pas être touchée par un script automatique.
  2. Si le markdown du lot a changé localement, il remplace la copie du
     dépôt.
  3. Toute section ## N du markdown sans ligne correspondante dans la file
     du dépôt en obtient une neuve (STATUT a_publier) — c'est ainsi qu'un
     lot 2, une fois collé dans le markdown local, se retrouve en file de
     publication sans étape manuelle.
  4. Tout visuel « page-*.jpg » présent localement et absent du dépôt y est
     copié.
  5. S'il y a un écart, commit + push direct sur main.
  6. Que le dépôt ait changé ou non, la file qui en résulte est réécrite
     PAR-DESSUS la copie locale — c'est ce qui tient sante_facebook.py et
     la vigie à jour sans qu'ils aient besoin de savoir que la publication
     est partie dans le cloud.

    python3 synchroniser_publicateur_facebook.py --essai   # montre l'écart, ne touche à rien

Pensé pour être appelé automatiquement par vigie.py à chaque passage
quotidien.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import journaliser  # noqa: E402

DEPOT_URL = "https://github.com/{{ORG_GITHUB}}/{{DEPOT_SITE}}.git"
SOUS_DOSSIER = "automatisation/facebook"

CONTENUS = os.path.expanduser("~/Bureau/{{ENTREPRISE}}/02_Marketing/Campagne_BG/Contenus")
LOT_LOCAL = os.path.join(CONTENUS, "Facebook-Residentiel-Lot-1.md")
TSV_LOCAL = os.path.join(CONTENUS, "_File_Facebook.tsv")
VISUELS_LOCAL = os.path.expanduser(
    "~/Bureau/{{ENTREPRISE}}/02_Marketing/Visuels-Facebook/1x1")
COLS = ["ID", "TITRE", "STATUT", "PUBLIE_LE", "POST_ID"]
ESSAI = "--essai" in sys.argv


def lire_lot(chemin):
    if not os.path.exists(chemin):
        return {}
    texte = open(chemin, encoding="utf-8").read()
    posts = {}
    for m in re.finditer(r"^## (\d+) — (.+?)$", texte, re.M):
        posts[int(m.group(1))] = m.group(2).strip()
    return posts


def lire_tsv(chemin):
    if not os.path.exists(chemin):
        return []
    lignes = [l for l in open(chemin, encoding="utf-8").read().splitlines() if l.strip()]
    if not lignes:
        return []
    entetes = lignes[0].split("\t")
    return [dict(zip(entetes, l.split("\t") + [""] * len(entetes))) for l in lignes[1:]]


def ecrire_tsv(chemin, rangs):
    corps = "\n".join(["\t".join(COLS)] +
                      ["\t".join(r.get(c, "") for c in COLS) for r in rangs]) + "\n"
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(corps)


def executer(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} : {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def main():
    if not os.path.exists(LOT_LOCAL):
        journaliser("synchroniser_publicateur_facebook : lot local introuvable, rien à faire")
        return 0

    dossier_tmp = tempfile.mkdtemp(prefix="sync-fb-")
    try:
        executer(["git", "clone", "--depth", "1", DEPOT_URL, "depot"], cwd=dossier_tmp)
        depot = os.path.join(dossier_tmp, "depot")
        cible = os.path.join(depot, SOUS_DOSSIER)
        os.makedirs(cible, exist_ok=True)
        os.makedirs(os.path.join(cible, "visuels"), exist_ok=True)

        lot_depot = os.path.join(cible, "Facebook-Residentiel-Lot-1.md")
        tsv_depot = os.path.join(cible, "_File_Facebook.tsv")
        visuels_depot = os.path.join(cible, "visuels")

        changements = []

        # 1. le texte du lot : la copie locale fait foi
        texte_local = open(LOT_LOCAL, encoding="utf-8").read()
        texte_depot = open(lot_depot, encoding="utf-8").read() if os.path.exists(lot_depot) else ""
        if texte_local != texte_depot:
            if not ESSAI:
                shutil.copyfile(LOT_LOCAL, lot_depot)
            changements.append("texte du lot mis à jour")

        # 2. la file : le dépôt fait foi pour l'état, le lot local pour les IDs à créer
        rangs = lire_tsv(tsv_depot)
        connus = {r["ID"] for r in rangs}
        posts = lire_lot(LOT_LOCAL)
        for num in sorted(posts):
            if str(num) not in connus:
                rangs.append({"ID": str(num), "TITRE": posts[num], "STATUT": "a_publier",
                              "PUBLIE_LE": "", "POST_ID": ""})
                changements.append(f"nouvelle entrée en file : {num} — {posts[num]}")
        if changements and not ESSAI:
            ecrire_tsv(tsv_depot, rangs)

        # 3. les visuels : tout ce qui est prêt localement et absent du dépôt
        if os.path.isdir(VISUELS_LOCAL):
            for nom in sorted(os.listdir(VISUELS_LOCAL)):
                if not nom.startswith("page-") or not nom.endswith(".jpg"):
                    continue
                if not os.path.exists(os.path.join(visuels_depot, nom)):
                    if not ESSAI:
                        shutil.copyfile(os.path.join(VISUELS_LOCAL, nom),
                                        os.path.join(visuels_depot, nom))
                    changements.append(f"visuel copié : {nom}")

        if ESSAI:
            if changements:
                print("Écart détecté (rien n'a été touché, --essai) :")
                for c in changements:
                    print(f"  - {c}")
            else:
                print("Aucun écart — dépôt et local déjà alignés.")
            # on peut quand même rapatrier l'état réel pour l'essai, en lecture seule
            rangs_reels = lire_tsv(tsv_depot)
            if rangs_reels:
                print(f"\nFile du dépôt : {len(rangs_reels)} entrée(s), "
                      + ", ".join(f"{sum(1 for r in rangs_reels if r['STATUT'] == s)} {s}"
                                  for s in {r['STATUT'] for r in rangs_reels}))
            return 0

        if changements:
            executer(["git", "add", SOUS_DOSSIER], cwd=depot)
            statut = executer(["git", "status", "--porcelain", "--", SOUS_DOSSIER], cwd=depot)
            if statut.strip():
                executer(["git", "-c", "user.name=github-actions-local[bot]",
                          "-c", "user.email=github-actions-local@{{DOMAINE}}",
                          "commit", "-m",
                          "Publicateur Facebook : synchronisation automatique du lot local\n\n"
                          + "\n".join(f"- {c}" for c in changements)], cwd=depot)
                executer(["git", "push", "origin", "HEAD:main"], cwd=depot)
                journaliser("synchroniser_publicateur_facebook : poussé — "
                            + " ; ".join(changements))
            rangs = lire_tsv(tsv_depot)

        # 4. dans tous les cas : la file locale reflète l'état réel du dépôt
        #    (ce qui tient sante_facebook.py et vigie.py à jour même quand
        #    seul le workflow cloud a publié depuis le dernier passage)
        rangs_reels = lire_tsv(tsv_depot)
        if rangs_reels and lire_tsv(TSV_LOCAL) != rangs_reels:
            ecrire_tsv(TSV_LOCAL, rangs_reels)
            journaliser("synchroniser_publicateur_facebook : file locale rafraîchie depuis le dépôt")

        if not changements:
            journaliser("synchroniser_publicateur_facebook : rien à synchroniser")
        return 0
    finally:
        shutil.rmtree(dossier_tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
