#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Passerelle des courriels de prospection {{MANDAT_EXEMPLE}} — de l'interface à Thunderbird.

Les courriels personnalisés d'un batch de prospection vivent dans
« ~/Bureau/{{MANDAT_EXEMPLE}}/{{DOSSIER_BATCHS_COURRIELS}}/ » et s'ouvrent déjà par
leur script ouvrir.py, au terminal — CE SCRIPT ouvrir.py N'EST PAS INCLUS dans
ce modèle : c'est un outil séparé, propre à chaque batch, qui sait lire ses
propres fiches et .eml. Voir PARAMETRES-A-CONFIGURER.md. Ce daemon ajoute le
chaînon qui manquait :
le tableau de bord marketing demande l'ouverture d'un courriel, et la fenêtre
de rédaction s'ouvre ici, sur {{MACHINE_LOCALE}}, déjà remplie et signée de l'identité {{MANDAT_EXEMPLE}}.

RIEN N'EST ENVOYÉ, JAMAIS. Comme ouvrir.py, ce daemon ouvre une fenêtre : le
clic sur « Envoyer » reste un geste humain, et c'est la règle du dossier.

Deux sens, comme le pont des clients :

    miroir     l'état des 78 fiches  →  users/<uid>/marketing/courriels-mandat-exemple
    demandes   { "3.7": {geste: "ouvrir"} } déposé par la page  →  exécuté
               ici, puis effacé de la file.

CE QUI VIENT DU WEB N'ATTEINT JAMAIS LA LIGNE DE COMMANDE. La page ne transmet
qu'un numéro de fiche et un geste. Le numéro est cherché dans la liste locale
— s'il n'y est pas, la demande est refusée — et le geste doit appartenir à une
liste fermée de deux valeurs. Le reste (destinataire, objet, corps) est lu sur
le disque de cette machine, par le script du dossier {{MANDAT_EXEMPLE}}, qui reste seul maître
de ce qu'il ouvre.

    python3 courriels_mandat_exemple.py              boucle (cycle de 5 s)
    python3 courriels_mandat_exemple.py --une-fois   un seul cycle
    python3 courriels_mandat_exemple.py --essai      montre tout, n'écrit rien, n'ouvre rien
