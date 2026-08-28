#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sante_facebook.py — état du montage de publication Facebook, en un coup d'œil.

Ne publie rien, ne modifie rien. Répond à quatre questions :

  1. Le jeton existe-t-il, et vit-il encore ? Jusqu'à quand ?
  2. La Page répond-elle, et l'app a-t-elle le droit d'y écrire ?
  3. Que dit la file : combien de textes restent, lequel est le prochain ?
  4. Quand la minuterie passera-t-elle, et qu'est-ce qui partira ?

    python3 sante_facebook.py

Sortie en clair, un verdict par ligne. Code de retour 0 si tout tient,
1 si quelque chose empêcherait la prochaine publication.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

ICI = os.path.dirname(os.path.abspath(__file__))
JETON = os.path.join(ICI, "facebook_jeton.json")
FILE_TSV = os.path.expanduser(
    "~/Bureau/{{ENTREPRISE}}/02_Marketing/Campagne_BG/Contenus/_File_Facebook.tsv")
GRAPH = "https://graph.facebook.com/v23.0"

OK, ALERTE, MORT = "✅", "⚠️ ", "❌"
problemes = []


def dire(marque, texte):
    print(f"  {marque} {texte}")
    if marque == MORT:
        problemes.append(texte)


def api(chemin, params):
    url = f"{GRAPH}/{chemin}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def duree_lisible(s):
    if s <= 0:
        return "expiré"
    j, h = s // 86400, (s % 86400) // 3600
    return f"{j} jour(s) {h} h" if j else f"{h} heure(s)"


# ─────────────────────────────── 1. le jeton
print("\n1. JETON")
cfg = None
if not os.path.exists(JETON):
    dire(MORT, f"absent : {os.path.basename(JETON)} — le publicateur est inerte")
    for reste in ("facebook_jeton.json.expire", "facebook_jeton.json.precedent"):
        if os.path.exists(os.path.join(ICI, reste)):
            dire(ALERTE, f"un ancien jeton traîne à côté : {reste}")
else:
    mode = oct(os.stat(JETON).st_mode)[-3:]
    dire(OK if mode == "600" else ALERTE, f"fichier présent, permissions {mode}")
    cfg = json.load(open(JETON, encoding="utf-8"))
    if not cfg.get("page_id") or not cfg.get("jeton"):
        dire(MORT, "fichier incomplet : il faut page_id ET jeton")
        cfg = None

if cfg:
    try:
        d = api("debug_token", {"input_token": cfg["jeton"],
                                "access_token": cfg["jeton"]}).get("data", {})
        if not d.get("is_valid"):
            dire(MORT, "jeton refusé par Facebook — à régénérer")
        else:
            exp = d.get("expires_at", None)
            if exp == 0:
                dire(OK, "n'expire pas — c'est l'état voulu")
            elif exp:
                reste = exp - int(time.time())
                quand = datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M")
                dire(MORT if reste <= 0 else ALERTE,
                     f"expire le {quand} — dans {duree_lisible(reste)}. "
                     "Un jeton de Page perpétuel vient d'un jeton d'utilisateur "
                     "PROLONGÉ au Débogueur.")
            portee = set(d.get("scopes", []))
            manque = {"pages_manage_posts", "pages_read_engagement"} - portee
            dire(MORT if manque else OK,
                 f"permissions manquantes : {', '.join(sorted(manque))}"
                 if manque else "permissions de publication présentes")
    except urllib.error.HTTPError as e:
        dire(MORT, f"Facebook refuse le jeton ({e.code}) — à régénérer")
    except urllib.error.URLError as e:
        dire(ALERTE, f"pas de réseau : {e.reason}")

# ─────────────────────────────── 2. la Page
print("\n2. PAGE")
if not cfg:
    dire(ALERTE, "non vérifiable sans jeton")
else:
    try:
        p = api(cfg["page_id"], {"fields": "id,name,fan_count",
                                 "access_token": cfg["jeton"]})
        dire(OK, f"{p.get('name')} — {p['id']}"
                 + (f", {p['fan_count']} abonné(s)" if "fan_count" in p else ""))
    except urllib.error.HTTPError as e:
        dire(MORT, f"la Page ne répond pas ({e.code})")
    except urllib.error.URLError:
        dire(ALERTE, "pas de réseau")

# ─────────────────────────────── 3. la file
print("\n3. FILE")
if not os.path.exists(FILE_TSV):
    dire(ALERTE, "aucune file — elle se crée au premier passage")
else:
    lignes = [l for l in open(FILE_TSV, encoding="utf-8").read().splitlines() if l.strip()]
    entetes = lignes[0].split("\t")
    rangs = [dict(zip(entetes, l.split("\t") + [""] * len(entetes))) for l in lignes[1:]]
    comptes = {}
    for r in rangs:
        comptes[r["STATUT"]] = comptes.get(r["STATUT"], 0) + 1
    dire(OK, f"{len(rangs)} textes — " + ", ".join(f"{n} {s}" for s, n in sorted(comptes.items())))

    suivant = next((r for r in rangs if r["STATUT"] == "a_publier"), None)
    if suivant:
        dire(OK, f"prochain : {suivant['ID']} — {suivant['TITRE']}")
    else:
        dire(ALERTE, "lot épuisé — écrire les sections ## 11+ du markdown")

    derniere = max((r["PUBLIE_LE"] for r in rangs if r.get("PUBLIE_LE")), default="")
    if derniere:
        ecart = (date.today() - date.fromisoformat(derniere)).days
        dire(OK if ecart >= 3 else ALERTE,
             f"dernière publication le {derniere} ({ecart} j) — "
             + ("la règle des 3 jours laisse passer" if ecart >= 3
                else "la règle des 3 jours BLOQUE le prochain passage"))
    else:
        dire(OK, "rien n'a encore été publié par le script")
        dire(ALERTE, "il ne voit pas les billets publiés à la main sur la Page")

# ─────────────────────────────── 4. la minuterie
print("\n4. MINUTERIE")
r = subprocess.run(["systemctl", "--user", "list-timers", "bg-publicateur.timer",
                    "--all", "--no-pager"], capture_output=True, text=True)
ligne = next((l for l in r.stdout.splitlines() if "bg-publicateur" in l), "")
etat = subprocess.run(["systemctl", "--user", "is-enabled", "bg-publicateur.timer"],
                      capture_output=True, text=True).stdout.strip()
dire(OK if etat == "enabled" else ALERTE, f"minuterie {etat or 'inconnue'}")
if ligne:
    dire(OK, "prochain passage : " + " ".join(ligne.split()[:5]))

# ─────────────────────────────── verdict
print("\n" + "─" * 60)
if problemes:
    print(f"{MORT} {len(problemes)} problème(s) empêchent la prochaine publication :")
    for p in problemes:
        print(f"     · {p}")
    sys.exit(1)
print(f"{OK} Le montage tient. La prochaine publication partira.")
sys.exit(0)
