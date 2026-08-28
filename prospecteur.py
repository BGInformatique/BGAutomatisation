#!/usr/bin/env python3
"""Prospecteur — automatisation de la prospection {{MANDAT_EXEMPLE}} (cadence hebdomadaire).

Lancé chaque lundi 8 h 30 par le minuteur systemd bg-prospecteur.timer.
Ce qu'il fait, dans l'ordre :

  1. FERME LA BOUCLE : les tâches « Relance — X » ou « Premier contact — X »
     du tableau de bord marquées faites depuis le dernier cycle mettent le
     journal à jour (statut envoyé, relance +1, prochaine échéance à J+14).
     Après 2 relances sans réponse, le prospect passe « dormant » — on
     n'écrit plus, sauf décision contraire du propriétaire.
  2. PRÉPARE LES SUIVANTES : pour chaque prospect dû (DATE_PROCHAINE échue,
     pas de tâche déjà en attente), rédige un brouillon via l'agent OpenClaw
     « {{AGENT_OPENCLAW}} » (Claude Sonnet 5, repli Gemini puis modèle
     gratuit OpenRouter en cas d'indisponibilité), ancré dans le dossier du
     prospect, l'ajoute au fichier
     Relances/Relances_<date>.md du jour et crée la tâche au tableau de bord.

  RIEN NE PART TOUT SEUL : l'envoi est toujours un geste du propriétaire. Le
  brouillon attend dans la tâche ; marquer la tâche faite = « je l'ai envoyé ».

Source de vérité : Marketing/03_Prospection/_Journal_Prospection.tsv
Statuts : a_contacter, contact_prepare, contacte_sans_reponse,
          relance_preparee, relance_envoyee, repondu, rdv_fixe, dormant,
          injoignable, client, abandonne.
Le prospecteur ne touche jamais aux statuts repondu / rdv_fixe / client /
abandonne : dès qu'un prospect répond, la suite est humaine.

Plan « Entonnoir 24 » (décisions 31-33, 9 août 2026) : la page consigne les
tentatives d'appel dans le miroir (champ « appels ») ; ce script les applique
au journal (compteurs APPELS / APPELS_JOINTS / DERNIER_APPEL), passe
« injoignable » après 3 tentatives sans joint, et recycle à J+60 (dormants et
injoignables, une seule fois, à partir de la mi-octobre 2026) sous un angle
différent.

    python3 prospecteur.py --essai    # montre ce qui serait fait, n'écrit rien
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import api, decoder, encoder, BASE, UID, journaliser  # noqa: E402

MARKETING = os.path.expanduser("~/Bureau/{{MANDAT_EXEMPLE}}/Marketing/03_Prospection")
JOURNAL_TSV = os.path.join(MARKETING, "_Journal_Prospection.tsv")
CANDIDATS_TSV = os.path.join(MARKETING, "Candidats", "_Candidats.tsv")
COLS_CANDIDATS = ["ID", "NOM", "SECTEUR", "VILLE", "SITE", "TELEPHONE", "TAILLE",
                  "ANGLE", "SOURCE", "STATUT", "PROPOSE_LE"]
INVENTAIRE_TSV = os.path.join(MARKETING, "_Inventaire.tsv")
COLS_INVENTAIRE = ["ID", "NOM", "SECTEUR", "VILLE", "LIEN", "ORIGINE", "STATUT", "NOTE",
                   "TELEPHONE", "COURRIEL", "CONTACT"]
DOSSIER_RELANCES = os.path.join(MARKETING, "Relances")
GABARIT = os.path.join(MARKETING, "00_Gabarits", "Messages_Prospection.txt")
OPENCLAW = os.path.expanduser("~/.npm-global/bin/openclaw")
ETAT = f"users/{UID}/marketing/state"

CLIENT = "{{MANDAT_EXEMPLE}}"
JOURS_ENTRE_RELANCES = 14
MAX_RELANCES = 2
ESSAI = "--essai" in sys.argv


def lire_tsv():
    lignes = open(JOURNAL_TSV, encoding="utf-8").read().splitlines()
    entetes = lignes[0].split("\t")
    rangs = []
    for l in lignes[1:]:
        if not l.strip():
            continue
        c = l.split("\t")
        c += [""] * (len(entetes) - len(c))
        rangs.append(dict(zip(entetes, c)))
    return entetes, rangs


def ecrire_tsv(entetes, rangs):
    if ESSAI:
        return
    corps = "\n".join(["\t".join(entetes)] +
                      ["\t".join(r.get(e, "") for e in entetes) for r in rangs]) + "\n"
    with open(JOURNAL_TSV + ".bak", "w", encoding="utf-8") as f:
        f.write(open(JOURNAL_TSV, encoding="utf-8").read())
    with open(JOURNAL_TSV, "w", encoding="utf-8") as f:
        f.write(corps)


def etat_marketing():
    doc = api(f"{BASE}/{ETAT}")
    return {k: decoder(v) for k, v in doc.get("fields", {}).items()}


# ── candidats proposés par le recherchiste ─────────────────────────────────

def lire_candidats():
    if not os.path.exists(CANDIDATS_TSV):
        return []
    lignes = open(CANDIDATS_TSV, encoding="utf-8").read().splitlines()
    if not lignes:
        return []
    entetes = lignes[0].split("\t")
    rangs = []
    for l in lignes[1:]:
        if not l.strip():
            continue
        c = l.split("\t")
        c += [""] * (len(entetes) - len(c))
        rangs.append(dict(zip(entetes, c)))
    return rangs


def ecrire_candidats(rangs):
    if ESSAI:
        return
    os.makedirs(os.path.dirname(CANDIDATS_TSV), exist_ok=True)
    corps = "\n".join(["\t".join(COLS_CANDIDATS)] +
                      ["\t".join(r.get(c, "") for c in COLS_CANDIDATS) for r in rangs]) + "\n"
    with open(CANDIDATS_TSV, "w", encoding="utf-8") as f:
        f.write(corps)


# ── l'inventaire : les 100 prospects potentiels, cadence incluse ───────────
#
# Statuts : en_cadence (au journal), candidat (proposé par l'engin, décision
# en attente), repertorie (recherches de juin, mobilisable par « cadencer »),
# rejete (définitif). L'inventaire est le bassin ; le journal reste la cadence.

def lire_inventaire():
    if not os.path.exists(INVENTAIRE_TSV):
        return []
    lignes = open(INVENTAIRE_TSV, encoding="utf-8").read().splitlines()
    rangs = []
    if lignes:
        entetes = lignes[0].split("\t")
        for l in lignes[1:]:
            if l.strip():
                c = l.split("\t")
                c += [""] * (len(entetes) - len(c))
                rangs.append(dict(zip(entetes, c)))
    return rangs


def ecrire_inventaire(rangs):
    if ESSAI:
        return
    corps = "\n".join(["\t".join(COLS_INVENTAIRE)] +
                      ["\t".join(r.get(c, "") for c in COLS_INVENTAIRE) for r in rangs]) + "\n"
    with open(INVENTAIRE_TSV, "w", encoding="utf-8") as f:
        f.write(corps)


def marquer_inventaire(inventaire, nom, statut, origine=""):
    """Aligne (ou crée) la ligne d'inventaire portant ce nom."""
    for r in inventaire:
        if r["NOM"].strip().lower() == nom.strip().lower():
            r["STATUT"] = statut
            return
    inventaire.append({"ID": re.sub(r"[^a-z0-9]+", "-", nom.lower()).strip("-"),
                       "NOM": nom, "SECTEUR": "", "VILLE": "", "LIEN": "",
                       "ORIGINE": origine or "manuel", "STATUT": statut, "NOTE": ""})


