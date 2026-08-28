#!/usr/bin/env python3
"""Pont Espace client — entre le projet des clients et les outils internes.

Les clients écrivent leurs demandes dans le projet Firebase de l'espace client
(collection racine « demandes »). Le propriétaire, lui, travaille dans le
projet des outils internes. Ce pont fait passer l'information d'un bord à
l'autre, dans les deux sens :

    projet CLIENTS                        projet INTERNE
    demandes/<id>          ──miroir──▶    users/<uid>/clientsweb/state
    demandes/<id>          ◀──état───     users/<uid>/clientsweb/signal-*
    demandes/<id>          ◀──état───     users/<uid>/clientsweb/lancement-*
    fiches/<uid client>    ──miroir──▶    users/<uid>/clientsweb/fiches
    fiches/<uid client>    ◀─verrou──     users/<uid>/clientsweb/signal-fiche-*
    fiches/<uid client>    ◀─activation─  users/<uid>/clientsweb/signal-fiche-*

UNE FICHE APPROUVÉE N'EST PAS UNE FICHE VERROUILLÉE. « approuvee » ouvre
l'accès du client aux demandes de modification (firestore.rules de l'espace
client le vérifie par get() à chaque création) ; « verrouillee » ferme la
fiche elle-même une fois le site monté. Le propriétaire les bascule
indépendamment depuis l'outil web « Espace client » (un autre chantier, non
inclus ici) — les deux voyagent dans le même document
signal-fiche-<uid>, déposé avec merge:true côté outil interne.

UNE FICHE N'EST PAS UNE DEMANDE. Les fiches d'installation (nom de
l'entreprise, domaine, compte GitHub à inviter) sont de l'information à lire,
jamais du travail à lancer : elles vivent dans leur propre document miroir, et
aucun éclair ne s'y attache. Le lanceur ne ramasse que des « lancement-* ».

POURQUOI UN PONT PLUTÔT QU'UNE RÈGLE INTER-UTILISATEURS. La vue du
propriétaire reste une lecture « users/<son-uid>/… », c'est-à-dire la règle
déjà éprouvée par TimeCalculator et le marketing. Aucun fichier de règles n'a
besoin de connaître une identité d'administrateur, donc aucune règle ne peut
verrouiller le propriétaire hors de ses propres données. Les comptes clients,
eux, n'existent tout simplement pas dans le projet interne.

LE DOSSIER DE TRAVAIL NE VIENT JAMAIS DU WEB. La table clients-web.json, sur
cette machine, relie un compte client à un nom de dossier sous
WebsiteMaestro/SitesWebClient/. Un client dont le compte n'y figure pas voit sa
demande arriver dans l'outil, marquée « non reliée » : elle est lisible, elle
n'est pas lançable. Une page web ne désigne pas le dépôt sur lequel la machine
va travailler.

CE QUI REMONTE AU CLIENT EST ÉCRIT ICI, PAS RECOPIÉ. La sortie de Claude peut
contenir des chemins de fichiers, des noms de dépôts, des notes de travail :
elle ne part jamais telle quelle vers un client. Le pont traduit un statut de
lancement en une phrase fixe ; le seul texte libre qu'un client reçoit est
celui que le propriétaire a écrit lui-même dans l'outil.

Aucune dépendance hors bibliothèque standard ; la signature RS256 passe par
openssl, comme lanceur.py.

Usage :
    python3 pont_clients.py            # boucle, un cycle par intervalle
    python3 pont_clients.py --une-fois # un seul cycle, puis sortie
    python3 pont_clients.py --essai    # montre ce qui changerait, n'écrit rien
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

CONFIG = os.path.expanduser("~/.config/bg-lanceur/clients-web.json")
JOURNAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal.log")

ESSAI = "--essai" in sys.argv
UNE_FOIS = "--une-fois" in sys.argv or ESSAI

cfg = json.load(open(CONFIG))
PROJET_CLIENTS = cfg["projet_clients"]
PROJET_INTERNE = cfg.get("projet_interne", "{{PROJET_FIREBASE}}")
CLE_CLIENTS = os.path.expanduser(cfg.get("cle_sa_clients",
                                         "~/.config/bg-lanceur/cle-sa-clients.json"))
CLE_INTERNE = os.path.expanduser(cfg.get("cle_sa_interne",
                                         "~/.config/bg-lanceur/cle-sa.json"))
UID = cfg["uid"]
COLLECTION = cfg.get("collection", "clientsweb")
RACINE_SITES = os.path.expanduser(cfg.get(
    "racine_sites",
    "~/Bureau/{{ENTREPRISE}}/04_Produits_Clients/WebsiteMaestro/SitesWebClient"))
# Cadence. Le pont interroge Firestore en boucle : chaque cycle coûte autant de
# LECTURES qu'il y a de demandes, plus celles du dossier interne. À 30 s et
# 30 demandes, on dépasse les 50 000 lectures/jour du palier gratuit avant midi.
# Cinq minutes suffisent largement — une demande n'est pas urgente à la seconde,
# et le propriétaire la traite à la main de toute façon.
INTERVALLE = cfg.get("intervalle", 300)
CLIENTS = cfg.get("clients", {})

BASE_CLIENTS = (f"https://firestore.googleapis.com/v1/projects/{PROJET_CLIENTS}"
                "/databases/(default)/documents")
BASE_INTERNE = (f"https://firestore.googleapis.com/v1/projects/{PROJET_INTERNE}"
                "/databases/(default)/documents")
PARENT = f"users/{UID}/{COLLECTION}"

# Ce qu'un client lit quand un lancement se termine. Des phrases, pas des
# codes, et surtout pas la sortie brute de Claude.
PHRASES = {
    "fait": "La modification a été appliquée et publiée sur votre site. "
            "Comptez une à deux minutes avant de la voir.",
    "echec": "Votre demande demande une intervention manuelle. "
             "{{ENTREPRISE}} s'en occupe et vous revient.",
    "attente_autorisation": "Votre demande est en cours de traitement et "
                            "attend une validation de {{ENTREPRISE}}.",
}


def journaliser(msg):
    ligne = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [pont] {msg}"
    print(ligne, flush=True)
    try:
        with open(JOURNAL, "a") as f:
            f.write(ligne + "\n")
    except OSError:
        pass


# ── jetons des deux comptes de service ──────────────────────────────────────
#
# Un cache par clé : les deux projets ont des identités distinctes et leurs
# jetons ne sont pas interchangeables. Mélanger les deux donnerait un 403
# intermittent, le plus pénible des symptômes.

_jetons = {}


def b64url(donnees):
    return base64.urlsafe_b64encode(donnees).rstrip(b"=").decode()


def jeton_acces(chemin_cle):
    cache = _jetons.get(chemin_cle)
    if cache and time.time() < cache["expire"] - 120:
        return cache["valeur"]
    sa = json.load(open(chemin_cle))
    maintenant = int(time.time())
    entete = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    corps = b64url(json.dumps({
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/datastore",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": maintenant, "exp": maintenant + 3600,
    }).encode())
    a_signer = f"{entete}.{corps}".encode()
    with tempfile.NamedTemporaryFile("w", suffix=".pem") as cle:
        cle.write(sa["private_key"])
        cle.flush()
        signature = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", cle.name],
            input=a_signer, capture_output=True, check=True).stdout
    jwt = f"{entete}.{corps}.{b64url(signature)}"
    donnees = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=donnees)
    with urllib.request.urlopen(req) as rep:
        r = json.load(rep)
    _jetons[chemin_cle] = {"valeur": r["access_token"],
                           "expire": time.time() + int(r.get("expires_in", 3600))}
    return _jetons[chemin_cle]["valeur"]


# ── Firestore REST ──────────────────────────────────────────────────────────

def api(url, cle, corps=None, methode=None):
    req = urllib.request.Request(
        url, method=methode or ("POST" if corps is not None else "GET"))
    req.add_header("Authorization", f"Bearer {jeton_acces(cle)}")
    donnees = None
    if corps is not None:
        req.add_header("Content-Type", "application/json")
        donnees = json.dumps(corps).encode()
    with urllib.request.urlopen(req, donnees) as rep:
        return json.loads(rep.read() or b"{}")


def decoder(v):
    if "stringValue" in v: return v["stringValue"]
    if "integerValue" in v: return int(v["integerValue"])
    if "doubleValue" in v: return v["doubleValue"]
    if "booleanValue" in v: return v["booleanValue"]
    if "timestampValue" in v: return v["timestampValue"]
    if "nullValue" in v: return None
    if "arrayValue" in v: return [decoder(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v: return {k: decoder(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return None


def encoder(v):
    if isinstance(v, bool): return {"booleanValue": v}
    if isinstance(v, int): return {"integerValue": str(v)}
    if isinstance(v, float): return {"doubleValue": v}
    if isinstance(v, str): return {"stringValue": v}
    if v is None: return {"nullValue": None}
    if isinstance(v, list): return {"arrayValue": {"values": [encoder(x) for x in v]}}
    if isinstance(v, dict): return {"mapValue": {"fields": {k: encoder(x) for k, x in v.items()}}}
    raise ValueError(type(v))


def lister(base, cle, chemin):
    """Tous les documents d'une collection, pages comprises."""
    docs, jeton_page = [], None
    while True:
        url = f"{base}/{chemin}?pageSize=300"
        if jeton_page:
            url += "&pageToken=" + urllib.parse.quote(jeton_page)
        try:
            rep = api(url, cle)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            raise
        for d in rep.get("documents", []):
            docs.append((d["name"].rsplit("/", 1)[-1],
                         {k: decoder(v) for k, v in d.get("fields", {}).items()}))
        jeton_page = rep.get("nextPageToken")
        if not jeton_page:
            return docs


