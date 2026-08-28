#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Passerelle des courriels de prospection — du tableau de bord à Thunderbird.

Le prospecteur (prospecteur.py) rédige un brouillon par claude -p et le dépose
dans le détail de la tâche « Premier contact — X » / « Relance N — X » du
tableau de bord. La page ouvrait ce brouillon avec un lien mailto: — et
mailto: ne choisit pas l'identité d'envoi : sur ce poste, il retombe sur
l'identité par défaut de Thunderbird (Github <github@{{DOMAINE}}>) au
lieu de celle du mandat visé, et Evolution récupère le lien (sans corps ni
expéditeur) quand Thunderbird est fermé. Cette passerelle fait ce que fait
déjà courriels_mandat_exemple.py pour les 78 courriels {{MANDAT_EXEMPLE}} : elle ouvre Thunderbird avec
la syntaxe à champs (from=…,to=…,subject=…,body=…), la seule qui sélectionne
la bonne identité dans le champ « De ».

RIEN N'EST ENVOYÉ, JAMAIS : une fenêtre s'ouvre, le clic sur « Envoyer » reste
un geste humain.

    demandesCourriel   { "<tâcheId>": {geste:"ouvrir", maj} } déposé par la
                       page dans users/<uid>/marketing/prospection, exécuté
                       ici à partir du brouillon de la tâche et du courriel
                       du prospect (déjà dans le miroir), puis effacé.

    demandeLancement   { geste:"lancer", maj } déposé par le bouton « Lancer
                       le prospecteur » : démarre la chaîne d'acquisition
                       (recherchiste + prospecteur), puis répond dans
                       « lancement » {etat, quand}.

    python3 courriels_prospection.py              boucle (cycle de 5 s)
    python3 courriels_prospection.py --une-fois    un seul cycle
    python3 courriels_prospection.py --essai       montre tout, n'ouvre rien
