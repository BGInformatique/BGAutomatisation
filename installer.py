#!/usr/bin/env python3
"""Installateur web — orchestre toute la préparation de BGAutomatisation.

Démarre un petit serveur local (bibliothèque standard seulement, aucune
dépendance à installer) et ouvre une page dans le navigateur qui guide TOUT
le parcours sans jamais avoir besoin d'un terminal ensuite : checklist de
comptes, clé API OpenRouter et santé d'OpenClaw, remplacement des jetons
`{{...}}`, connexion Facebook et Instagram (jetons Graph API échangés
directement depuis cette page — la logique d'appel à l'API reste dans
configurer_facebook.py/configurer_instagram.py, importée ici, pas
dupliquée), et installation des services planifiés — systemd sous Linux,
launchd sous macOS, Tâches planifiées sous Windows (voir planificateur.py,
qui traduit les fichiers bg-*.service/.timer, source unique de vérité, vers
le bon mécanisme natif selon l'OS détecté).

Seul `python3 installer.py` lui-même se lance dans un terminal — tout ce qui
suit reste dans le navigateur. `configurer_reseaux_sociaux.py` reste dans ce
dépôt tel quel, pour qui préfère malgré tout le terminal pour Facebook/
Instagram ; ce script-ci ne s'appuie plus dessus comme chemin obligé.

Chemin recommandé en tête de LISEZ-MOI.md ; les fichiers LISEZ-MOI_*.md et
PARAMETRES-A-CONFIGURER.md restent la référence détaillée si vous préférez
une étape à la main, ou si cet outil échoue pour une raison quelconque sur
votre poste.

Lancer avec `!` (session interactive) :
    python3 installer.py [--port PORT]
"""
import argparse
import glob
import http.server
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.parse
import webbrowser

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)

import configurer_facebook  # noqa: E402
import configurer_instagram  # noqa: E402
import configurer_reseaux_sociaux as reseaux_sociaux  # noqa: E402
import planificateur  # noqa: E402

ETAT_PATH = os.path.join(ICI, ".installateur-etat.json")

# 8420 : ni un port privilégié (<1024), ni un des ports par défaut déjà pris
# par des outils de dev courants chez un acheteur (3000 React/Node, 5000
# Flask/macOS AirPlay, 8000 Django, 8080 proxies/Tomcat) — collision peu
# probable au premier lancement. Reste un choix arbitraire, documenté : si
# occupé, une page dans le navigateur (pas un prompt terminal) en redemande
# un autre — voir demarrer_serveur().
PORT_PAR_DEFAUT = 8420

SESSION_TOKEN = secrets.token_urlsafe(24)

# Pages Facebook en attente de choix (échange ambigu — plusieurs Pages
# reçues, aucune présélection) : choix_id -> liste de {id, name, jeton}.
# En mémoire seulement, process-local, jamais persisté ni renvoyé au
# navigateur avec les jetons — voir /api/facebook/echanger et
# /api/facebook/choisir_page.
_PAGES_EN_ATTENTE = {}

# Réplique le tableau § 1 de PARAMETRES-A-CONFIGURER.md — description
# copiée depuis ce fichier, pas réinventée. Le 3e élément marque les jetons
# liés au second mandat exemple : masqués du formulaire si « mandat
# unique » est coché, voir retirer_mandat_exemple().
TOKENS = [
    ("ENTREPRISE", "nom affiché de votre entreprise (celle qui possède BGAutomatisation)", False),
    ("MACHINE_LOCALE", "nom/description de la machine qui fait tourner cette suite", False),
    ("CHEMIN_INSTALLATION", "chemin absolu de CE dossier une fois installé (ex. /home/vous/Bureau/VotreEntreprise/BGAutomatisation)", False),
    ("DOMAINE", "domaine de votre site public", False),
    ("DEPOT_SITE", "nom du dépôt du site (cadre clientsweb et bibliothèque de guides)", False),
    ("PROJET_FIREBASE", "ID de votre projet Firebase (outils internes)", False),
    ("HANDLE", "identifiant GoatCounter ET nom d'utilisateur Instagram (dépliez en deux jetons si différents chez vous)", False),
    ("TELEPHONE", "votre téléphone publié", False),
    ("COURRIEL_PUBLIC", "votre courriel publié", False),
    ("PROPRIETAIRE", "votre nom, pour la signature des courriels de prospection", False),
    ("PROJET_VISUELS_INSTAGRAM", "projet d'hébergement public des images Instagram (§ 6)", False),
    ("AGENT_OPENCLAW", "ID de l'agent OpenClaw configuré à l'étape 2 de 00-Demarrage/", False),
    ("MANDAT_EXEMPLE", "nom du second mandat — laissez vide si mandat unique", True),
    ("COURRIEL_MANDAT_EXEMPLE", "courriel du second mandat", True),
    ("TELEPHONE_MANDAT_EXEMPLE", "téléphone du second mandat", True),
    ("DOSSIER_BATCHS_COURRIELS", "nom du dossier d'un batch de courriels de prospection (§ 7)", True),
    ("ORG_GITHUB", "votre nom d'organisation/utilisateur GitHub (celui qui possède le dépôt de votre site)", False),
    ("APP_FACEBOOK", "nom de votre app développeur Facebook (voir LISEZ-MOI_Publicateur.md étape 2)", False),
    ("PAGE_ID_FACEBOOK", "id de votre Page Facebook — présélection pratique, pas un secret", False),
    ("FUSEAU_HORAIRE", "votre fuseau au format zoneinfo (ex. America/Toronto, Europe/Paris) — seulement pour le chemin cloud", False),
]

# Fichiers texte où les jetons `{{...}}` peuvent apparaître — mêmes
# extensions que celles listées en tête de PARAMETRES-A-CONFIGURER.md § 1.
EXTENSIONS_JETONS = (".py", ".md", ".service", ".timer", ".sh")
DOSSIERS_EXCLUS = {".git", "__pycache__"}


# --- Jetons {{...}} --------------------------------------------------------

def fichiers_a_jetons():
    resultat = []
    for racine, dossiers, fichiers in os.walk(ICI):
        dossiers[:] = [d for d in dossiers if d not in DOSSIERS_EXCLUS]
        for nom in fichiers:
            if nom.endswith(EXTENSIONS_JETONS):
                resultat.append(os.path.join(racine, nom))
    return resultat


