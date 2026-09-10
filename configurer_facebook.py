#!/usr/bin/env python3
"""Configuration du jeton de Page Facebook — CLI interactive ou import.

Frère de configurer_instagram.py, même logique : coller un jeton COURT
(depuis le Graph API Explorer, avec pages_manage_posts et
pages_read_engagement), échanger contre un jeton UTILISATEUR longue durée,
retrouver le jeton de PAGE qui n'expire jamais via GET /me/accounts, et
écrire facebook_jeton.json (600). Rien n'est envoyé ailleurs qu'à
graph.facebook.com.

`echanger_jeton_page()` et `ecrire_jeton()` sont des fonctions pures (pas de
input()/print()) réutilisées par installer.py pour le même flux depuis un
formulaire web — la logique d'appel à l'API Graph ne vit qu'ici, à un seul
endroit.

Ce qu'il faut avant de lancer ce script en CLI :
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


def echanger_jeton_page(jeton_court, app_id, app_secret, page_id_preselection=None):
    """Échange un jeton court contre le jeton de Page qui n'expire pas.

    Fonction pure : ne lit ni n'écrit rien sur disque, ne fait aucun
    print(). Retourne un dict :
      - {"ok": True, "page_id", "page_name", "jeton"} si une Page a pu être
        choisie sans ambiguïté (présélection trouvée, ou une seule Page
        reçue) ;
      - {"ok": False, "ambigu": True, "pages": [{"id","name","jeton"}...]}
        si plusieurs Pages sont reçues sans présélection qui matche —
        charge à l'appelant de faire choisir laquelle (voir choisir_page()) ;
      - {"ok": False, "erreur": "..."} sur tout échec (réseau, jeton
        refusé, aucune Page).
    """
    if not jeton_court or not app_id or not app_secret:
        return {"ok": False, "erreur": "jeton court, App ID et App secret sont tous requis"}

    url = (f"{GRAPH}/oauth/access_token?grant_type=fb_exchange_token"
           f"&client_id={urllib.parse.quote(app_id)}"
           f"&client_secret={urllib.parse.quote(app_secret)}"
           f"&fb_exchange_token={urllib.parse.quote(jeton_court)}")
    try:
        rep = appel(url)
        long_jeton = rep["access_token"]
    except Exception as e:
        return {"ok": False, "erreur": f"Échange refusé : {e!r}"}

    try:
        comptes = appel(f"{GRAPH}/me/accounts?access_token={urllib.parse.quote(long_jeton)}")
    except Exception as e:
        return {"ok": False, "erreur": f"Jeton utilisateur obtenu, mais /me/accounts a échoué : {e!r}"}

    pages = comptes.get("data", [])
    if not pages:
        return {"ok": False, "erreur": (
            "/me/accounts n'a retourné aucune Page — le compte utilisé à "
            "l'étape « Get User Access Token » gère-t-il bien votre Page ?"
        )}

    page = next((p for p in pages if p.get("id") == page_id_preselection), None) if page_id_preselection else None
    if page:
        return {"ok": True, "page_id": page["id"], "page_name": page.get("name", ""), "jeton": page["access_token"]}
    if len(pages) == 1:
        page = pages[0]
        return {"ok": True, "page_id": page["id"], "page_name": page.get("name", ""), "jeton": page["access_token"]}

    return {"ok": False, "ambigu": True, "pages": [
        {"id": p["id"], "name": p.get("name", ""), "jeton": p["access_token"]} for p in pages
    ]}


def ecrire_jeton(page_id, jeton):
    """Écrit facebook_jeton.json (600). Fonction pure côté disque, aucun print()."""
    cfg = {"page_id": page_id, "jeton": jeton}
    with open(JETON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(JETON, 0o600)
    return JETON


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

    resultat = echanger_jeton_page(court, app_id, secret, PAGE_ID_CONNU)

    if resultat.get("ambigu"):
        print("\nATTENTION : votre Page n'a pas été présélectionnée "
              f"(id attendu : {PAGE_ID_CONNU}). Pages reçues :")
        for p in resultat["pages"]:
            print(f"  - {p['name']} (id {p['id']})")
        print("Rien n'a été écrit — relancez après avoir confirmé le bon "
              "compte à l'étape « Get User Access Token », ou réglez "
              "PAGE_ID_CONNU sur l'id voulu ci-dessus.")
        return 1

    if not resultat["ok"]:
        print(f"\n{resultat['erreur']}")
        return 1

    chemin = ecrire_jeton(resultat["page_id"], resultat["jeton"])
    print(f"\nÉcrit : {chemin}")
    print(f"Page : {resultat['page_name']} (id {resultat['page_id']})")
    print("Ce jeton de Page n'expire pas (obtenu depuis un jeton utilisateur "
          "longue durée) — rien à renouveler.")
    print("\nVérifiez maintenant : python3 publicateur.py --essai")
    return 0


if __name__ == "__main__":
    sys.exit(main())
