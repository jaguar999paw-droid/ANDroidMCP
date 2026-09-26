#!/usr/bin/env bash
# =============================================================================
# ANDroidMCP — Dynamic Node Bring-Up Script
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'
BLU='\033[0;34m'; CYN='\033[0;36m'; DIM='\033[2m'; RST='\033[0m'
ok()   { echo -e "${GRN}  ✓${RST}  $*"; }
info() { echo -e "${BLU}  ►${RST}  $*"; }
warn() { echo -e "${YEL}  ⚠${RST}  $*"; }
die()  { echo -e "${RED}  ✗${RST}  $*" >&2; exit 1; }
sep()  { echo -e "${DIM}──────────────────────────────────────────────────────${RST}"; }

TAILSCALE_AUTH_KEY="tskey-[REDACTED]"
DIZASTER_TS_IP="100.118.209.46"
declare -A MCP_SERVERS=(
  ["android-userspace"]="http://${DIZASTER_TS_IP}:8110/mcp"
  ["android-bootloader"]="http://${DIZASTER_TS_IP}:8111/mcp"
  ["android-orchestrator"]="http://${DIZASTER_TS_IP}:8112/mcp"
  ["android-network"]="http://${DIZASTER_TS_IP}:8113/mcp"
)
NODE_TAG="tag:android"
SKIP_VERIFY=false
SUFFIX=""

for arg in "$@"; do
  case "$arg" in
    --skip-verify) SKIP_VERIFY=true ;;
    --*)           die "Unknown flag: $arg" ;;
    *)             SUFFIX="$arg" ;;
  esac
done

SUFFIX="${SUFFIX:-${ANDROID_NODE_SUFFIX:-}}"
if [[ -z "$SUFFIX" ]]; then
  SUFFIX="$(hostname | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/-*$//')"
  info "Auto-suffix from hostname: ${CYN}${SUFFIX}${RST}"
fi

NODE_HOSTNAME="ANDroid-${SUFFIX}"

echo ""
echo -e "${CYN}╔══════════════════════════════════════════════════════╗${RST}"
echo -e "${CYN}║        ANDroidMCP  —  Node Bring-Up                 ║${RST}"
echo -e "${CYN}╚══════════════════════════════════════════════════════╝${RST}"
echo ""
info "Node hostname  : ${CYN}${NODE_HOSTNAME}${RST}"
info "Tailscale tag  : ${CYN}${NODE_TAG}${RST}"
info "dizaster IP    : ${CYN}${DIZASTER_TS_IP}${RST}"
sep

info "Checking dependencies..."
for cmd in tailscale curl jq; do
  command -v "$cmd" &>/dev/null && ok "$cmd found" || die "$cmd not installed"
done
sep

info "Checking current Tailscale state..."
TS_STATUS="$(tailscale status --json 2>/dev/null || echo '{}')"
TS_BACKEND="$(echo "$TS_STATUS" | jq -r '.BackendState // "unknown"')"
TS_SELF_IP="$(echo "$TS_STATUS" | jq -r '.Self.TailscaleIPs[0] // empty' 2>/dev/null || true)"

if [[ "$TS_BACKEND" == "Running" && -n "$TS_SELF_IP" ]]; then
  CURRENT_HOST="$(echo "$TS_STATUS" | jq -r '.Self.HostName // "unknown"')"
  warn "Already on tailnet as '${CURRENT_HOST}' (${TS_SELF_IP})"
  warn "Will re-authenticate as '${NODE_HOSTNAME}'"
  read -rp "  Continue? [y/N] " confirm
  [[ "${confirm,,}" == "y" ]] || { info "Aborted."; exit 0; }
fi
sep

info "Joining tailnet as '${NODE_HOSTNAME}' with ${NODE_TAG}..."
TS_UP_ARGS=(
  "--authkey=${TAILSCALE_AUTH_KEY}"
  "--hostname=${NODE_HOSTNAME}"
  "--accept-routes"
  "--accept-dns"
)

