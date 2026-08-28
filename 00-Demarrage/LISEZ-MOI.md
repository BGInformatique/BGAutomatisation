# 00-Demarrage

Porte d'entrée du modèle neutre **BGAutomatisation**. Avant de configurer les
outils eux-mêmes (le reste de `BGAutomatisation-modele/`), préparer les
comptes et logiciels qu'ils utilisent :

1. Ouvrir `checklist.html` dans un navigateur (double-clic, ou
   `xdg-open checklist.html`) et cocher au fur et à mesure. Rien n'y est
   automatisé — chaque inscription (Claude, OpenRouter, Meta, Firebase) se
   fait à la main, la checklist ne fait qu'ordonner les étapes et donner les
   bons liens.
2. Lancer `bash installer-openclaw.sh` pour installer OpenClaw et le mettre
   en route en mode 100 % gratuit (OpenRouter, modèles `:free` seulement,
   aucun abonnement payant requis pour démarrer). L'ID d'agent que vous
   choisissez à cette étape est la valeur à mettre partout où
   `../PARAMETRES-A-CONFIGURER.md` mentionne `{{AGENT_OPENCLAW}}`.

Une fois ces deux étapes faites, revenir à `../LISEZ-MOI.md` pour la suite.
