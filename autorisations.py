#!/usr/bin/env python3
"""Le guichet des tâches lancées — autoriser, refuser, corriger.

Deux moments appellent une réponse du propriétaire, et ce script les sert tous
les deux :

  • une tâche qui BUTE sur un geste hors de portée, une sortie vers
    l'extérieur, une dépense ou une décision de fond s'arrête au statut
    « attente_autorisation » (voir lanceur.py) ;
  • une tâche qui a RENDU sa réponse et dont le travail doit être repris —
    le propriétaire l'a lue et veut autre chose.

    autorisations.py                      ce qui attend une autorisation
    autorisations.py voir <ref>           la demande au complet
    autorisations.py accorder <ref> "…"   accorde et remet la tâche en file
    autorisations.py refuser <ref> "…"    refuse ; la tâche ne repart pas

    autorisations.py reponses             les tâches qui ont rendu, récentes
    autorisations.py lire <ref>           la réponse au complet
    autorisations.py corriger <ref> "…"   relance la tâche avec ta correction

<ref> est le numéro affiché dans la liste correspondante, ou la fin du nom du
document. La réponse écrite est obligatoire : elle sert de consigne à la
reprise. Une autorisation dit OUI à un geste précis (« publie le texte tel
quel », « dépense jusqu'à 20 $ ») ; une correction dit ce qui doit changer.
Ni l'une ni l'autre n'élargit le cadre de travail, qui reste écrit dans
lanceur.py.

Accorder comme corriger remettent le document au statut « demande » : le
lanceur reprend la tâche, la réponse en tête du prompt. Une correction lui
remontre en plus un extrait de ce qu'elle avait rendu, pour qu'elle reprenne
son travail au lieu de le refaire — les corrections successives s'empilent dans
le document et restent rappelées à chaque tour.
"""
import os
import sys
import time

import lanceur

STATUT = "attente_autorisation"
LARGEUR = 78


def en_attente():
    """Les lancements marketing qui attendent une réponse, du plus vieux au plus récent."""
    q = {"structuredQuery": {
        "from": [{"collectionId": lanceur.COLLECTION_MARKETING}],
        "where": {"fieldFilter": {
            "field": {"fieldPath": "statut"},
            "op": "EQUAL",
            "value": {"stringValue": STATUT}}},
        "limit": 50}}
    docs = []
    for ligne in lanceur.api(f"{lanceur.BASE}/users/{lanceur.UID}:runQuery", q):
        d = ligne.get("document")
        if not d:
            continue
        nom = d["name"].rsplit("/", 1)[-1]
        if not nom.startswith("lancement-"):
            continue
        docs.append((nom, {k: lanceur.decoder(v) for k, v in d.get("fields", {}).items()}))
    return sorted(docs, key=lambda x: x[1].get("autorisationLe") or 0)


def reponses_rendues(limite=12):
    """Les lancements qui ont rendu quelque chose, du plus récent au plus ancien.

    « echec » y figure : une tâche qui s'est plantée mérite autant une
    correction qu'une tâche qui a mal compris.
    """
    q = {"structuredQuery": {
        "from": [{"collectionId": lanceur.COLLECTION_MARKETING}],
        "orderBy": [{"field": {"fieldPath": "demandeLe"}, "direction": "DESCENDING"}],
        "limit": 60}}
    docs = []
    for ligne in lanceur.api(f"{lanceur.BASE}/users/{lanceur.UID}:runQuery", q):
        d = ligne.get("document")
        if not d:
            continue
        nom = d["name"].rsplit("/", 1)[-1]
        if not nom.startswith("lancement-"):
            continue
        f = {k: lanceur.decoder(v) for k, v in d.get("fields", {}).items()}
        if f.get("statut") in ("fait", "echec") and (f.get("resultat") or f.get("erreur")):
            docs.append((nom, f))
    return docs[:limite]


def choisir(docs, ref):
    """Le document désigné par un numéro de liste ou une fin de nom."""
    if ref.isdigit() and 1 <= int(ref) <= len(docs):
        return docs[int(ref) - 1]
    trouves = [d for d in docs if d[0].endswith(ref) or ref in d[0]]
    if len(trouves) == 1:
        return trouves[0]
    if not trouves:
        sys.exit(f"aucune entrée de cette liste ne correspond à « {ref} »")
    sys.exit("référence ambiguë : " + ", ".join(n[-6:] for n, _ in trouves))


def date(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime((ms or 0) / 1000)) if ms else "?"


