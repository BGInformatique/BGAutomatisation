#!/usr/bin/env python3
"""Vigie — surveillance quotidienne de la présence web de {{ENTREPRISE}}.

Lancée chaque matin 7 h 45 par bg-vigie.timer. Ne publie rien, ne déploie
rien : elle SURVEILLE, RELANCE ce qui est tombé, et DÉPOSE ses alertes là où
le propriétaire regarde déjà — le tableau de bord marketing (voir
BGDashboard-modele/marketing/, un autre chantier).
Quand tout va bien, elle ne dérange personne : silence = tout tient.

Ce qu'elle vérifie, dans l'ordre :

  1. UNITÉS EN PANNE : un service bg-* en état « failed » (comme
     bg-prospecteur le 17 août, mort d'une panne DNS au réveil) est relancé
     une fois par jour. S'il retombe le lendemain, une tâche d'alerte est
     créée au tableau de bord — plus d'échec silencieux. Tout outil bg-*
     appartient à {{ENTREPRISE}}, mais l'alerte porte le client du mandat
     que l'unité sert ({{MANDAT_EXEMPLE}} pour prospecteur et recherchiste) :
     les informations des deux mandats ne se confondent jamais.
  2. LANCEMENTS GELÉS : une demande du bouton éclair qui reste « demande »
     plus de 2 h signifie que bg-lanceur ne suit plus — il est relancé.
  3. MONTAGE FACEBOOK : sante_facebook.py (jeton, droits, file, minuterie) ;
     un verdict d'échec devient une alerte. Une file qui n'a rien publié
     depuis plus de 10 jours alors que des textes attendent = alerte aussi
     (le publicateur n'a pas de Persistent= : deux fenêtres ratées passent
     sans trace ailleurs que dans journal.log).
  4. ÉPUISEMENT DU LOT FACEBOOK : à 3 textes restants ou moins, la vigie met
     en file UN lancement Claude qui rédige le lot 2 pour validation. Les
     textes s'arrêtent au guichet d'autorisations (cas « publication ») :
     rien ne part sans l'accord du propriétaire.
  5. FICHE GOOGLE : la publication mensuelle (décision du 14 août : le
     propriétaire écrit SES textes, jamais P1-P8) n'a aucun rappel — la
     vigie crée la tâche du mois au tableau de bord 4 jours avant le 14.
  6. SITE EN LIGNE : {{DOMAINE}}, les deux volets et sitemap.xml
     doivent répondre 200 avec le bon contenu ; GoatCounter doit exister.
  7. GUICHET DORMANT : une demande d'autorisation sans réponse depuis 5
     jours est rappelée par une tâche au tableau de bord.
  8. BIBLIOTHÈQUE : tant que des guides du registre (_bibliotheque/
     sujets.tsv, liste CLOSE de 14) restent « a_ecrire », la vigie en met
     UN à la fois en rédaction (au plus un par semaine) via le lanceur.
     Le brouillon s'arrête au guichet (categorie publication) : rien ne se
     committe ni ne se déploie sans l'accord du propriétaire, et un refus
     retire le sujet pour de bon.
  9. TÂCHES MANUELLES : ce qui attend la PERSONNE du propriétaire est rangé
     dans la colonne « À compléter manuellement » du tableau (jour =
     "manuel") — les tâches de la vigie, les écartées du pilote (refus ou
     échec) et les bloquées. On n'en sort jamais une tâche : ce geste-là
     appartient au propriétaire.
 10. PONT CLIENTS : tant que bg-pont-clients n'est pas activé, une sonde
     d'une lecture vérifie si l'accès IAM au projet clients a été accordé ;
     dès que oui, le service est démarré — le geste console du propriétaire
     est le seul qui reste.

Les tâches d'alerte portent des identifiants déterministes
(uuid5 « bg-vigie:<clé> ») : jamais de doublon, et une tâche supprimée par
le propriétaire (pierre tombale) n'est PAS recréée — supprimer, c'est
répondre « non merci ».

    python3 vigie.py --essai    # montre ce qui serait fait, n'écrit rien

État local (relances tentées, mois de fiche fait, lot 2 lancé) :
etat_vigie.json, à côté de ce script. Journal partagé : journal.log.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import api, decoder, encoder, BASE, UID, journaliser  # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))
ETAT_DOC = f"users/{UID}/marketing/state"
FICHIER_ETAT = os.path.join(ICI, "etat_vigie.json")
FILE_FACEBOOK = os.path.expanduser(
    "~/Bureau/{{ENTREPRISE}}/02_Marketing/Campagne_BG/Contenus/_File_Facebook.tsv")
SUJETS_TSV = os.path.expanduser(
    "~/Bureau/{{ENTREPRISE}}/01_Site_Web/{{DEPOT_SITE}}/_bibliotheque/sujets.tsv")
JOURS_ENTRE_GUIDES = 7  # un guide en rédaction à la fois, au plus un par semaine
ESSAI = "--essai" in sys.argv
CLIENT = "{{ENTREPRISE}}"

# Tout outil bg-* est un outil de {{ENTREPRISE}} — la vigie les surveille et
# les relance tous. Mais l'INFORMATION ne se confond pas : chaque unité est
# rattachée au mandat qu'elle sert, et ses alertes portent ce client-là au
# tableau de bord. La vigie ne relance JAMAIS autre chose que cette liste.
UNITES = {
    "bg-lanceur.service": CLIENT,
    "bg-publicateur.service": CLIENT,
    "bg-courriel.service": CLIENT,
    "bg-pont-clients.service": CLIENT,
    "bg-prospecteur.service": "{{MANDAT_EXEMPLE}}",
    "bg-recherchiste.service": "{{MANDAT_EXEMPLE}}",
}

# Pages publiques témoins : si l'une ne répond pas avec son marqueur, le site
# est considéré en panne. (Les outils internes ne sont pas testés : privés.)
PAGES_TEMOINS = [
    ("https://{{DOMAINE}}/", "{{ENTREPRISE}}"),
    ("https://{{DOMAINE}}/residentiel/", "{{ENTREPRISE}}"),
    ("https://{{DOMAINE}}/entreprises/", "{{ENTREPRISE}}"),
    ("https://{{DOMAINE}}/sitemap.xml", "<urlset"),
]
GOATCOUNTER = "https://{{HANDLE}}.goatcounter.com/"

SEUIL_LOT_BAS = 3          # textes a_publier restants avant de lancer le lot 2
JOURS_SILENCE_FACEBOOK = 10  # jours sans publication avant alerte
JOUR_FICHE_GOOGLE = 14     # jour d'ancrage de la publication mensuelle
AVANCE_RAPPEL = 4          # jours d'avance pour créer la tâche du mois
JOURS_GUICHET_DORMANT = 5  # jours sans réponse avant rappel


# ── état local ──────────────────────────────────────────────────────────────

def lire_etat_local():
    try:
        return json.load(open(FICHIER_ETAT, encoding="utf-8"))
    except (OSError, ValueError):
        # Amorçage : la publication de fiche Google d'août a été faite le 14.
        return {"fiche_google_faite": "2026-08", "relances": {}}


def ecrire_etat_local(e):
    if ESSAI:
        return
    with open(FICHIER_ETAT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=1)
    os.replace(FICHIER_ETAT + ".tmp", FICHIER_ETAT)


# ── réseau ──────────────────────────────────────────────────────────────────

def reseau_pret():
    try:
        socket.getaddrinfo("oauth2.googleapis.com", 443)
        return True
    except OSError:
        return False


def attendre_reseau(maximum=600):
    debut = time.time()
    while time.time() - debut < maximum:
        if reseau_pret():
            return True
        time.sleep(10)
    return False


# ── tableau de bord (document marketing/state) ─────────────────────────────

def id_vigie(cle):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bg-vigie:{cle}"))


def etat_marketing():
    doc = api(f"{BASE}/{ETAT_DOC}")
    return {k: decoder(v) for k, v in doc.get("fields", {}).items()}


def pousser_etat(etat):
    api(f"{BASE}/{ETAT_DOC}",
        {"fields": {k: encoder(v) for k, v in etat.items()}}, methode="PATCH")


def assurer_tache(etat, cle, titre, detail, chantier, priorite="haute",
                  echeance="", estime="15", client=CLIENT):
    """Crée la tâche si elle n'existe pas déjà. Une pierre tombale = le
    propriétaire l'a supprimée : on respecte, on ne recrée pas."""
    tid = id_vigie(cle)
    if tid in (etat.get("tombstones") or {}):
        return False
    if any(t.get("id") == tid for t in etat.get("taches") or []):
        return False
    if ESSAI:
        print(f"[essai] tâche à créer : {titre}")
        return False
    now = int(time.time() * 1000)
    # jour = "manuel" : la colonne « À compléter manuellement » du tableau.
    # Les tâches de la vigie s'adressent toutes au propriétaire — elles y
    # naissent d'office.
    etat.setdefault("taches", []).append({
        "id": tid, "titre": titre, "detail": detail, "client": client,
        "chantier": chantier, "stme": "", "priorite": priorite,
        "statut": "a_faire", "echeance": echeance, "estimeMin": estime,
        "jour": "manuel", "source": "vigie", "cree": now, "maj": now,
    })
    journaliser(f"vigie : tâche créée — {titre}")
    return True


