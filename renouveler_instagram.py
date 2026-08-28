#!/usr/bin/env python3
"""Renouvellement automatique du jeton Instagram — lancé par la minuterie.

Un jeton longue durée graph.instagram.com expire après 60 jours. Meta permet
de le renouveler (encore valide, pas encore expiré) pour 60 jours de plus,
sans repasser par « Add account » ni par configurer_instagram.py. Ce script
renouvelle dès qu'il reste moins de MARGE_JOURS avant l'échéance — largement
avant que publicateur_instagram.py ne bloque par prudence.

Ne fait rien si instagram_jeton.json n'existe pas, ou si l'échéance est
encore loin. S'il reste moins de MARGE_JOURS mais que le renouvellement
échoue (jeton déjà expiré, par exemple), c'est journalisé : à ce stade il
faut repasser par configurer_instagram.py à la main.

    python3 renouveler_instagram.py --essai   # dit ce qui se passerait
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import journaliser  # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))
JETON = os.path.join(ICI, "instagram_jeton.json")
GRAPH = "https://graph.instagram.com"
MARGE_JOURS = 10
ESSAI = "--essai" in sys.argv


def main():
    if not os.path.exists(JETON):
        return 0
    cfg = json.load(open(JETON, encoding="utf-8"))
    ig_user_id, jeton, expire_le = cfg.get("ig_user_id", ""), cfg.get("jeton", ""), cfg.get("expire_le", "")
    if not ig_user_id or not jeton or not expire_le:
        journaliser("renouveler_instagram : instagram_jeton.json incomplet — abandon")
        return 1

    jours_restants = (date.fromisoformat(expire_le) - date.today()).days
    if jours_restants > MARGE_JOURS:
        if ESSAI:
            print(f"encore {jours_restants} jour(s) avant échéance ({expire_le}) — rien à faire.")
        return 0

    url = (f"{GRAPH}/refresh_access_token?grant_type=ig_refresh_token"
           f"&access_token={urllib.parse.quote(jeton)}")
    if ESSAI:
        print(f"renouvellerait maintenant — échéance actuelle {expire_le} "
              f"({jours_restants} jour(s) restants).")
        return 0

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as rep:
            reponse = json.loads(rep.read())
    except Exception as e:
        journaliser(f"renouveler_instagram : échec du renouvellement : {e!r} — "
                    "repasser par configurer_instagram.py si le jeton est expiré")
        return 1

    cfg["jeton"] = reponse["access_token"]
    cfg["expire_le"] = (date.today() + timedelta(seconds=reponse.get("expires_in", 60 * 86400))).isoformat()
    with open(JETON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(JETON, 0o600)
    journaliser(f"renouveler_instagram : jeton renouvelé, valide jusqu'au {cfg['expire_le']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