def lister(docs):
    if not docs:
        print("Aucune demande d'autorisation en attente.")
        return
    print(f"{len(docs)} demande(s) en attente :\n")
    for i, (nom, f) in enumerate(docs, 1):
        print(f"  [{i}] {f.get('titre') or '(sans titre)'}")
        print(f"      {f.get('autorisationCategorie') or '?'} · "
              f"{f.get('chantier') or '?'} · arrêtée le {date(f.get('autorisationLe'))} · {nom[-6:]}")
        print(f"      → {f.get('autorisationDemande') or '(rien de consigné)'}")
        if f.get("autorisationOptions"):
            print(f"      options : {f['autorisationOptions']}")
        if f.get("autorisationOu") or f.get("autorisationQuand"):
            print(f"      où : {f.get('autorisationOu') or '?'}")
            print(f"      quand : {f.get('autorisationQuand') or '?'}")
        if f.get("autorisationTexte"):
            print(f"      texte prêt à coller ({len(f['autorisationTexte'])} caractères) "
                  f"— « voir {i} » l'affiche en entier")
        tours = int(f.get("autorisationTours") or 1)
        if tours > 1:
            print(f"      ⚠ {tours}e demande pour cette tâche — un accord précédent "
                  f"n'a pas suffi ; refuser ou revoir la tâche.")
        print()
    print("Répondre :  autorisations.py accorder <n> \"…\"   |   refuser <n> \"…\"")


def voir(nom, f):
    print(f"\n{'═' * LARGEUR}\n{f.get('titre') or '(sans titre)'}\n{'═' * LARGEUR}")
    print(f"Lancement  : {lanceur.COLLECTION_MARKETING}/{nom}")
    print(f"Mandat     : {f.get('client') or '?'}   Chantier : {f.get('chantier') or '?'}")
    print(f"Catégorie  : {f.get('autorisationCategorie') or '?'}")
    print(f"Arrêtée le : {date(f.get('autorisationLe'))}")
    if f.get("autorisationFichier"):
        print(f"Dossier    : autorisations/{f['autorisationFichier']}")
    for titre, cle in (("DEMANDÉ", "autorisationDemande"), ("POURQUOI", "autorisationPourquoi"),
                       ("OPTIONS", "autorisationOptions"), ("DÉJÀ PRÊT", "autorisationPret"),
                       ("OÙ", "autorisationOu"), ("QUAND", "autorisationQuand")):
        if f.get(cle):
            print(f"\n{titre}\n  {f[cle]}")
    # La marche à suivre, numérotée : elle est lue par quelqu'un qui n'a pas
    # suivi le travail. Si elle manque, on le dit — on ne laisse pas deviner.
    etapes = [e.strip() for e in (f.get("autorisationEtapes") or "").split("|") if e.strip()]
    if etapes:
        print("\nCOMMENT FAIRE")
        for i, e in enumerate(etapes, 1):
            print(f"  {i}. {e}")
    else:
        print("\nCOMMENT FAIRE\n  ⚠ aucune étape fournie — la fiche est incomplète."
              "\n    Ne devine pas : redemande avec « corriger ».")
    # Le texte se donne nu, entre deux règles : ce qui est entre les deux se
    # sélectionne et se colle, rien de plus.
    if f.get("autorisationTexte"):
        print(f"\nTEXTE À COLLER — tout ce qui est entre les deux règles\n{'─' * LARGEUR}")
        print(f["autorisationTexte"])
        print("─" * LARGEUR)
    for titre, cle in (("RÉUSSI QUAND", "autorisationVerif"),
                       ("SI ÇA RATE", "autorisationSiRate")):
        if f.get(cle):
            print(f"\n{titre}\n  {f[cle]}")
    if f.get("resultat"):
        print(f"\nRÉSULTAT DE LA TENTATIVE\n{'─' * LARGEUR}")
        print(f["resultat"].strip()[:4000])
    print()


def lister_reponses(docs):
    if not docs:
        print("Aucune tâche lancée n'a rendu de réponse récemment.")
        return
    print(f"{len(docs)} réponse(s) rendue(s) :\n")
    for i, (nom, f) in enumerate(docs, 1):
        marque = "échec" if f.get("statut") == "echec" else "fait"
        print(f"  [{i}] {f.get('titre') or '(sans titre)'}")
        print(f"      {marque} le {date(f.get('finiLe'))} · {f.get('chantier') or '?'} · {nom[-6:]}")
        premiere = next((l.strip() for l in (f.get("erreur") or f.get("resultat") or "").splitlines()
                         if l.strip()), "")
        print(f"      {premiere[:100]}")
        tours = [c for c in (f.get("corrections") or []) if c]
        if tours:
            print(f"      déjà corrigée {len(tours)} fois — dernière : « {tours[-1][:70]} »")
        print()
    print("Répondre :  autorisations.py corriger <n> \"ce qui doit changer\"")
    print("Lire :      autorisations.py lire <n>")


def lire(nom, f):
    print(f"\n{'═' * LARGEUR}\n{f.get('titre') or '(sans titre)'}\n{'═' * LARGEUR}")
    print(f"Lancement : {lanceur.COLLECTION_MARKETING}/{nom}   statut : {f.get('statut')}")
    print(f"Rendue le : {date(f.get('finiLe'))}"
          + (f"   coût : {f['coutUsd']:.2f} $ US" if isinstance(f.get("coutUsd"), float) else ""))
    for i, c in enumerate([c for c in (f.get("corrections") or []) if c], 1):
        print(f"Correction {i} déjà appliquée : « {c} »")
    print(f"\n{'─' * LARGEUR}")
    print((f.get("erreur") or f.get("resultat") or "").strip())
    print(f"{'─' * LARGEUR}\n")


