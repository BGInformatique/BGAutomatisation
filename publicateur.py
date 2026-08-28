#!/usr/bin/env python3
"""Publicateur — publication Facebook automatisée de {{ENTREPRISE}}.

Chantier 2 du plan de campagne (Plan-Campagne-{{ENTREPRISE}}-2026.md § 7). Lancé par
bg-publicateur.timer le jeudi 18 h 30 et le dimanche 10 h — les deux fenêtres
où le public résidentiel des Laurentides est sur Facebook. Ce qu'il fait :

  1. lit la file (_File_Facebook.tsv) et prend la première publication
     « a_publier », dans l'ordre ;
  2. retrouve son texte INTACT dans Facebook-Residentiel-Lot-1.md — le
     markdown reste la seule source de vérité des textes, la file ne porte
     que l'état ;
  3. la publie sur la Page via l'API Graph (POST /{page}/feed), puis
     consigne la date et l'identifiant du billet dans la file.

Au plus UNE publication par passage, et jamais deux à moins de trois jours
d'écart : si le jeudi passe (machine éteinte), le dimanche rattrape, puis la
cadence revient d'elle-même au jeudi. Publier plus souvent que le lot n'a été
pensé n'apporte rien — la cadence du plan est hebdomadaire.

SANS JETON, IL NE SE PASSE RIEN : le script sort en silence tant que
facebook_jeton.json n'existe pas. On peut donc armer la minuterie avant même
que la Page soit prête. La marche à suivre pour le jeton est dans
LISEZ-MOI_Publicateur.md.

    python3 publicateur.py --essai    # montre ce qui partirait, n'envoie rien

Le jeton ne doit JAMAIS approcher le dépôt du site : il vit ici, dans un
dossier non versionné, en fichier 600.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import journaliser  # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))
CONTENUS = os.path.expanduser("~/Bureau/{{ENTREPRISE}}/02_Marketing/Campagne_BG/Contenus")
LOT = os.path.join(CONTENUS, "Facebook-Residentiel-Lot-1.md")
FILE_TSV = os.path.join(CONTENUS, "_File_Facebook.tsv")
JETON = os.path.join(ICI, "facebook_jeton.json")
COLS = ["ID", "TITRE", "STATUT", "PUBLIE_LE", "POST_ID"]
GRAPH = "https://graph.facebook.com/v23.0"
JOURS_ENTRE = 3          # jeudi → dimanche bloqué ; dimanche → jeudi permis
ESSAI = "--essai" in sys.argv


def lire_lot():
    """Les publications du markdown : {numéro: (titre, texte)}.

    Une section est un titre « ## N — … » suivi d'un bloc de citation ; le
    texte publié est la citation, débarrassée des « > ». Tout ce qui n'est pas
    dans une citation (règles, notes) n'est jamais publié.
    """
    posts = {}
    texte = open(LOT, encoding="utf-8").read()
    for m in re.finditer(r"^## (\d+) — (.+?)$([\s\S]*?)(?=^## |\Z)",
                         texte, re.M):
        num, titre, corps = int(m.group(1)), m.group(2).strip(), m.group(3)
        lignes = []
        for l in corps.splitlines():
            if l.startswith(">"):
                lignes.append(l[1:].removeprefix(" "))
        message = "\n".join(lignes).strip()
        if message:
            posts[num] = (titre, message)
    return posts


def lire_file():
    if not os.path.exists(FILE_TSV):
        return []
    lignes = open(FILE_TSV, encoding="utf-8").read().splitlines()
    entetes = lignes[0].split("\t")
    rangs = []
    for l in lignes[1:]:
        if not l.strip():
            continue
        c = l.split("\t")
        c += [""] * (len(entetes) - len(c))
        rangs.append(dict(zip(entetes, c)))
    return rangs


def ecrire_file(rangs):
    corps = "\n".join(["\t".join(COLS)] +
                      ["\t".join(r.get(c, "") for c in COLS) for r in rangs]) + "\n"
    with open(FILE_TSV, "w", encoding="utf-8") as f:
        f.write(corps)


def amorcer_file(posts):
    """Crée la file depuis le lot ; ajoute les numéros nouveaux sans toucher
    aux existants (un lot 2 ajouté au markdown entre tout seul dans la file)."""
    rangs = lire_file()
    connus = {r["ID"] for r in rangs}
    for num in sorted(posts):
        if str(num) not in connus:
            rangs.append({"ID": str(num), "TITRE": posts[num][0],
                          "STATUT": "a_publier", "PUBLIE_LE": "", "POST_ID": ""})
    ecrire_file(rangs)
    return rangs


def publier(page_id, jeton, message):
    donnees = urllib.parse.urlencode(
        {"message": message, "access_token": jeton}).encode()
    req = urllib.request.Request(f"{GRAPH}/{page_id}/feed", data=donnees)
    with urllib.request.urlopen(req, timeout=30) as rep:
        return json.loads(rep.read()).get("id", "")


def main():
    posts = lire_lot()
    if not posts:
        journaliser("publicateur : aucun texte lisible dans le lot — vérifier le markdown")
        return 1
    rangs = amorcer_file(posts)

    if not os.path.exists(JETON):
        if ESSAI:
            print("jeton absent (facebook_jeton.json) — le tuyau est prêt, "
                  "rien ne partira tant qu'il n'existe pas.")
        return 0
    cfg = json.load(open(JETON, encoding="utf-8"))
    page_id, jeton = cfg.get("page_id", ""), cfg.get("jeton", "")
    if not page_id or not jeton:
        journaliser("publicateur : facebook_jeton.json incomplet (page_id, jeton)")
        return 1

    # Jamais deux publications rapprochées : la cadence du plan est hebdomadaire.
    aujourd_hui = date.today()
    for r in rangs:
        if r["PUBLIE_LE"]:
            ecart = (aujourd_hui - date.fromisoformat(r["PUBLIE_LE"])).days
            if ecart < JOURS_ENTRE:
                if ESSAI:
                    print(f"publication {r['ID']} partie il y a {ecart} jour(s) — on attend.")
                return 0

    suivant = next((r for r in rangs if r["STATUT"] == "a_publier"), None)
    if not suivant:
        journaliser("publicateur : lot épuisé — écrire le lot 2 "
                    "(Facebook-Residentiel-Lot-1.md, nouvelles sections ## 11+)")
        return 0
    titre, message = posts[int(suivant["ID"])]

    # Garde-fou de cloisonnement : ces textes sont ceux de {{ENTREPRISE}}.
    # Un texte qui mentionne {{MANDAT_EXEMPLE}} n'a rien à faire sur cette Page.
    if "{{MANDAT_EXEMPLE}}" in message:
        journaliser(f"publicateur : « {titre} » mentionne {{MANDAT_EXEMPLE}} — bloqué, à vérifier")
        return 1

    if ESSAI:
        print(f"partirait maintenant → {suivant['ID']} — {titre}\n")
        print(message)
        return 0

    try:
        post_id = publier(page_id, jeton, message)
    except Exception as e:
        journaliser(f"publicateur : échec de publication « {titre} » : {e!r}")
        return 1
    suivant["STATUT"] = "publie"
    suivant["PUBLIE_LE"] = aujourd_hui.isoformat()
    suivant["POST_ID"] = post_id
    ecrire_file(rangs)
    journaliser(f"publicateur : publié — {suivant['ID']} « {titre} » ({post_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
