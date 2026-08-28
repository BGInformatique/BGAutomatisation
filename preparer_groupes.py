#!/usr/bin/env python3
"""Préparateur de publications — groupes Facebook (Page {{ENTREPRISE}}).

Meta a retiré en avril 2024 tout accès API à la publication dans les groupes
(permission publish_to_groups supprimée pour toujours) : ce script ne publie
jamais rien lui-même. Il PRÉPARE, et le clic final reste humain :

  1. selon le calendrier de _File_Groupes.tsv, détermine le groupe du jour ;
  2. demande à Opus (via OpenClaw, agent {{AGENT_OPENCLAW}}) d'écrire UN texte
     neuf, dans la voix de {{ENTREPRISE}} (Voix-{{ENTREPRISE}}-Facebook.md) — jamais un texte déjà
     écrit d'avance. _Historique_Groupes.tsv ne sert qu'à lui dire quels
     sujets sont déjà couverts, pour ne jamais répéter un message ;
  3. ouvre un onglet Chrome sur le groupe et COPIE le texte dans le
     presse-papier (xclip) ;
  4. consigne la date et le sujet, pour ne jamais resolliciter le même
     groupe deux fois dans la semaine ni répéter un sujet déjà traité.

La dernière étape — coller (Ctrl+V) et cliquer Publier — reste VOLONTAIREMENT
humaine. Taper le texte à la place de l'utilisateur demanderait de piloter le
navigateur sans supervision, sur un horaire fixe et répétitif : exactement le
genre de comportement que la détection anti-abus de Meta repère. Ouvrir un
onglet et préparer le presse-papier ne touche à rien sur Facebook ; le clic
final reste toujours le vôtre.

Spotted St-Eustache est un cas à part : ses règles n'autorisent les
publications d'entreprise que le SAMEDI. Aucun rattrapage un autre jour pour
ce groupe-là. Les autres groupes tolèrent un léger retard (pas de rattrapage
en cours de semaine, pour ne jamais publier deux fois au même groupe à moins
de six jours d'écart).

    python3 preparer_groupes.py --essai    # écrit le texte, ne touche à rien d'autre

xclip doit être installé (sudo apt install xclip) — sans lui, le script
prévient et s'arrête avant d'ouvrir quoi que ce soit. L'appel à Opus prend
une à quelques minutes : c'est normal, le script attend.
"""
import os
import re
import subprocess
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import journaliser  # noqa: E402

CONTENUS = os.path.expanduser("~/Bureau/{{ENTREPRISE}}/02_Marketing/Campagne_BG/Contenus")
VOIX = os.path.join(CONTENUS, "Voix-{{ENTREPRISE}}-Facebook.md")
LOT_ORIGINE = os.path.join(CONTENUS, "Facebook-Residentiel-Lot-1.md")   # sujets de départ
FILE_TSV = os.path.join(CONTENUS, "_File_Groupes.tsv")
HISTORIQUE_TSV = os.path.join(CONTENUS, "_Historique_Groupes.tsv")
COLS_FILE = ["GROUPE", "URL", "JOUR", "PUBLIE_LE"]
COLS_HIST = ["DATE", "GROUPE", "SUJET"]
JOURS_MIN_ENTRE = 6                # jamais deux fois au même groupe à moins de 6 jours
GROUPE_JOUR_STRICT = "Spotted St-Eustache"   # samedi seulement, aucun rattrapage
NB_SUJETS_RAPPELES = 20            # combien de sujets récents on rappelle à Opus
OPENCLAW = os.path.expanduser("~/.npm-global/bin/openclaw")
AGENT = "{{AGENT_OPENCLAW}}"
MODELE = "claude-cli/claude-opus-4-8"
ESSAI = "--essai" in sys.argv

# Ce que la critique du 2026-08-24 (Opus, sur le lot 1) a identifié comme les
# travers à éviter — redonné à chaque génération pour ne pas les reproduire.
LECONS_CRITIQUE = """\
Défauts à éviter, identifiés lors d'une critique du lot précédent :
- Pas de glose recyclée après la citation d'ouverture (« C'est l'appel que je
  reçois le plus souvent », « C'est la phrase que j'entends… » et variantes) —
  va direct après la citation, comme un vrai deuxième temps de conversation.
- Une vraie blague tôt dans le texte, pas juste de la réassurance empathique.
  L'absolution (« vous n'êtes pas jugé ») reste bienvenue UNE fois, pas comme
  formule finale systématique.
- Le corps du texte doit tenir le registre parlé/joual de la citation
  d'ouverture, pas retomber en français de manuel dès la deuxième phrase.
- Évite la structure en liste à puces par défaut — varie : parfois une scène,
  parfois une seule question, parfois un dialogue, pas toujours « dans
  l'ordre : 1. 2. 3. ».
- Ne recopie pas une formule déjà utilisée mot pour mot dans un autre texte
  (ex. « je ne vends pas de matériel, donc je n'ai aucun intérêt à… ») —
  la même idée, dite autrement à chaque fois.
"""


def lire_voix():
    return open(VOIX, encoding="utf-8").read() if os.path.exists(VOIX) else ""


def sujets_de_depart():
    """Titres du lot 1 (déjà publiés/en rotation ailleurs) — à ne pas répéter
    telles quelles comme "nouveau" sujet pour les groupes."""
    if not os.path.exists(LOT_ORIGINE):
        return []
    texte = open(LOT_ORIGINE, encoding="utf-8").read()
    return [m.group(1).strip() for m in
            re.finditer(r"^## \d+ — (.+?)$", texte, re.M)]


def lire_tsv(chemin, cols):
    if not os.path.exists(chemin):
        return []
    lignes = open(chemin, encoding="utf-8").read().splitlines()
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