if sudo tailscale up "${TS_UP_ARGS[@]}" 2>&1; then
  ok "tailscale up succeeded"
else
  warn "sudo failed — retrying without sudo"
  tailscale up "${TS_UP_ARGS[@]}"
fi

sleep 3

info "Verifying node identity..."
NEW_STATUS="$(tailscale status --json 2>/dev/null || echo '{}')"
MY_IP="$(echo "$NEW_STATUS"   | jq -r '.Self.TailscaleIPs[0] // empty')"
MY_HOST="$(echo "$NEW_STATUS" | jq -r '.Self.HostName // empty')"
MY_TAGS="$(echo "$NEW_STATUS" | jq -r '.Self.Tags // [] | join(", ")')"

[[ -z "$MY_IP" ]] && die "No Tailscale IP after joining. Check 'tailscale status'."

ok "Node IP   : ${CYN}${MY_IP}${RST}"
ok "Hostname  : ${CYN}${MY_HOST}${RST}"
ok "Tags      : ${CYN}${MY_TAGS:-"(check admin — key-based tags may appear delayed)"}${RST}"
sep

if [[ "$SKIP_VERIFY" == "true" ]]; then
  warn "Skipping endpoint verification (--skip-verify)"
else
  info "Checking ANDroidMCP server reachability..."
  echo ""
  ALL_OK=true
  for name in "${!MCP_SERVERS[@]}"; do
    url="${MCP_SERVERS[$name]}"
    HTTP_CODE="$(curl -s -o /dev/null -w "%{http_code}" --max-time 6 \
      -H "Accept: text/event-stream" "$url" 2>/dev/null || echo "000")"
    if [[ "$HTTP_CODE" =~ ^(200|400|405)$ ]]; then
      printf "  ${GRN}✓${RST}  %-28s ${DIM}%s${RST}  HTTP %s\n" "$name" "$url" "$HTTP_CODE"
    else
      printf "  ${RED}✗${RST}  %-28s ${DIM}%s${RST}  HTTP %s\n" "$name" "$url" "$HTTP_CODE"
      ALL_OK=false
    fi
  done
  echo ""
  [[ "$ALL_OK" == "false" ]] && warn "Some servers unreachable. Run: ~/ANDroidMCP/scripts/start-servers.sh" \
                              || ok "All ANDroidMCP servers reachable"
fi
sep

CONFIG_OUT="${HOME}/.config/androidmcp-claude-config.json"
mkdir -p "$(dirname "$CONFIG_OUT")"
cat > "$CONFIG_OUT" <<EOF
{
  "_node": "${NODE_HOSTNAME}",
  "_node_ip": "${MY_IP}",
  "_dizaster_ip": "${DIZASTER_TS_IP}",
  "mcpServers": {
    "android-userspace":    { "url": "http://${DIZASTER_TS_IP}:8110/mcp" },
    "android-bootloader":   { "url": "http://${DIZASTER_TS_IP}:8111/mcp" },
    "android-orchestrator": { "url": "http://${DIZASTER_TS_IP}:8112/mcp" },
    "android-network":      { "url": "http://${DIZASTER_TS_IP}:8113/mcp" }
  }
}
EOF
ok "Config written: ${CYN}${CONFIG_OUT}${RST}"
sep

echo ""
echo -e "${GRN}╔══════════════════════════════════════════════════════╗${RST}"
echo -e "${GRN}║   ${NODE_HOSTNAME} is live on your tailnet           ║${RST}"
echo -e "${GRN}╚══════════════════════════════════════════════════════╝${RST}"
echo ""
echo -e "  ${CYN}IP${RST}      : ${MY_IP}"
echo -e "  ${CYN}Tag${RST}     : ${NODE_TAG}"
echo -e "  ${CYN}Config${RST}  : ${CONFIG_OUT}"
echo ""
echo -e "  Next: copy config → Claude Desktop, plug in USB, run adb devices"
echo ""
