#!/usr/bin/env python3
"""Publicateur — publication Instagram automatisée de {{ENTREPRISE}}.

Jumeau de publicateur.py (Facebook), même architecture, quatre différences
imposées par l'API Instagram (chemin « Instagram API avec connexion
Instagram » — @{{HANDLE}} garde son propre courriel, voir
LISEZ-MOI_Publicateur_Instagram.md) :

  1. l'hôte de l'API est graph.instagram.com, pas graph.facebook.com ;
  2. la publication se fait en DEUX appels — créer un conteneur média
     (POST /{ig-user-id}/media avec image_url + caption), puis le publier
     (POST /{ig-user-id}/media_publish avec le creation_id) ;
  3. image_url doit être une adresse PUBLIQUE — Instagram va la chercher
     lui-même, on ne peut pas lui envoyer le fichier local directement.
     Tant que BASE_URL_IMAGES n'est pas réglé plus bas, le script le dit
     et ne publie rien ;
  4. le jeton EXPIRE après 60 jours — renouveler_instagram.py le renouvelle
     avant l'échéance ; ce script-ci refuse de publier si l'échéance
     (expire_le) est dépassée plutôt que d'échouer à l'appel Graph.

Ici, contrairement à Facebook, il n'y a pas de markdown séparé pour les
textes : la file _File_Instagram.tsv EST la source de vérité (colonne
IMAGE + colonne LEGENDE ensemble), parce qu'une publication Instagram est
une paire image+texte, pas un texte seul. Une ligne dont la LEGENDE est
vide reste STATUT=a_ecrire — le script ne la touche pas tant qu'elle n'a
pas été écrite et remise à a_publier à la main.

SANS JETON, IL NE SE PASSE RIEN : le script sort en silence tant que
instagram_jeton.json n'existe pas. Ce fichier s'écrit avec
configurer_instagram.py (une fois, à la main) — la marche à suivre est dans
LISEZ-MOI_Publicateur_Instagram.md.

    python3 publicateur_instagram.py --essai   # montre ce qui partirait, n'envoie rien

Le jeton ne doit JAMAIS approcher le dépôt du site : il vit ici, dans un
dossier non versionné, en fichier 600.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import journaliser  # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))
CONTENUS = os.path.expanduser("~/Bureau/{{ENTREPRISE}}/02_Marketing/Campagne_BG/Contenus")
FILE_TSV = os.path.join(CONTENUS, "_File_Instagram.tsv")
JETON = os.path.join(ICI, "instagram_jeton.json")
COLS = ["ID", "IMAGE", "LEGENDE", "STATUT", "PUBLIE_LE", "POST_ID"]
GRAPH = "https://graph.instagram.com/v23.0"
JOURS_ENTRE = 3
ESSAI = "--essai" in sys.argv

# Dossier des visuels prêts ({{ENTREPRISE}} Instagram design/export/jpg).
DOSSIER_IMAGES = os.path.expanduser(
    "~/Bureau/{{ENTREPRISE}}/02_Marketing/{{ENTREPRISE}} Instagram design/export/jpg")

# Racine publique où DOSSIER_IMAGES est reflété — Instagram doit pouvoir
# télécharger l'image depuis cette adresse. Projet Firebase Hosting dédié
# ({{PROJET_VISUELS_INSTAGRAM}}), rien d'autre n'y vit. Pour ajouter une image :
# la déposer dans Campagne_BG/Instagram-Hebergement/public/ puis
# `firebase deploy --only hosting` depuis ce dossier.
BASE_URL_IMAGES = "https://{{PROJET_VISUELS_INSTAGRAM}}.web.app"


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


def appel(url, donnees=None):
    if donnees is not None:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(donnees).encode())
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as rep:
        return json.loads(rep.read())


def publier(ig_user_id, jeton, image_url, legende):
    """Conteneur puis publication — la création peut prendre quelques
    secondes côté Meta (téléchargement de l'image), on l'attend."""
    conteneur = appel(f"{GRAPH}/{ig_user_id}/media", {
        "image_url": image_url, "caption": legende, "access_token": jeton,
    })
    creation_id = conteneur["id"]

    for _ in range(10):
        statut = appel(f"{GRAPH}/{creation_id}?fields=status_code&access_token={jeton}")
        if statut.get("status_code") == "FINISHED":
            break
        if statut.get("status_code") == "ERROR":
            raise RuntimeError(f"conteneur en erreur : {statut}")
        time.sleep(3)

    publie = appel(f"{GRAPH}/{ig_user_id}/media_publish", {
        "creation_id": creation_id, "access_token": jeton,
    })
    return publie.get("id", "")


def main():
    rangs = lire_file()
    if not rangs:
        journaliser("publicateur_instagram : _File_Instagram.tsv vide ou absent")
        return 1

    if not os.path.exists(JETON):
        if ESSAI:
            print("jeton absent (instagram_jeton.json) — le tuyau est prêt, "
                  "rien ne partira tant qu'il n'existe pas.")
        return 0
    cfg = json.load(open(JETON, encoding="utf-8"))
    ig_user_id, jeton = cfg.get("ig_user_id", ""), cfg.get("jeton", "")
    expire_le = cfg.get("expire_le", "")
    if not ig_user_id or not jeton:
        journaliser("publicateur_instagram : instagram_jeton.json incomplet (ig_user_id, jeton)")
        return 1
    if expire_le and date.today() > date.fromisoformat(expire_le):
        journaliser(f"publicateur_instagram : jeton expiré depuis le {expire_le} — "
                    "lancer renouveler_instagram.py")
        return 1

    if not BASE_URL_IMAGES:
        if ESSAI:
            print("BASE_URL_IMAGES n'est pas réglé — aucune image n'est publique, "
                  "rien ne peut partir tant que l'hébergement n'est pas choisi.")
        else:
            journaliser("publicateur_instagram : BASE_URL_IMAGES non réglé — bloqué")
        return 0

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
        journaliser("publicateur_instagram : aucune publication prête "
                    "(tout est a_ecrire, publie, ou pause) — écrire une légende "
                    "et passer son STATUT à a_publier dans _File_Instagram.tsv")
        return 0

    # La TSV ne peut pas porter de vraie fin de ligne dans une cellule — les
    # légendes à paragraphes stockent \n en littéral, décodé seulement ici.
    legende = suivant["LEGENDE"].replace("\\n", "\n")

    # Garde-fou de cloisonnement, comme pour Facebook.
    if "{{MANDAT_EXEMPLE}}" in legende:
        journaliser(f"publicateur_instagram : « {suivant['IMAGE']} » mentionne {{MANDAT_EXEMPLE}} — bloqué, à vérifier")
        return 1

    chemin_local = os.path.join(DOSSIER_IMAGES, suivant["IMAGE"])
    if not os.path.exists(chemin_local):
        journaliser(f"publicateur_instagram : image introuvable — {chemin_local}")
        return 1
    image_url = BASE_URL_IMAGES.rstrip("/") + "/" + suivant["IMAGE"]

    if ESSAI:
        print(f"partirait maintenant → {suivant['ID']} — {suivant['IMAGE']}\n"
              f"URL : {image_url}\n\n{legende}")
        return 0

    try:
        post_id = publier(ig_user_id, jeton, image_url, legende)
    except Exception as e:
        journaliser(f"publicateur_instagram : échec de publication « {suivant['IMAGE']} » : {e!r}")
        return 1
    suivant["STATUT"] = "publie"
    suivant["PUBLIE_LE"] = aujourd_hui.isoformat()
    suivant["POST_ID"] = post_id
    ecrire_file(rangs)
    journaliser(f"publicateur_instagram : publié — {suivant['ID']} « {suivant['IMAGE']} » ({post_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
