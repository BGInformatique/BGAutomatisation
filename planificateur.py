#!/usr/bin/env python3
"""Traducteur systemd -> launchd (macOS) / Tâches planifiées (Windows).

Les fichiers `bg-*.service`/`bg-*.timer` de ce dépôt restent la SOURCE
UNIQUE de vérité pour « quoi lancer, et quand » — ce module les lit et
installe l'équivalent natif sur l'OS courant plutôt que de dupliquer trois
fois la même information. Sous Linux, le comportement est inchangé (symlink
vers ~/.config/systemd/user/, voir `installer_linux()` dans installer.py qui
fait exactement ce qu'il faisait avant ce module) — ce fichier ajoute
seulement les back-ends macOS et Windows.

Grammaire `OnCalendar=` reconnue (les 3 seules qui existent réellement dans
ce dépôt — toute autre syntaxe est refusée avec une erreur claire plutôt que
traduite au petit bonheur) :
  - `*-*-* HH:MM`                          -> tous les jours, une heure
  - `Jour *-*-* HH:MM`                     -> un jour de semaine précis
  - `*-*-* H1,H2,...:MM` (ou `:MM:SS`)     -> plusieurs heures, tous les jours

Limites connues, documentées plutôt que masquées :
  - `Persistent=` (rattrapage d'un passage manqué) n'a pas d'équivalent
    simple sur macOS (launchd) ni sur Windows (schtasks en ligne de
    commande — la variante XML avec `StartWhenAvailable` n'est pas générée
    ici) : ignoré, jamais simulé.
  - `RandomizedDelaySec=` n'a pas d'équivalent simple non plus : ignoré.
  - Sur Windows, un service continu (`Type=simple`/`Restart=always` côté
    systemd) devient une tâche planifiée « au logon » — PAS un vrai service
    supervisé : rien ne le relance si le processus plante. Un vrai service
    Windows demanderait une dépendance externe (NSSM, pywin32), hors de la
    contrainte « bibliothèque standard seulement » de cette suite.
"""
import dataclasses
import json
import platform
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent

_JOUR_VERS_LAUNCHD = {"Sun": 0, "Mon": 1, "Tue": 2, "Wed": 3, "Thu": 4, "Fri": 5, "Sat": 6}
_JOUR_VERS_SCHTASKS = {"Mon": "MON", "Tue": "TUE", "Wed": "WED", "Thu": "THU",
                        "Fri": "FRI", "Sat": "SAT", "Sun": "SUN"}

_RE_ONCALENDAR_JOUR = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\*-\*-\*\s+(\d{2}):(\d{2})$")
_RE_ONCALENDAR_SIMPLE = re.compile(r"^\*-\*-\*\s+([\d,]+):(\d{2})(?::(\d{2}))?$")


@dataclasses.dataclass
class Occurrence:
    heure: int
    minute: int
    jour: str = None  # "Mon".."Sun", ou None = tous les jours


@dataclasses.dataclass
class UniteMinutee:
    nom: str
    commande: list
    occurrences: list
    description: str = ""
    persistent: bool = False
    randomized_delay_sec: int = None


@dataclasses.dataclass
class UniteContinue:
    nom: str
    commande: list
    description: str = ""
    environment: dict = dataclasses.field(default_factory=dict)
    restart_sec: int = 30


# --- Lecture des fichiers .service/.timer --------------------------------

def _lire_unite(chemin):
    """Fichier ini-like (sections [Unit]/[Timer]/[Service]) -> dict
    section -> liste de (cle, valeur), car une clé (OnCalendar=) peut
    apparaître plusieurs fois dans la même section."""
    sections = {}
    section = None
    for ligne_brute in Path(chemin).read_text(encoding="utf-8").splitlines():
        ligne = ligne_brute.strip()
        if not ligne or ligne.startswith("#") or ligne.startswith(";"):
            continue
        if ligne.startswith("[") and ligne.endswith("]"):
            section = ligne[1:-1]
            sections.setdefault(section, [])
            continue
        if section is None or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        sections[section].append((cle.strip(), valeur.strip()))
    return sections


def _valeurs(sections, section, cle):
    return [v for k, v in sections.get(section, []) if k == cle]


def _valeur(sections, section, cle, defaut=None):
    vs = _valeurs(sections, section, cle)
    return vs[-1] if vs else defaut


def analyser_execstart(valeur):
    return shlex.split(valeur.strip())


