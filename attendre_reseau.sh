#!/bin/bash
# Attend que la résolution DNS fonctionne, au plus 5 minutes.
#
# Pourquoi : le rattrapage Persistent= des minuteries se déclenche au réveil
# de la machine, parfois avant que le réseau soit prêt — bg-prospecteur est
# mort exactement comme ça le 2026-08-17 (gaierror -3 sur oauth2.googleapis.com).
# Posé en ExecStartPre= (drop-in systemd), ce garde laisse le temps au DNS
# d'arriver avant de lancer le script. S'il n'arrive pas, l'unité échoue avec
# une cause claire, et la vigie la relancera à son prochain passage.

for _ in $(seq 1 60); do
    if getent hosts oauth2.googleapis.com >/dev/null 2>&1; then
        exit 0
    fi
    sleep 5
done
echo "attendre_reseau : toujours pas de résolution DNS après 5 minutes" >&2
exit 1
