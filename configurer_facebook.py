#!/usr/bin/env python3
"""Configuration interactive du jeton de Page Facebook — à lancer UNE fois, à la main.

Frère de configurer_instagram.py, même logique : coller un jeton COURT
(depuis le Graph API Explorer, avec pages_manage_posts et
pages_read_engagement), ce script l'échange contre un jeton UTILISATEUR
longue durée, puis retrouve le jeton de PAGE qui n'expire jamais via
GET /me/accounts, et écrit facebook_jeton.json (600). Rien n'est envoyé
ailleurs qu'à graph.facebook.com.

Ce qu'il faut avant de lancer ce script :
  - le jeton court (Graph API Explorer, app « {{APP_FACEBOOK}} », « Get User
    Access Token », permissions pages_manage_posts + pages_read_engagement) ;
  - l'App ID et l'App secret de « {{APP_FACEBOOK}} »
    (developers.facebook.com -> l'app -> Settings -> Basic, champs
    « App ID » et « App secret »).

Lancer avec `!` (session interactive), pas via un appel non interactif :
    python3 configurer_facebook.py
"""
import getpass
import json
import os
import sys
import urllib.parse
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
JETON = os.path.join(ICI, "facebook_jeton.json")
GRAPH = "https://graph.facebook.com/v23.0"
PAGE_ID_CONNU = "{{PAGE_ID_FACEBOOK}}"  # présélectionne votre Page dans la liste — facultatif, voir plus bas


def appel(url):
    with urllib.request.urlopen(url, timeout=30) as rep:
        return json.loads(rep.read())


def main():
    print("Configuration du jeton de Page Facebook — {{ENTREPRISE}}.\n")

    court = getpass.getpass(
        "Jeton COURT du Graph API Explorer (masqué à la saisie) : ").strip()
    if not court:
        print("Rien de collé — annulé.")
        return 1

    app_id = input("App ID de « {{APP_FACEBOOK}} » : ").strip()
    if not app_id:
        print("Rien de saisi — annulé.")
        return 1

    secret = getpass.getpass(
        "App secret de « {{APP_FACEBOOK}} » (Settings -> Basic -> champ "
        "« App secret », masqué à la saisie) : ").strip()
    if not secret:
        print("Rien de collé — annulé.")
        return 1

    url = (f"{GRAPH}/oauth/access_token?grant_type=fb_exchange_token"
           f"&client_id={urllib.parse.quote(app_id)}"
           f"&client_secret={urllib.parse.quote(secret)}"
           f"&fb_exchange_token={urllib.parse.quote(court)}")
    try:
        rep = appel(url)
    except Exception as e:
        print(f"\nÉchange refusé : {e!r}")
        return 1
    long_jeton = rep["access_token"]

    try:
        comptes = appel(f"{GRAPH}/me/accounts?access_token={urllib.parse.quote(long_jeton)}")
    except Exception as e:
        print(f"\nJeton utilisateur obtenu, mais /me/accounts a échoué : {e!r}")
        return 1

    pages = comptes.get("data", [])
    if not pages:
        print("\n/me/accounts n'a retourné aucune Page — le compte utilisé à "
              "l'étape « Get User Access Token » gère-t-il bien votre Page ?")
        return 1

    # Si PAGE_ID_CONNU n'est pas renseigné (jeton laissé tel quel), aucune Page
    # ne matche jamais — on tombe simplement dans la branche « non trouvée »
    # ci-dessous, qui liste les Pages reçues pour que vous pointiez la bonne.
    page = next((p for p in pages if p.get("id") == PAGE_ID_CONNU), None)
    if not page:
        print("\nATTENTION : votre Page n'a pas été présélectionnée "
              f"(id attendu : {PAGE_ID_CONNU}). Pages reçues :")
        for p in pages:
            print(f"  - {p.get('name')} (id {p.get('id')})")
        if len(pages) == 1:
            page = pages[0]
            print(f"\nUne seule Page reçue — on la prend : {page.get('name')}.")
        else:
            print("Rien n'a été écrit — relancez après avoir confirmé le bon "
                  "compte à l'étape « Get User Access Token », ou réglez "
                  "PAGE_ID_CONNU sur l'id voulu ci-dessus.")
            return 1

    cfg = {"page_id": page["id"], "jeton": page["access_token"]}
    with open(JETON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(JETON, 0o600)

    print(f"\nÉcrit : {JETON}")
    print(f"Page : {page.get('name')} (id {page['id']})")
    print("Ce jeton de Page n'expire pas (obtenu depuis un jeton utilisateur "
          "longue durée) — rien à renouveler.")
    print("\nVérifiez maintenant : python3 publicateur.py --essai")
    return 0


if __name__ == "__main__":
    sys.exit(main())
