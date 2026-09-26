#!/bin/bash
# ANDroidMCP — Local dev server launcher
# Starts all 4 HTTP MCP servers (userspace, bootloader, orchestrator, network/tailscale)
# on ports 8110–8113. Kills stale instances first.

set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT:$PROJECT_ROOT/servers"
export ORCHESTRATOR_MCP_URL="${ORCHESTRATOR_MCP_URL:-http://127.0.0.1:8112/mcp}"
export ANDROIDMCP_STAGING_ROOT="${ANDROIDMCP_STAGING_ROOT:-$PROJECT_ROOT/staging}"
mkdir -p "$ANDROIDMCP_STAGING_ROOT"

echo "═══════════════════════════════════════"
echo "  ANDroidMCP Dev Start"
echo "  Project: $PROJECT_ROOT"
echo "═══════════════════════════════════════"

python3 --version || { echo "ERROR: python3 not found"; exit 1; }
echo -n "ADB: "; adb version 2>/dev/null | head -1 || echo "not found (device ops will fail)"

# ── Kill any stale server processes ──────────────────────────────────────────
echo ""
echo "Stopping stale servers..."
for PORT in 8110 8111 8112 8113; do
    PID=$(ss -tlnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K[0-9]+' | head -1 || true)
    if [ -n "$PID" ]; then
        echo "  Killing pid $PID on :$PORT"
        kill "$PID" 2>/dev/null || true
        sleep 0.5
    fi
done
# Also kill by name just in case
pkill -f "ANDroidMCP/servers" 2>/dev/null || true
sleep 1

# ── Start servers ─────────────────────────────────────────────────────────────
echo ""
echo "Starting servers..."

start_server() {
    local name="$1"
    local dir="$2"
    local port="$3"
    local extra_env="${4:-}"

    cd "$PROJECT_ROOT/servers/$dir"
    eval "MCP_PORT=$port $extra_env python3 -u server.py" \
        > "/tmp/androidmcp_${dir}.log" 2>&1 &
    local pid=$!
    echo "  [$name] pid=$pid → http://127.0.0.1:$port/mcp  (log: /tmp/androidmcp_${dir}.log)"
    echo $pid
}

PID_ORCH=$(start_server  "orchestrator"   "orchestrator"  "8112")
sleep 1  # orchestrator first (others may check it)

PID_USER=$(start_server  "userspace"      "userspace"     "8110" "ADB_SERVER_HOST=127.0.0.1 ADB_SERVER_PORT=5037")
PID_BOOT=$(start_server  "bootloader"     "bootloader"    "8111" "ORCHESTRATOR_MCP_URL=$ORCHESTRATOR_MCP_URL ANDROIDMCP_STAGING_ROOT=$ANDROIDMCP_STAGING_ROOT")
PID_NET=$(start_server   "network"        "tailscale"     "8113")

sleep 2

# ── Health check ──────────────────────────────────────────────────────────────
echo ""
echo "Health check..."
BRIDGE="/home/kamau/MCP/http-to-stdio-bridge/venv/bin/python"
BRIDGE_SCRIPT="/home/kamau/MCP/http-to-stdio-bridge/http_mcp_bridge.py"
INIT_MSG='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"healthcheck","version":"1.0"}}}'

for SVC in userspace:8110 bootloader:8111 orchestrator:8112 network:8113; do
    NAME="${SVC%%:*}"
    PORT="${SVC##*:}"
    RESULT=$(echo "$INIT_MSG" | HTTP_MCP_URL="http://127.0.0.1:$PORT/mcp" \
        "$BRIDGE" "$BRIDGE_SCRIPT" 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if 'result' in d else 'FAIL: '+str(d.get('error','?')))" 2>/dev/null || echo "UNREACHABLE")
    echo "  [$NAME :$PORT] $RESULT"
done

echo ""
echo "═══════════════════════════════════════"
echo "  Servers running on:"
echo "  android-userspace   → http://127.0.0.1:8110/mcp"
echo "  android-bootloader  → http://127.0.0.1:8111/mcp"
echo "  android-orchestrator→ http://127.0.0.1:8112/mcp"
echo "  android-network     → http://127.0.0.1:8113/mcp"
echo ""
echo "  Logs: /tmp/androidmcp_*.log"
echo "  Ctrl+C to stop all."
echo "═══════════════════════════════════════"

# Wait for all background jobs
trap "kill $PID_USER $PID_BOOT $PID_ORCH $PID_NET 2>/dev/null; echo 'Stopped.'" EXIT INT TERM
wait