# ── miroir Firestore : le volet Prospection de la page web ─────────────────
#
# Le journal TSV reste la source de vérité. Le miroir (document
# marketing/prospection, mêmes règles que state) sert l'affichage, et la page
# peut y déposer des « signaux » (répondu, RDV fixé, dormant…) que ce script
# applique au journal au cycle suivant, puis efface.

def pousser_miroir(rangs):
    doc_p = {
        "prospects": [{
            "id": r["ID"], "prospect": r["PROSPECT"], "statut": r["STATUT"],
            "dernierContact": r.get("DERNIER_CONTACT", ""),
            "relances": int(r.get("RELANCES_FAITES") or 0),
            "prochaine": r.get("DATE_PROCHAINE", ""),
            "tacheId": r.get("TACHE_ID", ""), "note": r.get("NOTE", ""),
            "courriel": r.get("COURRIEL", ""),
            "contact": r.get("CONTACT", ""),
            "telephone": r.get("TELEPHONE", ""),
            "site": r.get("SITE", ""),
            "appelsFaits": int(r.get("APPELS") or 0),
            "appelsJoints": int(r.get("APPELS_JOINTS") or 0),
            "dernierAppel": r.get("DERNIER_APPEL", ""),
        } for r in rangs],
        "candidats": [{
            "id": c["ID"], "nom": c["NOM"], "secteur": c.get("SECTEUR", ""),
            "ville": c.get("VILLE", ""), "site": c.get("SITE", ""),
            "telephone": c.get("TELEPHONE", ""),
            "taille": c.get("TAILLE", ""), "angle": c.get("ANGLE", ""),
            "source": c.get("SOURCE", ""), "proposeLe": c.get("PROPOSE_LE", ""),
        } for c in lire_candidats() if c.get("STATUT") == "propose"],
        "inventaire": [{
            "id": r["ID"], "nom": r["NOM"], "secteur": r.get("SECTEUR", ""),
            "ville": r.get("VILLE", ""), "lien": r.get("LIEN", ""),
            "origine": r.get("ORIGINE", ""), "statut": r.get("STATUT", ""),
            "note": r.get("NOTE", ""),
            "telephone": r.get("TELEPHONE", ""), "courriel": r.get("COURRIEL", ""),
            "contact": r.get("CONTACT", ""),
        } for r in lire_inventaire()],
        "majLe": int(time.time() * 1000),
    }
    # PATCH avec masque : on ne touche QUE nos champs. Sans masque, Firestore
    # remplace le document entier — ce qui effacerait les boîtes de dépôt de la
    # page (signaux, appels…) et ses données propres (gestes, revenus, relevés).
    masque = "&".join(f"updateMask.fieldPaths={c}" for c in doc_p)
    api(f"{BASE}/users/{UID}/marketing/prospection?{masque}",
        {"fields": {k: encoder(v) for k, v in doc_p.items()}}, methode="PATCH")


