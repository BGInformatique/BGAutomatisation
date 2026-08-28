# Publicateur Instagram — jumeau du publicateur Facebook

`publicateur_instagram.py` publie sur `https://www.instagram.com/{{HANDLE}}/`
depuis `Campagne_BG/Contenus/_File_Instagram.tsv` — cette file EST la source
de vérité (image + légende ensemble), pas juste un état comme pour Facebook.

**État : armé, inactif.** Trois choses manquent, dans l'ordre : le compte
Instagram relié à la Page, le jeton, l'hébergement public des images. Tant
qu'une seule manque, chaque passage se termine sans rien faire.

Essai à blanc, à tout moment :

    python3 publicateur_instagram.py --essai

## Étape 1 — relier le compte Instagram à la Page Facebook {{ENTREPRISE}}

Le compte a son propre courriel, gardé volontairement séparé — ce lien ne
change ni le courriel ni le mot de passe Instagram, il ajoute seulement un
pont technique que l'API exige. Le chemin le plus fiable passe par Meta
Business Suite (l'app Instagram change trop souvent d'endroit pour ça).

**1.1 — Vérifier que le compte Instagram est en mode professionnel**
   - App Instagram, profil `{{HANDLE}}` → ☰ → **Paramètres et
     confidentialité** → **Type de compte et outils**.
   - Si ça propose « Passer à un compte professionnel », le faire (choisir
     Entreprise), catégorie libre (ex. « Services informatiques »).
   - VU QUAND C'EST FAIT : la mention « Compte professionnel » apparaît sous
     le nom d'utilisateur sur le profil.

**1.2 — Connecter la Page depuis Meta Business Suite**
   - Sur un ordinateur : <https://business.facebook.com/>, connecté avec le
     compte Facebook qui administre la Page **{{ENTREPRISE}}**.
   - Icône ⚙️ (Paramètres) en bas à gauche → **Comptes** → **Comptes
     Instagram**.
   - **+ Connecter un compte** → se connecter avec le courriel/mot de passe
     du compte Instagram `{{HANDLE}}` (celui-ci, pas celui de Facebook —
     Meta redemande explicitement les identifiants Instagram à cette étape).
   - Choisir la Page **{{ENTREPRISE}}** comme Page à relier, confirmer.
   - VU QUAND C'EST FAIT : le compte `@{{HANDLE}}` apparaît dans la
     liste sous **Comptes Instagram**, avec « {{ENTREPRISE}} » comme Page
     reliée.

**1.3 — Vérifier depuis la Page elle-même**
   - Page Facebook {{ENTREPRISE}} → **Paramètres** → **Comptes liés** (ou
     **Instagram** dans le menu de gauche) → doit afficher `@{{HANDLE}}`
     comme compte connecté.
   - Si cet écran est vide alors que l'étape 1.2 a semblé réussir, attendre
     quelques minutes et rafraîchir — la propagation entre Instagram et la
     Page n'est pas toujours instantanée.

## Étape 2 — le jeton (chemin « Instagram API avec connexion Instagram »)

L'app Meta existe déjà (« Publicateur {{ENTREPRISE}} », voir `LISEZ-MOI_Publicateur.md`).
Les apps récentes n'offrent plus `instagram_basic` /
`instagram_content_publish` via le cas d'utilisation Facebook existant : il
faut ajouter le cas d'utilisation séparé **Instagram API avec connexion
Instagram**, qui authentifie directement avec le compte Instagram — pas avec
la Page. C'est pour ça que l'étape 1 (compte relié à la Page) reste utile
mais n'est plus, techniquement, ce qui déverrouille le jeton ici.

1. Dans l'app → **Cas d'utilisation** → **Ajouter un cas d'utilisation** →
   **Instagram API avec connexion Instagram** (pas celui déjà personnalisé
   pour Facebook).
2. Onglet **Roles** → **Instagram Testers** → **Add Instagram Testers** →
   entrer `{{HANDLE}}`. Puis, dans l'app Instagram sur ce compte :
   Paramètres et confidentialité → Applications et sites web → accepter
   l'invitation de testeur pour « Publicateur {{ENTREPRISE}} ». Sans ça, l'étape
   suivante échoue.