def ecrire(base, cle, chemin, champs, fusion=True):
    if ESSAI:
        journaliser(f"[essai] écrirait {chemin} ← {list(champs)}")
        return
    if fusion:
        masque = "&".join(f"updateMask.fieldPaths={c}" for c in champs)
        api(f"{base}/{chemin}?{masque}",
            cle, {"fields": {k: encoder(v) for k, v in champs.items()}}, methode="PATCH")
    else:
        api(f"{base}/{chemin}", cle,
            {"fields": {k: encoder(v) for k, v in champs.items()}}, methode="PATCH")


def supprimer(base, cle, chemin):
    if ESSAI:
        journaliser(f"[essai] supprimerait {chemin}")
        return
    try:
        api(f"{base}/{chemin}", cle, methode="DELETE")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise


# ── correspondance client → dossier ─────────────────────────────────────────

def fiche_client(uid):
    """Nom et dossier de travail d'un compte client, d'après la table LOCALE.

    Renvoie None si le compte n'est pas déclaré : la demande reste visible
    dans l'outil, mais l'éclair y sera fermé. On ne devine jamais un dossier
    à partir de ce qu'un document raconte.
    """
    fiche = CLIENTS.get(uid)
    if not fiche or not fiche.get("nom"):
        return None
    dossier = os.path.join(RACINE_SITES, fiche["nom"])
    if not os.path.isdir(dossier):
        return None
    return {"nom": fiche["nom"], "dossier": dossier,
            "domaine": fiche.get("domaine", "")}


