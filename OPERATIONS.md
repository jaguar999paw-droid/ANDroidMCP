# ANDroidMCP — Operations Guide

Consolidated from `ANDROID_OPERATIONS_ASSESSMENT.md` + `SYSTEMD_SERVICES_SETUP.md` + `SYSTEMD_QUICK_REFERENCE.md` + `CLI_REFERENCE.md` + `INTERACTIVE_OPERATIONS.md` + `ANDROID_INTERACTION_CHECKLIST.md` + `INTEGRATION_GUIDE.md` (originals moved to `archive/`).
This is the how-to-run-it and what-to-be-careful-of reference. For current live state, see `STATUS_AND_HANDOFF.md`. For why it's built this way, see `ARCHITECTURE.md`.

## 1. Starting / Stopping

```bash
# Start all 4 HTTP servers (dev mode, must be up BEFORE Claude Desktop connects)
cd ~/ANDroidMCP && ./scripts/dev-start.sh

# Via systemd (installed but check STATUS_AND_HANDOFF.md — currently inactive)
systemctl --user status android-mcp-*.service
/home/kamau/ANDroidMCP/scripts/restart-services.sh
/home/kamau/ANDroidMCP/scripts/stop-services.sh
/home/kamau/ANDroidMCP/scripts/validate-services.sh

# Live logs
journalctl --user -u android-mcp-userspace -f
tail -f ~/ANDroidMCP/logs/{userspace,bootloader,orchestrator,network}.log
```

Claude Desktop only spawns stdio subprocesses. The 4 servers run `streamable-http`; `~/MCP/http-to-stdio-bridge/http_mcp_bridge.py` translates. The HTTP servers must already be listening before Claude Desktop starts the bridge, or the bridge fails immediately.

## 2. Tools Inventory

**android-userspace** (🟢, port 8110): `get_connected_devices`, `capture_screen_and_hierarchy`, `execute_shell_command`, `get_logcat`, `install_apk`, `tap`, `type_text`, `get_device_properties`, `health_check`

**android-bootloader** (🟡, port 8111): `get_fastboot_devices`, `preflight_flash`, `flash_partition`, `resume_flash`, `unlock_bootloader`, `lock_bootloader`, `get_bootloader_status`, `stage_image`, `health_check`

**android-orchestrator** (🟢, port 8112): `acquire_lock`, `release_lock`, `get_device_state`, `list_devices`, `heartbeat`, `validate_state_transition`, `cluster_health`, `store_preflight`, `get_preflight`, `register_device_health`

**android-network** (🟢, port 8113): `get_tailscale_status`, `get_own_tailscale_ip`, `check_mcp_endpoint_reachability`, `advertise_pod_cidr`, `list_advertised_routes`, `generate_claude_desktop_config`

**android-bootrom** (🔴, stdio-only): disabled, Phase 3 scaffold — do not enable without the HITL/TOTP work.

## 3. Safe Flash Workflow

```
1. preflight_flash(serial, partition, image_path)   → acquires lock, checks fastboot presence,
                                                          current slot, SHA256, staging path
2. flash_partition(serial, partition, image_path, preflight_id)  → returns HITL summary, does not flash yet
3. [human confirms in chat]
4. resume_flash(serial, partition, preflight_id, user_confirms=true)  → actually flashes
```

Images go under `~/ANDroidMCP/staging/{serial}/` — never streamed over Tailscale, always local to the edge host doing the flash.

## 4. Human-in-the-Loop Model (by tier)

| Tier | Examples | Requirement |
|---|---|---|
| 🟢 Read-only | `get_connected_devices`, `capture_screen_and_hierarchy`, `get_logcat` | Fully automated |
| ⚠️ Decision point | `install_apk`, `tap`, `type_text`, `execute_shell_command` | Chat confirmation before executing |
| 🟡 Device interaction | `unlock_bootloader` (30s window — user presses power button), `flash_partition` (2 min, device must stay connected) | Confirmation + physical device action + monitoring |
| 🔴 HITL token | Any BootROM write | TOTP + device attestation + "YES, I UNDERSTAND THE RISK" typed confirmation — not implemented yet, tier is disabled |