def statut_tache(etat, cle):
    tid = id_vigie(cle)
    for t in etat.get("taches") or []:
        if t.get("id") == tid:
            return t.get("statut")
    return None


def creer_lancement(titre, detail, chantier):
    """Met une demande dans la file du lanceur (même format que le bouton
    éclair de la page). La réponse aboutira au guichet d'autorisations."""
    if ESSAI:
        print(f"[essai] lancement à mettre en file : {titre}")
        return "essai"
    now = int(time.time() * 1000)
    nom = f"lancement-{now}-vg{os.urandom(2).hex()}"
    champs = {"idTache": "", "titre": titre, "detail": detail,
              "client": CLIENT, "chantier": chantier,
              "statut": "demande", "demandeLe": now, "maj": now}
    api(f"{BASE}/users/{UID}/marketing/{nom}",
        {"fields": {k: encoder(v) for k, v in champs.items()}}, methode="PATCH")
    journaliser(f"vigie : lancement mis en file — {nom} ({titre!r})")
    return nom


# ── 1. unités en panne ──────────────────────────────────────────────────────

def unites_en_panne(etat_local, alertes):
    r = subprocess.run(["systemctl", "--user", "list-units", "bg-*",
                        "--state=failed", "--plain", "--no-legend"],
                       capture_output=True, text=True)
    en_panne = [l.split()[0].lstrip("●* ") for l in r.stdout.splitlines()
                if l.strip()]
    pannes = etat_local.setdefault("pannes", {})
    # Une unité qui n'est plus en panne sort du compte : la prochaine panne
    # repartira comme un incident neuf.
    for unite in [u for u in pannes if u not in en_panne]:
        journaliser(f"vigie : {unite} de nouveau sur pied")
        del pannes[unite]
    semaine = date.today().strftime("%G-S%V")
    for unite in en_panne:
        if unite not in UNITES:
            journaliser(f"vigie : {unite} en panne mais hors liste — signalée sans relance")
            alertes.append((f"panne-{unite}-{semaine}", f"⚠️ Service {unite} en panne",
                            f"L'unité {unite} est en état « failed » et la vigie ne la "
                            "relance pas (hors de sa liste). Voir : journalctl --user -u "
                            f"{unite} -n 50", "Pilotage"))
            continue
        pannes[unite] = pannes.get(unite, 0) + 1
        if pannes[unite] >= 2:
            # Relancée hier et retombée : ce n'est pas transitoire — on le dit,
            # une fois par semaine, et on continue d'essayer. L'alerte porte le
            # client du mandat que l'unité sert.
            alertes.append((
                f"panne-{unite}-{semaine}",
                f"⚠️ {unite} retombe en panne malgré les relances",
                f"La vigie relance {unite} chaque matin depuis {pannes[unite]} jours "
                "et le service retombe en échec. La cause n'est pas transitoire.\n\n"
                "Pour voir l'erreur : ouvrir l'application Terminal et coller :\n"
                f"journalctl --user -u {unite} -n 50 --no-pager\n\n"
                "Ou lancer une session Claude et lui demander de diagnostiquer.",
                "Pilotage", UNITES[unite]))
        if not reseau_pret() and unite != "bg-lanceur.service":
            journaliser(f"vigie : {unite} en panne, réseau absent — relance remise à plus tard")
            continue
        if ESSAI:
            print(f"[essai] relance à faire : {unite}")
            continue
        subprocess.run(["systemctl", "--user", "reset-failed", unite],
                       capture_output=True)
        subprocess.run(["systemctl", "--user", "restart", "--no-block", unite],
                       capture_output=True)
        journaliser(f"vigie : {unite} relancée (était failed, {pannes[unite]}e jour)")