def analyser_oncalendar(ligne):
    """Une valeur OnCalendar= -> liste d'Occurrence. Lève ValueError si la
    syntaxe ne correspond à aucun des 3 patrons connus de ce dépôt — mieux
    vaut un échec net qu'une traduction silencieuse fausse."""
    ligne = ligne.strip()
    m = _RE_ONCALENDAR_JOUR.match(ligne)
    if m:
        jour, h, mi = m.groups()
        return [Occurrence(heure=int(h), minute=int(mi), jour=jour)]
    m = _RE_ONCALENDAR_SIMPLE.match(ligne)
    if m:
        heures_csv, mi, _se = m.groups()
        return [Occurrence(heure=int(h), minute=int(mi)) for h in heures_csv.split(",")]
    raise ValueError(
        f"OnCalendar={ligne!r} ne correspond à aucun patron connu "
        "(quotidien HH:MM, Jour HH:MM, ou plusieurs heures H,H,..:MM) — "
        "traduction refusée plutôt que risquer un mauvais horaire."
    )


def analyser_toutes_unites(repertoire=ICI):
    """(list[UniteMinutee], list[UniteContinue]) à partir des bg-*.service/
    .timer présents dans `repertoire`. Un .service SANS .timer n'est inclus
    que s'il ressemble à un daemon continu (Type=simple, Restart=always) —
    les oneshot sans timer (bg-prospecteur, bg-recherchiste) sont invoqués
    par pilote.py/lanceur.py, pas planifiés directement : hors périmètre
    de ce traducteur, volontairement ignorés ici."""
    repertoire = Path(repertoire)
    minutees, continues = [], []
    for fic_service in sorted(repertoire.glob("bg-*.service")):
        nom = fic_service.stem
        sections = _lire_unite(fic_service)
        description = _valeur(sections, "Unit", "Description", "")
        execstart = _valeur(sections, "Service", "ExecStart")
        if not execstart:
            continue
        commande = analyser_execstart(execstart)

        fic_timer = repertoire / f"{nom}.timer"
        if fic_timer.exists():
            sec_timer = _lire_unite(fic_timer)
            occurrences = []
            for ligne in _valeurs(sec_timer, "Timer", "OnCalendar"):
                occurrences.extend(analyser_oncalendar(ligne))
            persistent = _valeur(sec_timer, "Timer", "Persistent", "false").lower() == "true"
            delay = _valeur(sec_timer, "Timer", "RandomizedDelaySec")
            minutees.append(UniteMinutee(
                nom=nom, commande=commande, occurrences=occurrences,
                description=description, persistent=persistent,
                randomized_delay_sec=int(delay) if delay else None,
            ))
        else:
            type_service = _valeur(sections, "Service", "Type", "oneshot")
            restart = _valeur(sections, "Service", "Restart", "")
            if type_service == "simple" and restart == "always":
                env = {}
                for ev in _valeurs(sections, "Service", "Environment"):
                    if "=" in ev:
                        k, _, v = ev.partition("=")
                        env[k] = v
                restart_sec = _valeur(sections, "Service", "RestartSec", "30")
                continues.append(UniteContinue(
                    nom=nom, commande=commande, description=description,
                    environment=env, restart_sec=int(restart_sec),
                ))
    return minutees, continues


# --- Interpréteur Python à utiliser pour macOS/Windows -------------------

