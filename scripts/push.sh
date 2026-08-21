#!/usr/bin/env bash
# Push the current branch to the RayJoeMan/VideoAssistantXbotGo remote.
#
# Tries, in order:
#   1. default ssh-agent keys
#   2. the "lacrosse-ready-deploy" key (~/.ssh/id_ed25519_lacrosseready)
#   3. the "blaine-lax-girls" key (~/.ssh/id_ed25519_blaine_lax_girls)
#
# Usage:
#   ./scripts/push.sh            # push current branch
#   ./scripts/push.sh main       # push a specific branch
set -euo pipefail
cd "$(dirname "$0")/.."

BRANCH="${1:-$(git branch --show-current)}"
REMOTE="origin"

push_with() {
    local key="$1"
    if [ -n "$key" ]; then
        echo "[push] trying key: $key"
        GIT_SSH_COMMAND="ssh -i $key -o IdentitiesOnly=yes" \
            git push -u "$REMOTE" "$BRANCH"
    else
        echo "[push] trying default ssh-agent keys"
        git push -u "$REMOTE" "$BRANCH"
    fi
}

# 1) default ssh-agent keys
if push_with "" 2>/dev/null; then
    echo "[push] OK"
    exit 0
fi

# 2) lacrosse-ready deploy key
if [ -f "$HOME/.ssh/id_ed25519_lacrosseready" ]; then
    if push_with "$HOME/.ssh/id_ed25519_lacrosseready" 2>/dev/null; then
        echo "[push] OK"
        exit 0
    fi
fi

# 3) blaine-lax-girls deploy key
if [ -f "$HOME/.ssh/id_ed25519_blaine_lax_girls" ]; then
    if push_with "$HOME/.ssh/id_ed25519_blaine_lax_girls" 2>/dev/null; then
        echo "[push] OK"
        exit 0
    fi
fi

echo "[push] FAILED — no SSH key has write access to $REMOTE ($(git remote get-url "$REMOTE"))."
echo "[push] Fix: add one of these public keys as a DEPLOY KEY on the GitHub repo"
echo "           (Settings -> Deploy keys -> Add deploy key):"
echo "           $(cat "$HOME/.ssh/id_ed25519_lacrosseready.pub" 2>/dev/null || echo '~/.ssh/id_ed25519_lacrosseready.pub')"
exit 1
