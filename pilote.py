#!/usr/bin/env python3
"""Pilote — le tableau de bord marketing avance par lui-même.

Lancé chaque matin 9 h 15 par bg-pilote.timer. Le bouton éclair de l'outil
web lance UNE tâche quand le propriétaire clique ; le pilote fait le même
geste sans le clic : il choisit la prochaine tâche « a_faire » du tableau de
bord, la met en file du lanceur, puis consigne le résultat au tableau au
passage suivant. Le propriétaire n'intervient plus que là où le cadre
l'exige : au guichet d'autorisations.

Ce qu'il s'interdit :

  - UNE tâche du pilote à la fois — jamais de rafale ; tant que la
    précédente est en rédaction ou au guichet, il attend.
  - Les tâches du mandat {{MANDAT_EXEMPLE}} : elles ont leurs propres
    automatismes (prospecteur, recherchiste) et leurs informations ne se
    mêlent pas à celles de {{ENTREPRISE}}.
  - Les tâches de la vigie (source « vigie ») : ce sont des alertes et des
    rappels ADRESSÉS au propriétaire, pas du travail à déléguer.
  - Une tâche dont le lancement a échoué ou a été refusé n'est PAS relancée
    (liste « ecartees ») : le propriétaire la reprendra par le bouton éclair
    s'il la veut quand même.

Choix de la prochaine tâche : statut a_faire, priorité haute d'abord, puis
échéance la plus proche, puis la plus ancienne. Le détail de la tâche part
tel quel, coiffé d'une entête qui exige de VÉRIFIER LES PRÉMISSES avant
d'agir — le tableau peut charrier des consignes datées.

    python3 pilote.py           # un passage
    python3 pilote.py --essai   # montre ce qui serait lancé, n'écrit rien
    python3 pilote.py --rafale  # enchaîne les tâches jusqu'à épuisement :
                                # une tâche arrêtée au guichet est mise de
                                # côté (elle attend le propriétaire) et la
                                # file CONTINUE avec la suivante.

Un verrou (etat_pilote.lock) empêche deux pilotes de tourner en même temps —
la minuterie de 9 h 15 passe son tour si une rafale est en cours.

État local : etat_pilote.json (tâche en cours, tâches au guichet, écartées).
Journal partagé : journal.log.
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import api, decoder, encoder, BASE, UID, journaliser  # noqa: E402
from vigie import (assurer_tache, etat_marketing, pousser_etat,  # noqa: E402
                   reseau_pret)

ICI = os.path.dirname(os.path.abspath(__file__))
FICHIER_ETAT = os.path.join(ICI, "etat_pilote.json")
ESSAI = "--essai" in sys.argv
RAFALE = "--rafale" in sys.argv
MAX_RAFALE = 40        # plafond dur d'une rafale
MAX_ECHECS_SUITE = 3   # trois échecs d'affilée = quelque chose cloche, on arrête
PAUSE_PANNE = 300      # 5 min avant de réessayer après un creux passager…
MAX_ATTENTES = 4       # …puis 10, 15, 20 : au-delà, le service ne se replace pas

# Le mandat {{MANDAT_EXEMPLE}} a ses propres automatismes ; la vigie parle AU propriétaire.
CLIENTS_EXCLUS = {"{{MANDAT_EXEMPLE}}"}
SOURCES_EXCLUES = {"vigie"}
ORDRE_PRIORITE = {"haute": 0, "moyenne": 1, "basse": 2}

ENTETE_PILOTE = (
    "\n\n--- LANCÉE PAR LE PILOTE ---\n"
    "Cette tâche du tableau de bord part automatiquement, sans relecture "
    "humaine de son détail. AVANT d'agir : vérifie ses prémisses contre "
    "l'état réel — les fichiers, le dépôt, les décisions récentes de "
    "Campagne_BG/ — car le détail peut dater. Prémisse fausse, travail déjà "
    "fait ou décision contredite : ne force rien, dis-le en conclusion et "
    "termine là.\n"
    "Règles d'écriture {{ENTREPRISE}} : toujours « estimation sans frais », jamais "
    "« diagnostic gratuit » ; aucune promesse de délai ; {{ENTREPRISE}} ne vend aucun "
    "matériel ; aucune mention de {{MANDAT_EXEMPLE}} dans un contenu {{ENTREPRISE}} ; ne pas présenter "
    "de certifications ; coordonnées publiées : {{TELEPHONE}}, "
    "{{COURRIEL_PUBLIC}}.")


def lire_etat_local():
    try:
        return json.load(open(FICHIER_ETAT, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ecrire_etat_local(e):
    if ESSAI:
        return
    with open(FICHIER_ETAT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=1)
    os.replace(FICHIER_ETAT + ".tmp", FICHIER_ETAT)


def etat_lancement(nom):
    """Le statut d'un lancement et, s'il a échoué, son message d'erreur."""
    try:
        d = api(f"{BASE}/users/{UID}/marketing/{nom}")
        f = d.get("fields", {})
        return (decoder(f.get("statut", {"stringValue": ""})),
                decoder(f.get("erreur", {"stringValue": ""})) or "")
    except urllib.error.HTTPError:
        return "disparu", ""