def horodatage_ms(valeur):
    """Un « creeLe » Firestore arrive en texte ISO ; l'outil web trie sur des ms."""
    if isinstance(valeur, (int, float)):
        return int(valeur)
    if isinstance(valeur, str) and valeur:
        try:
            propre = valeur.replace("Z", "+00:00")
            return int(time.mktime(time.strptime(propre[:19], "%Y-%m-%dT%H:%M:%S")) * 1000)
        except (ValueError, OverflowError):
            return 0
    return 0


# ── les trois sens du pont ──────────────────────────────────────────────────

_dernier_miroir = None


def miroir(demandes):
    """Recopie l'état des demandes clients dans le dossier du propriétaire.

    L'écriture n'a lieu que si quelque chose a changé. Sans cette garde, le
    pont écrirait un document identique toutes les cinq minutes — 288 écritures
    par jour pour rien, et un « updatedAt » qui bouge sans qu'aucune donnée
    n'ait bougé, ce qui rend le journal illisible quand on cherche QUAND une
    demande est arrivée.
    """
    global _dernier_miroir
    lignes = []
    for id_doc, d in demandes:
        fiche = fiche_client(d.get("clientUid", ""))
        lignes.append({
            "id": id_doc,
            "clientUid": d.get("clientUid", ""),
            "client": fiche["nom"] if fiche else (d.get("clientNom")
                                                 or d.get("clientCourriel") or ""),
            "clientCourriel": d.get("clientCourriel", ""),
            "type": d.get("type", ""),
            "urgence": d.get("urgence", ""),
            "page": d.get("page", ""),
            "description": d.get("description", ""),
            "statut": d.get("statut", "recue"),
            "creeLe": horodatage_ms(d.get("creeLe")),
            "depotConnu": bool(fiche),
        })
    lignes.sort(key=lambda x: x["creeLe"], reverse=True)
    if lignes != _dernier_miroir:
        ecrire(BASE_INTERNE, CLE_INTERNE, f"{PARENT}/state",
               {"demandes": lignes, "updatedAt": int(time.time() * 1000)})
        _dernier_miroir = lignes
        journaliser(f"miroir mis à jour ({len(lignes)} demande(s))")
    return lignes


