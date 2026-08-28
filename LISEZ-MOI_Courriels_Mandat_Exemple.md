# Courriels de prospection {{MANDAT_EXEMPLE}} — depuis le tableau de bord

Les courriels personnalisés d'un batch de prospection vivent dans
`~/Bureau/{{MANDAT_EXEMPLE}}/{{DOSSIER_BATCHS_COURRIELS}}/` et s'ouvrent depuis
le volet **Prospection** du tableau de bord marketing, sous « Courriels
préparés ». **`ouvrir.py`, dans ce dossier, n'est PAS inclus dans ce
modèle** — c'est un script propre à chaque batch, écrit à part, qui sait lire
ses propres fiches et `.eml`. Voir `PARAMETRES-A-CONFIGURER.md`.

**Rien ne part tout seul.** Un clic sur `✉ ouvrir` ouvre une fenêtre de
rédaction Thunderbird déjà remplie — objet, destinataire, corps, et le champ
« De » réglé sur `{{COURRIEL_MANDAT_EXEMPLE}}`. Le clic sur « Envoyer » reste
un geste humain — c'est la règle du script `ouvrir.py` de chaque batch (non
inclus ici, voir plus haut).

## Comment ça circule

```
la page (n'importe où)                     {{MACHINE_LOCALE}}
  clic ✉ ouvrir  ──▶ Firestore  ──▶  bg-courriels-mandat-exemple.service
                     demandes           └─▶ ouvrir.py 3.7 ─▶ fenêtre Thunderbird
  liste, statuts ◀── courriels-mandat-exemple ◀──  miroir des fiches du batch
```

**Ce qui vient du web n'atteint jamais la ligne de commande.** La page
n'inscrit qu'un numéro de fiche (« 3.7 ») et un geste. Le numéro est cherché
dans la liste locale — absent, la demande est refusée — et le geste doit
figurer dans une liste fermée. Le destinataire, l'objet et le corps sont lus
sur cette machine, par le script du dossier {{MANDAT_EXEMPLE}}.

## Les gestes

| Dans la page | Ce qui se passe |
|---|---|
| `✉ ouvrir` | La fenêtre Thunderbird s'ouvre, remplie, avec la bonne identité |
| `marquer envoyé` | Inscrit `ENVOYÉ le AAAA-MM-JJ` sur la fiche du batch |

Un troisième geste existe, `essai`, qui ouvre la même fenêtre avec le
destinataire remplacé par `essai@example.invalid` (domaine réservé, ne route
nulle part). Il n'est pas dans l'interface — il sert aux vérifications :

```bash
python3 courriels_mandat_exemple.py --essai        # montre tout, n'écrit rien, n'ouvre rien
```

## Thunderbird endormi

Si Thunderbird ne tourne pas, la passerelle le démarre **d'abord**, puis
demande la fenêtre. Sans ce détour, `thunderbird -compose` démarre
l'application et reste accroché ; le script du dossier {{MANDAT_EXEMPLE}} coupe au bout de
30 secondes et tue du même coup l'application qu'il vient de lancer — la
fenêtre s'ouvrait puis disparaissait. Compter une trentaine de secondes pour
le premier courriel d'une session, puis c'est instantané.

## Après l'envoi : un seul geste

`marquer envoyé` dans la page (ou `./ouvrir.py --marquer 3.7`). **Le reste se
fait tout seul** : « envoyer vaut acceptation » est désormais appliqué par la
machine.

Au marquage, la passerelle dépose un ajout dans la boîte du prospecteur, avec
la date du contact. À son prochain cycle (lundi 8 h 30), le prospecteur porte
le prospect au journal **déjà contacté** — statut `contacte_sans_reponse`,
dernier contact à la date réelle, relance calée 14 jours plus tard. Sans cette
date, il aurait préparé un premier contact déjà fait, et le prospect aurait
reçu deux fois la même approche.

Un prospect déjà au journal n'est pas redéposé. Un courriel que rien ne relie
à l'inventaire (`· non relié` dans la page) s'ouvre et s'envoie normalement,
mais son acceptation reste à faire à la main — la page le dit sur la ligne.

## Le rapprochement courriel ↔ prospect

Les fiches nomment « Entreprise — Ville », le journal et l'inventaire nomment
l'entreprise seule : la passerelle compare sur la partie avant le tiret
cadratin, sans accents ni ponctuation. Un prospect du batch qui ne figure pas
encore dans le journal ou l'inventaire (retiré entre-temps, orthographe
différente…) reste « non relié » — le courriel s'ouvre et s'envoie
normalement, mais son acceptation reste à faire à la main.

## Exploitation

```bash
systemctl --user status bg-courriels-mandat-exemple.service
systemctl --user restart bg-courriels-mandat-exemple.service   # après modification du script
tail -f journal.log
```

Le service arrêté, la page continue d'afficher la liste (le miroir reste), mais
les clics ne font plus rien : les demandes s'accumulent et partiront au
redémarrage. Rien n'est perdu.