def statut_lancement(nom):
    return etat_lancement(nom)[0]


# Un échec qui ne dit RIEN sur la tâche : quota épuisé, réseau tombé, service
# surchargé. La tâche est saine — l'écarter serait la punir pour une panne de
# la machine. Le 2026-08-17, trois tâches de prospection ont été bannies comme
# ça, sur « You've hit your session limit ».
#
# Un mur ferme : rien ne repartira avant une remise à zéro (dont l'heure est
# souvent dans le message — voir programmer_reprise).
PANNES_BLOQUANTES = ("session limit", "usage limit", "usage credit",
                     "out of credit", "quota")
# Un creux passager : le même lancement réussira probablement dans dix
# minutes. On patiente, on ne renonce pas.
PANNES_PASSAGERES = ("overloaded", "rate limit", "name resolution",
                     "connection reset", "connection refused", "timed out",
                     "délai dépassé", "temporarily unavailable", "503", "529",
                     "502", "504")


def classer_panne(erreur):
    """« bloquante », « passagere », ou None si l'échec vient de la tâche."""
    e = (erreur or "").lower()
    if any(m in e for m in PANNES_BLOQUANTES):
        return "bloquante"
    if any(m in e for m in PANNES_PASSAGERES):
        return "passagere"
    return None


def est_panne_infra(erreur):
    return classer_panne(erreur) is not None


def programmer_reprise(erreur):
    """Revenir tout seul quand le mur tombe.

    Les messages de limite portent l'heure de la remise à zéro (« resets
    10:20pm »). Plutôt que d'attendre le passage du lendemain 9 h 15 — ou un
    geste du propriétaire —, on arme une minuterie éphémère qui relance la
    rafale cinq minutes après cette heure-là. Sans elle, une limite atteinte à
    midi coûtait une journée de travail au tableau.

    Le nom d'unité est fixe : une reprise déjà armée est remplacée, jamais
    empilée. Sans heure lisible, on ne devine pas — le passage quotidien
    reprendra le flambeau."""
    m = re.search(r"resets?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)", erreur or "", re.I)
    if not m:
        return
    heure = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
    quand = datetime.now().replace(hour=heure, minute=int(m.group(2) or 0),
                                   second=0, microsecond=0) + timedelta(minutes=5)
    if quand < datetime.now():                 # l'heure est déjà passée : demain
        quand += timedelta(days=1)
    subprocess.run(["systemctl", "--user", "stop", "bg-pilote-reprise.timer"],
                   capture_output=True)
    r = subprocess.run(
        ["systemd-run", "--user", "--unit=bg-pilote-reprise",
         f"--on-calendar={quand.strftime('%Y-%m-%d %H:%M:%S')}",
         "/usr/bin/python3", os.path.join(ICI, "pilote.py"), "--rafale"],
        capture_output=True, text=True)
    if r.returncode == 0:
        journaliser("pilote : reprise programmée pour "
                    + quand.strftime("%Y-%m-%d %H:%M"))
    else:
        journaliser(f"pilote : reprise impossible à programmer — "
                    f"{(r.stderr or '').strip()[:120]}")