def jetons_restants():
    """Jetons `{{...}}` encore présents quelque part — pour l'affichage d'état."""
    trouve = set()
    motif = re.compile(r"\{\{([A-Z_]+)\}\}")
    for chemin in fichiers_a_jetons():
        try:
            with open(chemin, encoding="utf-8") as f:
                contenu = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        trouve.update(motif.findall(contenu))
    return sorted(trouve)


def charger_etat():
    if os.path.exists(ETAT_PATH):
        try:
            with open(ETAT_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"checklist": {}, "single_mandat": False, "valeurs_jetons": {}}


def sauvegarder_etat(etat):
    with open(ETAT_PATH, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=2)


def retirer_mandat_exemple():
    """Patch ciblé § 2 : retire le filtrage du second mandat exemple.

    Ne touche QUE les lignes qui correspondent exactement au patron connu —
    si pilote.py/vigie.py ont changé de forme, ne fait rien et le signale
    plutôt que de deviner une modification risquée sur du code vivant.
    """
    rapport = []

    chemin_pilote = os.path.join(ICI, "pilote.py")
    motif_pilote = re.compile(r'CLIENTS_EXCLUS\s*=\s*\{"\{\{MANDAT_EXEMPLE\}\}"\}')
    if os.path.exists(chemin_pilote):
        contenu = open(chemin_pilote, encoding="utf-8").read()
        if motif_pilote.search(contenu):
            contenu = motif_pilote.sub("CLIENTS_EXCLUS = set()", contenu)
            open(chemin_pilote, "w", encoding="utf-8").write(contenu)
            rapport.append("pilote.py : CLIENTS_EXCLUS vidé.")
        elif "CLIENTS_EXCLUS = set()" in contenu:
            rapport.append("pilote.py : déjà vide, rien à faire.")
        else:
            rapport.append(
                "pilote.py : ligne CLIENTS_EXCLUS pas dans la forme attendue, "
                "à vérifier à la main (§ 2 de PARAMETRES-A-CONFIGURER.md)."
            )

    chemin_vigie = os.path.join(ICI, "vigie.py")
    motif_vigie = re.compile(
        r'^\s*"(bg-prospecteur\.service|bg-recherchiste\.service)"\s*:\s*'
        r'"\{\{MANDAT_EXEMPLE\}\}"\s*,?\s*$'
    )
    if os.path.exists(chemin_vigie):
        lignes = open(chemin_vigie, encoding="utf-8").read().splitlines(keepends=True)
        gardees = []
        retirees = 0
        for ligne in lignes:
            if motif_vigie.match(ligne):
                retirees += 1
                continue
            gardees.append(ligne)
        if retirees:
            open(chemin_vigie, "w", encoding="utf-8").write("".join(gardees))
            rapport.append(f"vigie.py : {retirees} entrée(s) UNITES retirée(s).")
        else:
            rapport.append(
                "vigie.py : aucune entrée UNITES bg-prospecteur.service/"
                "bg-recherchiste.service trouvée dans la forme attendue — "
                "déjà fait, ou à vérifier à la main."
            )

    rapport.append(
        "Ne pas déployer : courriels_mandat_exemple.py, "
        "bg-courriels-mandat-exemple.service, prospecteur.py, recherchiste.py "
        "(restent inertes si vous ne les activez pas, aucune suppression "
        "faite automatiquement)."
    )
    return rapport


def appliquer_jetons(valeurs, single_mandat):
    rapport = {"patrons": [], "fichiers": {}, "non_fournis": []}

    if single_mandat:
        rapport["patrons"] = retirer_mandat_exemple()
        valeurs = {k: v for k, v in valeurs.items()
                   if not any(t[0] == k and t[2] for t in TOKENS)}

    a_remplacer = {k: v for k, v in valeurs.items() if v}
    for nom, _, mandat in TOKENS:
        if nom not in a_remplacer and not (single_mandat and mandat):
            rapport["non_fournis"].append(nom)

    if not a_remplacer:
        return rapport

    for chemin in fichiers_a_jetons():
        try:
            with open(chemin, encoding="utf-8") as f:
                contenu = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        original = contenu
        touche = 0
        for nom, valeur in a_remplacer.items():
            motif = "{{%s}}" % nom
            if motif in contenu:
                touche += contenu.count(motif)
                contenu = contenu.replace(motif, valeur)
        if contenu != original:
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(contenu)
            rapport["fichiers"][os.path.relpath(chemin, ICI)] = touche

    return rapport


# --- systemd -----------------------------------------------------------

def unites_systemd():
    unites = []
    for chemin in sorted(glob.glob(os.path.join(ICI, "bg-*.service")) +
                          glob.glob(os.path.join(ICI, "bg-*.timer"))):
        nom = os.path.basename(chemin)
        statut = "inconnu"
        try:
            r = subprocess.run(["systemctl", "--user", "is-enabled", nom],
                                capture_output=True, text=True, timeout=5)
            statut = (r.stdout or r.stderr or "").strip() or "non-installé"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            statut = "systemctl indisponible"
        unites.append({"nom": nom, "statut": statut})
    return unites


