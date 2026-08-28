#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
installer_jeton.py — transforme un jeton d'UTILISATEUR Facebook en
facebook_jeton.json utilisable par publicateur.py.

Ce que tu fournis : le jeton d'utilisateur copié dans l'Explorateur de l'API
Graph (idéalement déjà prolongé au Débogueur de jeton — le script le dit s'il
ne l'est pas).

Ce que le script fait :
  1. interroge GET /me/accounts et liste les Pages que tu administres ;
  2. te laisse choisir la Page ;
  3. vérifie que le jeton de Page publie bien (permissions présentes) ;
  4. écrit facebook_jeton.json en 600, à côté de publicateur.py.

Il ne publie rien. Il ne touche à aucune Page.

    python3 installer_jeton.py

Le jeton peut aussi se passer en argument, mais la saisie interactive évite
qu'il reste dans l'historique du terminal.
"""

import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
JETON = os.path.join(ICI, "facebook_jeton.json")
GRAPH = "https://graph.facebook.com/v23.0"

# Ce dont publicateur.py a besoin pour faire son travail.
REQUISES = {"pages_manage_posts", "pages_read_engagement"}


def api(chemin, params):
    url = f"{GRAPH}/{chemin}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        corps = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(corps)["error"]["message"]
        except Exception:
            msg = corps[:400]
        raise SystemExit(f"\nFacebook refuse la requête ({e.code}) :\n  {msg}\n")
    except urllib.error.URLError as e:
        raise SystemExit(f"\nPas de réseau vers graph.facebook.com : {e.reason}\n")


def duree(jeton_utilisateur):
    moi = api("me", {"fields": "id,name", "access_token": jeton_utilisateur})
    return moi.get("name", "?"), moi.get("id", "?")


def echeance(jeton):
    """Quand ce jeton meurt-il, en secondes ? None si on ne peut pas savoir.

    debug_token accepte le jeton d'un développeur de l'app comme jeton
    d'appel : pas besoin du secret. `expires_at` à 0 = n'expire jamais.
    """
    try:
        d = api("debug_token", {"input_token": jeton, "access_token": jeton})
    except SystemExit:
        return None
    exp = d.get("data", {}).get("expires_at")
    if exp is None:
        return None
    if exp == 0:
        return 0  # jeton perpétuel
    return exp - int(time.time())


def main():
    # Deux modes : terminal vrai (on peut demander) ou appel non interactif
    # (Claude Code, cron, tuyau) où input() reçoit une fin de fichier.
    interactif = sys.stdin.isatty()

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    page_forcee = next((a.split("=", 1)[1] for a in sys.argv[1:]
                        if a.startswith("--page=")), None)

    jeton_u = args[0].strip() if args else os.environ.get("FB_JETON", "").strip()
    if not jeton_u and interactif:
        jeton_u = input("Jeton d'utilisateur (collé depuis l'Explorateur) : ").strip()
    if not jeton_u:
        print("Aucun jeton fourni, et pas de terminal pour le demander.\n")
        print("Passe-le en argument :")
        print("    python3 installer_jeton.py 'LE_JETON'\n")
        print("ou par une variable, pour qu'il ne reste pas dans l'historique :")
        print("    FB_JETON='LE_JETON' python3 installer_jeton.py")
        return 1

    if os.path.exists(JETON):
        print(f"⚠️  {JETON} existe déjà.")
        if interactif:
            if input("    L'écraser ? (o/N) ").strip().lower() not in ("o", "oui"):
                return 1
        else:
            print("    Il sera écrasé (une sauvegarde .precedent est gardée).")
            os.replace(JETON, JETON + ".precedent")

    nom, uid = duree(jeton_u)
    print(f"\nJeton valide — compte : {nom} ({uid})")

    # Le piège numéro un : un jeton court produit un jeton de Page court, et
    # la publication meurt en silence quelques heures plus tard.
    reste = echeance(jeton_u)
    if reste is None:
        print("Durée de vie : impossible à lire — à vérifier au Débogueur.")
    elif reste == 0:
        print("Durée de vie : n'expire pas. ✅")
    elif reste < 7 * 86400:
        h = reste // 3600
        print(f"\n❌ CE JETON EXPIRE DANS {h} HEURE(S) — il est de courte durée.")
        print("   Le jeton de Page qui en découlerait mourrait avec lui, et la")
        print("   publication échouerait sans prévenir.")
        print("\n   Va au Débogueur de jeton d'accès, colle-le, puis clique")
        print("   « Prolonger l'accès » (Extend Access Token) au bas de la page :")
        print("   https://developers.facebook.com/tools/debug/accesstoken/")
        print("   Reviens avec le jeton PROLONGÉ.")
        if not (interactif and input("\n   Installer quand même ? (o/N) ")
                .strip().lower() in ("o", "oui")):
            return 1
    else:
        print(f"Durée de vie : {reste // 86400} jours. ✅")

    perms = api("me/permissions", {"access_token": jeton_u}).get("data", [])
    accordees = {p["permission"] for p in perms if p.get("status") == "granted"}
    print("Permissions accordées : " + ", ".join(sorted(accordees)) or "(aucune)")

    manquantes = REQUISES - accordees
    if manquantes:
        # Avertissement, pas un arrêt : l'interface de Meta n'affiche pas
        # toujours ce qu'elle a réellement accordé. Le seul juge est l'API,
        # et elle tranchera à la première publication.
        print("\n⚠️  Manquent à l'appel : " + ", ".join(sorted(manquantes)))
        print("   Le jeton sera quand même installé, mais la publication")
        print("   échouera si l'API les exige vraiment. Le journal le dira.")

    pages = api("me/accounts",
                {"fields": "id,name,access_token,tasks",
                 "access_token": jeton_u}).get("data", [])
    if not pages:
        print("\n❌ Aucune Page administrée par ce compte.")
        print("   La Page {{ENTREPRISE}} doit exister et ce compte doit en")
        print("   être administrateur (étape 1 du LISEZ-MOI).")
        return 1

    print(f"\n{len(pages)} Page(s) administrée(s) :\n")
    for i, p in enumerate(pages, 1):
        peut = "CREATE_CONTENT" in (p.get("tasks") or [])
        print(f"  {i}. {p['name']}  (id {p['id']})"
              + ("" if peut else "   ⚠️ pas le droit de publier"))

    if page_forcee:
        page = next((p for p in pages if p["id"] == page_forcee), None)
        if page is None:
            print(f"\n❌ Aucune Page {page_forcee} dans cette liste.")
            return 1
    elif len(pages) == 1:
        page = pages[0]
        print("\nUne seule Page : c'est elle.")
    elif interactif:
        try:
            choix = int(input("\nLaquelle est la Page {{ENTREPRISE}} ? (numéro) "))
        except ValueError:
            choix = 0
        if not 1 <= choix <= len(pages):
            print("Numéro hors liste. Abandon.")
            return 1
        page = pages[choix - 1]
    else:
        print("\nPlusieurs Pages, et pas de terminal pour choisir.")
        print("Relance en nommant la bonne :")
        print(f"    python3 installer_jeton.py 'LE_JETON' --page={pages[0]['id']}")
        return 1

    if "CREATE_CONTENT" not in (page.get("tasks") or []):
        print("\n⚠️  Ce compte n'a pas la tâche CREATE_CONTENT sur cette Page.")
        print("   Rôle « Accès complet » requis dans les paramètres de la Page.")
        if interactif and input("    Écrire le jeton quand même ? (o/N) ") \
                .strip().lower() not in ("o", "oui"):
            return 1

    # Le jeton de Page se vérifie sur la Page elle-même, sans rien publier.
    api(page["id"], {"fields": "id,name", "access_token": page["access_token"]})

    with open(JETON, "w", encoding="utf-8") as f:
        json.dump({"page_id": page["id"], "jeton": page["access_token"]},
                  f, ensure_ascii=False)
    os.chmod(JETON, stat.S_IRUSR | stat.S_IWUSR)  # 600

    print(f"\n✅ Écrit : {JETON}  (600)")
    print(f"   Page : {page['name']} — {page['id']}")

    rp = echeance(page["access_token"])
    if rp == 0:
        print("   Jeton de Page : n'expire pas. ✅")
    elif rp is not None:
        print(f"   ⚠️  Jeton de Page : expire dans {rp // 3600} heure(s) "
              f"({rp // 86400} jour(s)).")
    print("\nEssai à blanc, ne publie rien :")
    print("    python3 publicateur.py --essai")
    return 0


if __name__ == "__main__":
    sys.exit(main())
