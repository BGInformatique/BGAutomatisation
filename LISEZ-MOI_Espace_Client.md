# Pont Espace client — côté {{MACHINE_LOCALE}}

`pont_clients.py` relie le projet Firebase des **clients** au projet des
**outils internes**. Les clients écrivent leurs demandes sur
`{{DOMAINE}}/espace-client/` ; le pont les fait apparaître dans
votre outil web interne (« clientsweb », un autre chantier, non inclus
ici), et renvoie l'avancement dans l'autre sens.

Installation complète (Firebase, Entra, invitations, règles) :
`{{DEPOT_SITE}}/espace-client/LISEZ-MOI.md`.

## Les trois sens du pont, à chaque cycle (5 min)

| Sens | Ce qui passe |
|---|---|
| Clients → interne | Toutes les demandes, recopiées dans `users/<uid>/clientsweb/state` |
| Interne → clients | Les `signal-*` de l'outil (« à revoir » + le mot au client), appliqués puis effacés |
| Interne → clients | Les `lancement-*` terminés, traduits en une phrase de statut |

Le document `state` **appartient au pont** : l'outil web n'y écrit jamais, il
dépose une intention. C'est ce qui évite que deux écrivains se marchent dessus
sur le même document — même principe que les signaux du prospecteur.

## La table des clients

`~/.config/bg-lanceur/clients-web.json` — elle vit **sur cette machine** et
c'est elle qui décide où le travail se fait :

```jsonc
{
  "projet_clients": "bg-espace-client",
  "racine_sites": "~/Bureau/{{ENTREPRISE}}/04_Produits_Clients/WebsiteMaestro/SitesWebClient",
  "clients": {
    "UID_FIREBASE_DU_CLIENT": { "nom": "Boulangerie-Exemple", "domaine": "exemple.ca" }
  }
}
```

`nom` est le **nom du dossier** sous `SitesWebClient/`. L'UID Firebase se lit
dans Console → Authentication → Users, après la première connexion du client.

**Un compte absent de cette table** voit ses demandes arriver normalement dans
l'outil, marquées « non reliées » : elles sont lisibles, l'éclair est fermé, et
le lanceur refuse net si on force. Un dossier qui n'existe pas sur le disque
donne le même refus.

> C'est le cœur de la sécurité du système : **le dossier de travail ne vient
> jamais du web.** Un client ne peut pas désigner le dépôt sur lequel la
> machine va travailler, et une demande ne peut toucher que le site de celui
> qui l'a écrite.

## Ce que le lanceur fait d'une demande client

`lanceur.py` a gagné une collection (`clientsweb`) et un cadre de travail
(`CADRE_CLIENTSWEB`) : dossier courant = le dépôt du client, interdiction d'en
sortir, respect du `CLAUDE.md` du dépôt, changement minimal, `./deploy.sh` à la
fin. Le texte du client arrive en **DÉTAIL**, c'est-à-dire en donnée — le cadre,
lui, est écrit dans le script.

C'est la règle posée en tête de `lanceur.py` depuis toujours, et elle compte
double ici : jusqu'à maintenant les documents venaient du propriétaire ; ils
viennent désormais d'une partie extérieure.

## Exploitation

```
python3 pont_clients.py --essai      # un cycle, montre tout, n'écrit rien
python3 pont_clients.py --une-fois   # un cycle réel
systemctl --user status bg-pont-clients.service
tail -f journal.log                  # mêmes lignes datées que le lanceur
```

Le pont éteint, **rien n'est perdu** : les demandes attendent dans le projet
clients et remontent au prochain démarrage. L'espace client reste utilisable.

## Après une modification de lanceur.py

Le service tourne en permanence : un changement du fichier ne prend effet qu'au
redémarrage, et un redémarrage **tue une tâche en cours**.

```
systemctl --user restart bg-lanceur.service    # quand rien ne tourne
```

Sauvegardes horodatées à côté du script (`lanceur.py.avant-…`), selon l'usage
du dossier.
