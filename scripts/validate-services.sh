#!/bin/bash
# Validate ANDroidMCP systemd services and connectivity
# This script checks if all services are running and can reach the backends

set -e

SERVICES=(
    "android-mcp-userspace"
    "android-mcp-bootloader"
    "android-mcp-orchestrator"
    "android-mcp-network"
)

echo "🔍 ANDroidMCP Service Validation"
echo "================================="
echo ""

# Check systemd services
echo "📋 Systemd Service Status:"
echo "------------------------"
all_running=true
for service in "${SERVICES[@]}"; do
    if systemctl --user is-active --quiet "$service.service"; then
        pid=$(systemctl --user show -p MainPID --value "$service.service")
        echo "✅ $service.service (PID: $pid)"
    else
        echo "❌ $service.service (STOPPED)"
        all_running=false
    fi
done

echo ""
echo "📊 Memory & CPU Usage:"
echo "---------------------"
systemctl --user status "${SERVICES[@]}" --no-pager | grep -E "Memory:|CPU:" || true

echo ""
echo "🔗 Bridge Connectivity:"
echo "---------------------"

# Test each bridge endpoint
for port in 8110 8111 8112 8113; do
    if timeout 2 bash -c "echo 'test' > /dev/tcp/127.0.0.1/$port" 2>/dev/null; then
        echo "✅ Bridge listening on 127.0.0.1:$port"
    else
        echo "⚠️  Bridge NOT responding on 127.0.0.1:$port"
    fi
done

echo ""
echo "📡 Tailscale Status:"
echo "-------------------"
tailscale status --self 2>/dev/null | grep -E "dizaster|IP:" || echo "⚠️  Tailscale not connected"

echo ""
if [ "$all_running" = true ]; then
    echo "✨ All services operational! Claude Desktop should work."
else
    echo "⚠️  Some services are down. Run: systemctl --user start android-mcp-*.service"
fi

echo ""
echo "💡 Next Steps:"
echo "  1. Ensure dizaster backend services are running"
echo "  2. Restart Claude Desktop"
echo "  3. Check Claude console for MCP initialization logs"
echo ""
echo "📖 View logs with: journalctl --user -u android-mcp-userspace -f"
