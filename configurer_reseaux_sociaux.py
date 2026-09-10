#!/usr/bin/env python3
"""Assistant interactif — connexion et configuration des réseaux sociaux.

Guide, dans l'ordre, la préparation de Facebook (Page, local ou cloud) et
d'Instagram sans avoir besoin d'ouvrir LISEZ-MOI_Publicateur.md ni
LISEZ-MOI_Publicateur_Instagram.md à côté — ce script réutilise
configurer_facebook.py et configurer_instagram.py pour l'échange de jeton
(rien n'est dupliqué, la logique d'appel à l'API reste dans ces deux
fichiers) et n'ajoute que l'orchestration : quoi faire dans quel ordre,
ouvrir les bonnes pages, copier les deux fichiers cloud dans le dépôt de
votre site si vous choisissez ce chemin, proposer le secret GitHub Actions.

Ne touche jamais au dépôt du SITE au-delà d'y COPIER des fichiers sur
disque : aucun `git add`/`commit`/`push` n'est fait pour vous là-bas, c'est
un dépôt de production qui ne vous appartient pas forcément si vous testez
ce modèle pour quelqu'un d'autre. Toute action système (`systemctl`) ou
secret GitHub (`gh secret set`) est proposée, jamais lancée sans confirmation
explicite.

Lancer avec `!` (session interactive), pas via un appel non interactif :
    python3 configurer_reseaux_sociaux.py
"""
import json
import os
import shutil
import subprocess
import sys
import webbrowser

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)

import configurer_facebook  # noqa: E402
import configurer_instagram  # noqa: E402

FACEBOOK_JETON = os.path.join(ICI, "facebook_jeton.json")
INSTAGRAM_JETON = os.path.join(ICI, "instagram_jeton.json")
CLOUD_DIR = os.path.join(ICI, "cloud-facebook")


def ouvrir(url):
    print(f"  → {url}")
    try:
        if webbrowser.open(url):
            return
    except Exception:
        pass


def confirmer(prompt):
    return input(f"{prompt} (o/N) : ").strip().lower() in ("o", "oui", "y", "yes")


def lire_json(chemin):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def etat_facebook():
    cfg = lire_json(FACEBOOK_JETON)
    if cfg is None:
        return "jeton absent" if not os.path.exists(FACEBOOK_JETON) else "jeton présent mais illisible"
    return f"jeton présent (Page id {cfg.get('page_id', '?')})"


def etat_instagram():
    cfg = lire_json(INSTAGRAM_JETON)
    if cfg is None:
        return "jeton absent" if not os.path.exists(INSTAGRAM_JETON) else "jeton présent mais illisible"
    return f"jeton présent (@{cfg.get('ig_user_id', '?')}, expire le {cfg.get('expire_le', '?')})"


def essai(script):
    if not confirmer(f"Lancer un essai à blanc ({script} --essai) ?"):
        return
    r = subprocess.run([sys.executable, os.path.join(ICI, script), "--essai"],
                        capture_output=True, text=True)
    sortie = (r.stdout + r.stderr).strip()
    print(sortie if sortie else "(aucune sortie)")


def activer_minuterie(unite):
    if not confirmer(f"Activer {unite} maintenant (systemctl --user enable --now {unite}) ?"):
        print(f"Pas activée — active-la plus tard : systemctl --user enable --now {unite}")
        return
    r = subprocess.run(["systemctl", "--user", "enable", "--now", unite],
                        capture_output=True, text=True)
    if r.returncode == 0:
        print("Activée.")
    else:
        print(f"Échec : {r.stderr.strip()} — vérifie que l'unité est installée "
              "(PARAMETRES-A-CONFIGURER.md § 12).")


# --- Facebook ---------------------------------------------------------

def config_local_facebook():
    print("\nChemin LOCAL : la minuterie de cette machine publie directement, mais "
          "seulement si l'ordinateur est allumé au bon moment.")
    activer_minuterie("bg-publicateur.timer")


def deployer_cloud(page_id, fuseau, chemin_site, forcer_ecrasement=False):
    """Copie les deux fichiers cloud dans le dépôt du site. Fonction pure
    (aucun input()/print()) réutilisée telle quelle par installer.py.

    Retourne {"ok": True, "dest_py", "dest_yml"} ou
    {"ok": False, "erreur", "existe_deja": [...]} (existe_deja rempli
    seulement si le blocage vient de fichiers déjà présents et
    forcer_ecrasement=False — laisse l'appelant redemander confirmation).
    """
    if not os.path.isdir(chemin_site):
        return {"ok": False, "erreur": f"« {chemin_site} » n'existe pas"}

    dest_py = os.path.join(chemin_site, "automatisation", "facebook", "publicateur_cloud.py")
    dest_yml = os.path.join(chemin_site, ".github", "workflows", "publicateur-facebook.yml")
    if not forcer_ecrasement:
        deja = [d for d in (dest_py, dest_yml) if os.path.exists(d)]
        if deja:
            return {"ok": False, "existe_deja": deja}

    os.makedirs(os.path.dirname(dest_py), exist_ok=True)
    os.makedirs(os.path.dirname(dest_yml), exist_ok=True)

    with open(os.path.join(CLOUD_DIR, "publicateur_cloud.py"), encoding="utf-8") as f:
        contenu = f.read()
    contenu = contenu.replace("{{PAGE_ID_FACEBOOK}}", page_id).replace("{{FUSEAU_HORAIRE}}", fuseau)
    with open(dest_py, "w", encoding="utf-8") as f:
        f.write(contenu)
    shutil.copy(os.path.join(CLOUD_DIR, "publicateur-facebook.yml"), dest_yml)

    return {"ok": True, "dest_py": dest_py, "dest_yml": dest_yml}