def signaler_panne(etat, erreur):
    """Une tâche à la colonne « À compléter manuellement » : l'automatisation
    s'arrête, et le propriétaire ne doit pas l'apprendre par le silence. Une
    seule par semaine (la clé porte la semaine), supprimable comme les
    autres — supprimer, c'est dire « je sais »."""
    credits = any(m in (erreur or "").lower()
                  for m in ("usage credit", "out of credit", "session limit",
                            "usage limit"))
    semaine = date.today().strftime("%G-S%V")
    if credits:
        titre = "⚠️ Crédits Claude épuisés — l'automatisation est en pause"
        detail = ("Le pilote et les tâches lancées se sont arrêtés : le compte "
                  "Claude n'a plus de crédit d'utilisation.\n\n"
                  f"Message reçu : « {(erreur or '').strip()[:200]} »\n\n"
                  "ÉTAPES :\n"
                  "1. Ouvrir https://claude.ai/settings/usage dans le "
                  "navigateur, connecté avec le compte de {{ENTREPRISE}}.\n"
                  "2. Regarder la date de remise à zéro, ou ajouter du crédit "
                  "si le travail ne peut pas attendre.\n\n"
                  "Aucune tâche n'est perdue : celles qui ont flanché sont "
                  "revenues « à faire » et repartiront d'elles-mêmes. Le pilote "
                  "réessaie chaque matin à 9 h 15 ; pour tout relancer d'un "
                  "coup dès que le crédit est revenu, ouvrir l'application "
                  "Terminal et coller :\n"
                  "systemd-run --user --unit=bg-pilote-rafale /usr/bin/python3 "
                  "{{CHEMIN_INSTALLATION}}/pilote.py --rafale")
    else:
        titre = "⚠️ L'automatisation a flanché sur une panne technique"
        detail = ("Une tâche lancée s'est arrêtée sur une panne qui ne vient "
                  "pas d'elle (réseau, service surchargé).\n\n"
                  f"Message reçu : « {(erreur or '').strip()[:200]} »\n\n"
                  "Les tâches touchées restent « à faire » et repartiront au "
                  "prochain passage du pilote (9 h 15). Si ça se répète "
                  "plusieurs jours, ouvrir une session Claude et lui demander "
                  "de diagnostiquer.")
    assurer_tache(etat, f"pilote-panne-{semaine}", titre, detail, "Pilotage",
                  priorite="haute", echeance=date.today().isoformat(), estime="5")


def tache_par_id(etat, tid):
    for t in etat.get("taches") or []:
        if t.get("id") == tid:
            return t
    return None


def finaliser(etat, etat_local, tid, titre, statut, erreur=""):
    """Consigne au tableau le sort d'un lancement TERMINÉ (fait, refuse,
    echec…). On ne touche à la tâche que si elle est restée telle que le
    pilote l'a laissée : un statut changé entre-temps est un geste du
    propriétaire. Rend le sort retenu : fait, refuse, echec ou panne."""
    t = tache_par_id(etat, tid)
    if statut == "fait":
        if t and t.get("statut") == "en_cours":
            t["statut"] = "fait"
            t["maj"] = int(time.time() * 1000)
        journaliser(f"pilote : « {titre} » terminée — consignée faite au tableau")
        return "fait"
    if statut == "refuse":
        if t and t.get("statut") == "en_cours":
            t["statut"] = "reporte"
            t["maj"] = int(time.time() * 1000)
        etat_local.setdefault("ecartees", []).append(tid)
        journaliser(f"pilote : « {titre} » refusée au guichet "
                    "— reportée, le pilote n'y reviendra pas")
        return "refuse"
    # Échec : la tâche redevient a_faire dans tous les cas. Elle n'est écartée
    # que si l'échec la concerne VRAIMENT — une panne de la machine la laisse
    # candidate, sinon une coupure de quota effacerait le reste du tableau.
    if t and t.get("statut") == "en_cours":
        t["statut"] = "a_faire"
        t["maj"] = int(time.time() * 1000)
    panne = classer_panne(erreur)
    if panne:
        journaliser(f"pilote : « {titre} » interrompue par une panne "
                    f"{panne} — « {erreur.strip()[:80]} ». La tâche reste "
                    "candidate.")
        if panne == "bloquante":
            signaler_panne(etat, erreur)
            programmer_reprise(erreur)
        return f"panne-{panne}"
    etat_local.setdefault("ecartees", []).append(tid)
    journaliser(f"pilote : « {titre} » terminée en "
                f"« {statut} » — remise a_faire et écartée du pilote")
    return "echec"


