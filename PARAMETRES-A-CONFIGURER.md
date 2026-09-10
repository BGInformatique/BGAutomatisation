# Paramètres à configurer

Copie neutre de **BGAutomatisation** (à l'origine « Claude_Lanceur » chez BG
Informatique) — la suite qui fait avancer un tableau de bord marketing tout
seul : lance des tâches Claude en tâche de fond, surveille les services,
prospecte, publie sur Facebook/Instagram, et arrête tout ce qui a besoin
d'un accord humain à un guichet d'autorisations en clair. Ce qui suit couvre
ce qui reste à fournir avant de faire tourner cette copie pour une autre
entreprise.

**Chemin recommandé :** `python3 installer.py` fait tout ce qui suit (jetons
compris) depuis une page dans le navigateur, sans avoir à lire ce fichier en
détail — voir `LISEZ-MOI.md`. Ce qui suit reste la référence complète pour
comprendre chaque jeton, dépanner, ou configurer à la main.

**Avant tout le reste (si vous ne passez pas par `installer.py`) :** faites
`00-Demarrage/` — comptes, logiciels, OpenClaw en mode gratuit. C'est le
prérequis de tout ce qui suit.

## 1. Jetons `{{...}}` à remplacer partout

`grep -rn '{{' .` et remplacez chaque occurrence dans TOUS les fichiers —
scripts `.py`, unités systemd, `LISEZ-MOI_*.md`. Certains jetons se répètent
dans une même chaîne (ex. un chemin complet) : remplacez-les tous, pas
seulement la première occurrence par fichier.

| Jeton | Où | Valeur |
|---|---|---|
| `{{ENTREPRISE}}` | partout | nom affiché de votre entreprise (celle qui possède BGAutomatisation) |
| `{{MACHINE_LOCALE}}` | `lanceur.py` et les `LISEZ-MOI_*` | nom/description de la machine qui fait tourner cette suite |
| `{{CHEMIN_INSTALLATION}}` | unités systemd, `pilote.py`, `vigie.py` | chemin absolu de CE dossier une fois installé (ex. `/home/vous/Bureau/VotreEntreprise/BGAutomatisation`) |
| `{{DOMAINE}}` | `vigie.py` | domaine de votre site public |
| `{{DEPOT_SITE}}` | `lanceur.py`, `vigie.py` | nom du dépôt du site (pour le cadre `clientsweb` et la bibliothèque de guides) |
| `{{PROJET_FIREBASE}}` | `lanceur.py`, `pont_clients.py` | ID de votre projet Firebase (celui des outils internes) |
| `{{HANDLE}}` | `vigie.py`, `configurer_instagram.py`, `publicateur_instagram.py`, LISEZ-MOI Instagram | identifiant GoatCounter ET nom d'utilisateur Instagram — si les deux diffèrent chez vous, dépliez ce jeton en deux avant de remplacer |
| `{{TELEPHONE}}` | `lanceur.py`, `pilote.py`, `vigie.py` | votre téléphone publié |
| `{{COURRIEL_PUBLIC}}` | `vigie.py`, `pilote.py`, `courriels_prospection.py` | votre courriel publié |
| `{{PROPRIETAIRE}}` | `prospecteur.py` | votre nom, pour la signature des courriels de prospection |
| `{{PROJET_VISUELS_INSTAGRAM}}` | `publicateur_instagram.py` | projet d'hébergement public des images Instagram (voir § 6) |
| `{{AGENT_OPENCLAW}}` | `prospecteur.py`, `preparer_groupes.py`, `recherchiste.py` | ID de l'agent OpenClaw configuré à l'étape 2 de `00-Demarrage/` |
| `{{MANDAT_EXEMPLE}}` | partout | voir § 2 — nom du second mandat, ou à retirer si vous n'en avez pas |
| `{{COURRIEL_MANDAT_EXEMPLE}}`, `{{TELEPHONE_MANDAT_EXEMPLE}}` | `courriels_mandat_exemple.py`, `courriels_prospection.py`, `prospecteur.py` | coordonnées du second mandat |
| `{{DOSSIER_BATCHS_COURRIELS}}` | `courriels_mandat_exemple.py` | voir § 7 — nom du dossier d'un batch de courriels de prospection |
| `{{ORG_GITHUB}}` | `sante_facebook.py`, `synchroniser_publicateur_facebook.py` | votre nom d'organisation/utilisateur GitHub (celui qui possède le dépôt de votre site) |
| `{{APP_FACEBOOK}}` | `configurer_facebook.py`, `LISEZ-MOI_Publicateur.md` | nom de votre app développeur Facebook (voir `LISEZ-MOI_Publicateur.md` étape 2) |
| `{{PAGE_ID_FACEBOOK}}` | `configurer_facebook.py`, `cloud-facebook/publicateur_cloud.py` | id de votre Page Facebook — présélection pratique, pas un secret ; laissez tel quel pour choisir la Page à la main au premier lancement de `configurer_facebook.py` |
| `{{FUSEAU_HORAIRE}}` | `cloud-facebook/publicateur_cloud.py` | votre fuseau au format `zoneinfo` (ex. `America/Toronto`, `Europe/Paris`) — seulement si vous activez le chemin cloud, voir § 5 |