# ── 2. lancements gelés ─────────────────────────────────────────────────────

def requete_lancements(statut):
    q = {"structuredQuery": {
        "from": [{"collectionId": "marketing"}],
        "where": {"fieldFilter": {
            "field": {"fieldPath": "statut"},
            "op": "EQUAL", "value": {"stringValue": statut}}},
        "limit": 20}}
    docs = []
    for ligne in api(f"{BASE}/users/{UID}:runQuery", q):
        d = ligne.get("document")
        if not d:
            continue
        nom = d["name"].rsplit("/", 1)[-1]
        if nom.startswith("lancement-"):
            docs.append((nom, {k: decoder(v) for k, v in d.get("fields", {}).items()}))
    return docs


def lancements_geles(etat_local):
    maintenant = int(time.time() * 1000)
    vieux = [nom for nom, ch in requete_lancements("demande")
             if maintenant - int(ch.get("demandeLe") or maintenant) > 2 * 3600 * 1000]
    if not vieux:
        return
    aujourdhui = date.today().isoformat()
    if etat_local.setdefault("relances", {}).get("lanceur-gele") == aujourdhui:
        return
    if ESSAI:
        print(f"[essai] {len(vieux)} demande(s) gelée(s) — bg-lanceur serait relancé")
        return
    etat_local["relances"]["lanceur-gele"] = aujourdhui
    subprocess.run(["systemctl", "--user", "restart", "--no-block",
                    "bg-lanceur.service"], capture_output=True)
    journaliser(f"vigie : {len(vieux)} demande(s) en file depuis plus de 2 h "
                "— bg-lanceur relancé")


