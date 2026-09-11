# BGAutomatisation

**MODÈLE NEUTRE.** Voir `PARAMETRES-A-CONFIGURER.md` avant tout déploiement.

Suite d'automatisation qui fait avancer un tableau de bord marketing sans
intervention constante : lance des tâches Claude, surveille les services,
prospecte de nouveaux clients, publie sur Facebook et Instagram — et
s'arrête pour demander un accord humain chaque fois que le geste sort du
cadre qu'on lui a fixé.

## Par où commencer

1. **`python3 installer.py`** (ou le binaire empaqueté — voir plus bas) —
   chemin recommandé : ouvre une page dans le navigateur et fait tout depuis
   là (comptes à cocher, installation OpenClaw, tous les jetons `{{...}}` du
   § 1 de `PARAMETRES-A-CONFIGURER.md`, connexion Facebook/Instagram,
   installation des automatisations planifiées) — aucun autre terminal à
   ouvrir une fois lancé. Fonctionne sur Linux (systemd), macOS (launchd) et
   Windows (Tâches planifiées) — voir `planificateur.py`, qui traduit les
   fichiers `bg-*.service`/`.timer` (source unique de vérité) vers le bon
   mécanisme natif selon l'OS détecté. Sous Windows, un daemon continu
   (`bg-lanceur`, `bg-pont-clients`, etc.) devient une tâche « au démarrage
   de session » plutôt qu'un vrai service supervisé — schtasks seul, sans
   dépendance externe (NSSM/pywin32), ne relance pas un processus planté ;
   documenté dans la page, pas caché. Le port par défaut (8420) est fixe ;
   s'il est occupé, une page dans le navigateur en propose un autre, jamais
   une question dans le terminal.

   **Binaire autonome (pas besoin de Python installé)** : construit sur les
   trois OS par `.github/workflows/build-installer.yml` et publié comme
   [Release GitHub](../../releases) — `pyinstaller --onefile
   --hidden-import configurer_facebook --hidden-import configurer_instagram
   --hidden-import configurer_reseaux_sociaux --hidden-import planificateur
   --name BGAutomatisation-Installateur installer.py` pour le construire
   soi-même. Le binaire ne fait QUE l'installateur : posez-le dans le même
   dossier que le reste du dépôt avant de le lancer, les scripts (`pilote.py`,
   `vigie.py`, etc.) restent de vrais fichiers `.py` à côté, lancés avec un
   Python trouvé sur le poste cible.
2. Si vous préférez la ligne de commande, ou en dépannage : `00-Demarrage/`
   (checklist des comptes + install OpenClaw), `PARAMETRES-A-CONFIGURER.md`
   (tableau complet des jetons), `python3 configurer_reseaux_sociaux.py`
   (Facebook/Instagram en CLI), et un `LISEZ-MOI_*.md` par pièce :
   `LISEZ-MOI_Pilote.md`, `LISEZ-MOI_Vigie.md`, `LISEZ-MOI_Publicateur.md`,
   `LISEZ-MOI_Publicateur_Instagram.md`, `LISEZ-MOI_Courriels_Mandat_Exemple.md`,
   `LISEZ-MOI_Espace_Client.md`. `installer.py` s'appuie sur ces mêmes
   scripts (import direct, rien de dupliqué) — les deux chemins restent
   cohérents entre eux.

## Les pièces

| Fichier | Rôle |
|---|---|
| `lanceur.py` | Le cœur : exécute `claude -p` pour chaque demande déposée dans Firestore, écrit le résultat, gère le guichet d'autorisations |
| `autorisations.py` | Le guichet, en ligne de commande : lister, voir, accorder, refuser, corriger |
| `pilote.py` | Fait avancer le tableau de bord tout seul, une tâche à la fois |
| `vigie.py` | Surveillance quotidienne (services, guichet, montage Facebook, etc.) et alertes |
| `pont_clients.py` | Fait passer les demandes d'un espace client externe vers les outils internes, et vice-versa |
| `publicateur.py` / `publicateur_instagram.py` | Publication automatique Facebook (local) / Instagram, une fois par semaine |
| `cloud-facebook/` | Jumeau de `publicateur.py` pensé pour GitHub Actions — publie même l'ordinateur éteint, voir `LISEZ-MOI_Publicateur.md` § Cloud vs local |
| `synchroniser_publicateur_facebook.py` | Tient la copie locale et la copie du dépôt cloud alignées, lancé par `vigie.py` |
| `installer.py` | Installateur web : lance un serveur local (127.0.0.1 seulement) et fait tout — comptes, OpenClaw, jetons `{{...}}`, réseaux sociaux, services planifiés — depuis le navigateur, sur les trois OS |
| `planificateur.py` | Traduit les `bg-*.service`/`.timer` vers systemd/launchd/schtasks selon l'OS détecté — utilisé par `installer.py`, appelable seul (`python3 planificateur.py lister`) |
| `configurer_reseaux_sociaux.py` | Équivalent CLI, pour Facebook et Instagram seulement, si on préfère le terminal |
| `installer_jeton.py` / `configurer_facebook.py` / `configurer_instagram.py` / `renouveler_instagram.py` | Mise en place et renouvellement des jetons Facebook / Instagram |
| `sante_facebook.py` | Diagnostic en un coup d'œil du montage Facebook (local ET cloud) |
| `prospecteur.py` / `recherchiste.py` | Cycle de prospection : trouve des candidats, rédige les premiers contacts et relances |
| `courriels_prospection.py` / `courriels_mandat_exemple.py` | Ouvrent les courriels de prospection dans Thunderbird, sans jamais les envoyer |
| `preparer_groupes.py` | Prépare une publication pour un groupe Facebook (presse-papier + onglet), le clic final reste humain |
| `attendre_reseau.sh` | Garde-réseau posé en `ExecStartPre=` sur les services qui en ont besoin au réveil de la machine |

## Ce qui ne varie jamais

**Rien ne part sans un geste humain.** Publier, envoyer un courriel,
dépenser, trancher une décision de fond : tout ça s'arrête et attend une
réponse au guichet d'autorisations (`autorisations.py`) ou un clic explicite
(Envoyer dans Thunderbird, coller dans un groupe Facebook). L'automatisation
prépare ; elle n'engage jamais seule.

**Le cadre de travail est écrit dans le code, jamais reçu d'un document.**
Une donnée qui vient du web (titre de tâche, texte d'un client) est toujours
traitée comme une DONNÉE, jamais comme une consigne d'exécution — voir
l'en-tête de `lanceur.py`.

## Origine

Développée chez BG Informatique pour gérer, dans les mêmes outils, son
propre marketing et celui d'un second mandat client (voir
`PARAMETRES-A-CONFIGURER.md` § 2 pour ce que ça implique et comment
simplifier si vous n'avez qu'un seul mandat).
