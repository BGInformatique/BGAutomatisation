#!/usr/bin/env python3
"""Où en est la file BGFoods : combien faites, en attente, en échec."""
import collections

import lanceur

q = {"structuredQuery": {"from": [{"collectionId": "bgfoods"}], "limit": 200}}
compte = collections.Counter()
faites, cout = [], 0.0
for ligne in lanceur.api(f"{lanceur.BASE}/users/{lanceur.UID}:runQuery", q):
    d = ligne.get("document")
    if not d:
        continue
    nom = d["name"].rsplit("/", 1)[-1]
    if not nom.startswith("lancement-"):
        continue
    f = {k: lanceur.decoder(v) for k, v in d.get("fields", {}).items()}
    statut = f.get("statut") or "?"
    compte[statut] += 1
    if statut == "fait":
        lignes = len([l for l in (f.get("resultat") or "").splitlines() if l.strip()])
        faites.append((f.get("epicerie"), lignes, f.get("coutUsd") or 0))
        cout += f.get("coutUsd") or 0

for statut, n in compte.most_common():
    print(f"  {statut:<10} {n}")
print(f"\n{len(faites)} circulaire(s) lue(s) :")
for e, n, c in faites:
    print(f"   {str(e)[:30]:<30} {n:>3} lignes   {c:.2f} $ US de jetons")
print(f"\nvaleur en jetons cumulée : {cout:.2f} $ US")
