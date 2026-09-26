#!/bin/bash
# Stop all ANDroidMCP systemd services

echo "🛑 Stopping ANDroidMCP services..."
systemctl --user stop android-mcp-{userspace,bootloader,orchestrator,network}.service

echo ""
sleep 1
systemctl --user status android-mcp-*.service --no-pager | grep -E "Active:|android-mcp"

echo ""
echo "✅ Services stopped."
