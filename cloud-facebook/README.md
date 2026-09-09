# Publication Facebook — version cloud (GitHub Actions)

Ce dossier n'est PAS destiné à rester ici. Il montre comment faire tourner
`publicateur.py` (voir la racine de ce dépôt) même quand votre ordinateur est
éteint, en le déplaçant sur GitHub Actions plutôt que sur une minuterie
systemd locale. Détail complet, contexte et marche à suivre : voir
`LISEZ-MOI_Publicateur.md` à la racine, section « Cloud vs local ».

## Où déplacer ces deux fichiers

Dans le dépôt GitHub de VOTRE site web (celui qui se publie déjà sur le web,
donc gratuit et déjà en place) :

| Fichier ici | Destination dans le dépôt du site |
|---|---|
| `publicateur_cloud.py` | `automatisation/facebook/publicateur_cloud.py` |
| `publicateur-facebook.yml` | `.github/workflows/publicateur-facebook.yml` |

Il faut en plus, dans ce même dossier `automatisation/facebook/` du dépôt du
site, une COPIE de vos contenus (le workflow les lit là, pas dans
Campagne_BG/Contenus/) :

- `Facebook-Residentiel-Lot-1.md` (vos textes)
- `_File_Facebook.tsv` (la file — peut démarrer vide, une seule ligne
  d'entêtes : `ID\tTITRE\tSTATUT\tPUBLIE_LE\tPOST_ID`)
- `visuels/` (facultatif — images `page-NN-*.jpg`)

## Pourquoi deux copies (locale et dépôt) ?

La copie locale (`Campagne_BG/Contenus/`) reste la source de vérité pour
RÉDIGER — c'est là que vous écrivez et relisez vos textes. La copie du dépôt
est celle que le cloud publie réellement. Les garder synchronisées à la main
est possible mais fastidieux ; `vigie.py` de ce dépôt sait le faire tout
seul à chaque passage si vous configurez un accès en écriture au dépôt du
site (voir `PARAMETRES-A-CONFIGURER.md`, section publication Facebook).

## Ce qu'il faut configurer

1. `{{PAGE_ID_FACEBOOK}}` dans `publicateur_cloud.py` — l'id de votre Page.
2. `{{FUSEAU_HORAIRE}}` dans `publicateur_cloud.py` — votre fuseau (format
   `zoneinfo`, ex. `America/Toronto`, `Europe/Paris`).
3. Le secret GitHub Actions `FB_PAGE_TOKEN` dans les réglages du dépôt du
   site (Settings → Secrets and variables → Actions) — jamais dans un
   fichier versionné.
4. Les deux horaires `cron:` du workflow, en UTC, pour votre créneau voulu.
5. Si vous n'activez PAS ce chemin cloud, laissez `bg-publicateur.timer`
   (local) activé à la place — mais jamais les deux en même temps, ils
   publieraient en double.
