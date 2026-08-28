#!/usr/bin/env python3
"""Recherchiste — l'engin de recherche de prospects {{MANDAT_EXEMPLE}}.

Lancé chaque jeudi 8 h 30 par bg-recherchiste.timer (ou à la main). Ce qu'il
fait : une recherche web par l'agent OpenClaw « {{AGENT_OPENCLAW}} » (Claude
Sonnet 5, repli Gemini puis modèle gratuit OpenRouter) selon le profil cible
du Cahier V5,
en excluant tout ce qui est déjà connu — prospects en cadence, candidats déjà
proposés (acceptés, rejetés ou en attente), prospects répertoriés aux rapports
de juin-juillet, et les CLIENTS ACTUELS de {{MANDAT_EXEMPLE}} (tirés des interventions du
time-tracker). Les trouvailles deviennent des CANDIDATS :

  - consignés dans Marketing/03_Prospection/Candidats/_Candidats.tsv ;
  - affichés dans le volet Prospection de la page web (miroir Firestore),
    où le propriétaire les accepte ou les rejette.

RIEN N'ENTRE DANS LA CADENCE SANS ACCEPTATION. Un candidat accepté est intégré
au journal par le prospecteur (dossier, fiche, premier contact) ; un rejeté ne
sera jamais reproposé.

    python3 recherchiste.py --essai    # montre les exclusions, n'appelle rien
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import api, decoder, BASE, UID, journaliser  # noqa: E402
import prospecteur as P  # noqa: E402

RAPPORT_21 = os.path.join(P.MARKETING, "00_Recherche_Marche",
                          "Rapport_21_Prospects_Laurentides_Lanaudiere.pdf")
CLIENTS_EXCLUS = os.path.join(P.MARKETING, "00_Recherche_Marche", "_Clients_Exclus.txt")
ESSAI = "--essai" in sys.argv
NB_CANDIDATS = 5
if "--nombre" in sys.argv:
    NB_CANDIDATS = max(1, min(25, int(sys.argv[sys.argv.index("--nombre") + 1])))


def clients_du_mandat():
    """Les clients actuels, tirés des interventions du time-tracker : on ne
    prospecte pas un client. Lecture seule ; l'absence du document n'arrête rien."""
    try:
        d = api(f"{BASE}/users/{UID}/timecalculator/state")
        champs = {k: decoder(v) for k, v in d.get("fields", {}).items()}
        return sorted({(iv.get("client") or "").strip()
                       for iv in champs.get("interventions") or [] if iv.get("client")})
    except Exception:
        return []


def deja_connus():
    noms = [r["PROSPECT"] for r in P.lire_tsv()[1]]
    noms += [c["NOM"] for c in P.lire_candidats()]
    noms += [r["NOM"] for r in P.lire_inventaire()]
    noms += clients_du_mandat()
    # Les 65 clients de la cartographie : la gouvernance du plan V5 interdit
    # de les verser au pipeline — ils ne doivent JAMAIS être proposés.
    if os.path.exists(CLIENTS_EXCLUS):
        for l in open(CLIENTS_EXCLUS, encoding="utf-8"):
            l = l.strip()
            if l and not l.startswith("#"):
                noms.append(l)
    return sorted({n for n in noms if n})


def repertoire_juin():
    """Extrait du rapport des 21 prospects, pour que l'engin ne les repropose pas."""
    try:
        return subprocess.run(["pdftotext", "-layout", RAPPORT_21, "-"],
                              capture_output=True, text=True, timeout=30).stdout[:5000]
    except Exception:
        return ""


