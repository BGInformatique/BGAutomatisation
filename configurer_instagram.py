#!/usr/bin/env python3
"""Configuration interactive du jeton Instagram — à lancer UNE fois, à la main.

Ce chemin est celui de « Instagram API avec connexion Instagram » (pas
l'ancien Facebook Login for Business) : le jeton généré à l'écran « Generate
access tokens » est COURT — ce script l'échange contre un jeton longue durée
(60 jours) via graph.instagram.com, retrouve l'identifiant du compte, et
écrit instagram_jeton.json avec la date d'expiration. Rien n'est envoyé
ailleurs qu'à graph.instagram.com.

Le jeton longue durée EXPIRE après 60 jours et doit être renouvelé — voir
renouveler_instagram.py, qui s'en charge tout seul avant l'échéance.

Lancer avec `!` (session interactive), pas via un appel non interactif :
    python3 configurer_instagram.py
"""
import getpass
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

ICI = os.path.dirname(os.path.abspath(__file__))
JETON = os.path.join(ICI, "instagram_jeton.json")
GRAPH = "https://graph.instagram.com"


def appel(url):
    with urllib.request.urlopen(url, timeout=30) as rep:
        return json.loads(rep.read())


def main():
    deja_long = "--deja-long" in sys.argv
    print("Configuration du jeton Instagram de {{ENTREPRISE}} (@{{HANDLE}}).\n")

    court = getpass.getpass(
        "Jeton généré à l'écran « Generate access tokens » (invisible en tapant) : ").strip()
    if not court:
        print("Rien de collé — annulé.")
        return 1

    if deja_long:
        long_jeton, expire_dans = court, 60 * 86400
    else:
        secret = getpass.getpass(
            "App secret de l'app « Publicateur {{ENTREPRISE}} » (App settings → Basic → "
            "App secret, invisible en tapant) : ").strip()
        if not secret:
            print("Rien de collé — annulé.")
            return 1
        url = (f"{GRAPH}/access_token?grant_type=ig_exchange_token"
               f"&client_secret={urllib.parse.quote(secret)}"
               f"&access_token={urllib.parse.quote(court)}")
        try:
            rep = appel(url)
        except Exception as e:
            print(f"\nÉchange refusé : {e!r}\n"
                  "Si le jeton collé est déjà une version longue durée, relancer avec "
                  "--deja-long pour sauter cette étape.")
            return 1
        long_jeton = rep["access_token"]
        expire_dans = rep.get("expires_in", 60 * 86400)

    try:
        moi = appel(f"{GRAPH}/me?fields=user_id,username&access_token="
                    f"{urllib.parse.quote(long_jeton)}")
    except Exception as e:
        print(f"\nJeton obtenu, mais impossible de lire le compte (/me) : {e!r}")
        return 1

    if moi.get("username") and moi["username"] != "{{HANDLE}}":
        print(f"\nATTENTION : /me renvoie le compte @{moi['username']}, "
              "pas @{{HANDLE}} — vérifier lequel a été connecté à l'étape "
              "« Add account » avant de continuer.")

    expire_le = (date.today() + timedelta(seconds=expire_dans)).isoformat()
    cfg = {"ig_user_id": str(moi["user_id"]), "jeton": long_jeton, "expire_le": expire_le}
    with open(JETON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(JETON, 0o600)

    print(f"\nÉcrit : {JETON}")
    print(f"Compte : @{moi.get('username', '?')} (id {moi['user_id']})")
    print(f"Jeton valide jusqu'au {expire_le} — renouveler_instagram.py le renouvellera "
          "avant l'échéance une fois la minuterie armée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
