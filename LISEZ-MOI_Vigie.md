# La vigie — surveillance quotidienne du montage marketing

Un passage par jour, à **7 h 45** (`bg-vigie.timer`, rattrapage au réveil si la
machine dormait). La vigie ne publie rien et ne décide rien : elle **surveille**
le montage existant et, quand quelque chose cloche ou qu'une échéance approche,
elle dépose une **tâche dans le Marketing Dashboard** — la surface que tu
regardes déjà. Aucun courriel, aucune notification à installer.

## Ce qu'elle surveille

| Quoi | Réaction |
|---|---|
| Services `bg-*` en échec (liste `UNITES` dans `vigie.py`) | Relance automatique chaque matin ; tâche d'alerte seulement si la panne persiste deux passages de suite |
| Demandes `lancement-*` gelées (> 2 h en « demande ») | Relance `bg-lanceur`, une fois par jour au plus |
| Synchronisation du publicateur Facebook cloud (voir `cloud-facebook/`) | Lance `synchroniser_publicateur_facebook.py` avant tout le reste, pour lire une file à jour |
| Montage Facebook (jeton, Page, file, dernier passage cloud) | Passe `sante_facebook.py` ; tâche d'alerte si quelque chose bloquerait la prochaine publication |
| Silence Facebook (> 10 jours avec des textes en attente) | Tâche d'alerte |
| File Facebook presque vide (≤ 3 textes `a_publier`) | Met en file la rédaction du **lot 2** via le lanceur — les brouillons arrivent au guichet d'autorisations, rien ne part sans ton accord |
| Fiche Google (publication mensuelle, ancrée au 14) | Tâche de rappel 4 jours d'avance ; c'est **toi** qui écris le texte |
| Site en ligne (4 pages témoins, 3 essais espacés) | Tâche d'alerte si le site ne répond plus |
| Demande au guichet devenue caduque (ex. « publier ce guide » déjà en ligne) | Fermée automatiquement, confirmé sur le fichier réel — simple avis, rien à répondre |
| Guichet d'autorisations dormant (fiche en attente ≥ 5 jours) | Tâche de rappel |
| Guides de la bibliothèque encore « a_ecrire » | Met UN guide à la fois en rédaction, au plus un par semaine ; le brouillon s'arrête au guichet — accorder publie, refuser retire le sujet pour de bon |
| Tâches qui attendent TA personne (tâches de la vigie, écartées du pilote, bloquées) | Rangées dans la colonne « À compléter manuellement » du tableau (le bouton épingle d'une carte fait le même geste à la main ; la vigie n'en sort jamais une tâche) |
| Pont Espace client pas encore actif | Sonde quotidienne (une lecture) : dès que l'accès IAM au projet clients est accordé, `bg-pont-clients.service` est démarré automatiquement |

Un second passage, allégé, ne fait QUE le guichet (caduc + dormant), sans
Facebook ni sonde du site : `bg-vigie-guichet.timer`, plusieurs fois par jour.
Sert à fermer une demande caduque ou rappeler une demande qui dort sans
attendre le prochain passage complet du lendemain matin. Se déclenche à la
main avec `python3 vigie.py --guichet`.

**Règle des mandats :** tout outil `bg-*` appartient à {{ENTREPRISE}} — la
vigie les surveille donc tous, y compris `bg-prospecteur` et
`bg-recherchiste` qui servent le mandat {{MANDAT_EXEMPLE}}. Mais les **informations** ne se
confondent pas : une alerte sur une unité au service de {{MANDAT_EXEMPLE}} arrive au
dashboard avec `client = {{MANDAT_EXEMPLE}}`, jamais mêlée aux données {{ENTREPRISE}}. La
vigie ne touche par ailleurs à aucune donnée de prospection {{MANDAT_EXEMPLE}} — seulement à
l'état des services.

La vigie vérifie une fois pour toutes, à son premier passage, que le compte
GoatCounter existe (HTTP 200 sur `{{HANDLE}}.goatcounter.com`) — sinon elle
crée une tâche d'alerte avec les étapes pour le créer (voir `vigie.py`).

## Les tâches de la vigie

Elles arrivent dans le dashboard avec `source = vigie` et un identifiant stable
par sujet : la même alerte ne se recrée pas en double. **Supprimer une tâche de
la vigie = ne plus jamais la revoir** (la suppression laisse une pierre tombale
que la vigie respecte). Pour faire taire une alerte sans la perdre, la marquer
`fait` ou `reporte` plutôt que la supprimer.

Cas particulier : le rappel « fiche Google » du mois se réarme quand la tâche
du mois est marquée **fait** — le mois suivant, un nouveau rappel arrive.

## Mettre en pause / arrêter

```bash
systemctl --user disable --now bg-vigie.timer   # arrêt
systemctl --user enable  --now bg-vigie.timer   # remise en route
python3 vigie.py --essai                        # essai à blanc, n'écrit rien
```

## Les fichiers

- `vigie.py` — le script (stdlib seulement, réutilise `lanceur.py`)
- `etat_vigie.json` — mémoire locale (compteurs de pannes, mois de la fiche
  Google, dédoublonnage) ; le supprimer remet les compteurs à zéro, sans danger
- `attendre_reseau.sh` — garde-réseau posé en `ExecStartPre=` sur
  `bg-prospecteur`, `bg-recherchiste` et `bg-publicateur` (drop-ins
  `~/.config/systemd/user/bg-*.service.d/10-reseau.conf`) : attend le DNS
  jusqu'à 5 minutes avant de lancer, parce que le rattrapage au réveil partait
  parfois avant le réseau (c'est ce qui a tué le cycle prospecteur du
  2026-08-17)
- `bg-vigie.service` / `bg-vigie.timer` — copies sources ; les copies
  installées vivent dans `~/.config/systemd/user/`