3. Dans le cas d'utilisation → section **2. Generate access tokens** →
   **Add account** → se connecter avec le courriel/mot de passe du compte
   Instagram `{{HANDLE}}` → autoriser. Un jeton **court** s'affiche.
4. Noter aussi l'**App secret** de l'app (Paramètres de l'app → Basique →
   App secret → Afficher) — il sert une seule fois, pour échanger le jeton
   court contre un jeton longue durée.
5. Lancer, dans un terminal (`!` si dans Claude Code, pour pouvoir taper) :

       python3 "$HOME/Bureau/{{ENTREPRISE}}/03_Automatisation/BGAutomatisation/configurer_instagram.py"

   Il demande le jeton court puis l'App secret (saisie invisible), fait
   l'échange contre un jeton longue durée auprès de `graph.instagram.com`,
   retrouve l'identifiant du compte, et écrit `instagram_jeton.json` (600)
   avec la date d'expiration.

**Le jeton expire après 60 jours** — contrairement au jeton de Page
Facebook. `renouveler_instagram.py` le renouvelle tout seul avant l'échéance
une fois sa minuterie armée (étape « Activer la minuterie » plus bas, à
répéter pour `bg-renouveler-instagram.timer`) ; `publicateur_instagram.py`
refuse de publier si l'échéance est dépassée plutôt que d'échouer à l'appel.

## Étape 3 — héberger les images

Instagram va chercher l'image par une adresse PUBLIQUE : il faut donc un
hébergement séparé du dépôt du site. Chez {{ENTREPRISE}}, c'est un projet
Firebase Hosting dédié (`{{PROJET_VISUELS_INSTAGRAM}}`), où rien d'autre ne
vit — les visuels prêts (`{{ENTREPRISE}} Instagram design/export/jpg/`) sont
copiés dans `Campagne_BG/Instagram-Hebergement/public/` et publiés sur
<https://{{PROJET_VISUELS_INSTAGRAM}}.web.app>. `BASE_URL_IMAGES`, dans
`publicateur_instagram.py`, doit pointer vers cette adresse une fois choisie
— n'importe quel hébergement public statique convient, Firebase Hosting
n'est qu'un choix pratique.

Pour ajouter ou remplacer une image : la déposer dans
`Campagne_BG/Instagram-Hebergement/public/`, puis depuis ce dossier :

    firebase deploy --only hosting

## Étape 4 — écrire les légendes

`_File_Instagram.tsv` contient déjà les 3 visuels de poste
(post-service, post-conseil, post-promo), STATUT `a_ecrire` — le script les
ignore tant qu'ils restent ainsi. Pour chacun : écrire la LEGENDE, puis
passer STATUT à `a_publier`. Vérifier ensuite avec `--essai`.

## Cadence et suivi

Même logique que Facebook : au plus une publication par passage, jamais deux
publications à moins de 3 jours d'écart. Pour suspendre une publication sans
la perdre : STATUT à `pause`. Pour tout arrêter :
`systemctl --user disable --now bg-publicateur-instagram.timer`.

- Journal : `journal.log` (même fichier que le publicateur Facebook et le
  lanceur).
- File : `Campagne_BG/Contenus/_File_Instagram.tsv` — ID, IMAGE, LEGENDE,
  STATUT (`a_ecrire` / `a_publier` / `publie` / `pause`), PUBLIE_LE, POST_ID.

## Activer la minuterie

Les fichiers `bg-publicateur-instagram.service` et `.timer` sont dans ce
dossier mais **pas encore installés** — contrairement à ceux de Facebook, il
n'y a aucune urgence à les armer tant que les étapes 1 à 4 ne sont pas
faites. Une fois prêt :

    systemctl --user link "$HOME/Bureau/{{ENTREPRISE}}/03_Automatisation/BGAutomatisation/bg-publicateur-instagram.service"
    systemctl --user link "$HOME/Bureau/{{ENTREPRISE}}/03_Automatisation/BGAutomatisation/bg-publicateur-instagram.timer"
    systemctl --user enable --now bg-publicateur-instagram.timer

**Sécurité :** même règle que pour Facebook — le jeton reste dans ce dossier
non versionné, en fichier 600. S'il fuit : <https://developers.facebook.com>
→ l'app → révoquer, en générer un autre.