def installer_systemd(selection):
    cible = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(cible, exist_ok=True)
    rapport = []
    connus = {os.path.basename(c) for c in
              glob.glob(os.path.join(ICI, "bg-*.service")) +
              glob.glob(os.path.join(ICI, "bg-*.timer"))}
    a_faire = [n for n in selection if n in connus]
    for nom in a_faire:
        source = os.path.join(ICI, nom)
        lien = os.path.join(cible, nom)
        try:
            if os.path.islink(lien) or os.path.exists(lien):
                os.remove(lien)
            os.symlink(source, lien)
            rapport.append(f"{nom} : lien créé.")
        except OSError as e:
            rapport.append(f"{nom} : échec du lien ({e}).")

    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"],
                        capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        rapport.append("systemctl introuvable — impossible d'activer quoi que ce soit ici.")
        return rapport

    for nom in a_faire:
        try:
            r = subprocess.run(["systemctl", "--user", "enable", "--now", nom],
                                capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                rapport.append(f"{nom} : activé.")
            else:
                rapport.append(f"{nom} : erreur — {(r.stderr or r.stdout).strip()}")
        except subprocess.TimeoutExpired:
            rapport.append(f"{nom} : délai dépassé.")

    return rapport


# --- Dispatch multi-OS (voir planificateur.py) ---------------------------
# Linux : comportement ci-dessus, INCHANGÉ, granularité par fichier
# (bg-x.service ET bg-x.timer listés/cochés séparément, comme avant).
# macOS/Windows : granularité par UNITÉ LOGIQUE (planificateur.py regroupe
# .service+.timer sous un seul nom, ex. "bg-pilote") puisqu'il n'y a qu'un
# seul objet natif (agent launchd, tâche planifiée) par unité sur ces OS.

def unites_planifiees():
    if platform.system() == "Linux":
        return unites_systemd()
    minutees, continues = planificateur.analyser_toutes_unites(ICI)
    return [{"nom": u.nom, "statut": planificateur.statut_natif(u.nom)} for u in minutees + continues]


def installer_unites(selection):
    if platform.system() == "Linux":
        return installer_systemd(selection)
    minutees, continues = planificateur.analyser_toutes_unites(ICI)
    par_nom = {u.nom: u for u in minutees + continues}
    unites_minutees = {u.nom for u in minutees}
    rapport = []
    for nom in selection:
        u = par_nom.get(nom)
        if u is None:
            rapport.append(f"{nom} : introuvable.")
            continue
        fn = planificateur.installer_unite_minutee if nom in unites_minutees else planificateur.installer_unite_continue
        r = fn(u, repertoire=ICI)
        if r.get("ok"):
            rapport.append(f"{nom} : installé(e) ({', '.join(r.get('taches') or [r.get('plist', '')])}).")
            for lim in r.get("limites", []):
                rapport.append(f"{nom} : ATTENTION — {lim}")
        else:
            rapport.append(f"{nom} : erreur — {r.get('erreur', 'échec inconnu')}")
    return rapport


# --- OpenClaw, non interactif --------------------------------------------
# `openclaw configure` (le flux interactif classique) n'a pas d'équivalent
# non interactif complet. Mais `openclaw config patch --stdin` accepte un
# patch JSON validé sans prompt (vérifié sur cette machine avec --dry-run :
# le chemin models.providers.openrouter.apiKey est accepté par le schéma),
# et `openclaw doctor --lint --non-interactive --json` existe pour les
# vérifications en lecture seule (sans --lint, --json est refusé).
# `openclaw daemon install`/`start` n'ont pas été testés pour de vrai ici
# (poste réel avec un gateway OpenClaw déjà en service) — voir le bouton
# dédié plus bas, avec repli clair si ça échoue ou traîne.

def openclaw_disponible():
    return shutil.which("openclaw") is not None


def openclaw_patch_cle_openrouter(cle):
    """Écrit la clé API OpenRouter sans prompt. Ne retourne ni ne journalise
    jamais la clé elle-même — seulement un état ok/erreur générique."""
    patch = json.dumps({"models": {"providers": {"openrouter": {"apiKey": cle}}}})
    try:
        r = subprocess.run(["openclaw", "config", "patch", "--stdin"],
                            input=patch, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return {"ok": False, "message": "openclaw introuvable."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "délai dépassé."}
    if r.returncode == 0:
        return {"ok": True, "message": "Clé enregistrée."}
    return {"ok": False, "message": "Échec — vérifiez la clé, ou utilisez `openclaw configure` dans un terminal."}


def openclaw_doctor():
    try:
        r = subprocess.run(["openclaw", "doctor", "--lint", "--non-interactive", "--json"],
                            capture_output=True, text=True, timeout=60)
        return {"ok": r.returncode == 0, "sortie": (r.stdout or r.stderr).strip()[:4000]}
    except FileNotFoundError:
        return {"ok": False, "sortie": "openclaw introuvable."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "sortie": "Délai dépassé — relancez, ou `openclaw doctor` dans un terminal."}


def openclaw_installer_demarrer_service():
    rapport = []
    for commande in (["openclaw", "daemon", "install"], ["openclaw", "daemon", "start"]):
        try:
            r = subprocess.run(commande, capture_output=True, text=True, timeout=60)
            sortie = (r.stdout or r.stderr).strip()
            rapport.append(f"{' '.join(commande)} : " + (sortie[:800] if sortie else ("ok" if r.returncode == 0 else "échec")))
            if r.returncode != 0:
                rapport.append(
                    "Étape arrêtée — si ça persiste, lancez ces commandes vous-même "
                    "dans un terminal : elles peuvent, dans de rares cas, demander "
                    "un choix (ex. port déjà pris par un autre service)."
                )
                break
        except FileNotFoundError:
            rapport.append("openclaw introuvable.")
            break
        except subprocess.TimeoutExpired:
            rapport.append(
                f"{' '.join(commande)} : délai dépassé — probablement bloqué sur une "
                "question. Terminez dans un terminal : " + " ".join(commande)
            )
            break
    return rapport


def tenter_ouvrir_terminal(commande):
    for emulateur in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
        chemin = shutil.which(emulateur)
        if not chemin:
            continue
        try:
            if emulateur == "gnome-terminal":
                subprocess.Popen([chemin, "--", "bash", "-lc", commande + "; exec bash"])
            else:
                subprocess.Popen([chemin, "-e", "bash", "-lc", commande + "; exec bash"])
            return True
        except OSError:
            continue
    return False


PAGE_HTML = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Installateur — BGAutomatisation</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; max-width: 50rem; margin: 2rem auto; padding: 0 1rem 4rem; line-height: 1.5; }
  h1 { font-size: 1.5rem; }
  h2 { font-size: 1.15rem; margin-top: 2.4rem; border-bottom: 1px solid #8884; padding-bottom: .3rem; }
  h3 { font-size: 1rem; margin-top: 1.4rem; }
  .note { font-size: .9rem; opacity: .75; }
  .champ { margin: .6rem 0; }
  .champ label { display: block; font-size: .9rem; margin-bottom: .2rem; }
  .champ input[type=text], .champ input[type=password] { width: 100%; box-sizing: border-box; padding: .4rem; }
  .desc { font-size: .8rem; opacity: .7; }
  button { padding: .5rem .9rem; margin: .3rem .4rem .3rem 0; cursor: pointer; }
  button.danger { background: #a33; color: #fff; border: none; border-radius: .3rem; }
  button:disabled { opacity: .5; cursor: not-allowed; }
  pre { background: #8882; padding: .6rem; border-radius: .4rem; overflow-x: auto; white-space: pre-wrap; }
  ul.check { list-style: none; padding: 0; }
  ul.check li { margin: .4rem 0; }
  label.case { display: flex; gap: .5rem; align-items: flex-start; cursor: pointer; }
  .statut { font-size: .85rem; opacity: .8; }
  code { background: #8882; padding: .1rem .3rem; border-radius: .2rem; }
  .avert { border-left: 3px solid #c93; padding-left: .8rem; margin: .6rem 0; font-size: .9rem; }
  fieldset { border: 1px solid #8884; border-radius: .4rem; margin: .8rem 0; }
  .radio-page { display: block; margin: .3rem 0; }
</style>
</head>
<body>

<h1>Installateur — BGAutomatisation</h1>
<p class="note">Tout le parcours reste dans cette page, aucun terminal requis
après le lancement de <code>installer.py</code>. Les fichiers
<code>LISEZ-MOI_*.md</code> et <code>PARAMETRES-A-CONFIGURER.md</code> restent la
référence détaillée si une étape échoue ici.</p>

<h2>1. Comptes à créer</h2>
<ul class="check" id="liste-checklist"></ul>

<h2>2. OpenClaw</h2>
<button id="btn-openclaw-installer">Installer OpenClaw</button>
<pre id="sortie-openclaw" hidden></pre>

<div class="champ">
  <label>Clé API OpenRouter (openrouter.ai/keys)</label>
  <input type="password" id="openclaw-cle" autocomplete="off">
  <div class="desc">Enregistrée sans prompt via <code>openclaw config patch</code> — jamais affichée ni renvoyée par le serveur.</div>
</div>
<button id="btn-openclaw-cle">Enregistrer la clé</button>
<button id="btn-openclaw-doctor">Vérifier (openclaw doctor)</button>
<pre id="sortie-openclaw-doctor" hidden></pre>
<button id="btn-openclaw-service">Installer + démarrer le service OpenClaw</button>
<pre id="sortie-openclaw-service" hidden></pre>
<p class="avert">Si un des trois derniers boutons reste bloqué : <code>openclaw configure</code>
dans un terminal reste le seul repli — ça n'arrive que si OpenClaw pose une
question imprévue (rare, aucun cas connu sur une machine neuve).</p>

<h2>3. Jetons à remplacer</h2>
<label class="case"><input type="checkbox" id="single-mandat"> Mandat unique (pas de second client — masque les jetons liés)</label>
<div id="liste-jetons"></div>
<button id="btn-jetons">Appliquer les jetons</button>
<pre id="rapport-jetons" hidden></pre>

<h2>4. Facebook (Page)</h2>
<p class="statut" id="statut-facebook"></p>
<div class="champ">
  <label>App ID</label>
  <input type="text" id="fb-app-id" autocomplete="off">
</div>
<div class="champ">
  <label>App secret</label>
  <input type="password" id="fb-app-secret" autocomplete="off">
</div>
<div class="champ">
  <label>Jeton court (Graph API Explorer → Get User Access Token)</label>
  <input type="password" id="fb-jeton-court" autocomplete="off">
</div>
<button id="btn-fb-ouvrir-explorer">Ouvrir le Graph API Explorer</button>
<button id="btn-fb-echanger">Échanger le jeton</button>
<div id="fb-choix-page" hidden>
  <p>Plusieurs Pages reçues — laquelle ?</p>
  <div id="fb-liste-pages"></div>
  <button id="btn-fb-choisir-page">Confirmer cette Page</button>
</div>
<pre id="rapport-facebook" hidden></pre>

<h3>Local ou cloud ?</h3>
<p class="note">Local : utilisez la case <code>bg-publicateur.timer</code> à la
section 6 ci-dessous. Cloud (recommandé, marche même l'ordinateur éteint) :</p>
<div class="champ">
  <label>Fuseau horaire (format zoneinfo, ex. America/Toronto)</label>
  <input type="text" id="fb-fuseau" autocomplete="off">
</div>
<div class="champ">
  <label>Chemin local du dépôt git de votre SITE (déjà publié sur le web)</label>
  <input type="text" id="fb-chemin-site" autocomplete="off">
</div>
<label class="case"><input type="checkbox" id="fb-creer-secret" checked> Créer aussi le secret GitHub FB_PAGE_TOKEN (si `gh` est disponible et connecté)</label>
<button id="btn-fb-cloud">Déployer le chemin cloud</button>
<pre id="rapport-facebook-cloud" hidden></pre>

<h2>5. Instagram</h2>
<p class="statut" id="statut-instagram"></p>
<p class="note">Compte pro relié à la Page (Meta Business Suite), jeton généré
à l'écran « Generate access tokens » d'une app avec le cas d'utilisation
« Instagram API avec connexion Instagram ».</p>
<div class="champ">
  <label>Jeton (court, ou déjà longue durée — voir case ci-dessous)</label>
  <input type="password" id="ig-jeton" autocomplete="off">
</div>
<label class="case"><input type="checkbox" id="ig-deja-long"> Ce jeton est déjà longue durée (saute l'échange)</label>
<div class="champ" id="ig-secret-wrap">
  <label>App secret</label>
  <input type="password" id="ig-app-secret" autocomplete="off">
</div>
<button id="btn-ig-echanger">Échanger le jeton</button>
<pre id="rapport-instagram" hidden></pre>
<p class="note">Hébergement public des images : pas automatisable ici (dépend
de votre hébergement statique) — voir LISEZ-MOI_Publicateur_Instagram.md § 3.</p>

<h2 id="titre-unites">6. Services planifiés</h2>
<ul class="check" id="liste-systemd"></ul>
<button id="btn-rafraichir-systemd">Rafraîchir l'état</button>
<button id="btn-installer-systemd">Installer et activer la sélection</button>
<pre id="rapport-systemd" hidden></pre>
<p class="avert" id="avert-lanceur"></p>
<p class="avert" id="avert-limites-os" hidden>Sur cet OS, certains réglages
systemd n'ont pas d'équivalent simple et ne sont pas reproduits (rattrapage
d'un passage manqué, délai aléatoire) — le rapport ci-dessus précise, unité
par unité, ce qui s'applique. Sous Windows, un service continu devient une
tâche « au démarrage de session », pas un vrai service supervisé (pas de
relance automatique s'il plante).</p>

<h2>Terminer</h2>
<button class="danger" id="btn-arreter">Arrêter l'installateur</button>
<p class="note">Le serveur ne tourne que sur 127.0.0.1, pour cette session
d'installation — l'arrêter ici ferme aussi cette page.</p>

<script>
const JETON = "__SESSION_TOKEN__";
const ID_CHECKLIST = [
  ["claude", "Compte Claude (ou aucun, si l'agent OpenClaw gratuit suffit)"],
  ["openrouter", "Clé API OpenRouter (openrouter.ai/keys)"],
  ["autres-ia", "Autres IA voulues, s'il y en a"],
  ["business-suite", "Page Facebook + compte Instagram pro liés (business.facebook.com)"],
  ["meta-dev", "Appli créée sur developers.facebook.com, jetons Graph notés"],
  ["firebase", "Projet Firebase créé (Firestore activé)"],
  ["sa", "Compte de service Firebase créé, clé JSON rangée hors du dépôt"],
  ["claude-chrome", "Extension « Claude for Chrome » installée si besoin"],
];

async function appelApi(chemin, corps) {
  const rep = await fetch(chemin, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Jeton-Session": JETON },
    body: JSON.stringify(corps || {}),
  });
  if (!rep.ok) throw new Error(await rep.text());
  return rep.json();
}

let ETAT = null;

async function rafraichirEtat() {
  const rep = await fetch("/api/etat");
  ETAT = await rep.json();
  dessinerChecklist();
  dessinerJetons();
  dessinerSystemd();
  document.getElementById("statut-facebook").textContent = "Facebook : " + ETAT.etat_facebook;
  document.getElementById("statut-instagram").textContent = "Instagram : " + ETAT.etat_instagram;
  document.getElementById("btn-openclaw-cle").disabled = !ETAT.openclaw_disponible;
  document.getElementById("btn-openclaw-doctor").disabled = !ETAT.openclaw_disponible;
  document.getElementById("btn-openclaw-service").disabled = !ETAT.openclaw_disponible;
}

function dessinerChecklist() {
  const ul = document.getElementById("liste-checklist");
  ul.innerHTML = "";
  for (const [id, texte] of ID_CHECKLIST) {
    const li = document.createElement("li");
    const label = document.createElement("label");
    label.className = "case";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!(ETAT.checklist || {})[id];
    cb.addEventListener("change", () => appelApi("/api/checklist", { id, valeur: cb.checked }));
    label.appendChild(cb);
    label.appendChild(document.createTextNode(texte));
    li.appendChild(label);
    ul.appendChild(li);
  }
}

function dessinerJetons() {
  document.getElementById("single-mandat").checked = !!ETAT.single_mandat;
  const div = document.getElementById("liste-jetons");
  div.innerHTML = "";
  const restants = new Set(ETAT.jetons_restants || []);
  for (const [nom, desc, mandat] of ETAT.tokens) {
    if (mandat && ETAT.single_mandat) continue;
    const wrap = document.createElement("div");
    wrap.className = "champ";
    const label = document.createElement("label");
    label.textContent = nom + (restants.has(nom) ? "  (encore présent dans le dépôt)" : "  (déjà réglé)");
    const input = document.createElement("input");
    input.type = "text";
    input.id = "jeton-" + nom;
    input.value = (ETAT.valeurs_jetons || {})[nom] || "";
    const d = document.createElement("div");
    d.className = "desc";
    d.textContent = desc;
    wrap.appendChild(label);
    wrap.appendChild(input);
    wrap.appendChild(d);
    div.appendChild(wrap);
  }
}

function dessinerSystemd() {
  const ul = document.getElementById("liste-systemd");
  ul.innerHTML = "";
  for (const u of ETAT.unites || []) {
    const li = document.createElement("li");
    const label = document.createElement("label");
    label.className = "case";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.nom = u.nom;
    label.appendChild(cb);
    label.appendChild(document.createTextNode(u.nom + " "));
    const s = document.createElement("span");
    s.className = "statut";
    s.textContent = "(" + u.statut + ")";
    label.appendChild(s);
    li.appendChild(label);
    ul.appendChild(li);
  }

  const os = ETAT.os_cible;
  document.getElementById("titre-unites").textContent =
    "6. Services " + (os === "Linux" ? "systemd" : os === "Darwin" ? "(launchd)" : os === "Windows" ? "(Tâches planifiées)" : "planifiés");
  document.getElementById("avert-lanceur").textContent =
    os === "Linux"
      ? "bg-lanceur.service n'a pas de fichier fourni — à créer sur le patron de bg-pont-clients.service (voir § 12 de PARAMETRES-A-CONFIGURER.md), puis systemctl --user enable --now bg-lanceur.service à la main."
      : "Le daemon lanceur.py n'a pas de fichier fourni pour cet OS — à installer à la main sur le patron des autres services continus (voir § 12 de PARAMETRES-A-CONFIGURER.md et planificateur.py).";
  document.getElementById("avert-limites-os").hidden = (os === "Linux");
}

document.getElementById("btn-openclaw-installer").addEventListener("click", async () => {
  if (!confirm("Lancer 00-Demarrage/installer-openclaw.sh maintenant ?")) return;
  const pre = document.getElementById("sortie-openclaw");
  pre.hidden = false;
  pre.textContent = "Installation en cours (peut prendre un moment selon le réseau)…";
  try {
    const rep = await appelApi("/api/openclaw/installer");
    pre.textContent = rep.sortie;
    await rafraichirEtat();
  } catch (e) {
    pre.textContent = "Erreur : " + e.message;
  }
});

document.getElementById("btn-openclaw-cle").addEventListener("click", async () => {
  const cle = document.getElementById("openclaw-cle").value.trim();
  if (!cle) { alert("Collez d'abord la clé."); return; }
  if (!confirm("Enregistrer cette clé OpenRouter dans la config OpenClaw ?")) return;
  try {
    const rep = await appelApi("/api/openclaw/cle", { cle });
    alert(rep.message);
    if (rep.ok) document.getElementById("openclaw-cle").value = "";
  } catch (e) {
    alert("Erreur : " + e.message);
  }
});

document.getElementById("btn-openclaw-doctor").addEventListener("click", async () => {
  const pre = document.getElementById("sortie-openclaw-doctor");
  pre.hidden = false;
  pre.textContent = "Vérification…";
  const rep = await appelApi("/api/openclaw/doctor");
  pre.textContent = rep.sortie;
});

document.getElementById("btn-openclaw-service").addEventListener("click", async () => {
  if (!confirm("Installer et démarrer le service OpenClaw (openclaw daemon install && start) ?")) return;
  const pre = document.getElementById("sortie-openclaw-service");
  pre.hidden = false;
  pre.textContent = "En cours…";
  const rep = await appelApi("/api/openclaw/service");
  pre.textContent = rep.rapport.join("\\n");
});

document.getElementById("btn-jetons").addEventListener("click", async () => {
  const single = document.getElementById("single-mandat").checked;
  const valeurs = {};
  for (const [nom] of ETAT.tokens) {
    const champ = document.getElementById("jeton-" + nom);
    if (champ) valeurs[nom] = champ.value.trim();
  }
  if (!confirm("Remplacer ces jetons dans tous les fichiers du dépôt ?")) return;
  try {
    const rep = await appelApi("/api/tokens/appliquer", { valeurs, single_mandat: single });
    const pre = document.getElementById("rapport-jetons");
    pre.hidden = false;
    pre.textContent = JSON.stringify(rep, null, 2);
    await rafraichirEtat();
  } catch (e) {
    alert("Erreur : " + e.message);
  }
});

document.getElementById("btn-fb-ouvrir-explorer").addEventListener("click", () => {
  window.open("https://developers.facebook.com/tools/explorer/", "_blank");
});

document.getElementById("btn-fb-echanger").addEventListener("click", async () => {
  const app_id = document.getElementById("fb-app-id").value.trim();
  const app_secret = document.getElementById("fb-app-secret").value.trim();
  const jeton_court = document.getElementById("fb-jeton-court").value.trim();
  if (!app_id || !app_secret || !jeton_court) { alert("Les trois champs sont requis."); return; }
  const pre = document.getElementById("rapport-facebook");
  pre.hidden = false;
  pre.textContent = "Échange en cours…";
  try {
    const rep = await appelApi("/api/facebook/echanger", { app_id, app_secret, jeton_court });
    if (rep.ambigu) {
      pre.textContent = "Plusieurs Pages reçues — choisissez ci-dessous.";
      const div = document.getElementById("fb-liste-pages");
      div.innerHTML = "";
      for (const p of rep.pages) {
        const label = document.createElement("label");
        label.className = "radio-page";
        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "fb-page";
        radio.value = p.id;
        label.appendChild(radio);
        label.appendChild(document.createTextNode(" " + p.name + " (id " + p.id + ")"));
        div.appendChild(label);
      }
      document.getElementById("fb-choix-page").hidden = false;
      document.getElementById("fb-choix-page").dataset.choixId = rep.choix_id;
    } else if (rep.ok) {
      pre.textContent = "Page : " + rep.page_name + " (id " + rep.page_id + "). Jeton écrit.";
      document.getElementById("fb-app-secret").value = "";
      document.getElementById("fb-jeton-court").value = "";
      await rafraichirEtat();
    } else {
      pre.textContent = "Erreur : " + rep.erreur;
    }
  } catch (e) {
    pre.textContent = "Erreur : " + e.message;
  }
});

document.getElementById("btn-fb-choisir-page").addEventListener("click", async () => {
  const choisi = document.querySelector('input[name="fb-page"]:checked');
  if (!choisi) { alert("Choisissez une Page."); return; }
  const choix_id = document.getElementById("fb-choix-page").dataset.choixId;
  try {
    const rep = await appelApi("/api/facebook/choisir_page", { choix_id, page_id: choisi.value });
    document.getElementById("rapport-facebook").textContent = rep.ok
      ? "Page : " + rep.page_name + " (id " + rep.page_id + "). Jeton écrit."
      : "Erreur : " + rep.erreur;
    document.getElementById("fb-choix-page").hidden = true;
    await rafraichirEtat();
  } catch (e) {
    alert("Erreur : " + e.message);
  }
});

document.getElementById("btn-fb-cloud").addEventListener("click", async () => {
  const fuseau = document.getElementById("fb-fuseau").value.trim();
  const chemin_site = document.getElementById("fb-chemin-site").value.trim();
  const creer_secret = document.getElementById("fb-creer-secret").checked;
  if (!fuseau || !chemin_site) { alert("Fuseau et chemin du dépôt requis."); return; }
  if (!confirm("Copier les fichiers cloud dans " + chemin_site + " (et créer le secret GitHub si coché) ?")) return;
  const pre = document.getElementById("rapport-facebook-cloud");
  pre.hidden = false;
  pre.textContent = "En cours…";
  try {
    let rep = await appelApi("/api/facebook/cloud", { fuseau, chemin_site, creer_secret, forcer: false });
    if (!rep.ok && rep.existe_deja) {
      if (!confirm("Ces fichiers existent déjà :\\n" + rep.existe_deja.join("\\n") + "\\nÉcraser ?")) {
        pre.textContent = "Annulé.";
        return;
      }
      rep = await appelApi("/api/facebook/cloud", { fuseau, chemin_site, creer_secret, forcer: true });
    }
    pre.textContent = JSON.stringify(rep, null, 2);
  } catch (e) {
    pre.textContent = "Erreur : " + e.message;
  }
});

document.getElementById("ig-deja-long").addEventListener("change", (e) => {
  document.getElementById("ig-secret-wrap").hidden = e.target.checked;
});

document.getElementById("btn-ig-echanger").addEventListener("click", async () => {
  const jeton_court = document.getElementById("ig-jeton").value.trim();
  const deja_long = document.getElementById("ig-deja-long").checked;
  const app_secret = document.getElementById("ig-app-secret").value.trim();
  if (!jeton_court) { alert("Collez d'abord le jeton."); return; }
  const pre = document.getElementById("rapport-instagram");
  pre.hidden = false;
  pre.textContent = "Échange en cours…";
  try {
    const rep = await appelApi("/api/instagram/echanger", { jeton_court, app_secret, deja_long });
    if (rep.ok) {
      pre.textContent = "Compte @" + rep.username + " — jeton valide jusqu'au " + rep.expire_le +
        (rep.avertissement ? "\\nATTENTION : " + rep.avertissement : "");
      document.getElementById("ig-jeton").value = "";
      document.getElementById("ig-app-secret").value = "";
      await rafraichirEtat();
    } else {
      pre.textContent = "Erreur : " + rep.erreur;
    }
  } catch (e) {
    pre.textContent = "Erreur : " + e.message;
  }
});

document.getElementById("btn-rafraichir-systemd").addEventListener("click", rafraichirEtat);

document.getElementById("btn-installer-systemd").addEventListener("click", async () => {
  const selection = Array.from(document.querySelectorAll("#liste-systemd input:checked"))
    .map((cb) => cb.dataset.nom);
  if (!selection.length) { alert("Aucune unité cochée."); return; }
  const verbe = ETAT.os_cible === "Linux" ? "Installer et ACTIVER (systemctl --user enable --now)"
    : ETAT.os_cible === "Darwin" ? "Installer et charger (launchctl load)"
    : ETAT.os_cible === "Windows" ? "Créer les tâches planifiées (schtasks)"
    : "Installer";
  if (!confirm(verbe + " " + selection.length + " unité(s) ?")) return;
  try {
    const rep = await appelApi("/api/unites/installer", { unites: selection });
    const pre = document.getElementById("rapport-systemd");
    pre.hidden = false;
    pre.textContent = rep.rapport.join("\\n");
    await rafraichirEtat();
  } catch (e) {
    alert("Erreur : " + e.message);
  }
});

document.getElementById("btn-arreter").addEventListener("click", async () => {
  if (!confirm("Arrêter l'installateur ?")) return;
  await appelApi("/api/arreter");
  document.body.innerHTML = "<p>Installateur arrêté. Vous pouvez fermer cet onglet.</p>";
});

rafraichirEtat();
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "InstallateurBGAutomatisation/1.0"

    def log_message(self, format, *args):
        pass  # outil local, un seul utilisateur — rien à journaliser côté serveur

    def _corps_json(self):
        longueur = int(self.headers.get("Content-Length", 0) or 0)
        if not longueur:
            return {}
        try:
            return json.loads(self.rfile.read(longueur))
        except json.JSONDecodeError:
            return {}

    def _repondre(self, code, corps, content_type="application/json"):
        octets = corps if isinstance(corps, bytes) else corps.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if "text" in content_type or "json" in content_type else ""))
        self.send_header("Content-Length", str(len(octets)))
        self.end_headers()
        self.wfile.write(octets)

    def _jeton_valide(self):
        return self.headers.get("X-Jeton-Session") == SESSION_TOKEN

    def do_GET(self):
        chemin = urllib.parse.urlparse(self.path).path
        if chemin == "/":
            self._repondre(200, PAGE_HTML.replace("__SESSION_TOKEN__", SESSION_TOKEN), "text/html")
        elif chemin == "/api/etat":
            etat = charger_etat()
            self._repondre(200, json.dumps({
                "checklist": etat.get("checklist", {}),
                "single_mandat": etat.get("single_mandat", False),
                "valeurs_jetons": etat.get("valeurs_jetons", {}),
                "tokens": TOKENS,
                "jetons_restants": jetons_restants(),
                "unites": unites_planifiees(),
                "os_cible": platform.system(),
                "etat_facebook": reseaux_sociaux.etat_facebook(),
                "etat_instagram": reseaux_sociaux.etat_instagram(),
                "openclaw_disponible": openclaw_disponible(),
            }))
        else:
            self._repondre(404, json.dumps({"erreur": "introuvable"}))

    def do_POST(self):
        chemin = urllib.parse.urlparse(self.path).path
        if not self._jeton_valide():
            self._repondre(403, json.dumps({"erreur": "jeton de session invalide"}))
            return

        corps = self._corps_json()
        etat = charger_etat()

        if chemin == "/api/checklist":
            etat.setdefault("checklist", {})[corps.get("id", "")] = bool(corps.get("valeur"))
            sauvegarder_etat(etat)
            self._repondre(200, json.dumps({"ok": True}))

        elif chemin == "/api/openclaw/installer":
            script = os.path.join(ICI, "00-Demarrage", "installer-openclaw.sh")
            try:
                r = subprocess.run(["bash", script], cwd=ICI, capture_output=True, text=True)
                sortie = (r.stdout or "") + (r.stderr or "")
            except FileNotFoundError:
                sortie = "Script introuvable ou bash absent."
            self._repondre(200, json.dumps({"sortie": sortie}))

        elif chemin == "/api/openclaw/cle":
            resultat = openclaw_patch_cle_openrouter(corps.get("cle", ""))
            self._repondre(200, json.dumps(resultat))

        elif chemin == "/api/openclaw/doctor":
            self._repondre(200, json.dumps(openclaw_doctor()))

        elif chemin == "/api/openclaw/service":
            self._repondre(200, json.dumps({"rapport": openclaw_installer_demarrer_service()}))

        elif chemin == "/api/tokens/appliquer":
            valeurs = corps.get("valeurs", {})
            single = bool(corps.get("single_mandat"))
            rapport = appliquer_jetons(valeurs, single)
            etat["single_mandat"] = single
            etat.setdefault("valeurs_jetons", {}).update({k: v for k, v in valeurs.items() if v})
            sauvegarder_etat(etat)
            self._repondre(200, json.dumps(rapport))

        elif chemin == "/api/facebook/echanger":
            resultat = configurer_facebook.echanger_jeton_page(
                corps.get("jeton_court", ""), corps.get("app_id", ""), corps.get("app_secret", ""),
                configurer_facebook.PAGE_ID_CONNU,
            )
            if resultat.get("ambigu"):
                choix_id = secrets.token_urlsafe(8)
                _PAGES_EN_ATTENTE[choix_id] = resultat["pages"]
                self._repondre(200, json.dumps({
                    "ok": False, "ambigu": True, "choix_id": choix_id,
                    "pages": [{"id": p["id"], "name": p["name"]} for p in resultat["pages"]],
                }))
            elif not resultat["ok"]:
                self._repondre(200, json.dumps({"ok": False, "erreur": resultat["erreur"]}))
            else:
                configurer_facebook.ecrire_jeton(resultat["page_id"], resultat["jeton"])
                self._repondre(200, json.dumps({"ok": True, "page_id": resultat["page_id"], "page_name": resultat["page_name"]}))

        elif chemin == "/api/facebook/choisir_page":
            pages = _PAGES_EN_ATTENTE.pop(corps.get("choix_id", ""), None)
            page = next((p for p in (pages or []) if p["id"] == corps.get("page_id")), None) if pages else None
            if not page:
                self._repondre(200, json.dumps({"ok": False, "erreur": "Choix expiré ou invalide — recommencez l'échange."}))
            else:
                configurer_facebook.ecrire_jeton(page["id"], page["jeton"])
                self._repondre(200, json.dumps({"ok": True, "page_id": page["id"], "page_name": page["name"]}))

        elif chemin == "/api/facebook/cloud":
            cfg = reseaux_sociaux.lire_json(configurer_facebook.JETON)
            if not cfg or not cfg.get("page_id") or not cfg.get("jeton"):
                self._repondre(200, json.dumps({"ok": False, "erreur": "Pas de jeton Facebook local — complétez d'abord l'étape du jeton."}))
                return
            resultat = reseaux_sociaux.deployer_cloud(
                cfg["page_id"], corps.get("fuseau", ""), corps.get("chemin_site", ""),
                forcer_ecrasement=bool(corps.get("forcer")),
            )
            if resultat["ok"] and corps.get("creer_secret"):
                resultat["secret_github"] = reseaux_sociaux.creer_secret_github(corps.get("chemin_site", ""), cfg["jeton"])
            self._repondre(200, json.dumps(resultat))

        elif chemin == "/api/instagram/echanger":
            resultat = configurer_instagram.echanger_jeton(
                corps.get("jeton_court", ""), corps.get("app_secret") or None, bool(corps.get("deja_long")),
            )
            if resultat["ok"]:
                configurer_instagram.ecrire_jeton(resultat["user_id"], resultat["jeton"], resultat["expire_le"])
                self._repondre(200, json.dumps({
                    "ok": True, "username": resultat["username"], "expire_le": resultat["expire_le"],
                    "avertissement": resultat["avertissement"],
                }))
            else:
                self._repondre(200, json.dumps({"ok": False, "erreur": resultat["erreur"]}))

        elif chemin == "/api/terminal":
            ouvert = tenter_ouvrir_terminal(corps.get("commande", ""))
            self._repondre(200, json.dumps({"ouvert": ouvert}))

        elif chemin == "/api/unites/installer":
            rapport = installer_unites(corps.get("unites", []))
            self._repondre(200, json.dumps({"rapport": rapport}))

        elif chemin == "/api/arreter":
            self._repondre(200, json.dumps({"ok": True}))
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        else:
            self._repondre(404, json.dumps({"erreur": "introuvable"}))


# --- Démarrage et repli de port, sans jamais passer par un input() ---------

PAGE_BOOTSTRAP = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Installateur — choix du port</title>
<style>body{{font-family:system-ui,sans-serif;max-width:30rem;margin:3rem auto;padding:0 1rem;}}
input{{padding:.4rem;width:6rem;}} button{{padding:.4rem .8rem;}} .erreur{{color:#c33;}}</style>
</head><body>
<h1>Port indisponible</h1>
{erreur_html}
<p>Le port {port} n'a pas pu être utilisé pour l'installateur. Choisissez-en un autre :</p>
<form method="post" action="/essayer">
  <input type="number" name="port" min="1" max="65535" value="{port}">
  <button type="submit">Essayer</button>
</form>
</body></html>
"""


def page_bootstrap(port, erreur=None):
    erreur_html = f'<p class="erreur">{erreur}</p>' if erreur else ""
    return PAGE_BOOTSTRAP.format(port=port, erreur_html=erreur_html)


def faire_handler_bootstrap(partagee):
    class HandlerBootstrap(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            corps = page_bootstrap(partagee["port"], partagee.get("erreur")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def do_POST(self):
            longueur = int(self.headers.get("Content-Length", 0) or 0)
            champs = urllib.parse.parse_qs(self.rfile.read(longueur).decode("utf-8"))
            brut = (champs.get("port") or [""])[0]
            try:
                port = int(brut)
            except ValueError:
                partagee["erreur"] = "Numéro de port invalide."
                self._rediriger()
                return
            try:
                httpd_reel = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
            except OSError as e:
                partagee["port"] = port
                partagee["erreur"] = f"Port {port} indisponible ({e})."
                self._rediriger()
                return
            partagee["resultat"] = (httpd_reel, port)
            url = f"http://127.0.0.1:{port}/"
            corps = (f'<!doctype html><meta http-equiv="refresh" content="0;url={url}">'
                     f'<a href="{url}">{url}</a>').encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def _rediriger(self):
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return HandlerBootstrap


def ouvrir_navigateur_sans_bloquer(url):
    """webbrowser.open() bloque parfois jusqu'à la fermeture du navigateur
    (certains contrôleurs, ex. GenericBrowser, appellent os.system au lieu
    de Popen) — sur un poste où ça arrive, ça gèlerait tout le démarrage du
    serveur. On l'appelle donc toujours depuis un thread à part ; l'échec
    (ou l'absence de navigateur graphique) n'empêche jamais de continuer,
    l'adresse reste affichée dans le terminal comme repli."""
    def cible():
        try:
            if not webbrowser.open(url):
                print(f"Ouvrez cette adresse manuellement : {url}")
        except Exception:
            print(f"Ouvrez cette adresse manuellement : {url}")

    threading.Thread(target=cible, daemon=True).start()


def demarrer_serveur(port_souhaite):
    """Lie le vrai serveur sur port_souhaite, ou — s'il est occupé — ouvre
    une petite page de repli (jamais un prompt terminal) qui laisse choisir
    un autre port jusqu'à ce que ça marche."""
    try:
        return http.server.ThreadingHTTPServer(("127.0.0.1", port_souhaite), Handler), port_souhaite
    except OSError as e:
        print(f"Port {port_souhaite} indisponible ({e}) — ouverture d'une page pour en choisir un autre.")

    partagee = {"port": port_souhaite, "erreur": None, "resultat": None}
    bootstrap = http.server.ThreadingHTTPServer(("127.0.0.1", 0), faire_handler_bootstrap(partagee))
    url_bootstrap = f"http://127.0.0.1:{bootstrap.server_address[1]}/"
    print(f"Ouverture de {url_bootstrap} pour choisir un port…")
    ouvrir_navigateur_sans_bloquer(url_bootstrap)

    bootstrap.serve_forever()
    bootstrap.server_close()

    if not partagee["resultat"]:
        raise RuntimeError("Aucun port valide choisi — installateur arrêté.")
    return partagee["resultat"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=PORT_PAR_DEFAUT,
                         help=f"port de départ (défaut {PORT_PAR_DEFAUT}) — si occupé, une page dans le navigateur en redemande un")
    args = parser.parse_args()

    httpd, port = demarrer_serveur(args.port)

    url = f"http://127.0.0.1:{port}/"
    print(f"Installateur démarré sur {url}")
    print("Ctrl+C ici, ou le bouton « Arrêter l'installateur » dans la page, pour terminer.")
    ouvrir_navigateur_sans_bloquer(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("Installateur arrêté.")


if __name__ == "__main__":
    main()
