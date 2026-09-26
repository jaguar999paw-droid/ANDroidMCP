#!/bin/bash
# Setup systemd services for ANDroidMCP servers
# This script enables the MCP server services and ensures they autostart

set -e

SERVICES=(
    "android-mcp-userspace"
    "android-mcp-bootloader"
    "android-mcp-orchestrator"
    "android-mcp-network"
)

echo "🔧 ANDroidMCP Systemd Service Setup"
echo "===================================="

# Reload systemd to recognize new services
echo "📦 Reloading systemd daemon..."
systemctl --user daemon-reload

# Enable all services
echo "✅ Enabling services to autostart..."
for service in "${SERVICES[@]}"; do
    systemctl --user enable "$service.service"
    echo "   ✓ $service enabled"
done

# Start all services
echo "🚀 Starting services..."
for service in "${SERVICES[@]}"; do
    systemctl --user start "$service.service"
    echo "   ✓ $service started"
done

# Show status
echo ""
echo "📊 Service Status:"
echo "================="
systemctl --user status "${SERVICES[@]}" --no-pager || true

echo ""
echo "✨ Setup Complete!"
echo ""
echo "Services will now:"
echo "  • Start automatically on user login"
echo "  • Automatically restart if they fail"
echo "  • Log to journalctl"
echo ""
echo "Useful commands:"
echo "  • View logs:     journalctl --user -u android-mcp-userspace -f"
echo "  • Stop service:  systemctl --user stop android-mcp-userspace"
echo "  • Restart all:   systemctl --user restart android-mcp-*.service"
echo "  • Check status:  systemctl --user status android-mcp-*.service"
echo ""
echo "📌 Next: Restart Claude Desktop to use these managed services"