Rule of thumb: **no destructive operation proceeds without explicit confirmation at the moment of execution**, and the user is responsible for physical device safety during flashes (don't unplug mid-write). Timeouts auto-abort and release the lock if the user doesn't respond (30s for unlock, 2 min for flash, 10 min for a BootROM write once that tier exists).

## 5. Effectiveness — What's Actually Remote vs Needs Physical Presence

| Scenario | Remote-only effectiveness |
|---|---|
| UI automation / logcat / shell on an already-authorized device | ~95% |
| ROM/firmware flashing (bootloader already unlocked) | ~80% |
| Fleet management via USB hub | ~85% |
| WiFi-only ADB (after `adb tcpip 5555` set once) | ~90% |
| Brand-new out-of-box device | ~40% — needs a physical USB-debugging tap once |
| BootROM/EDL | 0% — Phase 3 not implemented |

Needs a human physically present at least once: first-time USB authorization dialog, enabling Developer Options, the initial USB cable connection (until WiFi ADB is set up), and the power-button confirmation for bootloader unlock.

## 6. Security Backlog (bare-metal dev servers — not yet hardened)

These are gaps in the *currently running* dev servers, distinct from the K8s target-state threat model in `ARCHITECTURE.md`:

- **No auth on the HTTP endpoints** (`0.0.0.0:8110-8113`, zero auth) — add a static token header or Tailscale `whois`-based middleware before trusting this beyond localhost.
- **`execute_shell_command` has no allowlist/blocklist** — full `adb shell` reach on the device.
- **No audit logging** of which session called which tool with what args on which device.
- **`flash_partition` had no confirmation gate originally** — now mitigated by the preflight/resume-flash HITL pattern above, but `DANGEROUS_PARTITIONS` (bootloader/radio/recovery/userdata) should still get an extra token gate.
- **Servers bind `0.0.0.0`**, not `127.0.0.1` — reachable from any interface, not just loopback/Tailscale.
- **No device-owner consent registry** (`devices.yaml` mapping serial → owner → allowed ops) — anyone with USB-hub access could target someone else's device.
- **No rate limiting** on tool calls.

## 7. CLI Quick Reference

```bash
# ADB / fastboot
adb devices -l ; adb start-server ; adb shell ; adb logcat
adb shell screencap -p /sdcard/screenshot.png && adb pull /sdcard/screenshot.png
adb install app.apk

# K3s / K8s (once actually deployed — see ARCHITECTURE.md §6)
kubectl apply -f k8s/namespaces/androidmcp.yaml
kubectl get pods -n androidmcp -w
kubectl logs -f deployment/android-userspace-server -n androidmcp
kubectl exec -it deployment/android-userspace-server -n androidmcp -- bash
kubectl port-forward svc/android-userspace 8100:8100 -n androidmcp

# Tailscale
tailscale status
tailscale status | grep Routes
sudo tailscale up --advertise-routes=10.42.0.0/16 --accept-routes

# Docker image builds (blocked historically — see STATUS_AND_HANDOFF.md network notes)
docker build -f servers/userspace/Dockerfile -t androidmcp/userspace-server:latest .
```

## 8. Troubleshooting

- **Device not visible:** `adb devices -l`; if using K8s, `kubectl exec -it deployment/android-userspace-server -n androidmcp -- adb devices -l`.
- **Bridge / Claude Desktop can't see a server:** confirm the HTTP server is already running on its port (`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8110/mcp` — a `406` is fine, means it's alive but wants a proper MCP POST) before Claude Desktop starts. Restart Claude Desktop completely after any config change.
- **`journalctl --user -u android-mcp-userspace -n 20`** for systemd-managed server crash logs.
- **Tailscale IP resolution:** the bridge does `tailscale ip --4` → `tailscale status` grep → `~/.cache/androidmcp_ts_ip` → hardcoded fallback, in that order. Clear the cache file if the fallback IP goes stale.
- **Pod won't start (once on K8s):** `kubectl describe pod` / `kubectl get events -n androidmcp --sort-by='.lastTimestamp'`.

## References

Full detail — Interactive-operations decision trees with example transcripts, the pre/during/post-op checklist, and the original step-by-step K3s integration guide — is preserved in `archive/`: `INTERACTIVE_OPERATIONS.md`, `ANDROID_INTERACTION_CHECKLIST.md`, `INTEGRATION_GUIDE.md`, `CLI_REFERENCE.md`.
