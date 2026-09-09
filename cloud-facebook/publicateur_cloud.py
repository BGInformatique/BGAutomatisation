#!/usr/bin/env python3
"""Publicateur Facebook — version cloud (GitHub Actions).

Jumeau de publicateur.py (à la racine de ce dépôt), pensé pour tourner sur
les serveurs de GitHub plutôt que sur la machine locale : l'automatisation
marche même quand l'ordinateur de {{ENTREPRISE}} est fermé.

Différences avec la version locale :
  - le contenu (texte du lot, visuels, file d'état) vit ICI, dans le dépôt du
    site — c'est cette copie qui fait foi pour la publication automatique,
    pas Campagne_BG/Contenus/ ;
  - pas de minuterie systemd : c'est un cron GitHub Actions (UTC) qui
    déclenche ce script deux fois par fenêtre visée (été/hiver), et c'est CE
    script qui vérifie l'heure réelle dans votre fuseau avant de publier —
    ainsi le changement d'heure ne fait dériver rien ;
  - la file `_File_Facebook.tsv` est modifiée sur place ; c'est le workflow
    (pas ce script) qui la commite et la pousse si elle a changé.

    python3 publicateur_cloud.py --essai    # montre ce qui partirait, n'envoie rien

Le jeton de Page vient de la variable d'environnement FB_PAGE_TOKEN (secret
GitHub Actions) — jamais d'un fichier local, jamais du dépôt.

Emplacement voulu une fois installé : automatisation/facebook/ à la racine
du dépôt de VOTRE site — voir README.md de ce dossier.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ICI = Path(__file__).resolve().parent
LOT = ICI / "Facebook-Residentiel-Lot-1.md"
FILE_TSV = ICI / "_File_Facebook.tsv"
VISUELS = ICI / "visuels"
COLS = ["ID", "TITRE", "STATUT", "PUBLIE_LE", "POST_ID"]
GRAPH = "https://graph.facebook.com/v23.0"
PAGE_ID = "{{PAGE_ID_FACEBOOK}}"  # pas un secret, juste un id
JOURS_ENTRE = 3          # une fenêtre bloquée si l'autre est passée moins de 3 jours avant
FUSEAU = ZoneInfo("{{FUSEAU_HORAIRE}}")  # ex. America/Toronto
ESSAI = "--essai" in sys.argv


def sortie(cle, valeur):
    """Écrit dans $GITHUB_OUTPUT si dispo (pour le message de commit du workflow)."""
    chemin = os.environ.get("GITHUB_OUTPUT")
    if not chemin:
        return
    with open(chemin, "a", encoding="utf-8") as f:
        f.write(f"{cle}={valeur}\n")


def deplier(texte):
    """Rend au texte ses paragraphes d'un seul tenant (voir la version locale)."""
    paras = []
    for bloc in texte.split("\n\n"):
        lignes = [l.strip() for l in bloc.splitlines() if l.strip()]
        if lignes:
            paras.append(" ".join(lignes))
    return "\n\n".join(paras)


def lire_lot():
    posts = {}
    texte = LOT.read_text(encoding="utf-8")
    for m in re.finditer(r"^## (\d+) — (.+?)$([\s\S]*?)(?=^## |\Z)", texte, re.M):
        num, titre, corps = int(m.group(1)), m.group(2).strip(), m.group(3)
        lignes = [l[1:].removeprefix(" ") for l in corps.splitlines() if l.startswith(">")]
        message = deplier("\n".join(lignes))
        if message:
            posts[num] = (titre, message)
    return posts


def lire_file():
    if not FILE_TSV.exists():
        return []
    lignes = FILE_TSV.read_text(encoding="utf-8").splitlines()
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
    FILE_TSV.write_text(corps, encoding="utf-8")


def amorcer_file(posts):
    rangs = lire_file()
    connus = {r["ID"] for r in rangs}
    for num in sorted(posts):
        if str(num) not in connus:
            rangs.append({"ID": str(num), "TITRE": posts[num][0],
                          "STATUT": "a_publier", "PUBLIE_LE": "", "POST_ID": ""})
    ecrire_file(rangs)
    return rangs


def visuel_de(id_publication):
    """Le visuel de cette publication, si son fichier est déposé dans visuels/."""
    correspondances = sorted(VISUELS.glob(f"page-{int(id_publication):02d}-*.jpg"))
    return correspondances[0] if correspondances else None