# ── 3 et 4. montage Facebook et épuisement du lot ───────────────────────────

def lire_file_facebook():
    if not os.path.exists(FILE_FACEBOOK):
        return []
    lignes = [l for l in open(FILE_FACEBOOK, encoding="utf-8").read().splitlines()
              if l.strip()]
    if not lignes:
        return []
    entetes = lignes[0].split("\t")
    return [dict(zip(entetes, l.split("\t") + [""] * len(entetes)))
            for l in lignes[1:]]


def surveiller_facebook(etat_local, alertes):
    semaine = date.today().strftime("%G-S%V")
    # a) le bilan de santé complet (jeton, droits, file, minuterie)
    if reseau_pret():
        try:
            r = subprocess.run([sys.executable, os.path.join(ICI, "sante_facebook.py")],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                problemes = "\n".join(l.strip() for l in r.stdout.splitlines()
                                      if "·" in l) or r.stdout[-800:]
                alertes.append((
                    f"sante-facebook-{semaine}",
                    "⚠️ Le montage Facebook ne tiendra pas la prochaine publication",
                    "sante_facebook.py rapporte :\n" + problemes +
                    "\n\nPour le détail : ouvrir l'application Terminal et coller :\n"
                    "cd {{CHEMIN_INSTALLATION}} && python3 sante_facebook.py",
                    "Contenu"))
        except (subprocess.TimeoutExpired, OSError) as e:
            journaliser(f"vigie : sante_facebook.py injouable ({e!r})")
    # b) la file : silence prolongé et épuisement
    rangs = lire_file_facebook()
    if not rangs:
        return
    restants = sum(1 for r in rangs if r.get("STATUT") == "a_publier")
    derniere = max((r.get("PUBLIE_LE", "") for r in rangs if r.get("PUBLIE_LE")),
                   default="")
    if derniere and restants:
        ecart = (date.today() - date.fromisoformat(derniere)).days
        if ecart > JOURS_SILENCE_FACEBOOK:
            alertes.append((
                f"facebook-silence-{semaine}",
                f"⚠️ Aucune publication Facebook depuis {ecart} jours",
                f"La dernière publication du lot date du {derniere} alors que "
                f"{restants} texte(s) attendent encore. Les deux fenêtres du "
                "publicateur (jeudi 18 h 30, dimanche 10 h) ont probablement été "
                "ratées — machine éteinte ou panne. Vérifier :\n"
                "cd {{CHEMIN_INSTALLATION}} && python3 sante_facebook.py",
                "Contenu"))
    if restants <= SEUIL_LOT_BAS and not etat_local.get("lot2_lance"):
        nom = creer_lancement(
            "Rédiger le lot Facebook 2 (10 textes) pour validation",
            f"Le lot Facebook 1 s'épuise : il ne reste que {restants} texte(s) "
            "a_publier dans Campagne_BG/Contenus/_File_Facebook.tsv.\n"
            "Rédige le LOT 2 : 10 nouveaux billets résidentiels.\n"
            "Ton et registre : calqués sur Campagne_BG/Contenus/Voix-{{ENTREPRISE}}-Facebook.md "
            "et les billets du lot 1 (Facebook-Residentiel-Lot-1.md). Ne répète pas "
            "les sujets du lot 1 ; puise dans les services résidentiels du site "
            "(ordinateur lent, virus et arnaques, WiFi, sauvegarde de photos, "
            "courriel, nouvel appareil, accompagnement des aînés) et la saison.\n"
            "Règles fermes : jamais « diagnostic gratuit » (toujours « estimation "
            "sans frais »), aucune promesse de délai, aucune vente de matériel, "
            "aucune mention de {{MANDAT_EXEMPLE}}.\n"
            "Dépose les 10 textes dans Livrables/. NE MODIFIE PAS "
            "Facebook-Residentiel-Lot-1.md : y ajouter des sections ## 11+ les met "
            "en file de publication AUTOMATIQUE. C'est donc une PUBLICATION — "
            "termine par un bloc AUTORISATION REQUISE (categorie publication) "
            "demandant l'accord d'ajouter les 10 sections au markdown, textes "
            "joints dans TEXTE A COLLER.",
            "Contenu")
        if nom != "essai":
            etat_local["lot2_lance"] = nom


# ── 5. fiche Google : la publication mensuelle ─────────────────────────────

def mois_suivant(am):
    a, m = int(am[:4]), int(am[5:7])
    return f"{a + (m == 12):04d}-{(m % 12) + 1:02d}"


def rappel_fiche_google(etat, etat_local):
    fait = etat_local.get("fiche_google_faite", "2026-08")
    mois_du = mois_suivant(fait)
    due = date(int(mois_du[:4]), int(mois_du[5:7]), JOUR_FICHE_GOOGLE)
    cle = f"fiche-google-{mois_du}"
    # Le propriétaire a marqué la tâche du mois faite : on avance l'ancre.
    if statut_tache(etat, cle) == "fait":
        etat_local["fiche_google_faite"] = mois_du
        journaliser(f"vigie : publication de fiche Google consignée pour {mois_du}")
        return False
    if date.today() < due - timedelta(days=AVANCE_RAPPEL):
        return False
    mois_nom = ["", "janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre",
                "décembre"][due.month]
    return assurer_tache(
        etat, cle,
        f"Fiche Google — publication de {mois_nom} (mensuelle)",
        "Écrire VOTRE texte (150 à 300 mots) et le publier sur la fiche Google "
        "Business Profile : Ajouter une actualité, bouton « Appeler » ou « En "
        "savoir plus » vers une page existante du site.\n"
        "Règles : alterner résidentiel / travail d'un mois à l'autre ; toujours "
        "« estimation sans frais », jamais « diagnostic gratuit » ; aucune "
        "promesse de délai.\n"
        "Pendant que la console est ouverte : téléverser les 2 photos du mois "
        "et répondre aux avis en attente, s'il y en a.\n"
        "Marquer cette tâche FAITE une fois le texte publié — c'est ce qui "
        "programme le rappel du mois suivant (créé par la vigie, 4 jours avant "
        f"le {JOUR_FICHE_GOOGLE}).",
        "Fiche Google", priorite="moyenne", echeance=due.isoformat(),
        estime="30")


# ── 6. site en ligne et GoatCounter ────────────────────────────────────────

def page_repond(url, marqueur):
    req = urllib.request.Request(url, headers={"User-Agent": "bg-vigie/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status == 200 and marqueur in r.read(200_000).decode("utf-8", "replace")


def surveiller_site(etat_local, alertes):
    if not reseau_pret():
        journaliser("vigie : pas de réseau — vérification du site sautée")
        return
    en_panne = []
    for url, marqueur in PAGES_TEMOINS:
        ok = False
        for _ in range(3):
            try:
                if page_repond(url, marqueur):
                    ok = True
                    break
            except (urllib.error.URLError, OSError, TimeoutError):
                pass
            time.sleep(20)
        if not ok:
            en_panne.append(url)
    if en_panne:
        semaine = date.today().strftime("%G-S%V")
        alertes.append((
            f"site-{semaine}",
            "🚨 Le site ne répond pas correctement",
            "Ces pages ne répondent pas (ou plus avec le bon contenu), vérifié "
            "3 fois à 20 s d'écart :\n- " + "\n- ".join(en_panne) +
            "\n\nÀ vérifier : l'état de GitHub Pages (https://www.githubstatus.com), "
            "le domaine chez GoDaddy, puis le dépôt {{DEPOT_SITE}}.",
            "Pilotage"))
        journaliser(f"vigie : site en panne — {', '.join(en_panne)}")
    elif etat_local.pop("site_en_panne", None):
        journaliser("vigie : le site répond de nouveau")
    etat_local["site_en_panne"] = bool(en_panne)
    # GoatCounter : le compte existe-t-il seulement ? (Question ouverte depuis
    # le 3 août : le script de mesure est sur les 46 pages, mais un compte non
    # réclamé = des mesures dans le vide.)
    if not etat_local.get("goatcounter_verifie"):
        try:
            req = urllib.request.Request(GOATCOUNTER,
                                         headers={"User-Agent": "bg-vigie/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except (urllib.error.URLError, OSError):
            return  # pas concluant, on réessaiera demain
        if code == 404:
            alertes.append((
                "goatcounter-absent",
                "⚠️ Le compte GoatCounter n'existe pas — l'analytique part dans le vide",
                "Les 46 pages publiques envoient leurs mesures à "
                "https://{{HANDLE}}.goatcounter.com/count, mais ce compte "
                "répond 404 : il n'a jamais été créé. Depuis le 3 août, aucune "
                "visite n'est comptée.\n\nÉTAPES :\n"
                "1. Ouvrir https://www.goatcounter.com dans le navigateur\n"
                "2. Cliquer « Sign up » et créer le compte avec le code "
                "« {{HANDLE}} » (exactement, en minuscules)\n"
                "3. Utiliser le courriel {{COURRIEL_PUBLIC}}\n"
                "4. Vérification : https://{{HANDLE}}.goatcounter.com doit "
                "afficher un tableau de bord — les visites comptent dès cet instant, "
                "sans rien changer au site.",
                "Mesure"))
            etat_local["goatcounter_verifie"] = "absent-signale"
        else:
            journaliser(f"vigie : compte GoatCounter confirmé (HTTP {code})")
            etat_local["goatcounter_verifie"] = "existe"


# ── 7. guichet dormant ──────────────────────────────────────────────────────

def guichet_dormant(alertes):
    maintenant = int(time.time() * 1000)
    seuil = JOURS_GUICHET_DORMANT * 24 * 3600 * 1000
    for nom, ch in requete_lancements("attente_autorisation"):
        depuis = int(ch.get("autorisationLe") or ch.get("demandeLe") or maintenant)
        jours = (maintenant - depuis) // (24 * 3600 * 1000)
        if maintenant - depuis < seuil:
            continue
        alertes.append((
            f"attente-{nom}",
            f"⏳ Une demande d'autorisation attend depuis {jours} jours",
            f"« {ch.get('titre') or nom} » est arrêtée au guichet depuis {jours} "
            "jours (" + (ch.get("autorisationDemande") or "demande non consignée")[:200] +
            ").\n\nPour répondre : ouvrir l'application Terminal et coller :\n"
            "cd {{CHEMIN_INSTALLATION}} && python3 autorisations.py\n"
            "puis « voir », « accorder » ou « refuser » selon le cas.",
            "Pilotage"))


# ── 8. bibliothèque : les guides du site ────────────────────────────────────

def lire_sujets():
    if not os.path.exists(SUJETS_TSV):
        return []
    lignes = [l for l in open(SUJETS_TSV, encoding="utf-8").read().splitlines()
              if l.strip()]
    if not lignes:
        return []
    entetes = lignes[0].split("\t")
    return [dict(zip(entetes, l.split("\t") + [""] * len(entetes)))
            for l in lignes[1:]]


def consigne_guide(g):
    return (
        f"Rédige le guide « {g['TITRE']} » de la bibliothèque du site "
        "({{DEPOT_SITE}}/), volet " + g["VOLET"] + ", slug " + g["SLUG"] + ".\n\n"
        "AVANT D'ÉCRIRE : lis {{DEPOT_SITE}}/CLAUDE.md, la ligne du guide "
        "dans _bibliotheque/sujets.tsv (PROMESSE, ANCRES, ÉTIQUETTE), un guide "
        "déjà écrit du même volet pour le gabarit et le ton, et deploy.sh pour "
        "connaître les régénérations attendues (_gabarits/, "
        "generer-bibliotheque.py). L'entête et le pied viennent des gabarits — "
        "jamais écrits à la main dans la page.\n\n"
        "Règles fermes : français québécois ; toujours « estimation sans "
        "frais », jamais « diagnostic gratuit » ; aucune promesse de délai ; "
        "{{ENTREPRISE}} ne vend aucun matériel (c'est un argument : conseils sans marge) ; "
        "aucune mention de {{MANDAT_EXEMPLE}} ; ne pas parler de certifications ; coordonnées "
        "publiées seulement — {{TELEPHONE}}, {{COURRIEL_PUBLIC}}.\n\n"
        "PHASE 1 (si le prompt NE contient PAS de réponse du propriétaire) : "
        "écrire la page complète du guide, mettre à jour sa ligne de "
        "sujets.tsv (ETAT ecrit, FICHIER, RESUME comme les guides écrits), "
        "faire les régénérations. NE PAS committer, NE PAS pousser — pousser "
        "main déploie la production. Terminer par un bloc AUTORISATION "
        "REQUISE (categorie publication) : DEMANDE = publier ce guide ; "
        "ETAPES = comment relire le fichier local puis répondre au guichet ; "
        "VERIF = l'adresse publique de la page après déploiement.\n\n"
        "PHASE 2 (si le propriétaire a répondu OUI) : committer UNIQUEMENT "
        "les fichiers de ce guide par chemin explicite — jamais « git add . » "
        "ni deploy.sh tel quel : d'autres sessions ont du travail non commité "
        "dans ce dépôt. Puis pousser (l'accord du guichet est l'accord de "
        "déploiement), et vérifier que l'adresse publique répond.")


def bibliotheque_guides(etat_local, alertes):
    """Met UN guide en rédaction à la fois, au plus un par semaine. Le
    brouillon s'arrête au guichet ; un refus du propriétaire vaut « jamais » :
    le sujet ne sera plus relancé (comme une pierre tombale)."""
    sujets = lire_sujets()
    if not sujets:
        return
    en_cours = etat_local.get("bibliotheque")
    if en_cours:
        slug, nom = en_cours.get("slug"), en_cours.get("lancement")
        try:
            d = api(f"{BASE}/users/{UID}/marketing/{nom}")
            statut = decoder(d.get("fields", {}).get("statut",
                                                     {"stringValue": ""}))
        except urllib.error.HTTPError:
            statut = "disparu"
        if statut in ("demande", "en_cours", "attente_autorisation"):
            return  # rédaction ou guichet : on attend
        if statut == "refuse":
            etat_local.setdefault("guides_refuses", []).append(slug)
            journaliser(f"vigie : guide {slug} refusé au guichet — "
                        "il ne sera plus proposé")
        elif statut == "fait":
            journaliser(f"vigie : guide {slug} publié")
        else:  # echec, annule, disparu : le sujet redeviendra candidat
            journaliser(f"vigie : lancement du guide {slug} terminé en "
                        f"« {statut} » — le sujet redeviendra candidat")
        del etat_local["bibliotheque"]
    refuses = set(etat_local.get("guides_refuses") or [])
    candidats = [s for s in sujets
                 if s.get("ETAT") == "a_ecrire" and s.get("SLUG") not in refuses]
    if not candidats:
        return
    dernier = etat_local.get("guide_dernier_lance", "")
    if dernier and (date.today() - date.fromisoformat(dernier)).days < JOURS_ENTRE_GUIDES:
        return
    g = candidats[0]
    nom = creer_lancement(f"Rédiger le guide « {g['TITRE']} » pour validation",
                          consigne_guide(g), "Bibliothèque")
    if nom != "essai":
        etat_local["bibliotheque"] = {"slug": g["SLUG"], "lancement": nom}
        etat_local["guide_dernier_lance"] = date.today().isoformat()


# ── 9. tâches à compléter manuellement ──────────────────────────────────────

def marquer_manuelles(etat):
    """Range dans la colonne « À compléter manuellement » (jour = "manuel")
    les tâches qui attendent la personne du propriétaire : celles de la vigie,
    celles que le pilote a écartées (refus au guichet ou échec), et les
    bloquées. On ne SORT jamais une tâche de la colonne : ça, c'est le geste
    du propriétaire (l'épingle de la carte)."""
    try:
        ecartees = set(json.load(open(os.path.join(ICI, "etat_pilote.json"),
                                      encoding="utf-8")).get("ecartees") or [])
    except (OSError, ValueError):
        ecartees = set()
    modif = False
    for t in etat.get("taches") or []:
        if t.get("statut") == "fait" or t.get("jour") == "manuel":
            continue
        if (t.get("source") == "vigie" or t.get("id") in ecartees
                or t.get("statut") == "bloque"):
            if ESSAI:
                print(f"[essai] à marquer manuelle : {t.get('titre')}")
                continue
            t["jour"] = "manuel"
            t["maj"] = int(time.time() * 1000)
            journaliser(f"vigie : « {t.get('titre')} » rangée dans "
                        "« À compléter manuellement »")
            modif = True
    return modif


# ── 10. pont clients : démarrage dès que l'accès est accordé ─────────────────

def demarrer_pont_si_pret():
    """Le pont espace-client attend UN geste du propriétaire : donner au
    compte de service l'accès Firestore du projet clients (console IAM).
    Chaque matin, une sonde d'une lecture vérifie si c'est fait ; dès que
    oui, la vigie démarre bg-pont-clients.service — aucun autre geste."""
    r = subprocess.run(["systemctl", "--user", "is-enabled",
                        "bg-pont-clients.service"], capture_output=True, text=True)
    if r.stdout.strip() == "enabled":
        return
    try:
        cw = json.load(open(os.path.expanduser(
            "~/.config/bg-lanceur/clients-web.json"), encoding="utf-8"))
        projet = cw["projet_clients"]
    except (OSError, ValueError, KeyError):
        return
    if projet.startswith("À_"):
        return
    try:
        api(f"https://firestore.googleapis.com/v1/projects/{projet}"
            "/databases/(default)/documents/demandes?pageSize=1")
    except urllib.error.HTTPError:
        return  # accès pas encore accordé : on resondera demain
    if ESSAI:
        print("[essai] accès au projet clients OK — bg-pont-clients serait démarré")
        return
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    "bg-pont-clients.service"], capture_output=True)
    journaliser("vigie : accès au projet clients accordé — bg-pont-clients démarré")


# ── passage ────────────────────────────────────────────────────────────────

def main():
    journaliser("vigie : passage" + (" (essai)" if ESSAI else ""))
    attendre_reseau(600)  # au réveil, le DNS peut traîner ; on fait avec ensuite
    etat_local = lire_etat_local()
    alertes = []  # (cle, titre, detail, chantier[, client — CLIENT par défaut])

    unites_en_panne(etat_local, alertes)
    try:
        if reseau_pret():
            lancements_geles(etat_local)
    except Exception as e:
        journaliser(f"vigie : vérification des lancements impossible ({e!r})")
    surveiller_facebook(etat_local, alertes)
    surveiller_site(etat_local, alertes)
    try:
        if reseau_pret():
            guichet_dormant(alertes)
    except Exception as e:
        journaliser(f"vigie : lecture du guichet impossible ({e!r})")
    try:
        if reseau_pret():
            bibliotheque_guides(etat_local, alertes)
    except Exception as e:
        journaliser(f"vigie : chantier bibliothèque impossible ({e!r})")
    try:
        if reseau_pret():
            demarrer_pont_si_pret()
    except Exception as e:
        journaliser(f"vigie : sonde du pont clients impossible ({e!r})")

    # Une seule lecture-écriture du tableau de bord pour tout le passage.
    try:
        if reseau_pret():
            etat = etat_marketing()
            modif = rappel_fiche_google(etat, etat_local)
            modif = marquer_manuelles(etat) or modif
            for cle, titre, detail, chantier, *extra in alertes:
                if assurer_tache(etat, cle, titre, detail, chantier,
                                 echeance=date.today().isoformat(),
                                 client=extra[0] if extra else CLIENT):
                    modif = True
            if modif:
                etat["updatedAt"] = int(time.time() * 1000)
                pousser_etat(etat)
        elif alertes:
            journaliser("vigie : pas de réseau — alertes gardées pour demain : "
                        + " ; ".join(a[1] for a in alertes))
            return  # ne pas consigner l'état local : on rejouera tout demain
    except Exception as e:
        journaliser(f"vigie : écriture au tableau de bord impossible ({e!r}) — "
                    "alertes gardées pour demain")
        return

    ecrire_etat_local(etat_local)
    journaliser(f"vigie : passage terminé — {len(alertes)} alerte(s)")


if __name__ == "__main__":
    main()