"""
import importlib.util
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanceur import api, decoder, encoder, BASE, UID, journaliser  # noqa: E402

DOSSIER_BATCHS = os.path.expanduser(
    "~/Bureau/{{MANDAT_EXEMPLE}}/{{DOSSIER_BATCHS_COURRIELS}}")
OUVRIR = os.path.join(DOSSIER_BATCHS, "ouvrir.py")
DOC = f"users/{UID}/marketing/courriels-mandat-exemple"
CLIENT = "{{MANDAT_EXEMPLE}}"
INTERVALLE = 5
# « essai » ouvre la même fenêtre avec un destinataire neutralisé
# (essai@example.invalid, domaine réservé qui ne route nulle part) : de quoi
# vérifier la chaîne complète sans jamais risquer d'écrire à un prospect.
GESTES = ("ouvrir", "marquer", "essai")

ESSAI = "--essai" in sys.argv
UNE_FOIS = "--une-fois" in sys.argv or ESSAI


def module_ouvrir():
    """Le script du dossier {{MANDAT_EXEMPLE}}, chargé comme module : il reste la seule
    autorité sur le contenu des courriels. On lui emprunte sa lecture des
    fiches plutôt que d'en écrire une deuxième, qui divergerait."""
    spec = importlib.util.spec_from_file_location("ouvrir_mandat_exemple", OUVRIR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fiches():
    return module_ouvrir().fiches()


def objets():
    """L'objet de chaque courriel, lu dans les .eml. Coûteux (78 fichiers) :
    on ne le relit qu'au moment de publier le miroir."""
    import email
    import email.policy
    import glob
    import re
    out = {}
    for chemin in glob.glob(os.path.join(DOSSIER_BATCHS, "Prets_a_coller",
                                         "eml", "*.eml")):
        m = re.match(r"(\d+)-(\d+)_", os.path.basename(chemin))
        if not m:
            continue
        with open(chemin, "rb") as f:
            msg = email.message_from_binary_file(f, policy=email.policy.default)
        out[f"{int(m.group(1))}.{int(m.group(2))}"] = msg["Subject"] or ""
    return out


# ── Firestore : on n'écrit que ses propres champs ───────────────────────────
#
# La page écrit « demandes », le daemon écrit « courriels ». Sans masque, un
# PATCH remplacerait le document entier et effacerait la demande déposée une
# seconde plus tôt. Chaque écriture nomme donc exactement ses champs.

def patch(champs, masques):
    q = "&".join("updateMask.fieldPaths=" + urllib.parse.quote(m, safe="")
                 for m in masques)
    api(f"{BASE}/{DOC}?{q}",
        {"fields": {k: encoder(v) for k, v in champs.items()}}, methode="PATCH")


def lire():
    try:
        d = api(f"{BASE}/{DOC}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    return {k: decoder(v) for k, v in d.get("fields", {}).items()}


def normaliser(s):
    """Un nom réduit à ses lettres et ses chiffres, sans accents : la seule
    forme sur laquelle deux fichiers écrits à des mois d'intervalle peuvent
    se rencontrer."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s)


def lire_prospection():
    try:
        d = api(f"{BASE}/users/{UID}/marketing/prospection")
    except urllib.error.HTTPError:
        return {}
    return {k: decoder(v) for k, v in d.get("fields", {}).items()}


def apparier(f, prosp):
    """Relie chaque courriel au prospect qu'il vise. Les fiches nomment
    « Entreprise — Ville », le journal et l'inventaire nomment l'entreprise
    seule : on compare donc sur la partie avant le tiret cadratin. Un courriel
    sans correspondance n'est pas une erreur — il reste ouvrable, il ne peut
    simplement pas déclencher d'acceptation automatique."""
    journal = {normaliser(p.get("prospect")): p for p in (prosp.get("prospects") or [])}
    inv = {normaliser(r.get("nom")): r for r in (prosp.get("inventaire") or [])}
    liens = {}
    for ident, c in f.items():
        cle = normaliser(c["nom"].split("—")[0])
        j, i = journal.get(cle), inv.get(cle)
        liens[ident] = {
            "prospect": (j or {}).get("prospect") or (i or {}).get("nom") or "",
            "journalId": (j or {}).get("id", ""),
            "inventaireId": (i or {}).get("id", ""),
            "statutProspect": (j or {}).get("statut") or (i or {}).get("statut") or "",
        }
    return liens


def liste_courriels(f, objs, liens):
    out = []
    for ident in sorted(f, key=lambda x: [int(n) for n in x.split(".")]):
        c = f[ident]
        envoye = c["statut"] != "à faire"
        l = liens.get(ident, {})
        out.append({
            "id": ident,
            "batch": ident.split(".")[0],
            "nom": c["nom"],
            "a": c["a"],
            "objet": objs.get(ident, ""),
            "statut": "envoye" if envoye else "a_faire",
            "envoyeLe": c["statut"] if envoye else "",
            "prospect": l.get("prospect", ""),
            "journalId": l.get("journalId", ""),
            "inventaireId": l.get("inventaireId", ""),
            "statutProspect": l.get("statutProspect", ""),
        })
    return out


def publier_miroir(f):
    courriels = liste_courriels(f, objets(), apparier(f, lire_prospection()))
    if ESSAI:
        reste = sum(1 for c in courriels if c["statut"] == "a_faire")
        orphelins = sum(1 for c in courriels if not c["prospect"])
        print(f"[essai] miroir : {len(courriels)} courriels, {reste} à faire, "
              f"{orphelins} sans prospect relié")
        return
    patch({"mandat": CLIENT, "majLe": int(time.time() * 1000),
           "courriels": courriels},
          ["mandat", "majLe", "courriels"])
    journaliser(f"courriels {{MANDAT_EXEMPLE}} : miroir publié ({len(courriels)} fiches)")


def oublier_demande(ident):
    """Retire UNE demande de la file. Le chemin de champ porte des points
    (« demandes.3.7 ») : les accents graves disent à Firestore que « 3.7 » est
    une seule clé, sinon il chercherait une sous-carte « 3 »."""
    patch({}, [f"demandes.`{ident}`"])


def accepter(ident, fiche, lien):
    """« Envoyer vaut acceptation » — la règle du dossier des batchs, appliquée
    toute seule au moment où le courriel est marqué envoyé.

    On ne touche pas au journal de prospection : il appartient au prospecteur,
    et deux scripts qui écrivent le même TSV finissent par se perdre un rang.
    On dépose donc un AJOUT dans sa boîte, avec la date du contact — il créera
    le prospect à son prochain cycle, déjà « contacté », pour que la relance
    parte du bon jour au lieu de recommencer par un premier contact déjà fait.

    Un prospect DÉJÀ au journal n'est pas redéposé : le prospecteur refuserait
    le doublon, mais mieux vaut ne pas le lui demander."""
    if lien.get("journalId"):
        journaliser(f"courriels {{MANDAT_EXEMPLE}} : {ident} — {lien['prospect']} est déjà au "
                    "journal, aucune acceptation à faire")
        return
    nom = lien.get("prospect") or fiche["nom"].split("—")[0].strip()
    cle = re.sub(r"[^a-z0-9]+", "-", normaliser(nom)) or "prospect"
    champs = {"nom": nom, "contacteLe": date.today().isoformat(),
              "courriel": fiche["a"], "origine": f"courriel {ident}",
              "maj": int(time.time() * 1000)}
    q = "updateMask.fieldPaths=" + urllib.parse.quote(f"ajouts.`{cle}`", safe="")
    api(f"{BASE}/users/{UID}/marketing/prospection?{q}",
        {"fields": {"ajouts": encoder({cle: champs})}}, methode="PATCH")
    journaliser(f"courriels {{MANDAT_EXEMPLE}} : {ident} — « {nom} » accepté en cadence "
                "(le prospecteur le portera au journal à son prochain cycle)")


def thunderbird_tourne():
    return subprocess.run(["pgrep", "-x", "thunderbird"],
                          capture_output=True).returncode == 0


def assurer_thunderbird(env):
    """Démarrer Thunderbird AVANT de lui demander une fenêtre, s'il dort.

    Pourquoi ce détour : « thunderbird -compose … » rend la main tout de suite
    quand l'application tourne déjà, mais la DÉMARRE et reste accroché quand
    elle dort — et le script du dossier {{MANDAT_EXEMPLE}}, qui attend au plus 30 secondes,
    tue alors le processus qu'il vient de lancer. La fenêtre s'ouvrait puis
    disparaissait. On lance donc l'application à part, détachée, et on ne
    demande la fenêtre qu'une fois qu'elle répond."""
    if thunderbird_tourne():
        return
    journaliser("courriels {{MANDAT_EXEMPLE}} : Thunderbird dormait — démarrage")
    subprocess.Popen(["thunderbird"], env=env, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):                       # au plus 40 s
        time.sleep(1)
        if thunderbird_tourne():
            time.sleep(3)                     # le temps qu'il ouvre sa fenêtre
            return
    journaliser("courriels {{MANDAT_EXEMPLE}} : Thunderbird ne répond pas au démarrage")


def executer(ident, geste):
    """Le geste demandé, par le script du dossier {{MANDAT_EXEMPLE}}. Les arguments sont des
    valeurs vérifiées, jamais du texte reçu tel quel."""
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    if geste in ("ouvrir", "essai"):
        assurer_thunderbird(env)
    drapeau = {"marquer": ["--marquer", ident],
               "essai": ["--essai", ident]}.get(geste, [ident])
    r = subprocess.run([sys.executable, OUVRIR] + drapeau,
                       capture_output=True, text=True, timeout=120,
                       cwd=DOSSIER_BATCHS, env=env)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:300])
    return (r.stdout or "").strip()