## 2. Le mandat `{{MANDAT_EXEMPLE}}` — une vraie fonctionnalité, pas un exemple jetable

Chez BG, cette suite gère DEUX clients à la fois dans les mêmes documents
Firestore : BG elle-même, et un second mandat client réel (une firme de
prospection B2B, `{{MANDAT_EXEMPLE}}` dans cette copie). Chaque tâche, chaque
alerte, chaque unité systemd porte un `client`/`mandat` explicite pour que
les deux ne se mélangent jamais — voir `vigie.py`, `pilote.py`,
`publicateur.py`, `recherchiste.py`.

**Si vous n'avez qu'un seul mandat (vous-même)** : c'est le cas le plus
simple. Retirez de la config tout ce qui filtre sur `{{MANDAT_EXEMPLE}}` :
- `pilote.py` → `CLIENTS_EXCLUS = {"{{MANDAT_EXEMPLE}}"}` → videz l'ensemble ;
- `vigie.py` → `UNITES` → retirez les entrées `bg-prospecteur.service` et
  `bg-recherchiste.service` si vous ne les utilisez pas pour un second
  mandat ;
- ne déployez pas `courriels_mandat_exemple.py`,
  `bg-courriels-mandat-exemple.service`, `prospecteur.py`,
  `recherchiste.py`.

**Si vous avez un second mandat** (vous gérez le marketing d'un client, en
plus du vôtre) : gardez l'architecture telle quelle, remplacez
`{{MANDAT_EXEMPLE}}` par son nom partout, et adaptez les identités
Thunderbird dans `courriels_prospection.py` (dict `IDENTITES`).

## 3. Le lanceur — le cœur de la suite

`lanceur.py` surveille des collections Firestore (par défaut : `marketing`),
exécute `claude -p` pour chaque demande, et écrit le résultat. Il exige :

- `~/.config/bg-lanceur/config.json` — `projet`, `uid`, `dossier_travail`,
  `claude` (chemin de l'exécutable), `collections` (liste, ex.
  `["marketing"]` ou `["marketing", "bgfoods"]`) ;
- `~/.config/bg-lanceur/cle-sa.json` — clé d'un compte de service Firebase
  avec le rôle `datastore.user` seulement (jamais plus) ;
- `openssl` en ligne de commande (signature RS256 du jeton — aucune
  dépendance Python hors bibliothèque standard).

Le cadre de travail de chaque collection est ÉCRIT DANS `lanceur.py`, jamais
reçu d'un document Firestore — c'est délibéré, voir l'en-tête du fichier.
Deux cadres existent déjà en exemple : `marketing` (le vôtre) et `bgfoods`
(lecture de circulaires d'épicerie, hors sujet ici mais montre le patron
« plusieurs outils, un seul lanceur » si vous voulez ajouter le vôtre).

## 4. Le guichet d'autorisations

Une tâche qui bute sur un geste hors de portée, une publication, une dépense
ou une décision de fond s'arrête et dépose une fiche en clair dans
`autorisations/` (créé au premier besoin, pas versionné). Vous répondez avec
`python3 autorisations.py` (liste, `voir`, `accorder`, `refuser`) ou
`autorisations.py reponses` / `corriger` pour reprendre une tâche déjà
rendue. Rien à configurer ici — ça marche dès que `lanceur.py` tourne.