def solder(etat, etat_local):
    """Consigne le sort du lancement précédent. Une tâche arrêtée au guichet
    est mise de côté (elle attend le propriétaire) et la file CONTINUE.
    Rend « libre » (on peut lancer), « attend » (un lancement tourne) ou
    « panne » (la machine est en panne : ne rien relancer tout de suite)."""
    en_cours = etat_local.get("en_cours")
    if not en_cours:
        return "libre"
    tid, nom = en_cours.get("tache"), en_cours.get("lancement")
    statut, erreur = etat_lancement(nom)
    if statut in ("demande", "en_cours"):
        journaliser(f"pilote : « {en_cours.get('titre')} » toujours en "
                    f"« {statut} » — on attend")
        return "attend"
    sort = "guichet"
    if statut == "attente_autorisation":
        etat_local.setdefault("au_guichet", {})[tid] = en_cours
        journaliser(f"pilote : « {en_cours.get('titre')} » au guichet — mise "
                    "de côté, la file continue")
    else:
        sort = finaliser(etat, etat_local, tid, en_cours.get("titre"),
                         statut, erreur)
    del etat_local["en_cours"]
    return sort if sort.startswith("panne-") else "libre"


def solder_guichet(etat, etat_local):
    """Repasse sur les tâches mises de côté au guichet : celles que le
    propriétaire a tranchées (la tâche est repartie puis a fini) sont
    consignées ; les autres attendent encore."""
    modif = False
    for tid, info in list((etat_local.get("au_guichet") or {}).items()):
        statut, erreur = etat_lancement(info.get("lancement"))
        if statut in ("demande", "en_cours", "attente_autorisation"):
            continue
        finaliser(etat, etat_local, tid, info.get("titre"), statut, erreur)
        del etat_local["au_guichet"][tid]
        modif = True
    return modif


def prochaine(etat, etat_local):
    ecartees = set(etat_local.get("ecartees") or [])
    c = [t for t in etat.get("taches") or []
         if t.get("statut") == "a_faire"
         and t.get("client") not in CLIENTS_EXCLUS
         and t.get("source") not in SOURCES_EXCLUES
         and t.get("id") not in ecartees]
    c.sort(key=lambda t: (ORDRE_PRIORITE.get(t.get("priorite"), 1),
                          t.get("echeance") or "9999-12-31",
                          int(t.get("cree") or 0)))
    return c[0] if c else None


def lancer(t):
    if ESSAI:
        print(f"[essai] serait lancée : [{t.get('priorite')}] {t.get('titre')} "
              f"(client {t.get('client')}, chantier {t.get('chantier')})")
        return "essai"
    now = int(time.time() * 1000)
    nom = f"lancement-{now}-pi{os.urandom(2).hex()}"
    champs = {"idTache": t.get("id") or "", "titre": t.get("titre") or "",
              "detail": (t.get("detail") or "") + ENTETE_PILOTE,
              "client": t.get("client") or "", "chantier": t.get("chantier") or "",
              "statut": "demande", "demandeLe": now, "maj": now}
    api(f"{BASE}/users/{UID}/marketing/{nom}",
        {"fields": {k: encoder(v) for k, v in champs.items()}}, methode="PATCH")
    journaliser(f"pilote : lancée — {nom} ({t.get('titre')!r})")
    return nom


def passage():
    """Un passage complet. Rend « lance » (une tâche vient de partir),
    « attend » (un lancement tourne encore), « rien » (plus de candidate)
    ou « erreur » (réseau ou tableau illisible)."""
    journaliser("pilote : passage" + (" (essai)" if ESSAI else ""))
    if not reseau_pret():
        journaliser("pilote : pas de réseau — on réessaiera plus tard")
        return "erreur"
    etat_local = lire_etat_local()
    try:
        etat = etat_marketing()
    except Exception as e:
        journaliser(f"pilote : tableau de bord illisible ({e!r})")
        return "erreur"
    modif_avant = json.dumps(etat.get("taches"), sort_keys=True, default=str)
    resultat = "rien"
    solder_guichet(etat, etat_local)
    etat_precedent = solder(etat, etat_local)
    if etat_precedent == "attend":
        resultat = "attend"
    elif etat_precedent.startswith("panne-"):
        # La machine vient de flancher : relancer dans la seconde gaspillerait
        # la tâche suivante de la même façon. Un creux passager se laisse
        # passer, un mur ferme arrête tout.
        resultat = etat_precedent
    else:
        t = prochaine(etat, etat_local)
        if not t:
            journaliser("pilote : aucune tâche lançable — le tableau est au propre")
        else:
            nom = lancer(t)
            if nom != "essai":
                t["statut"] = "en_cours"
                t["maj"] = int(time.time() * 1000)
                etat_local["en_cours"] = {"tache": t.get("id"), "lancement": nom,
                                          "titre": (t.get("titre") or "")[:80]}
            resultat = "lance"
    if not ESSAI and json.dumps(etat.get("taches"), sort_keys=True,
                                default=str) != modif_avant:
        etat["updatedAt"] = int(time.time() * 1000)
        pousser_etat(etat)
    ecrire_etat_local(etat_local)
    journaliser("pilote : passage terminé")
    return resultat


