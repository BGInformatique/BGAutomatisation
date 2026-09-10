#!/usr/bin/env python3
"""Configuration du jeton Instagram — CLI interactive ou import.

Ce chemin est celui de « Instagram API avec connexion Instagram » (pas
l'ancien Facebook Login for Business) : le jeton généré à l'écran « Generate
access tokens » est COURT — on l'échange contre un jeton longue durée (60
jours) via graph.instagram.com, on retrouve l'identifiant du compte, et on
écrit instagram_jeton.json avec la date d'expiration. Rien n'est envoyé
ailleurs qu'à graph.instagram.com.

`echanger_jeton()` et `ecrire_jeton()` sont des fonctions pures (pas de
input()/print()) réutilisées par installer.py pour le même flux depuis un
formulaire web.

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


def echanger_jeton(jeton_court, app_secret=None, deja_long=False):
    """Échange un jeton court Instagram contre un jeton longue durée.

    Fonction pure : ne lit ni n'écrit rien sur disque, ne fait aucun
    print(). `deja_long=True` saute l'échange (le jeton collé est déjà une
    version longue durée). Retourne :
      - {"ok": True, "user_id", "username", "jeton", "expire_le",
         "avertissement"} (avertissement non vide si /me renvoie un autre
         compte que {{HANDLE}}) ;
      - {"ok": False, "erreur": "..."} sur tout échec.
    """
    if not jeton_court:
        return {"ok": False, "erreur": "jeton court requis"}

    if deja_long:
        long_jeton, expire_dans = jeton_court, 60 * 86400
    else:
        if not app_secret:
            return {"ok": False, "erreur": "App secret requis (ou cocher « jeton déjà longue durée »)"}
        url = (f"{GRAPH}/access_token?grant_type=ig_exchange_token"
               f"&client_secret={urllib.parse.quote(app_secret)}"
               f"&access_token={urllib.parse.quote(jeton_court)}")
        try:
            rep = appel(url)
        except Exception as e:
            return {"ok": False, "erreur": (
                f"Échange refusé : {e!r} — si le jeton collé est déjà une "
                "version longue durée, cocher « jeton déjà longue durée »."
            )}
        long_jeton = rep["access_token"]
        expire_dans = rep.get("expires_in", 60 * 86400)

    try:
        moi = appel(f"{GRAPH}/me?fields=user_id,username&access_token="
                    f"{urllib.parse.quote(long_jeton)}")
    except Exception as e:
        return {"ok": False, "erreur": f"Jeton obtenu, mais impossible de lire le compte (/me) : {e!r}"}

    avertissement = ""
    if moi.get("username") and moi["username"] != "{{HANDLE}}":
        avertissement = (f"/me renvoie le compte @{moi['username']}, pas @{{HANDLE}} "
                          "— vérifier lequel a été connecté à l'étape « Add account ».")

    expire_le = (date.today() + timedelta(seconds=expire_dans)).isoformat()
    return {
        "ok": True,
        "user_id": str(moi["user_id"]),
        "username": moi.get("username", "?"),
        "jeton": long_jeton,
        "expire_le": expire_le,
        "avertissement": avertissement,
    }


def ecrire_jeton(ig_user_id, jeton, expire_le):
    """Écrit instagram_jeton.json (600). Fonction pure côté disque, aucun print()."""
    cfg = {"ig_user_id": ig_user_id, "jeton": jeton, "expire_le": expire_le}
    with open(JETON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(JETON, 0o600)
    return JETON


def main():
    deja_long = "--deja-long" in sys.argv
    print("Configuration du jeton Instagram de {{ENTREPRISE}} (@{{HANDLE}}).\n")

    court = getpass.getpass(
        "Jeton généré à l'écran « Generate access tokens » (invisible en tapant) : ").strip()
    if not court:
        print("Rien de collé — annulé.")
        return 1

    secret = None
    if not deja_long:
        secret = getpass.getpass(
            "App secret de l'app « Publicateur {{ENTREPRISE}} » (App settings → Basic → "
            "App secret, invisible en tapant) : ").strip()
        if not secret:
            print("Rien de collé — annulé.")
            return 1

    resultat = echanger_jeton(court, secret, deja_long)
    if not resultat["ok"]:
        print(f"\n{resultat['erreur']}")
        return 1

    if resultat["avertissement"]:
        print(f"\nATTENTION : {resultat['avertissement']}")

    chemin = ecrire_jeton(resultat["user_id"], resultat["jeton"], resultat["expire_le"])
    print(f"\nÉcrit : {chemin}")
    print(f"Compte : @{resultat['username']} (id {resultat['user_id']})")
    print(f"Jeton valide jusqu'au {resultat['expire_le']} — renouveler_instagram.py le "
          "renouvellera avant l'échéance une fois la minuterie armée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
