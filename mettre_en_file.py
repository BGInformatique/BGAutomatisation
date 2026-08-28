#!/usr/bin/env python3
"""Met en file les circulaires des Laurentides pour le lanceur.

Lit /tmp/lancements.json (produit par la résolution des adresses) et dépose une
demande par circulaire dans users/<uid>/bgfoods/. Le lanceur les traite dans
l'ordre des `demandeLe`, une à la fois.

Les très grosses circulaires sont coupées : au-delà de MAX_PAGES, une seule
tâche risquerait le délai. Chaque morceau devient alors sa propre circulaire
dans l'outil — c'est le prix à payer, et le titre le dit.
"""
import json
import sys
import time

import lanceur

MAX_PAGES = 26
FICHIER = "/tmp/lancements.json"

circulaires = json.load(open(FICHIER, encoding="utf-8"))
base_ts = int(time.time() * 1000)
demandes, pages_total, rang = [], 0, 0

for c in circulaires:
    urls = c["urls"]
    morceaux = [urls] if len(urls) <= MAX_PAGES else [
        urls[i:i + MAX_PAGES] for i in range(0, len(urls), MAX_PAGES)
    ]
    for n, morceau in enumerate(morceaux, start=1):
        suffixe = f" — partie {n} sur {len(morceaux)}" if len(morceaux) > 1 else ""
        dates = (f" (valide du {c['debut']} au {c['fin']})" if c["debut"] else "")
        demandes.append({
            "outil": "BGFoods",
            "statut": "demande",
            "slug": c["slug"],
            "epicerie": c["epicerie"] + suffixe,
            "debut": c["debut"], "fin": c["fin"],
            "titre": f"Lire les {len(morceau)} pages de la circulaire {c['epicerie']}"
                     + suffixe + dates,
            "detail": "\n".join(morceau),
            # Un rang par demande : le lanceur trie là-dessus, donc l'ordre du
            # fichier (les grandes bannières d'abord) est respecté.
            "demandeLe": base_ts + rang,
            "maj": base_ts + rang,
        })
        rang += 1
        pages_total += len(morceau)

print(f"{len(demandes)} demande(s), {pages_total} pages\n")
for d in demandes:
    print(f"  {d['epicerie'][:34]:<34} {len(d['detail'].splitlines()):>3} pages")

if "--vraiment" not in sys.argv:
    print("\n(essai à blanc — relancer avec --vraiment pour déposer)")
    sys.exit(0)

for i, d in enumerate(demandes):
    nom = f"lancement-{d['demandeLe']}-{d['slug'][:12]}-{i}"
    lanceur.api(
        f"{lanceur.BASE}/{lanceur.parent('bgfoods')}?documentId={nom}",
        {"fields": {k: lanceur.encoder(v) for k, v in d.items()}},
    )
    print(f"déposée : {nom}")
print(f"\n{len(demandes)} demande(s) en file.")