def vider_boites(doc_prosp):
    """Efface des boîtes de dépôt UNIQUEMENT les clés lues en début de cycle —
    un dépôt fait sur la page PENDANT le cycle (qui peut durer plusieurs
    minutes, claude -p compris) survit jusqu'au cycle suivant. Suppression de
    champ Firestore : la clé figure dans updateMask mais pas dans fields ; les
    identifiants sont cités en accents graves (chiffres et tirets obligent)."""
    chemins = []
    for boite in ("signaux", "candidatures", "ajouts", "appels", "retraits"):
        for cle in (doc_prosp.get(boite) or {}):
            sain = str(cle).replace("`", "").replace("\\", "")
            chemins.append(f"{boite}.%60{sain}%60")
    if not chemins:
        return
    masque = "&".join(f"updateMask.fieldPaths={c}" for c in chemins)
    api(f"{BASE}/users/{UID}/marketing/prospection?{masque}",
        {"fields": {}}, methode="PATCH")


def lire_doc_prospection():
    try:
        d = api(f"{BASE}/users/{UID}/marketing/prospection")
    except Exception:
        return {}
    return {k: decoder(v) for k, v in d.get("fields", {}).items()}


def pousser_etat(etat):
    api(f"{BASE}/{ETAT}", {"fields": {k: encoder(v) for k, v in etat.items()}},
        methode="PATCH")


def texte_du_dossier(dossier):
    """Concatène le texte des PDF du dossier prospect (fiches, aides-mémoire)."""
    chemin = os.path.join(MARKETING, "Prospects", dossier)
    morceaux = []
    if os.path.isdir(chemin):
        for f in sorted(os.listdir(chemin))[:8]:
            if not f.lower().endswith(".pdf"):
                continue
            try:
                txt = subprocess.run(["pdftotext", "-layout",
                                      os.path.join(chemin, f), "-"],
                                     capture_output=True, text=True,
                                     timeout=30).stdout
                morceaux.append(f"--- {f} ---\n{txt[:3000]}")
            except Exception:
                pass
    return "\n".join(morceaux)[:12000]


# ─── Modèles de fallback (ordre de priorité) ──────────────────────────────
# Correspond à la config ~/.openclaw/openclaw.json → agents.list[{{AGENT_OPENCLAW}}].model
MODELES_FALLBACK = [
    {"name": "claude-cli/claude-sonnet-5", "label": "Claude Sonnet 5", "timeout": 600},
    {"name": "google/gemini-3.5-flash", "label": "Gemini 3.5 Flash", "timeout": 600},
    {"name": "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free", "label": "Nemotron 3 Ultra (gratuit)", "timeout": 900},
]