def ecrire_tsv(chemin, cols, rangs):
    corps = "\n".join(["\t".join(cols)] +
                      ["\t".join(r.get(c, "") for c in cols) for r in rangs]) + "\n"
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(corps)


NOMS_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def groupe_du_jour(rangs, aujourd_hui):
    """Le premier groupe dû aujourd'hui et pas encore préparé aujourd'hui, ou None."""
    jour_iso = aujourd_hui.isoweekday()  # 1=lundi … 7=dimanche
    for r in rangs:
        if int(r["JOUR"]) != jour_iso:
            continue
        if r["GROUPE"] == GROUPE_JOUR_STRICT and jour_iso != 6:
            continue  # ceinture et bretelles
        if r["PUBLIE_LE"]:
            ecart = (aujourd_hui - date.fromisoformat(r["PUBLIE_LE"])).days
            if ecart < JOURS_MIN_ENTRE:
                continue
        return r
    return None


def sujets_deja_couverts(historique):
    recents = [h["SUJET"] for h in historique[-NB_SUJETS_RAPPELES:] if h.get("SUJET")]
    return sujets_de_depart() + recents


def construire_prompt(groupe, sujets_evites):
    liste = "\n".join(f"- {s}" for s in sujets_evites) or "(aucun pour l'instant)"
    return f"""Écris UNE publication Facebook neuve pour {{ENTREPRISE}}, à poster
dans le groupe communautaire « {groupe} » (Laurentides). Registre B de la voix
de {{ENTREPRISE}} (voir Voix-{{ENTREPRISE}}-Facebook.md, déjà dans ton contexte de travail) : part
d'une phrase de client entendue, explication technique plate sans métaphore
filée, une vraie blague tôt dans le texte, finit sur la permission plutôt
qu'un appel à l'action impératif. Le numéro {{TELEPHONE}} à la fin.

{LECONS_CRITIQUE}

Sujets déjà couverts récemment — choisis-en un AUTRE, dans l'offre réelle de
{{ENTREPRISE}} (ordinateur lent, virus/arnaques, WiFi, sauvegarde photo, courriel piraté,
nouvel appareil, imprimante, mots de passe, aînés, ou le volet travail :
Microsoft 365, automatisation, IA/Copilot pour PME) :
{liste}

Réponds STRICTEMENT dans ce format, rien avant, rien après :
SUJET: résumé du sujet en une courte ligne
TITRE: titre du billet
---
le corps du texte complet, prêt à publier, sur autant de lignes qu'il faut
"""


def appeler_opus(message):
    r = subprocess.run(
        [OPENCLAW, "agent", "--agent", AGENT, "--model", MODELE,
         "--message", message, "--timeout", "280"],
        capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "sortie vide").strip()[:500])
    return r.stdout


def extraire_reponse(sortie):
    m_sujet = re.search(r"^SUJET:\s*(.+)$", sortie, re.M)
    m_titre = re.search(r"^TITRE:\s*(.+)$", sortie, re.M)
    if "---" not in sortie or not m_sujet or not m_titre:
        raise RuntimeError("réponse d'Opus dans un format inattendu — "
                            "voir la sortie brute dans le journal")
    corps = sortie.split("---", 1)[1].strip()
    return m_sujet.group(1).strip(), m_titre.group(1).strip(), corps


def presse_papier_dispo():
    return subprocess.run(["which", "xclip"], capture_output=True).returncode == 0


def copier_presse_papier(texte):
    subprocess.run(["xclip", "-selection", "clipboard"],
                   input=texte.encode("utf-8"), check=True)


def ouvrir_onglet(url, env):
    subprocess.Popen(["google-chrome", url], env=env, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    if not os.path.exists(FILE_TSV):
        journaliser("préparateur groupes : _File_Groupes.tsv introuvable")
        return 1

    rangs = lire_tsv(FILE_TSV, COLS_FILE)
    aujourd_hui = date.today()
    r = groupe_du_jour(rangs, aujourd_hui)
    if not r:
        if ESSAI:
            print(f"Rien à préparer aujourd'hui ({NOMS_JOURS[aujourd_hui.isoweekday() - 1]}).")
        return 0

    historique = lire_tsv(HISTORIQUE_TSV, COLS_HIST)
    evites = sujets_deja_couverts(historique)
    prompt = construire_prompt(r["GROUPE"], evites)

    try:
        sortie = appeler_opus(prompt)
        sujet, titre, texte = extraire_reponse(sortie)
    except Exception as e:
        journaliser(f"préparateur groupes : échec de génération pour {r['GROUPE']} : {e!r}")
        return 1

    if ESSAI:
        print(f"s'ouvrirait maintenant → {r['GROUPE']} ({r['URL']})")
        print(f"sujet : {sujet}\ntitre : {titre}\n\n{texte}")
        return 0

    if not presse_papier_dispo():
        journaliser("préparateur groupes : xclip absent (sudo apt install xclip) — "
                    "rien n'est ouvert tant qu'il manque")
        return 1

    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    copier_presse_papier(texte)
    ouvrir_onglet(r["URL"], env)

    r["PUBLIE_LE"] = aujourd_hui.isoformat()
    ecrire_tsv(FILE_TSV, COLS_FILE, rangs)
    historique.append({"DATE": aujourd_hui.isoformat(), "GROUPE": r["GROUPE"], "SUJET": sujet})
    ecrire_tsv(HISTORIQUE_TSV, COLS_HIST, historique)

    journaliser(f"préparateur groupes : {r['GROUPE']} — « {titre} » (sujet : {sujet}) "
                "copié dans le presse-papier, onglet ouvert — reste à coller et publier")
    return 0


if __name__ == "__main__":
    sys.exit(main())
