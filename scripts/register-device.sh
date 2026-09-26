#!/bin/bash
# register-device.sh — Add a new Android device to ANDroidMCP inventory
# Usage: ./register-device.sh <serial> <model> <node_hostname> [brom_capable]
set -e

SERIAL="${1:-}"
MODEL="${2:-unknown}"
NODE="${3:-dizaster}"
BROM="${4:-false}"

[ -z "$SERIAL" ] && echo "Usage: $0 <serial> <model> <node_hostname> [brom_capable=false]" && exit 1

echo "Registering device: serial=$SERIAL model=$MODEL node=$NODE brom=$BROM"

# Verify ADB sees the device
adb -s "$SERIAL" get-state 2>/dev/null || echo "WARNING: ADB cannot see $SERIAL — is it connected?"

# Apply K8s ConfigMap for device state
kubectl apply -f - << YAML
apiVersion: v1
kind: ConfigMap
metadata:
  name: device-state-${SERIAL}
  namespace: androidmcp
  labels:
    androidmcp/device: "true"
    androidmcp/brom-capable: "${BROM}"
data:
  serial: "${SERIAL}"
  model: "${MODEL}"
  current_state: "CONNECTED"
  lock_holder: ""
  edge_node_hostname: "${NODE}"
  brom_capable: "${BROM}"
  registered_at: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
YAML

echo "Device $SERIAL registered in androidmcp namespace."
echo "Run: kubectl get configmap device-state-${SERIAL} -n androidmcp -o yaml"