def _appel_openclaw_simple(prompt, modele, timeout, session_key):
    """Un appel unique à OpenClaw avec un modèle explicite.
    Retourne (texte, modele_utilise) ou lève une exception."""
    cmd = [
        OPENCLAW, "agent", "--agent", "{{AGENT_OPENCLAW}}",
        "--session-key", session_key,
        "--message", prompt, "--json",
    ]
    # Override du modèle si pas le premier (défaut agent)
    if modele != MODELES_FALLBACK[0]["name"]:
        cmd += ["--model", modele]
    p = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "HOME": os.path.expanduser("~")})
    if p.returncode != 0 or not p.stdout.strip():
        err = (p.stderr or "").strip()
        raise RuntimeError(f"openclaw({modele}) code={p.returncode} : {err[:500]}")
    r = json.loads(p.stdout)
    if r.get("status") != "ok":
        raise RuntimeError(r.get("summary") or f"échec openclaw ({modele})")
    trace = r["result"]["meta"].get("executionTrace") or {}
    winner = trace.get("winnerModel") or modele
    texte = (r["result"]["payloads"][0]["text"] or "").strip() if r["result"].get("payloads") else ""
    if not texte:
        finish = r["result"]["meta"].get("completion", {}).get("finishReason")
        raise RuntimeError(f"openclaw({winner}) : réponse vide (fin={finish})")
    return texte, winner


def appeler_openclaw(prompt, timeout=600):
    """Appel robuste à l'agent {{AGENT_OPENCLAW}} avec fallback explicite.
    Essaie dans l'ordre : Claude Sonnet 5 → Gemini 3.5 Flash → Nemotron 3 Ultra (gratuit).
    Chaque modèle a sa propre session (clé unique). Retry 1x par modèle sur erreurs transitoires.
    Lève une exception si tous échouent ; renvoie le texte du premier qui réussit."""
    session_base = f"agent:{{AGENT_OPENCLAW}}:tache-{uuid.uuid4()}"
    dernier_err = None
    for idx, m in enumerate(MODELES_FALLBACK):
        for tentative in (1, 2):  # 1 essai + 1 retry par modèle
            session_key = f"{session_base}-m{idx}-t{tentative}"
            try:
                if idx > 0 or tentative > 1:
                    journaliser(f"openclaw : tentative {tentative}/2 sur {m['label']} ({m['name']})")
                texte, winner = _appel_openclaw_simple(prompt, m["name"], m["timeout"], session_key)
                if winner != m["name"]:
                    journaliser(f"openclaw : repli effectif → {winner}")
                return texte
            except RuntimeError as e:
                dernier_err = e
                msg = str(e).lower()
                # Erreurs qui justifient un retry sur le MÊME modèle
                if tentative == 1 and any(k in msg for k in (
                        "timeout", "connection", "reset", "temporarily", "rate limit",
                        "overloaded", "unavailable", "503", "502", "504")):
                    time.sleep(2 * tentative)  # backoff 2s, 4s
                    continue
                # Erreurs qui justifient de passer au modèle SUIVANT
                if any(k in msg for k in (
                        "session limit", "quota exceeded", "billing", "permission denied",
                        "model not found", "invalid model", "401", "403", "404")):
                    journaliser(f"openclaw : {m['label']} indisponible ({e}) → fallback")
                    break  # sort de la boucle tentative, passe au modèle suivant
                # Autre erreur : on retry une fois puis fallback
                if tentative == 1:
                    time.sleep(2)
                    continue
                journaliser(f"openclaw : {m['label']} échoué après retry ({e}) → fallback")
                break
            except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
                dernier_err = RuntimeError(f"openclaw({m['name']}) : {type(e).__name__} : {e}")
                if tentative == 1:
                    time.sleep(2)
                    continue
                journaliser(f"openclaw : {m['label']} timeout/JSON invalide → fallback")
                break
    raise RuntimeError(f"openclaw : tous les modèles ont échoué — dernier : {dernier_err}")


def rediger(rang, premier):
    """Brouillon par OpenClaw (agent {{AGENT_OPENCLAW}}), ancré dans le dossier. None si échec."""
    genre = "un PREMIER message de prospection" if premier else \
        f"une RELANCE no {int(rang['RELANCES_FAITES'] or 0) + 1}"
    prompt = f"""Rédige {genre} pour la prospection de {{MANDAT_EXEMPLE}} (firme TI, Rive-Nord, Québec).

PROSPECT : {rang['PROSPECT']} — contact : {rang['CONTACT'] or 'non documenté'} — canal : {rang['CANAL']}
Dernier contact : {rang['DERNIER_CONTACT'] or 'jamais'} — note : {rang['NOTE']}

STYLE (impératif) : calqué sur les messages du gabarit ci-dessous — direct,
chaleureux, québécois, sobre. CTA = un appel ou une rencontre, JAMAIS un lien.
Signature exacte : « {{PROPRIETAIRE}} — {{MANDAT_EXEMPLE}}, {{TELEPHONE_MANDAT_EXEMPLE}} ».
Court : 3 paragraphes maximum.

INTERDICTIONS ABSOLUES : ne jamais inventer un résultat d'appel ou une
conversation qui n'est pas documentée ci-dessous ; jamais de statistiques ;
jamais « {{MANDAT_EXEMPLE}} peut… » (ancrer dans la réalité du prospect) ; ne
jamais mentionner AWS/Azure/GCP, COBOL, cybersécurité seule, SMS ; ne pas
révéler qu'un audit technique du prospect a été fait.

GABARIT DE STYLE :
{open(GABARIT, encoding='utf-8').read()[:6000]}

DOSSIER DU PROSPECT (extraits) :
{texte_du_dossier(rang['DOSSIER']) or '(aucun document)'}

Réponds avec le message SEULEMENT, sans commentaire ni mise en forme markdown."""
    try:
        texte = appeler_openclaw(prompt)
        return texte if "{{TELEPHONE_MANDAT_EXEMPLE}}" in texte else None
    except Exception as e:
        journaliser(f"prospecteur : rédaction échouée ({rang['PROSPECT']}) : {e!r}")
        return None


