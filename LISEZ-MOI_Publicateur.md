# Publicateur Facebook — chantier 2 de la campagne {{ENTREPRISE}}

`publicateur.py` publie les textes du lot résidentiel sur la Page Facebook de
{{ENTREPRISE}}, une fois par semaine, sans intervention. Les textes restent
dans `Campagne_BG/Contenus/Facebook-Residentiel-Lot-1.md` — c'est la seule
source de vérité ; le script n'invente ni ne modifie rien, il publie les
citations telles quelles.

**État : armé, inactif.** Tant que `facebook_jeton.json` n'existe pas, chaque
passage de la minuterie se termine sans rien faire. Il s'activera tout seul
une fois les deux étapes ci-dessous complétées.

## Ce que ça fait, à chaque passage (jeudi 18 h 30, dimanche 10 h)

1. Met la file `_File_Facebook.tsv` au niveau du lot markdown (les sections
   `## 11+` d'un futur lot 2 y entrent automatiquement).
2. S'il y a eu une publication il y a moins de 3 jours : rien. C'est ce qui
   fait que le dimanche ne publie que si le jeudi a sauté (machine éteinte),
   et que la cadence revient ensuite d'elle-même au jeudi.
3. Sinon, publie la première entrée « a_publier » de la file via l'API Graph,
   puis consigne la date et l'identifiant du billet.

Pour suspendre une publication sans la perdre : mettre son STATUT à `pause`
dans la file. Pour tout arrêter : `systemctl --user disable --now
bg-publicateur.timer`.

Essai à blanc, à tout moment :

    python3 publicateur.py --essai

## Étape 1 — la Page (tâche déjà dans le tableau de bord)

« Créer ou remettre à jour la page Facebook {{ENTREPRISE}} » : photo d'une
vraie personne, bouton « Appeler maintenant », coordonnées identiques au site.

## Étape 2 — le jeton (une fois, ~20 minutes)

1. <https://developers.facebook.com> → **Créer une app** → type **Entreprise**.
   Le nom n'a aucune importance (« Publicateur {{ENTREPRISE}} »), elle ne sera jamais
   publiée : en mode développement, elle n'agit que sur tes propres Pages.
2. Dans l'app : **Outils** → **Explorateur de l'API Graph**
   (<https://developers.facebook.com/tools/explorer/>).
3. Dans l'explorateur : choisir ton app, puis **Obtenir un jeton d'utilisateur**
   avec les permissions `pages_manage_posts` et `pages_read_engagement`.
4. Échanger ce jeton court contre un **jeton de Page qui n'expire pas** :
   requête `GET /me/accounts` dans l'explorateur — la réponse liste tes Pages
   avec, pour chacune, `id` (le page_id) et `access_token` (le jeton de Page).
   Un jeton de Page obtenu à partir d'un jeton d'utilisateur **longue durée**
   n'expire pas ; pour obtenir la version longue durée d'abord :
   **Outils** → **Débogueur de jeton d'accès** → coller le jeton → **Prolonger
   l'accès**. Puis refaire `GET /me/accounts` avec le jeton prolongé.
5. Écrire le fichier (dans CE dossier, jamais dans le dépôt du site) :

        cat > "$HOME/Bureau/{{ENTREPRISE}}/03_Automatisation/BGAutomatisation/facebook_jeton.json" <<'FIN'
        {"page_id": "LE_PAGE_ID", "jeton": "LE_JETON_DE_PAGE"}
        FIN
        chmod 600 "$HOME/Bureau/{{ENTREPRISE}}/03_Automatisation/BGAutomatisation/facebook_jeton.json"

6. Vérifier sans rien publier : `python3 publicateur.py --essai` doit
   afficher la publication 1, telle qu'écrite dans
   `Facebook-Residentiel-Lot-1.md`. La vraie première publication partira à
   la fenêtre suivante de la minuterie.

**Pourquoi c'est permis :** l'API Graph interdit de *lire* le fil, pas de
*publier sur sa propre Page* — c'est exactement l'usage prévu de
`pages_manage_posts`. Aucune règle de Meta n'est contournée.

**Sécurité :** le jeton donne le droit de publier au nom de la Page. Il reste
dans ce dossier non versionné, en fichier 600. S'il fuit un jour :
<https://developers.facebook.com> → l'app → révoquer, et en générer un autre.

## Suivi

- Journal : `journal.log` (mêmes lignes datées que le prospecteur).
- File : `Campagne_BG/Contenus/_File_Facebook.tsv` — ID, TITRE, STATUT
  (`a_publier` / `publie` / `pause`), PUBLIE_LE, POST_ID.
- Quand le lot est épuisé, le journal le dit : écrire le lot 2 à la suite du
  même fichier markdown (sections `## 11` et suivantes), rien d'autre à faire.
