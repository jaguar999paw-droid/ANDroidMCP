# ANDroidMCP — Operations Guide

Consolidated from `ANDROID_OPERATIONS_ASSESSMENT.md` + `SYSTEMD_SERVICES_SETUP.md` + `SYSTEMD_QUICK_REFERENCE.md` + `CLI_REFERENCE.md` + `INTERACTIVE_OPERATIONS.md` + `ANDROID_INTERACTION_CHECKLIST.md` + `INTEGRATION_GUIDE.md`.
This is the how-to-run-it and what-to-be-careful-of reference. For current live state, see `GAP.md`. For why it's built this way, see `ARCHITECTURE.md`.

## 1. Starting / Stopping

```bash
# Start all 4 HTTP servers (dev mode, must be up BEFORE Claude Desktop connects)
cd ~/ANDroidMCP && ./scripts/dev-start.sh

# Via systemd (run scripts/setup-systemd-services.sh once to install the backend units)
systemctl --user status android-mcp-*.service
~/ANDroidMCP/scripts/restart-services.sh
~/ANDroidMCP/scripts/stop-services.sh
~/ANDroidMCP/scripts/validate-services.sh

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

## 5. Remote operation and physical requirements

The MCP client can be remote from the **edge host**, but Android operations run
where the server process and device connection are. By default, the HTTP servers
bind to `127.0.0.1`, so a remote client needs a secure tunnel (for example SSH
port forwarding). Direct tailnet access requires setting `MCP_HOST` to the
edge host's Tailscale interface and configuring `MCP_AUTH_TOKEN` on both the
server and a bridge that sends the bearer header. Do not expose the endpoints
on a public interface. Details and a tunnel example are in `README.md`.

| Situation | What works / what is needed |
|---|---|
| ADB over USB | Device is connected to the edge host, Android debugging is enabled, and the host is authorized. First authorization may need a physical approval on the device. |
| ADB over device Wi-Fi | Android ADB-over-TCP is configured and the device is reachable from the ADB server used by `android-userspace`. This is separate from remotely reaching the MCP endpoint. |
| Fastboot | Device is in a supported Fastboot mode and USB-connected to the edge host. The host runs `fastboot`; ADB and Fastboot are separate modes/tools. |
| MediaTek BootROM / Qualcomm EDL | Not supported by the current runtime; the BootROM server is a scaffold and is not launched. |

Developer Options, initial USB setup, and some bootloader unlock flows may
require a person physically present. For flashing, stage the image on the edge
host and keep the device connected during the operation.

## 6. Security status and open limitations

The HTTP services bind to `127.0.0.1` by default. A non-loopback `MCP_HOST`
requires `MCP_AUTH_TOKEN`; the token is static bearer authentication, not
per-user or per-tool authorization. Configure the separate stdio bridge to
send the bearer header when auth is enabled. Do not rely on the Tailscale
server's endpoint URLs as proof that listeners are reachable remotely.

Implemented protections include input validation, staging-path confinement,
preflight confirmation tokens, and an audit log for selected sensitive
operations (see section 8 and `GAP.md`). Important limitations remain:

- `execute_shell_command` still permits arbitrary Android shell commands.
- Confirmation codes are returned through the calling MCP client, so the
  confirmation flow is not an independent human-authentication boundary.
- There is no per-device ownership/consent registry or general tool-call rate
  limit.
- The BootROM/MTK/EDL server is only a scaffold; its design claims are not
  deployed security controls.

Use `GAP.md` for the detailed, current issue list.

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

# Docker image builds (blocked historically — see GAP.md O6)
docker build -f servers/userspace/Dockerfile -t androidmcp/userspace-server:latest .
```

## 8. Troubleshooting

- **Device not visible:** `adb devices -l`; if using K8s, `kubectl exec -it deployment/android-userspace-server -n androidmcp -- adb devices -l`.
- **Bridge / Claude Desktop can't see a server:** confirm the HTTP server is already running on its port (`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8110/mcp` — a `406` is fine, means it's alive but wants a proper MCP POST) before Claude Desktop starts. Restart Claude Desktop completely after any config change.
- **`journalctl --user -u android-mcp-userspace -n 20`** for systemd-managed server crash logs.
- **Tailscale IP resolution:** the bridge does `tailscale ip --4` → `tailscale status` grep → `~/.cache/androidmcp_ts_ip` → hardcoded fallback, in that order. Clear the cache file if the fallback IP goes stale.
- **Pod won't start (once on K8s):** `kubectl describe pod` / `kubectl get events -n androidmcp --sort-by='.lastTimestamp'`.

## References

Full detail — Interactive-operations decision trees with example transcripts, the pre/during/post-op checklist, and the original step-by-step K3s integration guide — is not included in this repository.

## 8. Hardening settings

| Variable | Default | Effect |
|---|---|---|
| `MCP_HOST` | `127.0.0.1` | Interface the HTTP servers bind to. Setting a non-loopback value requires `MCP_AUTH_TOKEN`; the server refuses to start otherwise. |
| `MCP_AUTH_TOKEN` | unset | When set, every request must carry `Authorization: Bearer <token>`. Backend-to-orchestrator calls send it automatically. The stdio bridge must be configured to send the same header. |
| `ANDROIDMCP_STAGING_ROOT` | `~/ANDroidMCP/staging` | Image files must live here (symlinks are resolved first). |
| `ANDROIDMCP_IMAGE_ROOTS` | unset | Extra directories (`os.pathsep`-separated) from which images may be flashed. |
| `ANDROIDMCP_PREFLIGHT_TTL` | `600` | Seconds a flash/unlock preflight stays valid. |
| `ANDROIDMCP_MAX_TOKEN_ATTEMPTS` | `5` | Wrong confirmation codes before the preflight is revoked. |
| `ANDROIDMCP_AUDIT_FILE` | `~/.cache/androidmcp/audit.log` | JSON-lines audit log (owner-only) of shell, install, flash, unlock and lock calls. Secrets are never written. |
| `HOST_TS_IP` | unset | Tailscale IP used by the network server for endpoint URLs (falls back to live detection). |
| `TAILSCALE_AUTH_KEY` | unset | Only needed for node provisioning; never commit it. |

Behaviour changes worth knowing: `lock_bootloader` now requires `confirm="LOCK"`; confirmation codes are single-use;
partitions in the boot chain (`boot`, `vbmeta*`, `recovery`, `radio`, ...) are treated as CRITICAL and need
`partition_confirm`; `execute_shell_command` timeouts are capped at 300 s.