def creer_secret_github(chemin_site, jeton):
    """Tente `gh secret set FB_PAGE_TOKEN`. Fonction pure (aucun input()/
    print()), réutilisée telle quelle par installer.py.

    Retourne {"ok": bool, "gh_disponible": bool, "message": "..."}.
    """
    try:
        r = subprocess.run(["gh", "auth", "status"], cwd=chemin_site,
                            capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        r = None
    if r is None or r.returncode != 0:
        return {"ok": False, "gh_disponible": False, "message": (
            "`gh` (CLI GitHub) absent ou non connecté — crée le secret à la main : "
            "Settings → Secrets and variables → Actions → New repository secret → FB_PAGE_TOKEN."
        )}
    r2 = subprocess.run(["gh", "secret", "set", "FB_PAGE_TOKEN"], cwd=chemin_site,
                         input=jeton, capture_output=True, text=True, timeout=30)
    if r2.returncode == 0:
        return {"ok": True, "gh_disponible": True, "message": "Secret FB_PAGE_TOKEN créé."}
    return {"ok": False, "gh_disponible": True, "message": f"Échec : {r2.stderr.strip()} — crée-le à la main."}


def config_cloud_facebook():
    cfg = lire_json(FACEBOOK_JETON)
    if cfg is None:
        print("Pas de jeton local lisible — fais d'abord l'étape du jeton.")
        return
    page_id, jeton = cfg.get("page_id"), cfg.get("jeton")
    if not page_id or not jeton:
        print("facebook_jeton.json est incomplet — relance la configuration du jeton.")
        return

    fuseau = input("Ton fuseau horaire (format zoneinfo, ex. America/Toronto) : ").strip()
    if not fuseau:
        print("Fuseau requis pour le chemin cloud — annulé.")
        return

    chemin_site = os.path.expanduser(
        input("Chemin local du dépôt GIT de ton SITE (celui déjà publié sur le web) : ").strip())
    if not os.path.isdir(chemin_site):
        print(f"« {chemin_site} » n'existe pas — annulé.")
        return
    if not os.path.isdir(os.path.join(chemin_site, ".git")):
        if not confirmer(f"« {chemin_site} » ne ressemble pas à un dépôt git (pas de .git) — continuer quand même ?"):
            return

    resultat = deployer_cloud(page_id, fuseau, chemin_site)
    if not resultat["ok"] and resultat.get("existe_deja"):
        for dest in resultat["existe_deja"]:
            if not confirmer(f"« {dest} » existe déjà — écraser ?"):
                print("Annulé — copie le reste toi-même si besoin.")
                return
        resultat = deployer_cloud(page_id, fuseau, chemin_site, forcer_ecrasement=True)
    if not resultat["ok"]:
        print(f"Annulé : {resultat.get('erreur', '?')}")
        return

    print(f"\nCopiés dans {chemin_site} :")
    print(f"  {resultat['dest_py']}")
    print(f"  {resultat['dest_yml']}")
    print("Rien n'a été commité ni poussé là-bas — ajoute tes contenus "
          "(Facebook-Residentiel-Lot-1.md, _File_Facebook.tsv, visuels/) au "
          "même dossier automatisation/facebook/, puis commit/push toi-même.")

    offrir_secret_github(chemin_site, jeton)

    print("\nSi tu actives le cloud, désactive le local pour ne pas publier en double :")
    print("  systemctl --user disable --now bg-publicateur.timer")


def offrir_secret_github(chemin_site, jeton):
    if not shutil.which("gh"):
        print("\n`gh` (CLI GitHub) absent — crée le secret à la main : "
              "Settings → Secrets and variables → Actions → New repository "
              "secret → FB_PAGE_TOKEN.")
        return
    if not confirmer("\nCréer/mettre à jour le secret FB_PAGE_TOKEN dans ce dépôt avec gh secret set ?"):
        print("Pas créé — marche à suivre manuelle : Settings → Secrets and "
              "variables → Actions → New repository secret → FB_PAGE_TOKEN.")
        return
    resultat = creer_secret_github(chemin_site, jeton)
    print(resultat["message"])


def assistant_facebook():
    print("\n--- Facebook Page ---")
    if not confirmer("La Page Facebook « {{ENTREPRISE}} » existe déjà et est prête "
                      "(photo, bouton Appeler, coordonnées à jour) ?"):
        print("Reviens ici une fois la Page prête.")
        return

    if not os.path.exists(FACEBOOK_JETON):
        print("\nLe jeton de Page :")
        print("1. Graph API Explorer → ton app développeur → « Get User Access "
              "Token » → permissions pages_manage_posts + pages_read_engagement "
              "→ copie le jeton COURT.")
        ouvrir("https://developers.facebook.com/tools/explorer/")
        print("2. Note aussi l'App ID et l'App secret (Settings → Basic).")
        if not confirmer("Prêt à les coller maintenant ?"):
            print("Reviens plus tard, relance ce menu.")
            return
        if configurer_facebook.main() != 0:
            print("La configuration du jeton a échoué — relance quand tu es prêt.")
            return
    else:
        print("\nUn jeton de Page existe déjà — étape sautée.")

    print("\nOù publier ?")
    print("  LOCAL : simple, publie seulement si cet ordinateur est allumé au bon moment.")
    print("  CLOUD : GitHub Actions, publie même l'ordinateur éteint (recommandé).")
    choix = input("Choix (local/cloud, Entrée pour passer) : ").strip().lower()
    if choix.startswith("l"):
        config_local_facebook()
    elif choix.startswith("c"):
        config_cloud_facebook()
    else:
        print("Passé — configure-le plus tard (LISEZ-MOI_Publicateur.md § Cloud vs local).")

    essai("publicateur.py")


# --- Instagram ----------------------------------------------------------

def assistant_instagram():
    print("\n--- Instagram ---")
    print("Trois choses, dans l'ordre : relier le compte à la Page, obtenir le "
          "jeton, héberger les images. Détail complet si besoin : "
          "LISEZ-MOI_Publicateur_Instagram.md.")

    print("\nRelier le compte à la Page Facebook « {{ENTREPRISE}} » :")
    print("  1. Compte Instagram en mode professionnel (app Instagram → ☰ → "
          "Paramètres et confidentialité → Type de compte et outils).")
    print("  2. Meta Business Suite → ⚙️ Paramètres → Comptes → Comptes "
          "Instagram → + Connecter un compte.")
    ouvrir("https://business.facebook.com/")
    print("  3. Vérifier depuis la Page elle-même (Paramètres → Comptes liés).")
    if not confirmer("Compte relié ?"):
        print("Reviens ici une fois relié.")
        return

    if not os.path.exists(INSTAGRAM_JETON):
        print("\nLe jeton :")
        print("  App Meta → Cas d'utilisation → Ajouter → « Instagram API avec "
              "connexion Instagram ».")
        print("  Roles → Instagram Testers → ajouter ton compte, puis accepter "
              "l'invitation dans l'app Instagram.")
        print("  Section « Generate access tokens » → Add account → note le "
              "jeton COURT et l'App secret.")
        if not confirmer("Prêt à les coller maintenant ?"):
            print("Reviens plus tard, relance ce menu.")
            return
        if configurer_instagram.main() != 0:
            print("La configuration du jeton a échoué — relance quand tu es prêt.")
            return
    else:
        cfg = lire_json(INSTAGRAM_JETON) or {}
        print(f"\nUn jeton existe déjà (expire le {cfg.get('expire_le', '?')}) — étape sautée.")

    print("\nLe jeton expire après 60 jours — renouvelé automatiquement une fois "
          "la minuterie armée.")
    activer_minuterie("bg-renouveler-instagram.timer")

    print("\nHébergement public des images : Instagram exige une adresse "
          "publique pour chaque image. Pas automatisable ici (dépend de ton "
          "hébergement statique) — voir LISEZ-MOI_Publicateur_Instagram.md § 3, "
          "puis régler BASE_URL_IMAGES dans publicateur_instagram.py.")

    print("\nLégendes : écris-les dans _File_Instagram.tsv (STATUT a_ecrire → "
          "a_publier) quand tu es prêt à publier.")

    essai("publicateur_instagram.py")


# --- Menu -----------------------------------------------------------------

def menu():
    while True:
        print("\n=== Réseaux sociaux — état actuel ===")
        print(f"  Facebook Page : {etat_facebook()}")
        print(f"  Instagram     : {etat_instagram()}")
        print("\n1) Configurer Facebook (Page)")
        print("2) Configurer Instagram")
        print("3) Quitter")
        choix = input("\nChoix : ").strip().lower()
        if choix == "1":
            assistant_facebook()
        elif choix == "2":
            assistant_instagram()
        elif choix in ("3", "q", "quit", "quitter"):
            print("Terminé.")
            return
        else:
            print("Choix non reconnu.")


def main():
    print("Assistant réseaux sociaux — {{ENTREPRISE}}.")
    try:
        menu()
    except (KeyboardInterrupt, EOFError):
        print("\nInterrompu — rien n'est perdu, relance ce menu quand tu veux.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