def corriger(nom, f, remarque):
    """Renvoie la tâche au lanceur avec la remarque du propriétaire."""
    maintenant = int(time.time() * 1000)
    lanceur.maj_doc(lanceur.COLLECTION_MARKETING, nom, {
        "correction": remarque,
        "resultatPrecedent": (f.get("resultat") or f.get("erreur") or "")[:20000],
        "correctionLe": maintenant,
        "statut": "demande", "demandeLe": maintenant, "maj": maintenant,
        "resultat": "", "erreur": "",
    })
    lanceur.journaliser(f"{lanceur.COLLECTION_MARKETING}/{nom} : correction — {remarque[:110]}")
    relu = lanceur.statut_doc(lanceur.COLLECTION_MARKETING, nom)
    print(f"« {f.get('titre')} » → statut {relu}  (reprise dans les 10 s, "
          f"avec ta correction et un extrait de sa réponse précédente)")


def consigner_reponse(f, accorde, reponse):
    """Ajoute la décision au dossier déposé par le lanceur, s'il existe."""
    fichier = f.get("autorisationFichier")
    if not fichier:
        return
    chemin = os.path.join(lanceur.DOSSIER_AUTORISATIONS, fichier)
    if not os.path.exists(chemin):
        return
    texte = open(chemin, encoding="utf-8").read()
    verdict = "ACCORDÉE" if accorde else "REFUSÉE"
    texte = texte.replace("| Statut | **EN ATTENTE** |", f"| Statut | **{verdict}** |", 1)
    texte = texte.replace(
        "_En attente — répondre avec `autorisations.py accorder` ou `refuser`._",
        f"**{verdict}** le {time.strftime('%Y-%m-%d %H:%M')} :\n\n> {reponse}", 1)
    with open(chemin, "w", encoding="utf-8") as fi:
        fi.write(texte)


def repondre(nom, f, accorde, reponse):
    champs = {"autorisation" if accorde else "autorisationRefus": reponse,
              "autorisationRepondueLe": int(time.time() * 1000),
              "maj": int(time.time() * 1000)}
    if accorde:
        # Retour en file : le lanceur reprend la tâche avec la réponse en tête.
        champs.update({"statut": "demande", "resultat": "", "erreur": "",
                       "demandeLe": int(time.time() * 1000)})
    else:
        champs.update({"statut": "refuse", "finiLe": int(time.time() * 1000),
                       "erreur": f"Autorisation refusée : {reponse}"})
    lanceur.maj_doc(lanceur.COLLECTION_MARKETING, nom, champs)
    consigner_reponse(f, accorde, reponse)
    lanceur.journaliser(
        f"{lanceur.COLLECTION_MARKETING}/{nom} : autorisation "
        f"{'accordée' if accorde else 'refusée'} — {reponse[:110]}")
    # On relit : l'écriture n'est pas la preuve.
    relu = lanceur.statut_doc(lanceur.COLLECTION_MARKETING, nom)
    print(f"« {f.get('titre')} » → statut {relu}"
          + ("  (le lanceur la reprendra dans les 10 s)" if accorde else ""))


def main(argv):
    action = (argv[0] if argv else "lister").lower()
    if action in ("-h", "--help", "aide"):
        print(__doc__)
        return 0
    # Deux files distinctes : ce qui attend un accord, et ce qui a rendu. Un
    # numéro ne vaut que dans sa propre liste.
    if action in ("reponses", "reponse", "lire", "corriger"):
        docs = reponses_rendues()
        if action in ("reponses", "reponse"):
            lister_reponses(docs)
            return 0
        if len(argv) < 2:
            sys.exit(f"usage : autorisations.py {action} <ref>"
                     + ("" if action == "lire" else " \"ce qui doit changer\""))
        nom, f = choisir(docs, argv[1])
        if action == "lire":
            lire(nom, f)
            return 0
        remarque = " ".join(argv[2:]).strip()
        if not remarque:
            sys.exit("une correction écrite est obligatoire : elle sert de consigne à la reprise")
        corriger(nom, f, remarque)
        return 0

    docs = en_attente()
    if action in ("lister", "liste"):
        lister(docs)
        return 0
    if action not in ("voir", "accorder", "refuser"):
        sys.exit(f"action inconnue : {action} (voir --help)")
    if len(argv) < 2:
        sys.exit(f"usage : autorisations.py {action} <ref>"
                 + ("" if action == "voir" else " \"réponse\""))
    nom, f = choisir(docs, argv[1])
    if action == "voir":
        voir(nom, f)
        return 0
    reponse = " ".join(argv[2:]).strip()
    if not reponse:
        sys.exit("une réponse écrite est obligatoire : elle sert de consigne à la reprise")
    repondre(nom, f, action == "accorder", reponse)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