def rafale():
    """Enchaîne les tâches sans attendre la minuterie : lance, attend la fin
    du lancement, consigne, recommence. S'arrête quand il n'y a plus rien à
    lancer, au plafond, ou après trois échecs d'affilée. Les tâches arrêtées
    au guichet restent de côté — elles n'arrêtent pas la file."""
    journaliser(f"pilote : RAFALE — au plus {MAX_RAFALE} tâches, arrêt après "
                f"{MAX_ECHECS_SUITE} échecs d'affilée")
    lances, echecs_suite, attentes = 0, 0, 0
    while lances < MAX_RAFALE:
        r = passage()
        if r == "rien":
            journaliser(f"pilote : rafale terminée — {lances} tâche(s) "
                        "traitée(s), plus rien à lancer")
            return
        if r == "erreur":
            journaliser("pilote : rafale interrompue par une erreur")
            return
        if r == "panne-bloquante":
            journaliser(f"pilote : rafale arrêtée après {lances} tâche(s) — "
                        "mur ferme (crédits ou limite de compte). Les tâches "
                        "touchées restent candidates ; relancer plus tard.")
            return
        if r == "panne-passagere":
            attentes += 1
            if attentes > MAX_ATTENTES:
                journaliser(f"pilote : rafale arrêtée après {lances} tâche(s) "
                            f"— {MAX_ATTENTES} creux d'affilée, le service ne "
                            "se replace pas. Les tâches restent candidates.")
                return
            pause = PAUSE_PANNE * attentes
            journaliser(f"pilote : creux passager ({attentes}/{MAX_ATTENTES}) "
                        f"— on patiente {pause // 60} min puis on réessaie")
            time.sleep(pause)
            continue
        if r == "lance":
            lances += 1
        en_cours = lire_etat_local().get("en_cours")
        if not en_cours:
            time.sleep(20)
            continue
        debut, statut, erreur = time.time(), "", ""
        while time.time() - debut < 45 * 60:
            time.sleep(20)
            statut, erreur = etat_lancement(en_cours["lancement"])
            if statut not in ("demande", "en_cours"):
                break
        else:
            journaliser("pilote : rafale arrêtée — un lancement est immobile "
                        "depuis 45 minutes")
            return
        # Une panne d'infrastructure n'est PAS un échec de tâche : c'est le
        # passage suivant qui la classera et fera patienter la rafale. La
        # compter ici aussi ferait mentir le compteur — trois 529 d'affilée
        # s'annonçaient « quelque chose cloche » alors que rien ne clochait
        # dans les tâches. Un lancement qui aboutit remet les deux à zéro ;
        # un lancement qui part n'y suffit pas, sinon un service en panne
        # ferait tourner la rafale indéfiniment.
        if statut == "echec" and classer_panne(erreur):
            continue
        attentes = 0
        echecs_suite = echecs_suite + 1 if statut == "echec" else 0
        if echecs_suite >= MAX_ECHECS_SUITE:
            journaliser(f"pilote : rafale arrêtée — {MAX_ECHECS_SUITE} échecs "
                        "de tâche d'affilée, quelque chose cloche")
            return
    journaliser(f"pilote : rafale arrêtée au plafond de {MAX_RAFALE} tâches")


def main():
    # Un seul pilote à la fois : la minuterie passe son tour si une rafale
    # (ou un autre passage) tient déjà le verrou.
    verrou = open(os.path.join(ICI, "etat_pilote.lock"), "w")
    try:
        fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        journaliser("pilote : un autre pilote tourne déjà — je passe mon tour")
        return
    if RAFALE:
        rafale()
    else:
        passage()


if __name__ == "__main__":
    main()