_dernieres_fiches = None

# Les champs d'une fiche d'installation, dans l'ordre où on veut les lire.
# Même liste que le formulaire et que firestore.rules : les trois bougent
# ensemble. Aucun mot de passe n'y figure, et c'est délibéré.
CHAMPS_FICHE = ("entreprise", "contactPublic", "adresse", "horaires", "reseaux",
                "domaine", "domaineEtat", "registraire",
                "githubEtat", "githubCourriel", "siteActuel", "notes")


def miroir_fiches(fiches):
    """Recopie les fiches d'installation dans le dossier du propriétaire.

    Document SÉPARÉ de « state » : une fiche se lit une fois au montage du
    site, une demande se traite en boucle. Les mêler ferait grossir un
    document relu à chaque cycle, et surtout ferait passer une fiche pour une
    ligne de la file de travail.
    """
    global _dernieres_fiches
    lignes = []
    for uid, f in fiches:
        fc = fiche_client(uid)
        ligne = {
            "clientUid": uid,
            "clientNom": f.get("clientNom", ""),
            "clientCourriel": f.get("clientCourriel", ""),
            "declare": bool(fc),
            "dossier": fc["nom"] if fc else "",
            "verrouillee": bool(f.get("verrouillee")),
            "approuvee": bool(f.get("approuvee")),
            "majLe": horodatage_ms(f.get("majLe") or f.get("creeLe")),
        }
        for champ in CHAMPS_FICHE:
            ligne[champ] = f.get(champ, "")
        lignes.append(ligne)
    lignes.sort(key=lambda x: x["majLe"], reverse=True)
    if lignes != _dernieres_fiches:
        ecrire(BASE_INTERNE, CLE_INTERNE, f"{PARENT}/fiches",
               {"fiches": lignes, "updatedAt": int(time.time() * 1000)})
        _dernieres_fiches = lignes
        journaliser(f"fiches mises à jour ({len(lignes)} fiche(s))")
    return lignes