def interpreteur_systeme():
    """Un vrai interpréteur Python du poste cible — jamais l'exécutable
    figé de installer.py lui-même une fois empaqueté (PyInstaller) : les
    scripts pilote.py/vigie.py/etc. restent des fichiers .py ordinaires,
    même quand installer.py devient un binaire autonome."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    for candidat in ("python3", "python"):
        chemin = shutil.which(candidat)
        if chemin:
            return chemin
    raise RuntimeError(
        "Aucun interpréteur Python trouvé dans le PATH (python3/python) — "
        "installez Python 3 avant de continuer : les scripts de cette suite "
        "restent des fichiers .py, même une fois l'installateur empaqueté."
    )


# --- Linux : symlink systemd (comportement existant, inchangé) ----------

def installer_linux(nom_unite, repertoire=ICI, activer=True):
    repertoire = Path(repertoire)
    cible_dir = Path.home() / ".config" / "systemd" / "user"
    cible_dir.mkdir(parents=True, exist_ok=True)
    fichiers = [f for f in (repertoire / f"{nom_unite}.service", repertoire / f"{nom_unite}.timer") if f.exists()]
    if not fichiers:
        return {"ok": False, "erreur": f"aucun fichier {nom_unite}.service/.timer trouvé"}
    for f in fichiers:
        lien = cible_dir / f.name
        if lien.is_symlink() or lien.exists():
            lien.unlink()
        lien.symlink_to(f.resolve())
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True,
                        capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "erreur": f"daemon-reload : {e}"}
    if activer:
        unite_a_activer = f"{nom_unite}.timer" if (repertoire / f"{nom_unite}.timer").exists() else f"{nom_unite}.service"
        r = subprocess.run(["systemctl", "--user", "enable", "--now", unite_a_activer],
                            capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return {"ok": False, "erreur": (r.stderr or r.stdout).strip()}
    return {"ok": True, "fichiers": [f.name for f in fichiers]}


# --- macOS : launchd -------------------------------------------------------

def _label_macos(nom):
    return f"com.bgautomatisation.{nom}"


def _chemin_plist(nom):
    return Path.home() / "Library" / "LaunchAgents" / f"{_label_macos(nom)}.plist"


def _calendrier_macos(occurrences):
    entrees = []
    for occ in occurrences:
        d = {"Hour": occ.heure, "Minute": occ.minute}
        if occ.jour:
            d["Weekday"] = _JOUR_VERS_LAUNCHD[occ.jour]
        entrees.append(d)
    return entrees[0] if len(entrees) == 1 else entrees


def installer_macos_minutee(unite, repertoire=ICI, activer=True):
    commande = [interpreteur_systeme()] + list(unite.commande[1:])
    plist = {
        "Label": _label_macos(unite.nom),
        "ProgramArguments": commande,
        "StartCalendarInterval": _calendrier_macos(unite.occurrences),
    }
    chemin = _chemin_plist(unite.nom)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "wb") as f:
        plistlib.dump(plist, f)
    limites = []
    if unite.persistent:
        limites.append("Persistent (rattrapage d'un passage manqué) : pas d'équivalent launchd pour un intervalle calendaire — non reproduit.")
    if unite.randomized_delay_sec:
        limites.append("RandomizedDelaySec : pas d'équivalent launchd simple — non reproduit.")
    if not activer:
        return {"ok": True, "plist": str(chemin), "limites": limites}
    r = subprocess.run(["launchctl", "load", "-w", str(chemin)], capture_output=True, text=True)
    if r.returncode != 0:
        return {"ok": False, "erreur": (r.stderr or r.stdout).strip()}
    return {"ok": True, "plist": str(chemin), "limites": limites}


def installer_macos_continue(unite, repertoire=ICI, activer=True):
    commande = [interpreteur_systeme()] + list(unite.commande[1:])
    env = {k: v for k, v in unite.environment.items() if k != "DISPLAY"}
    # DISPLAY est une notion X11/Linux ; les agents launchd tournent déjà
    # dans la session graphique de l'utilisateur sur macOS, sans équivalent
    # à fournir.
    plist = {
        "Label": _label_macos(unite.nom),
        "ProgramArguments": commande,
        "RunAtLoad": True,
        "KeepAlive": True,
    }
    if env:
        plist["EnvironmentVariables"] = env
    chemin = _chemin_plist(unite.nom)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "wb") as f:
        plistlib.dump(plist, f)
    if not activer:
        return {"ok": True, "plist": str(chemin)}
    r = subprocess.run(["launchctl", "load", "-w", str(chemin)], capture_output=True, text=True)
    if r.returncode != 0:
        return {"ok": False, "erreur": (r.stderr or r.stdout).strip()}
    return {"ok": True, "plist": str(chemin)}


def desinstaller_macos(nom):
    chemin = _chemin_plist(nom)
    if chemin.exists():
        subprocess.run(["launchctl", "unload", "-w", str(chemin)], capture_output=True, text=True)
        chemin.unlink()


def statut_macos(nom):
    sortie = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    return "installé" if _label_macos(nom) in sortie else "non-installé"


# --- Windows : Tâches planifiées (schtasks) -------------------------------

def _nom_tache_windows(nom, suffixe=None):
    base = f"BGAutomatisation\\{nom}"
    return f"{base}-{suffixe}" if suffixe else base


def installer_windows_minutee(unite, repertoire=ICI, activer=True):
    commande = [interpreteur_systeme()] + list(unite.commande[1:])
    ligne_commande = subprocess.list2cmdline(commande)
    limites = []
    if unite.persistent:
        limites.append("Persistent : pas de rattrapage automatique via schtasks en ligne de commande (StartWhenAvailable demande un fichier XML, non généré ici) — non reproduit.")
    if unite.randomized_delay_sec:
        limites.append("RandomizedDelaySec : pas d'équivalent schtasks simple — non reproduit.")

    jours = {occ.jour for occ in unite.occurrences}
    taches = []
    if jours == {None}:
        if len(unite.occurrences) == 1:
            occ = unite.occurrences[0]
            taches.append((_nom_tache_windows(unite.nom),
                            ["/sc", "DAILY", "/st", f"{occ.heure:02d}:{occ.minute:02d}"]))
        else:
            for occ in unite.occurrences:
                taches.append((_nom_tache_windows(unite.nom, suffixe=f"{occ.heure:02d}{occ.minute:02d}"),
                                ["/sc", "DAILY", "/st", f"{occ.heure:02d}:{occ.minute:02d}"]))
    elif None not in jours:
        for occ in unite.occurrences:
            jour_w = _JOUR_VERS_SCHTASKS[occ.jour]
            taches.append((_nom_tache_windows(unite.nom, suffixe=jour_w),
                            ["/sc", "WEEKLY", "/d", jour_w, "/st", f"{occ.heure:02d}:{occ.minute:02d}"]))
    else:
        return {"ok": False, "erreur": "mélange jours précis / quotidien non supporté par ce traducteur"}

    if not activer:
        return {"ok": True, "taches": [t[0] for t in taches], "limites": limites}

    erreurs = []
    noms_crees = []
    for nom_tache, args_horaire in taches:
        r = subprocess.run(["schtasks", "/create", "/f", "/tn", nom_tache, "/tr", ligne_commande] + args_horaire,
                            capture_output=True, text=True)
        if r.returncode == 0:
            noms_crees.append(nom_tache)
        else:
            erreurs.append(f"{nom_tache} : {(r.stderr or r.stdout).strip()}")
    if erreurs:
        return {"ok": False, "erreur": " ; ".join(erreurs), "taches": noms_crees, "limites": limites}
    return {"ok": True, "taches": noms_crees, "limites": limites}


def installer_windows_continue(unite, repertoire=ICI, activer=True):
    commande = [interpreteur_systeme()] + list(unite.commande[1:])
    ligne_commande = subprocess.list2cmdline(commande)
    nom_tache = _nom_tache_windows(unite.nom)
    limite = ("Tâche « au logon », PAS un vrai service supervisé : si le "
              "processus plante, rien ne le relance automatiquement "
              "(contrairement à Restart=always sous systemd/launchd). Limite "
              "connue de schtasks sans dépendance externe (NSSM/pywin32), "
              "documentée volontairement plutôt que masquée.")
    if not activer:
        return {"ok": True, "taches": [nom_tache], "limites": [limite]}
    r = subprocess.run(["schtasks", "/create", "/f", "/tn", nom_tache, "/tr", ligne_commande, "/sc", "ONLOGON"],
                        capture_output=True, text=True)
    if r.returncode != 0:
        return {"ok": False, "erreur": (r.stderr or r.stdout).strip(), "limites": [limite]}
    return {"ok": True, "taches": [nom_tache], "limites": [limite]}


def desinstaller_windows_tache(nom_tache):
    subprocess.run(["schtasks", "/delete", "/tn", nom_tache, "/f"], capture_output=True, text=True)


def statut_windows(nom):
    r = subprocess.run(["schtasks", "/query", "/tn", _nom_tache_windows(nom)], capture_output=True, text=True)
    # Approximation : pour une unité éclatée en plusieurs tâches suffixées
    # (plusieurs heures/jour), la tâche de base n'existe pas telle quelle —
    # affiche « non-installé » même si les sous-tâches existent. Cosmétique
    # seulement (le bouton « installer » reste idempotent grâce à /f), pas
    # une erreur fonctionnelle.
    return "installé" if r.returncode == 0 else "non-installé"


# --- Dispatch générique, utilisé par installer.py -------------------------

def installer_unite_minutee(unite, repertoire=ICI, activer=True):
    systeme = platform.system()
    if systeme == "Linux":
        return installer_linux(unite.nom, repertoire, activer=activer)
    if systeme == "Darwin":
        return installer_macos_minutee(unite, repertoire, activer=activer)
    if systeme == "Windows":
        return installer_windows_minutee(unite, repertoire, activer=activer)
    return {"ok": False, "erreur": f"OS non supporté : {systeme}"}


def installer_unite_continue(unite, repertoire=ICI, activer=True):
    systeme = platform.system()
    if systeme == "Linux":
        return installer_linux(unite.nom, repertoire, activer=activer)
    if systeme == "Darwin":
        return installer_macos_continue(unite, repertoire, activer=activer)
    if systeme == "Windows":
        return installer_windows_continue(unite, repertoire, activer=activer)
    return {"ok": False, "erreur": f"OS non supporté : {systeme}"}


def statut_natif(nom):
    systeme = platform.system()
    if systeme == "Darwin":
        return statut_macos(nom)
    if systeme == "Windows":
        return statut_windows(nom)
    return "inconnu"


# --- CLI : listage, installation manuelle, auto-test pour la CI ----------

def _auto_test():
    """Installe une unité FACTICE inoffensive (juste un `print`, à un
    horaire improbable) sur l'OS courant, vérifie qu'elle apparaît dans le
    planificateur natif, puis la retire. C'est la seule vérification
    réelle possible des back-ends macOS/Windows depuis une machine Linux —
    utilisé par la CI (voir .github/workflows/build-installer.yml)."""
    systeme = platform.system()
    nom = "bgautomatisation-auto-test"
    unite = UniteMinutee(
        nom=nom,
        commande=[interpreteur_systeme(), "-c", "print('ok')"],
        occurrences=[Occurrence(heure=23, minute=59, jour="Sun")],
    )

    if systeme == "Linux":
        print("auto-test Linux : ignoré ici — le back-end Linux se contente de "
              "symlinker des fichiers .service/.timer réels du dépôt, déjà "
              "testé indirectement via installer.py.")
        return
    if systeme == "Darwin":
        r = installer_macos_minutee(unite)
        print(json.dumps(r, ensure_ascii=False))
        assert r["ok"], "échec installation launchd"
        sortie = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
        assert _label_macos(nom) in sortie, "la tâche factice n'apparaît pas dans `launchctl list`"
        desinstaller_macos(nom)
        sortie2 = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
        assert _label_macos(nom) not in sortie2, "la tâche factice est toujours là après désinstallation"
        print("auto-test macOS : OK")
    elif systeme == "Windows":
        r = installer_windows_minutee(unite)
        print(json.dumps(r, ensure_ascii=False))
        assert r["ok"], "échec création tâche planifiée"
        for tache in r["taches"]:
            q1 = subprocess.run(["schtasks", "/query", "/tn", tache], capture_output=True, text=True)
            assert q1.returncode == 0, f"tâche {tache} introuvable après création"
            desinstaller_windows_tache(tache)
            q2 = subprocess.run(["schtasks", "/query", "/tn", tache], capture_output=True, text=True)
            assert q2.returncode != 0, f"tâche {tache} toujours là après suppression"
        print("auto-test Windows : OK")
    else:
        print(f"auto-test : OS non supporté ({systeme})")


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sous = ap.add_subparsers(dest="commande", required=True)

    p_lister = sous.add_parser("lister", help="Liste les unités détectées")
    p_lister.add_argument("repertoire", nargs="?", default=str(ICI))

    p_test = sous.add_parser("verifier", help="Vérifie la traduction des 8 fichiers .timer réels (sans rien installer)")
    p_test.add_argument("repertoire", nargs="?", default=str(ICI))

    sous.add_parser("auto-test", help="Installe puis retire une unité factice sur cet OS — vérification réelle en CI")

    args = ap.parse_args()
    if args.commande == "lister":
        minutees, continues = analyser_toutes_unites(args.repertoire)
        for u in minutees:
            jours = ", ".join(sorted({o.jour or "tous les jours" for o in u.occurrences}))
            print(f"[minutée] {u.nom} : {len(u.occurrences)} passage(s) ({jours}) — {' '.join(u.commande)}")
        for u in continues:
            print(f"[continue] {u.nom} : {' '.join(u.commande)}")
    elif args.commande == "verifier":
        minutees, _continues = analyser_toutes_unites(args.repertoire)
        for u in minutees:
            print(f"{u.nom} : {[dataclasses.asdict(o) for o in u.occurrences]}")
        print(f"{len(minutees)} unité(s) minutée(s) analysée(s) sans erreur.")
    elif args.commande == "auto-test":
        _auto_test()


if __name__ == "__main__":
    _cli()
