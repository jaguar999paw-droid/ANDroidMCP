#!/bin/bash
# emergency-unlock-usb.sh — Release a stuck USB device lock in the orchestrator
# Usage: ./emergency-unlock-usb.sh <device_serial>
# Run when: a server crashes while holding a device lock, leaving it stuck.
set -e

SERIAL="${1:-}"
[ -z "$SERIAL" ] && echo "Usage: $0 <device_serial>" && exit 1

echo "Emergency USB unlock for device: $SERIAL"
echo "WARNING: Only run this if the lock holder server has crashed."
read -p "Are you sure? (yes/no): " CONFIRM
[ "$CONFIRM" != "yes" ] && echo "Aborted." && exit 0

# Patch the ConfigMap to clear the lock
kubectl patch configmap "device-state-${SERIAL}" -n androidmcp \
  --type merge \
  -p "{\"data\":{\"lock_holder\":\"\",\"current_state\":\"CONNECTED\",\"lock_acquired_at\":\"\",\"emergency_unlock_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}}"

echo "Lock cleared for $SERIAL."
echo "Device state reset to CONNECTED."
kubectl get configmap "device-state-${SERIAL}" -n androidmcp -o jsonpath='{.data}' | python3 -m json.tool