def appliquer_signaux(connues, fiches_connues, internes):
    """Les changements d'état demandés depuis l'outil, appliqués puis effacés.

    Le document « state » appartient au pont : l'outil web n'y touche pas et
    dépose plutôt une intention. C'est ce qui évite que deux écrivains se
    marchent dessus sur le même document — même principe que les signaux du
    prospecteur dans le tableau de bord marketing.
    """
    for nom, champs in internes:
        if not nom.startswith("signal-"):
            continue

        # Verrouillage d'une fiche (site monté) et activation des demandes
        # (fiche lue, accès ouvert) : deux intentions distinctes qui peuvent
        # partager le même signal-fiche-<uid> (déposé avec merge:true côté
        # outil interne). On applique celles qui sont présentes, rien de plus
        # — un signal qui ne porte que l'une des deux ne touche pas l'autre.
        id_fiche = champs.get("idFiche")
        if id_fiche:
            if id_fiche in fiches_connues:
                maj = {}
                if "verrouiller" in champs:
                    maj["verrouillee"] = bool(champs["verrouiller"])
                if "activerDemandes" in champs:
                    maj["approuvee"] = bool(champs["activerDemandes"])
                if maj:
                    ecrire(BASE_CLIENTS, CLE_CLIENTS, f"fiches/{id_fiche}", maj)
                    journaliser(f"fiche {id_fiche} : "
                                + ", ".join(f"{k}={v}" for k, v in maj.items()))
            supprimer(BASE_INTERNE, CLE_INTERNE, f"{PARENT}/{nom}")
            continue

        id_demande = champs.get("idDemande")
        voulu = champs.get("statutVoulu")
        if id_demande in connues and voulu:
            maj = {"statut": voulu}
            if champs.get("reponse"):
                maj["reponse"] = champs["reponse"]
            ecrire(BASE_CLIENTS, CLE_CLIENTS, f"demandes/{id_demande}", maj)
            journaliser(f"état « {voulu} » appliqué à la demande {id_demande}")
        supprimer(BASE_INTERNE, CLE_INTERNE, f"{PARENT}/{nom}")


def remonter_lancements(connues, internes):
    """Un lancement terminé se traduit en une phrase pour le client.

    « reporte » marque ce qui a déjà été remonté : sans ce drapeau, chaque
    cycle réécrirait le même statut et un état changé à la main dans l'outil
    serait repoussé en boucle par le pont.
    """
    for nom, champs in internes:
        if not nom.startswith("lancement-") or champs.get("reporte"):
            continue
        statut = champs.get("statut")
        if statut not in PHRASES:
            continue
        id_demande = champs.get("idDemande")
        if id_demande in connues:
            ecrire(BASE_CLIENTS, CLE_CLIENTS, f"demandes/{id_demande}", {
                "statut": "en_ligne" if statut == "fait" else "analyse",
                "reponse": PHRASES[statut],
            })
            journaliser(f"lancement {statut} remonté à la demande {id_demande}")
        ecrire(BASE_INTERNE, CLE_INTERNE, f"{PARENT}/{nom}", {"reporte": True})


def cycle():
    demandes = lister(BASE_CLIENTS, CLE_CLIENTS, "demandes")
    connues = {i for i, _ in demandes}
    # Les fiches sont peu nombreuses (une par client, à vie) : la lecture
    # supplémentaire ne pèse rien à côté des demandes.
    fiches = lister(BASE_CLIENTS, CLE_CLIENTS, "fiches")
    fiches_connues = {i for i, _ in fiches}
    # Le dossier interne est lu UNE fois par cycle : les signaux et les
    # lancements y vivent côte à côte, et deux passes coûteraient deux fois
    # les lectures pour la même information.
    internes = lister(BASE_INTERNE, CLE_INTERNE, PARENT)
    lignes = miroir(demandes)
    fiches_lignes = miroir_fiches(fiches)
    appliquer_signaux(connues, fiches_connues, internes)
    remonter_lancements(connues, internes)
    a_traiter = sum(1 for l in lignes if l["statut"] in ("recue", "analyse"))
    non_relies = sum(1 for l in lignes if not l["depotConnu"])
    a_monter = sum(1 for f in fiches_lignes if not f["verrouillee"])
    detail = f"{len(lignes)} demande(s), {a_traiter} à traiter"
    if non_relies:
        detail += f", {non_relies} sans dossier déclaré"
    if fiches_lignes:
        detail += f", {len(fiches_lignes)} fiche(s) dont {a_monter} à monter"
    return detail


def main():
    journaliser(f"pont démarré ({PROJET_CLIENTS} ↔ {PROJET_INTERNE})"
                + (" — ESSAI, aucune écriture" if ESSAI else ""))
    while True:
        try:
            journaliser(cycle())
        except urllib.error.HTTPError as e:
            journaliser(f"HTTP {e.code} : {e.read()[:300]!r}")
        except Exception as e:                      # noqa: BLE001
            journaliser(f"erreur : {type(e).__name__} : {e}")
        if UNE_FOIS:
            return
        time.sleep(INTERVALLE)


if __name__ == "__main__":
    main()
