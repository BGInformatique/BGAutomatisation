# BGAutomatisation

> *Un des quatre modèles neutres du [portfolio public de BG Informatique](https://bginformatique.ca) — service informatique pour PME et particuliers, Saint-Jérôme et Laurentides.*
>
> C'est la suite que je fais tourner moi-même pour mon propre marketing, pas une démo écrite pour l'occasion — d'où le ton opérationnel qui suit : installation, jetons à configurer, systemd. Le principe qui structure tout le reste : un orchestrateur (`lanceur.py`) exécute des agents Claude à partir d'une file Firestore, mais **rien de risqué ne part sans un geste humain explicite** — publier, envoyer, dépenser s'arrêtent tous au guichet d'autorisations avant de continuer.

**MODÈLE NEUTRE.** Voir `PARAMETRES-A-CONFIGURER.md` avant tout déploiement.

Suite d'automatisation qui fait avancer un tableau de bord marketing sans
intervention constante : lance des tâches Claude, surveille les services,
prospecte de nouveaux clients, publie sur Facebook et Instagram — et
s'arrête pour demander un accord humain chaque fois que le geste sort du
cadre qu'on lui a fixé.

## Par où commencer

1. `00-Demarrage/` — checklist des comptes à créer et installation d'OpenClaw
   en mode gratuit. Prérequis de tout le reste.
2. `PARAMETRES-A-CONFIGURER.md` — tous les jetons `{{...}}` à remplacer, et
   ce qui est délibérément laissé en exemple plutôt que génériquement
   configurable.
3. Un `LISEZ-MOI_*.md` par pièce : `LISEZ-MOI_Pilote.md`,
   `LISEZ-MOI_Vigie.md`, `LISEZ-MOI_Publicateur.md`,
   `LISEZ-MOI_Publicateur_Instagram.md`, `LISEZ-MOI_Courriels_Mandat_Exemple.md`,
   `LISEZ-MOI_Espace_Client.md`.

## Les pièces

| Fichier | Rôle |
|---|---|
| `lanceur.py` | Le cœur : exécute `claude -p` pour chaque demande déposée dans Firestore, écrit le résultat, gère le guichet d'autorisations |
| `autorisations.py` | Le guichet, en ligne de commande : lister, voir, accorder, refuser, corriger |
| `pilote.py` | Fait avancer le tableau de bord tout seul, une tâche à la fois |
| `vigie.py` | Surveillance quotidienne (services, guichet, montage Facebook, etc.) et alertes |
| `pont_clients.py` | Fait passer les demandes d'un espace client externe vers les outils internes, et vice-versa |
| `publicateur.py` / `publicateur_instagram.py` | Publication automatique Facebook / Instagram, une fois par semaine |
| `installer_jeton.py` / `configurer_instagram.py` / `renouveler_instagram.py` | Mise en place et renouvellement des jetons Facebook / Instagram |
| `sante_facebook.py` | Diagnostic en un coup d'œil du montage Facebook |
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
