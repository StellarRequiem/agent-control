#!/usr/bin/env bash
# Always-available control plane (bridges up). NEVER auto-arms leashes.
# Usage:
#   ./always_available.sh install   # launchd Load (login, keepalive)
#   ./always_available.sh uninstall
#   ./always_available.sh status
#   ./always_available.sh start     # one-shot up without launchd
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCHD="$ROOT/launchd"
UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"

labels=(
  com.stellarrequiem.browser-leash
  com.stellarrequiem.desktop-leash
)

install_soc="${INSTALL_SOC_WATCH:-0}"

cmd="${1:-status}"

_plist_for() {
  echo "$LAUNCHD/$1.plist"
}

_bootstrap() {
  local label="$1"
  local plist
  plist="$(_plist_for "$label")"
  if [[ ! -f "$plist" ]]; then
    echo "missing $plist" >&2
    return 1
  fi
  # copy into LaunchAgents for stable path
  local dest="$HOME/Library/LaunchAgents/${label}.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cp "$plist" "$dest"
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$dest"
  launchctl enable "$DOMAIN/$label" 2>/dev/null || true
  launchctl kickstart -k "$DOMAIN/$label" 2>/dev/null || true
  echo "installed $label"
}

_bootout() {
  local label="$1"
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/${label}.plist"
  echo "removed $label"
}

case "$cmd" in
  install)
    for l in "${labels[@]}"; do _bootstrap "$l"; done
    if [[ "$install_soc" == "1" ]]; then
      _bootstrap com.stellarrequiem.agent-soc-watch
    else
      echo "skip agent-soc-watch (set INSTALL_SOC_WATCH=1 to include freeze-only watch)"
    fi
    echo "claim: bridges always available — ARM is still operator/extension intentional"
    sleep 1
    python3 "$ROOT/cli.py" available || true
    ;;
  uninstall)
    for l in "${labels[@]}"; do _bootout "$l"; done
    _bootout com.stellarrequiem.agent-soc-watch || true
    ;;
  start)
    python3 "$ROOT/cli.py" up --no-arm-desktop
    python3 "$ROOT/cli.py" available
    ;;
  status|available)
    python3 "$ROOT/cli.py" available
    ;;
  *)
    echo "usage: $0 install|uninstall|start|status" >&2
    exit 2
    ;;
esac