def creer_tache(etat, rang, brouillon, premier, fichier_relances):
    t_id = str(uuid.uuid4())
    now = int(time.time() * 1000)
    titre = (f"Premier contact — {rang['PROSPECT']}" if premier
             else f"Relance {int(rang['RELANCES_FAITES'] or 0) + 1} — {rang['PROSPECT']}")
    etat["taches"].append({
        "id": t_id, "titre": titre,
        "detail": f"Canal : {rang['CANAL']} — contact : {rang['CONTACT'] or 'à identifier'}\n"
                  f"Brouillon prêt (à relire, ajuster, puis envoyer À LA MAIN) :\n\n{brouillon}\n\n"
                  "Marquer cette tâche faite = « le message est parti ». Le journal "
                  "de prospection se met à jour au prochain cycle du prospecteur.",
        "client": CLIENT, "chantier": "Prospection", "stme": "",
        "priorite": "moyenne", "statut": "a_faire", "echeance": "",
        "estimeMin": "15", "jour": "",
        "source": os.path.relpath(fichier_relances, os.path.dirname(MARKETING)),
        "cree": now, "maj": now,
    })
    return t_id


def main():
    aujourd_hui = date.today().isoformat()
    entetes, rangs = lire_tsv()
    if "TACHE_ID" not in entetes:
        entetes.append("TACHE_ID")
    etat = etat_marketing()
    taches = {t.get("id"): t for t in etat.get("taches", [])}
    modif_tsv = modif_etat = False

    doc_prosp = lire_doc_prospection()

    # ── 0a. candidats acceptés/rejetés et ajouts manuels depuis la page ──
    def prochaine_id():
        return f"{max((int(r['ID']) for r in rangs if r['ID'].isdigit()), default=0) + 1:02d}"

    def creer_prospect(nom, note, fiche_texte="", telephone="", site=""):
        pid = prochaine_id()
        slug = re.sub(r"[^A-Za-z0-9]+", "_", nom).strip("_") or "Prospect"
        dossier = f"{pid}.{slug}"
        chemin = os.path.join(MARKETING, "Prospects", dossier)
        if not ESSAI:
            os.makedirs(chemin, exist_ok=True)
            if fiche_texte:
                with open(os.path.join(chemin, "Fiche_Candidat.md"), "w",
                          encoding="utf-8") as f:
                    f.write(fiche_texte)
        rangs.append({"ID": pid, "PROSPECT": nom, "DOSSIER": dossier,
                      "CONTACT": "a identifier", "CANAL": "a determiner",
                      "STATUT": "a_contacter", "DERNIER_CONTACT": "",
                      "RELANCES_FAITES": "0", "DATE_PROCHAINE": aujourd_hui,
                      "TACHE_ID": "", "NOTE": note,
                      "TELEPHONE": telephone, "SITE": site})
        journaliser(f"prospecteur : prospect créé — {nom} ({dossier})")

    candidats = lire_candidats()
    inventaire = lire_inventaire()
    decisions = doc_prosp.get("candidatures") or {}
    modif_candidats = False
    for c in candidats:
        d = decisions.get(c["ID"])
        if not d or c.get("STATUT") != "propose":
            continue
        if d.get("decision") == "accepte":
            c["STATUT"] = "accepte"
            marquer_inventaire(inventaire, c["NOM"], "en_cadence", "engin")
            creer_prospect(c["NOM"], f"candidat de l'engin — {c.get('ANGLE', '')}"[:180],
                           f"# {c['NOM']} — fiche candidat\n\n"
                           f"- Secteur : {c.get('SECTEUR', '')}\n"
                           f"- Ville : {c.get('VILLE', '')}\n"
                           f"- Site : {c.get('SITE', '')}\n"
                           f"- Téléphone : {c.get('TELEPHONE', '')}\n"
                           f"- Taille estimée : {c.get('TAILLE', '')}\n"
                           f"- Angle : {c.get('ANGLE', '')}\n"
                           f"- Source : {c.get('SOURCE', '')}\n"
                           f"- Proposé le : {c.get('PROPOSE_LE', '')}, accepté le {aujourd_hui}\n",
                           telephone=c.get("TELEPHONE", ""), site=c.get("SITE", ""))
            modif_tsv = True
        elif d.get("decision") == "rejete":
            c["STATUT"] = "rejete"
            marquer_inventaire(inventaire, c["NOM"], "rejete", "engin")
            journaliser(f"prospecteur : candidat rejeté — {c['NOM']}")
        modif_candidats = True
    if modif_candidats:
        ecrire_candidats(candidats)

    # « Cadencer » depuis l'inventaire ou ajout manuel : même chemin. Si
    # l'inventaire connaît déjà des coordonnées, le journal en hérite.
    for ajout in (doc_prosp.get("ajouts") or {}).values():
        nom = (ajout.get("nom") or "").strip()
        if nom and not any(r["PROSPECT"].lower() == nom.lower() for r in rangs):
            inv = next((r for r in inventaire
                        if r["NOM"].strip().lower() == nom.lower()), {})
            # « contacteLe » : l'ajout vient d'un courriel DÉJÀ envoyé (la
            # passerelle des batchs {{MANDAT_EXEMPLE}} le dépose au moment du « marquer
            # envoyé »). Le prospect entre alors au journal comme contacté, à
            # sa date réelle — sinon la cadence lui préparerait un premier
            # contact déjà fait, et le prospect recevrait deux fois la même
            # approche.
            contacte = (ajout.get("contacteLe") or "").strip()
            creer_prospect(nom,
                           f"contacté le {contacte} — {ajout.get('origine') or 'courriel préparé'}"
                           if contacte else "mis en cadence depuis la page",
                           telephone=inv.get("TELEPHONE", ""),
                           site=inv.get("LIEN", ""))
            if contacte:
                r = rangs[-1]
                r["STATUT"] = "contacte_sans_reponse"
                r["DERNIER_CONTACT"] = contacte
                r["COURRIEL"] = ajout.get("courriel") or r.get("COURRIEL", "")
                try:
                    depart = date.fromisoformat(contacte)
                except ValueError:
                    depart = date.today()
                r["DATE_PROCHAINE"] = (depart + timedelta(days=JOURS_ENTRE_RELANCES)).isoformat()
                journaliser(f"prospecteur : {nom} entre au journal déjà contacté "
                            f"({contacte}) — relance le {r['DATE_PROCHAINE']}")
            marquer_inventaire(inventaire, nom, "en_cadence")
            modif_tsv = True

    # ── 0b. appliquer les signaux déposés depuis la page web ──
    # Un signal humain (répondu, RDV…) prime sur tout : il arrête la cadence.
    # Une tâche pendante rendue caduque est REPORTÉE au tableau de bord (avec
    # motif), jamais laissée « à faire » pour un prospect qu'on ne relance plus.
    def caduque(tid, motif):
        t_c = taches.get(tid or "")
        if t_c and t_c.get("statut") not in ("fait", "reporte"):
            t_c["statut"] = "reporte"
            t_c["detail"] = ((t_c.get("detail") or "") +
                             f"\n\n[Reportée le {aujourd_hui} : {motif}]").strip()
            t_c["maj"] = int(time.time() * 1000)
            return True
        return False

    # ── 0c. retraits demandés depuis la page (le « × » d'une ligne) ──
    # Un retrait ne discute pas l'état d'avancement : le prospect sort de la
    # liste, qu'il soit candidat, en cadence ou déjà client. Le journal le
    # passe en « abandonne » (la cadence s'arrête), l'inventaire et les
    # candidats en « rejete » — un rejet ne se repropose jamais, sinon le
    # prospect reviendrait au cycle suivant et le geste n'aurait servi à rien.
    for cle in (doc_prosp.get("retraits") or {}):
        vu = False
        for r in rangs:
            if r["ID"] != cle:
                continue
            r["STATUT"] = "abandonne"
            if caduque(r["TACHE_ID"], f"retiré depuis la page — {r['PROSPECT']}"):
                modif_etat = True
            r["TACHE_ID"] = ""
            marquer_inventaire(inventaire, r["PROSPECT"], "rejete")
            vu = modif_tsv = True
            journaliser(f"prospecteur : retiré du journal — {r['PROSPECT']}")
        for c in candidats:
            if c["ID"] == cle and c.get("STATUT") != "rejete":
                c["STATUT"] = "rejete"
                marquer_inventaire(inventaire, c["NOM"], "rejete")
                vu = modif_candidats = True
                journaliser(f"prospecteur : candidat retiré — {c['NOM']}")
        for r in inventaire:
            if r["ID"] == cle and r["STATUT"] != "rejete":
                r["STATUT"] = "rejete"
                vu = True
                journaliser(f"prospecteur : retiré de l'inventaire — {r['NOM']}")
        if not vu:
            journaliser(f"prospecteur : retrait sans correspondance — « {cle} »")
    if modif_candidats:
        ecrire_candidats(candidats)
    ecrire_inventaire(inventaire)

    SIGNAUX_PERMIS = {"repondu", "rdv_fixe", "client", "dormant", "abandonne", "a_contacter"}
    signaux = doc_prosp.get("signaux") or {}
    for r in rangs:
        s = signaux.get(r["ID"])
        if not s or s.get("statut") not in SIGNAUX_PERMIS:
            continue
        r["STATUT"] = s["statut"]
        if caduque(r["TACHE_ID"], f"signal « {s['statut']} » sur {r['PROSPECT']}"):
            modif_etat = True
        r["TACHE_ID"] = ""
        if s["statut"] == "a_contacter":     # réactivation : cadence repartie à zéro
            r["RELANCES_FAITES"] = "0"
            r["APPELS"] = "0"
            r["APPELS_JOINTS"] = "0"
            r["DATE_PROCHAINE"] = aujourd_hui
        modif_tsv = True
        journaliser(f"prospecteur : signal appliqué — {r['PROSPECT']} → {r['STATUT']}")

    # ── 1. fermer la boucle sur les envois confirmés ──
    # AVANT d'appliquer les appels : un envoi marqué fait doit être consigné
    # avant qu'une bascule « injoignable » ne vide la tâche qui le prouve.
    for r in rangs:
        tid = r.get("TACHE_ID", "")
        if not tid or r["STATUT"] not in ("relance_preparee", "contact_prepare"):
            continue
        t = taches.get(tid)
        if not t:
            continue
        if t.get("statut") == "fait":
            premier = r["STATUT"] == "contact_prepare"
            r["DERNIER_CONTACT"] = aujourd_hui
            r["TACHE_ID"] = ""
            if premier:
                r["STATUT"] = "contacte_sans_reponse"
            else:
                r["RELANCES_FAITES"] = str(int(r["RELANCES_FAITES"] or 0) + 1)
                if int(r["RELANCES_FAITES"]) >= MAX_RELANCES:
                    r["STATUT"] = "dormant"
                    r["NOTE"] = (r["NOTE"] + " ; " if r["NOTE"] else "") + \
                        f"dormant depuis le {aujourd_hui} ({MAX_RELANCES} relances sans réponse)"
                else:
                    r["STATUT"] = "relance_envoyee"
            r["DATE_PROCHAINE"] = (date.today() + timedelta(days=JOURS_ENTRE_RELANCES)).isoformat()
            modif_tsv = True
            journaliser(f"prospecteur : {r['PROSPECT']} → {r['STATUT']}")

    # ── 1b. appliquer les tentatives d'appel consignées depuis la page ──
    # La page dépose { appels: { id: [{date, resultat, ts}] } } ; on incrémente
    # les compteurs du journal. 3 tentatives sans un seul joint = « injoignable »
    # (jamais pour un statut humain : répondu, RDV, client, abandonné, dormant).
    EN_CADENCE = {"a_contacter", "contact_prepare", "contacte_sans_reponse",
                  "relance_preparee", "relance_envoyee"}
    appels = doc_prosp.get("appels") or {}
    ids_connus = {r["ID"] for r in rangs}
    orphelins = [k for k in appels if k not in ids_connus]
    if orphelins:
        journaliser(f"prospecteur : appels orphelins ignorés — {', '.join(orphelins)}")
    for r in rangs:
        liste = appels.get(r["ID"]) or []
        if not liste:
            continue
        faits = int(r.get("APPELS") or 0) + len(liste)
        joints = int(r.get("APPELS_JOINTS") or 0) + \
            sum(1 for a in liste if a.get("resultat") == "joint")
        r["APPELS"] = str(faits)
        r["APPELS_JOINTS"] = str(joints)
        r["DERNIER_APPEL"] = max([a.get("date", "") for a in liste] +
                                 [r.get("DERNIER_APPEL", "")])
        if faits >= 3 and joints == 0 and r["STATUT"] in EN_CADENCE:
            r["STATUT"] = "injoignable"
            if caduque(r["TACHE_ID"], f"{r['PROSPECT']} injoignable "
                       f"({faits} tentatives sans joint)"):
                modif_etat = True
            r["TACHE_ID"] = ""
            journaliser(f"prospecteur : {r['PROSPECT']} → injoignable "
                        f"({faits} tentatives sans joint)")
        modif_tsv = True

    # ── 1c. recyclage J+60 (plan Entonnoir 24) : à partir de la mi-octobre,
    # un dormant ou injoignable sans contact depuis 60 jours revient une seule
    # fois en cadence, sous un angle différent — compteurs d'appels repartis à
    # zéro, sinon la bascule injoignable resterait armée à la première tentative.
    if aujourd_hui >= "2026-10-12":
        seuil = (date.today() - timedelta(days=60)).isoformat()
        for r in rangs:
            dernier = max(r.get("DERNIER_CONTACT", ""), r.get("DERNIER_APPEL", ""))
            if r["STATUT"] in ("dormant", "injoignable") and dernier and \
               dernier <= seuil and "recyclage J+60" not in r.get("NOTE", ""):
                r["STATUT"] = "a_contacter"
                r["RELANCES_FAITES"] = "0"
                r["APPELS"] = "0"
                r["APPELS_JOINTS"] = "0"
                r["DATE_PROCHAINE"] = aujourd_hui
                r["NOTE"] = (r["NOTE"] + " ; " if r["NOTE"] else "") + \
                    f"recyclage J+60 le {aujourd_hui} - angle different"
                modif_tsv = True
                journaliser(f"prospecteur : recyclage J+60 — {r['PROSPECT']}")

    # ── 2. préparer ce qui est dû ──
    dus = [r for r in rangs if not r.get("TACHE_ID") and (
        (r["STATUT"] in ("contacte_sans_reponse", "relance_envoyee")
         and int(r["RELANCES_FAITES"] or 0) < MAX_RELANCES
         and (r["DATE_PROCHAINE"] or "9999") <= aujourd_hui)
        or r["STATUT"] == "a_contacter")]
    if ESSAI:
        print("signaux en attente :", {k: v.get("statut") for k, v in signaux.items()} or "aucun")
        print("dus :", [r["PROSPECT"] for r in dus] or "aucun")
        print("journal modifié :", modif_tsv)
        return
    fichier = os.path.join(DOSSIER_RELANCES, f"Relances_{aujourd_hui}.md")
    for r in dus:
        premier = r["STATUT"] == "a_contacter"
        brouillon = rediger(r, premier)
        if not brouillon:
            journaliser(f"prospecteur : {r['PROSPECT']} — brouillon non produit, sauté")
            continue
        os.makedirs(DOSSIER_RELANCES, exist_ok=True)
        entete_f = "" if os.path.exists(fichier) else \
            f"# Relances de prospection — {aujourd_hui}\n\nBrouillons du prospecteur. " \
            "Rien ne part tout seul : relire, ajuster, envoyer à la main, puis marquer " \
            "la tâche faite au tableau de bord.\n"
        with open(fichier, "a", encoding="utf-8") as f:
            f.write(f"{entete_f}\n---\n\n## {r['PROSPECT']} — "
                    f"{'premier contact' if premier else 'relance ' + str(int(r['RELANCES_FAITES'] or 0) + 1)}\n"
                    f"**Contact :** {r['CONTACT'] or 'à identifier'} · **Canal :** {r['CANAL']}\n\n"
                    + "\n".join("> " + l for l in brouillon.splitlines()) + "\n")
        r["TACHE_ID"] = creer_tache(etat, r, brouillon, premier, fichier)
        r["STATUT"] = "contact_prepare" if premier else "relance_preparee"
        modif_tsv = modif_etat = True
        journaliser(f"prospecteur : brouillon prêt — {r['PROSPECT']}")

    if modif_etat:
        etat["updatedAt"] = int(time.time() * 1000)
        pousser_etat(etat)
    if modif_tsv:
        ecrire_tsv(entetes, rangs)
    # Vider les boîtes traitées (les clés lues en début de cycle seulement),
    # puis pousser le miroir — un dépôt fait pendant le cycle survit.
    vider_boites(doc_prosp)
    pousser_miroir(rangs)
    journaliser(f"prospecteur : cycle terminé — {len(dus)} préparé(s)")


if __name__ == "__main__":
    main()
