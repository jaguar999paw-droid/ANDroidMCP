#!/bin/bash
# Install systemd *user* units that run the four ANDroidMCP backend servers directly
# (not the stdio bridge, which Claude Desktop spawns itself).
#
# NOTE: this overwrites existing android-mcp-*.service files of the same names.
#
# Optional environment:
#   ANDROIDMCP_PYTHON    interpreter to use      (default: <repo>/venv/bin/python)
#   ANDROIDMCP_ENV_FILE  extra EnvironmentFile   (default: ~/.config/androidmcp/env;
#                        put MCP_HOST / MCP_AUTH_TOKEN there, mode 600)
#   ANDROIDMCP_UNIT_DIR  where to write units    (default: ~/.config/systemd/user)
#   NO_SYSTEMCTL=1       only write the unit files (used for testing)

set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ANDROIDMCP_PYTHON:-$PROJECT/venv/bin/python}"
ENV_FILE="${ANDROIDMCP_ENV_FILE:-$HOME/.config/androidmcp/env}"
UNIT_DIR="${ANDROIDMCP_UNIT_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"

# name : server dir : port
SERVICES=(
    "orchestrator:orchestrator:8112"
    "userspace:userspace:8110"
    "bootloader:bootloader:8111"
    "network:tailscale:8113"
)

[ -x "$PYTHON" ] || { echo "Python interpreter not found: $PYTHON (set ANDROIDMCP_PYTHON)" >&2; exit 1; }

mkdir -p "$UNIT_DIR" "$(dirname "$ENV_FILE")"
if [ ! -f "$ENV_FILE" ]; then
    ( umask 077; printf '# MCP_HOST=127.0.0.1\n# MCP_AUTH_TOKEN=\n' > "$ENV_FILE" )
    echo "Created $ENV_FILE (owner-only). Put MCP_AUTH_TOKEN there if you expose the servers."
fi

echo "ANDroidMCP systemd setup"
echo "========================"

for entry in "${SERVICES[@]}"; do
    IFS=: read -r name dir port <<< "$entry"
    after="network.target"
    [ "$name" = "orchestrator" ] || after="network.target android-mcp-orchestrator.service"

    cat > "$UNIT_DIR/android-mcp-$name.service" <<EOF
[Unit]
Description=ANDroidMCP $name server (port $port)
After=$after

[Service]
Type=simple
WorkingDirectory=$PROJECT/servers/$dir
Environment=PYTHONPATH=$PROJECT:$PROJECT/servers
Environment=MCP_PORT=$port
Environment=ORCHESTRATOR_MCP_URL=http://127.0.0.1:8112/mcp
Environment=ANDROIDMCP_STAGING_ROOT=$PROJECT/staging
EnvironmentFile=-$ENV_FILE
ExecStart=$PYTHON -u server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
    echo "  wrote android-mcp-$name.service"
done

if [ "${NO_SYSTEMCTL:-0}" = "1" ]; then
    echo "NO_SYSTEMCTL=1: units written, not enabled."
    exit 0
fi

systemctl --user daemon-reload
for entry in "${SERVICES[@]}"; do
    name="${entry%%:*}"
    systemctl --user enable --now "android-mcp-$name.service"
done

echo ""
systemctl --user --no-pager status 'android-mcp-*.service' | grep -E 'Active:|android-mcp' || true
echo ""
echo "Logs:    journalctl --user -u android-mcp-userspace -f"
echo "Restart: systemctl --user restart 'android-mcp-*.service'"
echo "Boot persistence for a user without an active login: loginctl enable-linger \$USER"
