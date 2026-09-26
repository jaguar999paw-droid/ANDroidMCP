#!/usr/bin/env bash
# ANDroidMCP — Linux installer for the standalone release build.
# Installs the 4 prebuilt binaries + bundled adb/fastboot, wires them up
# as systemd --user services (server.py-direct pattern, not the old
# stdio-bridge pattern), and enables them so they survive a reboot.
set -euo pipefail

INSTALL_DIR="${ANDROIDMCP_INSTALL_DIR:-$HOME/.local/share/androidmcp}"
UNIT_DIR="$HOME/.config/systemd/user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing ANDroidMCP to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR/bin" "$INSTALL_DIR/platform-tools" "$INSTALL_DIR/logs" "$INSTALL_DIR/staging" "$UNIT_DIR"

cp "$SCRIPT_DIR"/bin/* "$INSTALL_DIR/bin/"
chmod +x "$INSTALL_DIR"/bin/*
if [ -d "$SCRIPT_DIR/platform-tools" ]; then
  cp -r "$SCRIPT_DIR"/platform-tools/* "$INSTALL_DIR/platform-tools/"
  chmod +x "$INSTALL_DIR"/platform-tools/adb "$INSTALL_DIR"/platform-tools/fastboot 2>/dev/null || true
fi

write_unit() {
  local name="$1" bin="$2" port="$3" extra_env="$4"
  cat > "$UNIT_DIR/androidmcp-${name}.service" << UNITEOF
[Unit]
Description=ANDroidMCP ${name} (:${port})
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/bin/${bin}
Environment=MCP_PORT=${port}
Environment=PATH=${INSTALL_DIR}/platform-tools:/usr/bin:/bin:/usr/local/bin
${extra_env}
Restart=on-failure
RestartSec=5
StartLimitInterval=300
StartLimitBurst=5
StandardOutput=append:${INSTALL_DIR}/logs/${name}.log
StandardError=append:${INSTALL_DIR}/logs/${name}.log
SyslogIdentifier=androidmcp-${name}

[Install]
WantedBy=default.target
UNITEOF
}

write_unit userspace    android-userspace    8110 $'Environment=ADB_SERVER_HOST=127.0.0.1\nEnvironment=ADB_SERVER_PORT=5037\nEnvironment=ORCHESTRATOR_MCP_URL=http://127.0.0.1:8112/mcp'
write_unit bootloader   android-bootloader   8111 $'Environment=ORCHESTRATOR_MCP_URL=http://127.0.0.1:8112/mcp\nEnvironment=ANDROIDMCP_STAGING_ROOT='"${INSTALL_DIR}"'/staging'
write_unit orchestrator android-orchestrator 8112 ""
write_unit network      android-network      8113 ""

systemctl --user daemon-reload
systemctl --user enable --now androidmcp-userspace androidmcp-bootloader androidmcp-orchestrator androidmcp-network

echo ""
echo "Installed and started. Status:"
for s in userspace bootloader orchestrator network; do
  printf "  %-14s " "$s"
  systemctl --user is-active "androidmcp-$s"
done

TS_IP="$(command -v tailscale >/dev/null 2>&1 && tailscale ip -4 2>/dev/null || echo "<this-host-tailscale-ip>")"
echo ""
echo "MCP endpoints (reachable over your tailnet):"
echo "  http://${TS_IP}:8110/mcp  (userspace)"
echo "  http://${TS_IP}:8111/mcp  (bootloader)"
echo "  http://${TS_IP}:8112/mcp  (orchestrator)"
echo "  http://${TS_IP}:8113/mcp  (network)"
echo ""
echo "Point your MCP client / bridge config at these URLs."
