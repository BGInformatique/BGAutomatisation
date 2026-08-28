# Le pilote — le tableau de bord avance par lui-même

Un passage par jour, à **9 h 15** (`bg-pilote.timer`, rattrapage au réveil).
Le bouton éclair de l'outil web lance une tâche quand tu cliques ; le pilote
fait le même geste sans le clic : chaque matin, il prend **la prochaine tâche
« à faire »** du Marketing Dashboard, la lance, et consigne le résultat au
tableau. Ton seul rôle restant : répondre au guichet d'autorisations quand un
geste, une publication, une dépense ou une décision l'exige.

## Comment il choisit

Priorité haute d'abord, puis l'échéance la plus proche, puis la plus
ancienne. **Une seule tâche en travail à la fois** ; une tâche arrêtée au
guichet est **mise de côté** (elle attend ta réponse) et la file continue
avec la suivante — plusieurs fiches peuvent donc t'attendre au guichet en
même temps.

## La rafale

`python3 pilote.py --rafale` enchaîne les tâches sans attendre la minuterie :
lance, attend la fin, consigne, recommence. Elle s'arrête d'elle-même quand
il n'y a plus rien à lancer, au plafond de 40 tâches, après 3 échecs
d'affilée, ou si un lancement reste immobile 45 minutes. Un verrou
(`etat_pilote.lock`) fait passer son tour à la minuterie de 9 h 15 tant
qu'une rafale tourne. Pour en suivre une :
`systemctl --user status bg-pilote-rafale.service` — pour l'arrêter :
`systemctl --user stop bg-pilote-rafale.service`.

Quand une limite de compte l'arrête, le pilote lit l'heure de remise à zéro
dans le message (« resets 10:20pm ») et arme `bg-pilote-reprise` pour repartir
cinq minutes après. Rien à relancer à la main. Voir ce qui est armé :
`systemctl --user list-timers 'bg-pilote*'`.

Il ne touche jamais :
- aux tâches **{{MANDAT_EXEMPLE}}** (leurs automatismes propres, leurs
  informations séparées) ;
- aux tâches de la **vigie** (ce sont des alertes qui s'adressent à toi) ;
- à une tâche **écartée** : un lancement refusé au guichet ou terminé en
  échec n'est pas retenté — la tâche reste visible au tableau (reportée ou à
  faire) et l'éclair reste là si tu la veux quand même.

## Ce que tu vois au tableau

| Le pilote… | La tâche devient |
|---|---|
| lance la tâche | `en_cours` |
| voit le lancement réussir | `fait` |
| voit un refus au guichet | `reporte` (et il n'y revient pas) |
| voit un échec dû à la tâche | `a_faire` (et il n'y revient pas — à toi de relancer par l'éclair) |
| voit un **creux passager** (API surchargée 529, réseau, délai) | `a_faire`, **la tâche reste candidate** ; la rafale patiente 5, 10, 15 puis 20 minutes et réessaie — elle n'abandonne qu'après 4 creux d'affilée |
| voit un **mur ferme** (crédits Claude épuisés, limite de compte) | `a_faire`, **la tâche reste candidate** ; la rafale s'arrête, une alerte arrive dans « À compléter manuellement », et **une reprise s'arme toute seule** pour cinq minutes après l'heure de remise à zéro annoncée dans le message |

Si tu changes toi-même le statut d'une tâche pendant que le pilote la
traite, ton geste gagne : il ne l'écrase jamais.

Chaque tâche part avec une entête qui exige de **vérifier les prémisses**
avant d'agir (le tableau charrie des consignes qui datent) et rappelle les
règles d'écriture {{ENTREPRISE}} (« estimation sans frais », aucune promesse de délai,
aucune vente de matériel, aucune mention {{MANDAT_EXEMPLE}}).

## Mettre en pause / arrêter

```bash
systemctl --user disable --now bg-pilote.timer   # arrêt
systemctl --user enable  --now bg-pilote.timer   # remise en route
python3 pilote.py --essai                        # montre le choix, n'écrit rien
```

## Les fichiers

- `pilote.py` — le script (réutilise lanceur.py et vigie.py)
- `etat_pilote.json` — tâche en cours et tâches écartées ; le supprimer
  remet les compteurs à zéro (les écartées redeviendraient candidates)
- `bg-pilote.service` / `bg-pilote.timer` — copies sources ; les copies
  installées vivent dans `~/.config/systemd/user/`
