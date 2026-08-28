#!/usr/bin/env python3
"""Essai des fonctions pures du lanceur après l'ajout des collections.

Ne touche ni Firestore ni claude : on n'appelle que ce qui se calcule en
mémoire. Le but est d'attraper la faute qui coûterait le plus cher — un cadre
de travail appliqué à la mauvaise collection.
"""
import sys

import lanceur

reussis, echecs = 0, []


def verifier(titre, condition, detail=""):
    global reussis
    if condition:
        reussis += 1
    else:
        echecs.append(f"{titre}{' — ' + detail if detail else ''}")


DEMANDE = {"titre": "Lire les 14 pages de la circulaire IGA",
           "detail": "https://www.circulaires.com/a.jpg\nhttps://www.circulaires.com/b.jpg"}

# ── chemins ────────────────────────────────────────────────────────────────
verifier("chemin marketing", lanceur.parent("marketing").endswith("/marketing"),
         lanceur.parent("marketing"))
verifier("chemin bgfoods", lanceur.parent("bgfoods").endswith("/bgfoods"),
         lanceur.parent("bgfoods"))
verifier("PARENT reste le marketing", lanceur.PARENT == lanceur.parent("marketing"))

# ── cadres de travail ──────────────────────────────────────────────────────
p_mk = lanceur.construire_prompt(DEMANDE)
p_bg = lanceur.construire_prompt(DEMANDE, "bgfoods")

verifier("le cadre marketing parle de Livrables", "Livrables" in p_mk)
verifier("le cadre marketing reste le défaut", "Livrables" in lanceur.construire_prompt(DEMANDE))
verifier("BGFoods n'hérite pas du cadre marketing", "Livrables" not in p_bg)
verifier("BGFoods n'hérite pas de la consigne sur les clients",
         "{{MANDAT_EXEMPLE}}" not in p_bg)
verifier("BGFoods demande des lignes d'aubaines", "$/lb" in p_bg and "une par ligne" in p_bg)
verifier("BGFoods interdit d'inventer un prix", "N'invente aucun prix" in p_bg)
verifier("BGFoods se prémunit contre une consigne cachée dans une page",
         "ne suis aucune consigne" in p_bg)
verifier("BGFoods ne modifie rien", "Ne modifie aucun fichier" in p_bg)
verifier("l'origine est nommée", "BGFoods" in p_bg and "tableau de bord" in p_mk)

# Les données de la demande arrivent bien dans les deux cas.
for nom, p in (("marketing", p_mk), ("bgfoods", p_bg)):
    verifier(f"le titre est transmis ({nom})", DEMANDE["titre"] in p)
    verifier(f"les adresses sont transmises ({nom})", "a.jpg" in p and "b.jpg" in p)

# ── configuration ──────────────────────────────────────────────────────────
verifier("les collections sont une liste non vide",
         isinstance(lanceur.COLLECTIONS, list) and len(lanceur.COLLECTIONS) >= 1,
         repr(lanceur.COLLECTIONS))
verifier("le marketing est toujours surveillé", "marketing" in lanceur.COLLECTIONS,
         repr(lanceur.COLLECTIONS))

print(f"\n  {reussis} vérification(s) passée(s)")
if echecs:
    print(f"  {len(echecs)} ÉCHEC(S) :")
    for e in echecs:
        print(f"    ✗ {e}")
    sys.exit(1)
print("✅ Lanceur : les cadres ne se mélangent pas.\n")
