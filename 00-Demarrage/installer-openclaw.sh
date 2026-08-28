#!/usr/bin/env bash
# Installe OpenClaw (passerelle multi-canaux, github.com/openclaw/openclaw)
# et le configure en mode 100 % gratuit par défaut : uniquement des modèles
# OpenRouter marqués « :free ». Aucun abonnement payant n'est requis pour
# démarrer — Claude, Gemini ou tout autre modèle payant s'ajoutent plus tard
# à la main, dans agents.defaults.model ou par agent, une fois que le client
# a choisi ses abonnements.
set -euo pipefail

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js est requis (18+) et n'a pas été trouvé." >&2
  echo "Debian/Ubuntu : sudo apt install nodejs npm" >&2
  exit 1
fi

echo "== npm install -g openclaw =="
npm install -g openclaw

CONFIG="$HOME/.openclaw/openclaw.json"
mkdir -p "$(dirname "$CONFIG")"

if [ -f "$CONFIG" ]; then
  echo "Une configuration existe déjà ($CONFIG) — rien n'est écrasé."
else
  cat > "$CONFIG" <<'JSON'
{
  "agents": {
    "defaults": {
      "workspace": "~/.openclaw/workspace",
      "model": {
        "primary": "openrouter/nvidia/nemotron-3.5-lightning:free",
        "fallbacks": [
          "openrouter/google/gemma-4-31b-it:free",
          "openrouter/google/gemma-4-26b-a4b-it:free",
          "openrouter/free"
        ]
      }
    }
  }
}
JSON
  echo "Configuration créée dans $CONFIG — mode gratuit (OpenRouter :free)."
fi

cat <<'EOF'

Prochaines étapes, dans l'ordre :

  openclaw configure         # coller la clé API OpenRouter (voir étape 2 de la checklist)
  openclaw doctor            # vérifie que la config et les identifiants sont valides
  openclaw daemon install    # installe le service (systemd/launchd/schtasks)
  openclaw daemon start

Pour ajouter un modèle payant plus tard (Claude, Gemini…) une fois
l'abonnement du client en place :

  openclaw config patch '{"agents":{"defaults":{"models":{
    "claude-cli/claude-sonnet-5": {"alias": "sonnet"}
  }}}}'
EOF