## 5. Facebook et Instagram

Chemin rapide, guidé : `python3 configurer_reseaux_sociaux.py` (orchestre
tout ce qui suit, y compris le choix local/cloud et le secret GitHub).

Marche à suivre complète, étape par étape : `LISEZ-MOI_Publicateur.md`
(Facebook) et `LISEZ-MOI_Publicateur_Instagram.md` (Instagram — dépend du
jeton généré par `configurer_instagram.py`, renouvelé automatiquement par
`renouveler_instagram.py`). Les deux publicateurs restent inertes tant que
leur fichier de jeton n'existe pas : aucun risque de publication accidentelle
pendant la configuration.

`configurer_facebook.py` (recommandé) et `installer_jeton.py` font tous
deux le jeton Facebook en version guidée interactive, à partir de deux
points de départ différents : `configurer_facebook.py` part d'un jeton
COURT et fait l'échange lui-même (App ID + App secret requis) ;
`installer_jeton.py` part d'un jeton UTILISATEUR déjà prolongé à la main au
Débogueur. Les deux écrivent le même `facebook_jeton.json` — n'utilisez
qu'un seul des deux, celui qui colle à l'étape où vous en êtes dans
`LISEZ-MOI_Publicateur.md`.

Publication cloud (GitHub Actions, marche même l'ordinateur éteint) :
facultative, voir `cloud-facebook/README.md` — deux fichiers à copier dans
le dépôt de votre site, jetons `{{ORG_GITHUB}}`, `{{PAGE_ID_FACEBOOK}}` et
`{{FUSEAU_HORAIRE}}` à remplacer, secret GitHub `FB_PAGE_TOKEN` à créer.
N'activez JAMAIS ce chemin en même temps que `bg-publicateur.timer` local :
les deux publieraient chaque billet en double.

## 6. Hébergement des images Instagram

Instagram télécharge lui-même l'image depuis une adresse PUBLIQUE — vous ne
pouvez pas lui envoyer un fichier local. Chez BG, c'est un projet Firebase
Hosting séparé et dédié (rien d'autre n'y vit), mais n'importe quel
hébergement statique public convient. Réglez `{{PROJET_VISUELS_INSTAGRAM}}`
et, si vous n'utilisez pas Firebase Hosting, réécrivez directement
`BASE_URL_IMAGES` dans `publicateur_instagram.py`.

## 7. Les courriels de prospection — deux passerelles, un script séparé requis

- `courriels_prospection.py` ouvre dans Thunderbird les brouillons rédigés
  par `prospecteur.py` (le tableau de bord dépose une demande, la passerelle
  ouvre la fenêtre). Autonome, rien d'autre requis.
- `courriels_mandat_exemple.py` fait la même chose pour un **batch de
  courriels préparés à l'avance** (fiches + `.eml`), mais délègue la lecture
  de ces fiches à un script `ouvrir.py` **qui N'EST PAS INCLUS dans ce
  modèle** — c'est un outil écrit à part pour chaque batch réel, avec son
  propre format de fiches. `{{DOSSIER_BATCHS_COURRIELS}}` est le nom de ce
  dossier (chez BG : un dossier daté par batch). Si vous n'avez pas ce genre
  de batch, ne déployez pas `courriels_mandat_exemple.py` ni
  `bg-courriels-mandat-exemple.service`.

## 8. Le pilote et la vigie

`pilote.py` fait avancer le tableau de bord sans clic (une tâche « à faire »
à la fois, chaque matin ou en rafale). `vigie.py` surveille dix choses
différentes (services en panne, lancements gelés, montage Facebook, guichet
dormant, etc.) et dépose des alertes. Aucun réglage propre à ces deux
fichiers au-delà des jetons du § 1 — mais voir le § 9 pour ce qu'ils
encodent en plus des jetons.

## 9. Contenu et règles d'affaires réels, à réécrire pour vous

Trois endroits contiennent, en dur, le VRAI contenu marketing de BG plutôt
qu'un jeton substituable — traitez-les comme un exemple de patron à copier,
pas comme une config à remplir :

- **`recherchiste.py`**, fonction `chercher()` : le profil de prospect cible
  (villes de la Rive-Nord et des Laurentides, secteurs B2B précis) est écrit
  en dur dans le prompt envoyé à l'agent. Réécrivez ce profil pour votre
  propre zone et vos propres secteurs avant d'utiliser cet outil.
- **`preparer_groupes.py`** : `GROUPE_JOUR_STRICT` code un vrai groupe
  Facebook avec une règle de jour propre à lui (« Spotted St-Eustache »,
  publication le samedi seulement) ; `LECONS_CRITIQUE` code des consignes de
  ton tirées d'une vraie relecture des textes de BG. Adaptez les deux à vos
  groupes et à votre voix.
- **`vigie.py`**, fonctions `surveiller_facebook()` (rédaction du lot 2) et
  `consigne_guide()` (rédaction d'un guide de bibliothèque) : les règles
  d'écriture qu'elles envoient à Claude (« jamais diagnostic gratuit »,
  services résidentiels précis, ton) sont celles de BG. `ENTETE_PILOTE` dans
  `pilote.py` porte les mêmes règles pour toute tâche lancée par le pilote.

Ce n'est pas une lacune à corriger — c'est le patron réel de BG, laissé en
place pour montrer comment brancher vos propres règles au même endroit.

## 10. Dossiers d'un autre chantier, référencés mais non inclus

Plusieurs scripts lisent ou écrivent dans des dossiers voisins qui
n'existent QUE chez BG et ne font pas partie de cette copie :

- `Campagne_BG/Contenus/` — les fichiers `_File_Facebook.tsv`,
  `_File_Instagram.tsv`, `_File_Groupes.tsv`, `_Historique_Groupes.tsv`,
  `Facebook-Residentiel-Lot-1.md`, `Voix-{{ENTREPRISE}}-Facebook.md` : à
  créer vous-même (voir les `LISEZ-MOI_*` pour le format attendu de chacun).
- `{{DEPOT_SITE}}/_bibliotheque/sujets.tsv` — le registre des guides de la
  bibliothèque du site, utilisé par `vigie.py` (chantier bibliothèque). Sans
  ce fichier, cette fonctionnalité de la vigie ne fait simplement rien.
- `04_Produits_Clients/WebsiteMaestro/SitesWebClient/` — requis seulement si
  vous utilisez le cadre `clientsweb` du lanceur (voir
  `LISEZ-MOI_Espace_Client.md`) ; sans lui, cette partie de `lanceur.py`
  reste inerte, rien d'autre n'est affecté.
- `Tableau_de_Bord/amorce-bg.json`, mentionné dans le cadre de travail de
  `lanceur.py` (`construire_prompt()`) comme un exemple de piège à éviter
  (« ne pas confondre un instantané figé avec l'état réel ») — vous n'avez
  probablement pas ce fichier : retirez ce paragraphe du prompt, ou
  remplacez-le par la référence à votre propre source de vérité si vous en
  avez une.

## 11. Ce qui n'est délibérément PAS inclus

Secrets et état d'exécution réels, propres à l'installation de BG — à
recréer, jamais à copier d'ailleurs :
`facebook_jeton.json`, `instagram_jeton.json`, `~/.config/bg-lanceur/*.json`
(config et clés de service), `etat_pilote.json`, `etat_pilote.lock`,
`etat_vigie.json`, `journal.log`, le dossier `autorisations/`.

## 12. Installation systemd

Chaque `bg-*.service` / `bg-*.timer` de ce dossier est une COPIE SOURCE ; les
copies actives vivent dans `~/.config/systemd/user/`. Une fois les jetons du
§ 1 remplacés :

```bash
for f in bg-*.service bg-*.timer; do
  ln -sf "$(pwd)/$f" ~/.config/systemd/user/
done
systemctl --user daemon-reload
systemctl --user enable --now bg-vigie.timer bg-pilote.timer bg-lanceur.service
# puis les autres timers/services une fois leurs prérequis (jetons, dossiers
# du § 10) en place — voir chaque LISEZ-MOI_*.md pour l'ordre recommandé.
```

`bg-lanceur.service` n'a pas de fichier fourni ici : c'est le service du
processus `lanceur.py` lui-même — installez-le en suivant le même patron que
`bg-pont-clients.service` (`Type=simple`, `Restart=always`).