"""
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import api, decoder, encoder, BASE, UID, journaliser  # noqa: E402

DOC = f"users/{UID}/marketing/prospection"
ETAT = f"users/{UID}/marketing/state"
INTERVALLE = 5

# L'identité Thunderbird qui doit apparaître dans « De », selon le mandat du
# prospect. Doit correspondre EXACTEMENT à une adresse déjà configurée sur ce
# poste (Thunderbird → Paramètres des comptes) — une adresse absente ne
# sélectionne rien, et Thunderbird retombe sur son identité par défaut,
# silencieusement. Vérifier qu'un compte {{COURRIEL_PUBLIC}} existe sur ce
# poste avant le premier prospect côté {{ENTREPRISE}}.
IDENTITES = {
    "{{MANDAT_EXEMPLE}}": "{{COURRIEL_MANDAT_EXEMPLE}}",
    "{{ENTREPRISE}}": "{{COURRIEL_PUBLIC}}",
}

RE_BROUILLON = re.compile(
    r"Brouillon prêt[^:]*:\n\n(.*?)\n\nMarquer cette tâche", re.S)

ESSAI = "--essai" in sys.argv
UNE_FOIS = "--une-fois" in sys.argv or ESSAI


def lire(chemin):
    try:
        d = api(f"{BASE}/{chemin}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    return {k: decoder(v) for k, v in d.get("fields", {}).items()}


def patch(champs, masques):
    q = "&".join("updateMask.fieldPaths=" + urllib.parse.quote(m, safe="")
                 for m in masques)
    api(f"{BASE}/{DOC}?{q}",
        {"fields": {k: encoder(v) for k, v in champs.items()}}, methode="PATCH")


def oublier_demande(tache_id):
    """Retire UNE demande de la file (accents graves : l'identifiant, un
    uuid4, contient des chiffres et des tirets — Firestore chercherait sinon
    une sous-carte)."""
    patch({}, [f"demandesCourriel.`{tache_id}`"])


def maintenant_ms():
    """Époque en millisecondes, comme le Date.now() de la page — l'accusé
    « lancement.quand » doit se comparer au moment du clic côté navigateur."""
    return int(time.time() * 1000)


def demarrer_service(service, script, args=()):
    """Démarre un service utilisateur sans bloquer (--no-block : un oneshot
    ferait attendre systemctl jusqu'à la fin du cycle sinon). Repli sur un
    lancement direct du script quand le bus utilisateur ne répond pas."""
    r = subprocess.run(["systemctl", "--user", "start", "--no-block", service],
                       capture_output=True, text=True, timeout=20)
    if r.returncode == 0:
        return
    chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)), script)
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    subprocess.Popen([sys.executable, chemin, *args], env=env,
                     start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def lancer_acquisition(doc_p):
    """« Lancer le prospecteur » déclenche toute la chaîne d'acquisition :

      1. le RECHERCHISTE cherche de nouveaux clients potentiels (candidats) ;
      2. le PROSPECTEUR rédige les courriels personnalisés des prospects dus.

    Entre les deux vit un garde-fou VOULU : un candidat n'entre dans la
    cadence — et n'obtient son courriel — qu'après acceptation du propriétaire au
    tableau de bord. Ce clic ne le contourne pas : il remplit la liste de
    candidats et rédige pour ceux déjà acceptés et dus.

    On démarre les deux services (même chemin que les cycles planifiés, avec
    leur attente réseau), puis on renvoie un accusé dans « lancement » (que la
    page lit pour rallumer son bouton). La demande est CONSOMMÉE d'abord : un
    clic, un lancement, même en cas d'échec — sinon on relancerait à chaque
    tour de 5 s."""
    dem = doc_p.get("demandeLancement")
    if not dem:
        return
    if ESSAI:
        print(f"[essai] chaîne d'acquisition demandée — {dem}")
        return
    patch({}, ["demandeLancement"])
    try:
        demarrer_service("bg-recherchiste.service", "recherchiste.py",
                         ["--nombre", "15"])
        demarrer_service("bg-prospecteur.service", "prospecteur.py")
        patch({"lancement": {"etat": "lance", "quand": maintenant_ms()}}, ["lancement"])
        journaliser("courriels prospection : chaîne d'acquisition lancée "
                    "(recherchiste + prospecteur, demande du tableau de bord)")
    except Exception as e:                                   # noqa: BLE001
        patch({"lancement": {"etat": "erreur", "quand": maintenant_ms(),
                             "resume": str(e)[:200]}}, ["lancement"])
        journaliser(f"courriels prospection : lancement acquisition a échoué — {e}")


def brouillon_de(tache):
    """Même extraction que brouillonDe() côté page (js/app.js) : le texte
    entre l'entête posée par prospecteur.py:creer_tache() et la consigne de
    fin. Les deux lectures doivent rester identiques, sinon la page montre un
    brouillon que la passerelle ne retrouve pas."""
    m = RE_BROUILLON.search((tache or {}).get("detail") or "")
    return m.group(1).strip() if m else ""


def thunderbird_tourne():
    return subprocess.run(["pgrep", "-x", "thunderbird"],
                          capture_output=True).returncode == 0


def assurer_thunderbird(env):
    """Même détour que courriels_mandat_exemple.py : démarrer Thunderbird à part avant
    de lui demander une fenêtre, sinon la fenêtre s'ouvre puis disparaît."""
    if thunderbird_tourne():
        return
    journaliser("courriels prospection : Thunderbird dormait — démarrage")
    subprocess.Popen(["thunderbird"], env=env, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):                       # au plus 40 s
        time.sleep(1)
        if thunderbird_tourne():
            time.sleep(3)                     # le temps qu'il ouvre sa fenêtre
            return
    journaliser("courriels prospection : Thunderbird ne répond pas au démarrage")


def sain(texte):
    """Une apostrophe droite casse la syntaxe à guillemets simples de
    « thunderbird -compose » (elle fermerait le champ en cours). On la
    convertit en apostrophe typographique plutôt que de refuser d'ouvrir :
    ce n'est qu'un brouillon, relu avant l'envoi de toute façon."""
    return (texte or "").replace("'", "’")


def ouvrir(dest, expediteur, objet, corps):
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    assurer_thunderbird(env)
    args = (f"from='{sain(expediteur)}',to='{sain(dest)}',"
            f"subject='{sain(objet)}',body='{sain(corps)}'")
    subprocess.run(["thunderbird", "-compose", args], timeout=30,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


def cycle():
    doc_p = lire(DOC)
    lancer_acquisition(doc_p)
    demandes = doc_p.get("demandesCourriel") or {}
    if not demandes:
        return
    doc_e = lire(ETAT)
    taches = {t.get("id"): t for t in (doc_e.get("taches") or [])}
    mandat_doc = doc_p.get("mandat") or (doc_e.get("config") or {}).get("mandatStme") or ""
    prospects_par_tache = {p.get("tacheId"): p
                           for p in (doc_p.get("prospects") or []) if p.get("tacheId")}

    for tache_id in sorted(demandes):
        d = demandes[tache_id] or {}
        geste = d.get("geste") or "ouvrir"
        t = taches.get(tache_id)
        p = prospects_par_tache.get(tache_id)
        brouillon = brouillon_de(t)
        if geste != "ouvrir" or not t or not p or not brouillon:
            journaliser(f"courriels prospection : demande refusée — « {tache_id} » / "
                        f"« {geste} » (tâche, prospect ou brouillon introuvable)")
            if not ESSAI:
                oublier_demande(tache_id)
            continue
        mandat = p.get("mandat") or mandat_doc
        expediteur = IDENTITES.get(mandat)
        if not expediteur:
            journaliser(f"courriels prospection : mandat « {mandat} » sans identité "
                        f"Thunderbird connue — {p.get('prospect')} sauté")
            if not ESSAI:
                oublier_demande(tache_id)
            continue
        dest = p.get("courriel") or ""
        if ESSAI:
            print(f"[essai] {p.get('prospect')} — de {expediteur} à "
                  f"{dest or '(destinataire à compléter)'}")
            continue
        try:
            ouvrir(dest, expediteur, p.get("prospect") or "", brouillon)
            journaliser(f"courriels prospection : fenêtre ouverte — {p.get('prospect')} "
                        f"({expediteur} → {dest or 'destinataire à compléter'})")
        except Exception as e:                                   # noqa: BLE001
            journaliser(f"courriels prospection : {p.get('prospect')} a échoué — {e}")
        finally:
            oublier_demande(tache_id)


def main():
    journaliser("courriels prospection : passerelle démarrée"
                + (" — ESSAI, aucune écriture" if ESSAI else ""))
    while True:
        try:
            cycle()
        except urllib.error.HTTPError as e:
            journaliser(f"courriels prospection : HTTP {e.code} — {(e.read() or b'')[:200]!r}")
        except Exception as e:                                   # noqa: BLE001
            journaliser(f"courriels prospection : erreur — {type(e).__name__} : {e}")
        if UNE_FOIS:
            return
        time.sleep(INTERVALLE)


if __name__ == "__main__":
    main()
