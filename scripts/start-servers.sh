#!/bin/bash
# ANDroidMCP — persistent server launcher
# Run at login or via: systemctl --user start androidmcp
# Servers bind to 0.0.0.0 but are only reachable via Tailscale (100.118.209.46)

set -e
PROJECT="/home/kamau/ANDroidMCP"
LOGS="/tmp/androidmcp_logs"
mkdir -p "$LOGS"

stop_all() {
    pkill -f "$PROJECT/servers" 2>/dev/null && echo "[androidmcp] servers stopped" || true
}

# Check if already running — exit BEFORE the trap is armed, so an
# already-healthy fleet is never killed by a second invocation of this script.
if ss -tlnp | grep -qE '8110|8111|8112|8113'; then
    echo "[androidmcp] servers already running:"
    ss -tlnp | grep -E '8110|8111|8112|8113'
    exit 0
fi

# Only from here on do we own these processes, so only from here on do we
# trap on exit to clean them up.
trap stop_all EXIT INT TERM

echo "[androidmcp] starting orchestrator :8112..."
nohup bash -c "cd $PROJECT/servers/orchestrator && exec python3 -u server.py" \
    > "$LOGS/orchestrator.log" 2>&1 & PIDS="$!"
sleep 3

echo "[androidmcp] starting userspace :8110..."
nohup bash -c "cd $PROJECT/servers/userspace && PYTHONPATH=. exec python3 -u server.py" \
    > "$LOGS/userspace.log" 2>&1 & PIDS="$PIDS $!"
sleep 2

echo "[androidmcp] starting bootloader :8111..."
nohup bash -c "cd $PROJECT/servers/bootloader && exec python3 -u server.py" \
    > "$LOGS/bootloader.log" 2>&1 & PIDS="$PIDS $!"
sleep 2

echo "[androidmcp] starting tailscale-coord :8113..."
nohup bash -c "cd $PROJECT/servers/tailscale && exec python3 -u server.py" \
    > "$LOGS/tailscale.log" 2>&1 & PIDS="$PIDS $!"
sleep 3

echo "[androidmcp] verifying endpoints..."
for port in 8110 8111 8112 8113; do
    if curl -s --max-time 3 "http://127.0.0.1:$port/mcp" | grep -q 'jsonrpc'; then
        echo "  :$port ✓ live"
    else
        echo "  :$port ✗ not responding — check $LOGS/"
    fi
done

echo ""
echo "[androidmcp] all servers started. Accessible via Tailscale at:"
echo "  android-userspace    → http://100.118.209.46:8110/mcp"
echo "  android-bootloader   → http://100.118.209.46:8111/mcp"
echo "  android-orchestrator → http://100.118.209.46:8112/mcp"
echo "  android-network      → http://100.118.209.46:8113/mcp"
echo ""
echo "[androidmcp] Claude Desktop: restart app to pick up new servers."
echo "[androidmcp] Logs: $LOGS/"
echo ""
echo "Keeping process alive. Ctrl+C to stop all servers."
wait
