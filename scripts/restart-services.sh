#!/bin/bash
# Restart all ANDroidMCP systemd services

echo "🔄 Restarting ANDroidMCP services..."
systemctl --user restart android-mcp-{userspace,bootloader,orchestrator,network}.service

echo ""
sleep 1
systemctl --user status android-mcp-*.service --no-pager | grep -E "Active:|android-mcp"

echo ""
echo "✅ Services restarted. Give them a few seconds to stabilize."