def publier(jeton, message, image=None):
    if not image:
        donnees = urllib.parse.urlencode(
            {"message": message, "access_token": jeton}).encode()
        req = urllib.request.Request(f"{GRAPH}/{PAGE_ID}/feed", data=donnees)
        with urllib.request.urlopen(req, timeout=30) as rep:
            return json.loads(rep.read()).get("id", "")

    limite = "----{{ENTREPRISE}}" + os.urandom(8).hex()
    corps = bytearray()
    for cle, valeur in (("caption", message), ("access_token", jeton)):
        corps += (f"--{limite}\r\nContent-Disposition: form-data; name=\"{cle}\"\r\n"
                  f"\r\n{valeur}\r\n").encode()
    corps += (f"--{limite}\r\nContent-Disposition: form-data; name=\"source\"; "
              f"filename=\"{image.name}\"\r\nContent-Type: image/jpeg\r\n\r\n").encode()
    corps += image.read_bytes() + b"\r\n"
    corps += f"--{limite}--\r\n".encode()

    req = urllib.request.Request(f"{GRAPH}/{PAGE_ID}/photos", data=bytes(corps))
    req.add_header("Content-Type", f"multipart/form-data; boundary={limite}")
    with urllib.request.urlopen(req, timeout=120) as rep:
        r = json.loads(rep.read())
        return r.get("post_id") or r.get("id", "")


def main():
    maintenant = datetime.now(FUSEAU)
    aujourd_hui = maintenant.date()

    posts = lire_lot()
    if not posts:
        print("aucun texte lisible dans le lot — vérifier le markdown")
        sortie("resultat", "erreur-lot")
        return 1
    rangs = amorcer_file(posts)

    # Hors fenêtre : le cron tourne deux fois pour couvrir l'heure d'été et
    # l'heure d'hiver, seule celle qui tombe vraiment à midi dans votre
    # fuseau doit agir. Adaptez l'heure de garde (12) si votre créneau diffère.
    if maintenant.hour != 12 and not ESSAI:
        print(f"hors fenêtre ({maintenant.strftime('%H:%M %Z')}) — on attend midi")
        sortie("resultat", "hors-fenetre")
        return 0

    for r in rangs:
        if r["PUBLIE_LE"]:
            ecart = (aujourd_hui - datetime.fromisoformat(r["PUBLIE_LE"]).date()).days
            if ecart < JOURS_ENTRE:
                if ESSAI:
                    print(f"publication {r['ID']} partie il y a {ecart} jour(s) — on attend.")
                sortie("resultat", "trop-tot")
                return 0

    suivant = next((r for r in rangs if r["STATUT"] == "a_publier"), None)
    if not suivant:
        print("lot épuisé — écrire le lot 2 (nouvelles sections ## 11+)")
        sortie("resultat", "lot-epuise")
        return 0
    titre, message = posts[int(suivant["ID"])]

    if "{{MANDAT_EXEMPLE}}" in message:
        print(f"« {titre} » mentionne {{MANDAT_EXEMPLE}} — bloqué, à vérifier")
        sortie("resultat", "bloque-mandat-exemple")
        return 1

    image = visuel_de(suivant["ID"])

    if ESSAI:
        print(f"partirait maintenant → {suivant['ID']} — {titre}")
        print(f"visuel : {image or '(aucun — texte seul)'}\n")
        print(message)
        sortie("resultat", "essai")
        return 0

    jeton = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not jeton:
        print("FB_PAGE_TOKEN absent — rien ne peut partir")
        sortie("resultat", "sans-jeton")
        return 1

    try:
        post_id = publier(jeton, message, image)
    except Exception as e:
        print(f"échec de publication « {titre} » : {e!r}")
        sortie("resultat", f"echec : {titre}")
        return 1

    suivant["STATUT"] = "publie"
    suivant["PUBLIE_LE"] = aujourd_hui.isoformat()
    suivant["POST_ID"] = post_id
    ecrire_file(rangs)
    resume = (f"publié — {suivant['ID']} « {titre} » ({post_id})"
              + (f" avec {image.name}" if image else " — texte seul"))
    print(resume)
    sortie("resultat", resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