def chercher(exclusions):
    prompt = f"""Tu es l'engin de recherche de prospects de {{MANDAT_EXEMPLE}} (firme TI B2B,
Rive-Nord de Montréal, Québec). Trouve {NB_CANDIDATS} entreprises candidates par
RECHERCHE WEB RÉELLE (annuaires d'entreprises, chambres de commerce, registres,
sites d'entreprises, cartes locales).

PROFIL CIBLE (Cahier V5 / audit STME 1) :
- PME de 5 à 50 postes, Rive-Nord et Laurentides (Saint-Jérôme, Blainville,
  Mirabel, Saint-Eustache, Saint-Colomban, Sainte-Thérèse…) ou Lanaudière proche.
- Secteurs validés : cliniques dentaires ou médicales, cabinets comptables ou
  professionnels, manufacturiers et transformation, construction et métiers
  spécialisés, distribution industrielle, design ou impression industrielle.
- Signaux d'intérêt : entreprise établie (10 ans et plus), informatique
  vraisemblablement sans TI interne, données sensibles (Loi 25), téléphonie
  d'affaires, logiciels de gestion vieillissants.
- À éviter : franchises et grandes chaînes, secteur public, entreprises de TI,
  entreprises hors région.

EXCLUSIONS STRICTES — ne JAMAIS proposer (déjà clients, en cadence ou répertoriés) :
{chr(10).join("- " + n for n in exclusions)}

Déjà répertoriés en juin (extrait du rapport — ne pas reproposer non plus) :
{repertoire_juin()}

RÈGLES ABSOLUES :
- Chaque entreprise doit être RÉELLE et VÉRIFIÉE par ta recherche web, avec
  l'URL de la preuve (son site ou sa fiche d'annuaire). N'invente RIEN : si tu
  ne peux vérifier que 2 entreprises, retournes-en 2.
- Si tu ne peux pas faire de recherche web, réponds exactement [] et rien d'autre.

RÉPONSE : uniquement un tableau JSON (aucun texte autour), chaque élément :
{{"nom": "...", "secteur": "...", "ville": "...", "site": "https://...",
  "telephone": "ligne principale au format 450 555-0123, vue sur le site ou la
  fiche d'annuaire — chaîne vide si introuvable, ne JAMAIS l'inventer",
  "taille": "estimation postes/employés", "angle": "pourquoi {{MANDAT_EXEMPLE}} est pertinent
  pour elle, une phrase ancrée dans SA réalité", "source": "URL de la preuve"}}"""
    texte = P.appeler_openclaw(prompt, timeout=1200)
    texte = re.sub(r"^```(?:json)?|```$", "", texte, flags=re.M).strip()
    return json.loads(texte), None


def main():
    exclusions = deja_connus()
    if ESSAI:
        print(f"exclusions ({len(exclusions)}) :", ", ".join(exclusions))
        print("candidats en attente :",
              sum(1 for c in P.lire_candidats() if c.get("STATUT") == "propose"))
        return
    try:
        trouvailles, cout = chercher(exclusions)
    except Exception as e:
        journaliser(f"recherchiste : recherche échouée — {e!r}")
        return
    if not isinstance(trouvailles, list) or not trouvailles:
        journaliser("recherchiste : aucune trouvaille (recherche web indisponible ?)")
        return

    candidats = P.lire_candidats()
    connus = {n.lower() for n in exclusions} | {c["NOM"].lower() for c in candidats}
    ajoutes = 0
    for t in trouvailles:
        nom = (t.get("nom") or "").strip()
        if not nom or nom.lower() in connus or not (t.get("source") or "").startswith("http"):
            continue
        connus.add(nom.lower())
        cid = re.sub(r"[^a-z0-9]+", "-", nom.lower()).strip("-")
        candidats.append({"ID": cid, "NOM": nom,
                          "SECTEUR": (t.get("secteur") or "")[:80],
                          "VILLE": (t.get("ville") or "")[:60],
                          "SITE": (t.get("site") or "")[:200],
                          "TELEPHONE": (t.get("telephone") or "")[:30],
                          "TAILLE": (t.get("taille") or "")[:60],
                          "ANGLE": (t.get("angle") or "")[:300],
                          "SOURCE": (t.get("source") or "")[:200],
                          "STATUT": "propose", "PROPOSE_LE": date.today().isoformat()})
        ajoutes += 1
    P.ecrire_candidats(candidats)
    # Chaque trouvaille entre aussi à l'inventaire, statut « candidat ».
    inventaire = P.lire_inventaire()
    for c in candidats:
        if c.get("STATUT") == "propose" and \
           not any(r["NOM"].strip().lower() == c["NOM"].strip().lower() for r in inventaire):
            inventaire.append({"ID": c["ID"], "NOM": c["NOM"],
                               "SECTEUR": c.get("SECTEUR", ""), "VILLE": c.get("VILLE", ""),
                               "LIEN": c.get("SITE", ""), "ORIGINE": "engin",
                               "STATUT": "candidat", "NOTE": "",
                               "TELEPHONE": c.get("TELEPHONE", "")})
    P.ecrire_inventaire(inventaire)
    P.pousser_miroir(P.lire_tsv()[1])
    journaliser(f"recherchiste : {ajoutes} candidat(s) proposé(s)"
                + (f" (coût {cout:.2f} $ US)" if isinstance(cout, float) else ""))


if __name__ == "__main__":
    main()