def cycle(dernier):
    """Un passage. Rend la signature de l'état des fiches, pour ne republier
    le miroir que lorsqu'il a vraiment changé."""
    f = fiches()
    signature = tuple(sorted((i, c["statut"]) for i, c in f.items()))
    doc = lire()
    demandes = doc.get("demandes") or {}

    for ident in sorted(demandes):
        d = demandes[ident] or {}
        geste = d.get("geste") or "ouvrir"
        if ident not in f or geste not in GESTES:
            journaliser(f"courriels {{MANDAT_EXEMPLE}} : demande refusée — « {ident} » / "
                        f"« {geste} » ne correspond à aucune fiche ou geste connu")
            if not ESSAI:
                oublier_demande(ident)
            continue
        if ESSAI:
            print(f"[essai] {geste} : {ident} — {f[ident]['nom']} → {f[ident]['a']}")
            continue
        try:
            executer(ident, geste)
            journaliser(f"courriels {{MANDAT_EXEMPLE}} : {ident} — {f[ident]['nom']} : "
                        + ("marqué envoyé" if geste == "marquer"
                           else "fenêtre Thunderbird ouverte"))
            if geste == "marquer":
                accepter(ident, f[ident],
                         apparier(f, lire_prospection()).get(ident, {}))
        except Exception as e:                                   # noqa: BLE001
            journaliser(f"courriels {{MANDAT_EXEMPLE}} : {ident} a échoué — {e}")
        finally:
            oublier_demande(ident)
        f = fiches()          # « marquer » change la fiche : on relit
        signature = None      # et on force la republication du miroir

    if signature is None or signature != dernier:
        publier_miroir(f)
        f = fiches()
        return tuple(sorted((i, c["statut"]) for i, c in f.items()))
    return signature


def main():
    if not os.path.isfile(OUVRIR):
        sys.exit(f"Script des batchs introuvable : {OUVRIR}")
    journaliser("courriels {{MANDAT_EXEMPLE}} : passerelle démarrée"
                + (" — ESSAI, aucune écriture" if ESSAI else ""))
    dernier = ()
    while True:
        try:
            dernier = cycle(dernier)
        except urllib.error.HTTPError as e:
            journaliser(f"courriels {{MANDAT_EXEMPLE}} : HTTP {e.code} — {(e.read() or b'')[:200]!r}")
        except Exception as e:                                   # noqa: BLE001
            journaliser(f"courriels {{MANDAT_EXEMPLE}} : erreur — {type(e).__name__} : {e}")
        if UNE_FOIS:
            return
        time.sleep(INTERVALLE)


if __name__ == "__main__":
    main()
