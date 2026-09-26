# ANDroidMCP — Architecture

Consolidated from `REASONING.md` + `ARCHITECTURAL_SYNTHESIS_INTEGRATION.md` (originals moved to `archive/`).
This is the design reference: what the system is, why it's shaped this way, and what's designed-but-not-yet-built.

## 1. What This Is

A hardware-sovereign AI orchestration platform: Claude, via MCP, gets authenticated, audited, low-latency reach into the Android hardware stack — from UI automation down to raw BootROM silicon — on devices physically attached to **dizaster**, without needing physical presence.

Three constraints drive every design decision:
1. **USB physicality** — USB isn't a network protocol; bridging it into a networked control plane without losing exclusivity or security is the core challenge.
2. **Risk stratification** — flashing `boot.img` and exploiting a MediaTek BROM are categorically different risk classes; the architecture makes it *structurally* impossible (not just policy-impossible) to reach BootROM writes without the right auth chain.
3. **State coherence** — a device can't be in ADB mode and Fastboot mode simultaneously. One orchestrator enforces a single state machine per device serial across all servers.

## 2. Five MCP Servers — Risk Tiers

| Server | Risk | Transport | Notes |
|---|---|---|---|
| `android-userspace-server` | 🟢 LOW | HTTP/SSE (bridged to stdio for Claude Desktop) | ADB: screenshots, shell, logcat, install, UI automation |
| `android-bootloader-server` | 🟡 MEDIUM | HTTP/SSE (bridged) | Fastboot: flash, unlock/lock, getvar |
| `android-orchestrator-server` | 🟢 LOW | HTTP/SSE (bridged) | Device state machine + exclusive locks |
| `android-network-server` (tailscale) | 🟢 LOW | HTTP/SSE (bridged) | Tailscale status/routing |
| `android-bootrom-exploit-server` | 🔴 CRITICAL | **stdio ONLY** | MTK/EDL raw hardware — Phase 3, not deployed |

**Critical design decision:** the BootROM server is stdio-only, reachable only via `kubectl exec` from an active human terminal session. It cannot be hit over HTTP, cannot be routed through Tailscale, cannot be reached by an automated retry loop — unattended BootROM exploitation is structurally impossible, not just policy-forbidden.

## 3. USB Passthrough Strategy

| Mode | Path | Container privilege |
|---|---|---|
| ADB | Host `adb server` on TCP 5037; container speaks ADB-over-TCP only | Unprivileged |
| Fastboot | K8s Device Plugin exposes `/dev/bus/usb/BUS/DEVICE` as a resource | `hostPath` mount, no full privilege |
| BootROM/EDL (MTK vendor `0e8d:0003`, Qualcomm EDL `05c6:9008`) | Full `/dev/bus/usb` tree, `privileged: true` | Privileged; no network interface; `FROM scratch` image, no shell |

**Revised guidance (from the integration synthesis):** MTK/EDL timing is too sensitive for a remote pod over Tailscale. The corrected plan is a **host-native `mtk-edge-daemon`** (systemd, stdio or unix socket) rather than routing BootROM through K8s + Tailscale — this pillar is deliberately deferred (Phase 3, lowest priority) rather than built as originally sketched.

## 4. Device State Machine

Single authoritative state per device serial, owned exclusively by the orchestrator:

```
CONNECTED → ANDROID_OS (userspace lock) → FASTBOOT_MODE (bootloader lock) → BROM/EDL_MODE (bootrom lock)
```

Design target: a K8s ConfigMap per serial (`current_state`, `lock_holder`, `current_slot`, `staging_path`, `health_status`). **What's actually implemented today:** a file-backed store at `~/.cache/androidmcp/device_states.json` (survives process restart; ConfigMap migration is a Phase 2 item, not done). Every server must acquire a lock before acting and validate the device is in the expected state; requests from a non-lock-holder are rejected.

## 5. Tailscale Integration

Three patterns were evaluated — Tailscale-as-CNI (clean, complex), **subnet router (recommended, in use)**, and per-pod sidecar (max isolation, most overhead). dizaster runs Pattern B: it advertises the K3s pod CIDR and is directly reachable over the tailnet without a K8s operator.

**Important correction from the integration review:** don't stream multi-GB flash images over Tailscale. MCP JSON-RPC traffic goes over the tailnet; image bytes are staged locally on the edge host (`~/ANDroidMCP/staging/{serial}/`) and referenced by local path in `flash_partition`.

## 6. Kubernetes Status

Manifests exist under `k8s/` (namespaces, network policies, RBAC, device-plugin scaffold, deployments for all 4 non-critical servers plus the full `android-bootrom-exploit-server` spec with `NetworkPolicy: deny-all`, `automountServiceAccountToken: false`, and an HITL init-container gate). **None of this has been `kubectl apply`'d.** Current runtime is bare-metal dev mode on dizaster (see `STATUS_AND_HANDOFF.md`) — K3s/minikube deploy is still a Phase 2 task.

## 7. Standard Response Envelope (target, partially adopted)

```json
{ "ok": true, "code": "OK", "data": {}, "error": null, "hints": [] }
```

Adopted in `orchestrator` and `bootloader` (`servers/common/mcp_response.py`). Not yet migrated in `userspace` / `tailscale` servers — Phase 2 item.

## 8. Security Threat Model

| Threat | Mitigation (designed) |
|---|---|
| Prompt injection via logcat | logcat output is read-only text, never executed |
| Confused deputy (userspace server calling bootrom tools) | Orchestrator-enforced state machine; RBAC separates namespaces |
| Unattended BootROM write | stdio-only transport, no HTTP endpoint, requires an active human terminal |
| USB hijacking | udev rules lock device nodes to a dedicated GID; device plugin enforces single-pod assignment |
| Tailscale node impersonation | Single-use device auth keys; ACLs |
| K8s API abuse from the BootROM pod | No ServiceAccount token mounted |
| Dump exfiltration | Encrypted PVC target; `NetworkPolicy: deny-all`; explicit `kubectl cp` required to retrieve |

Note: the threat model above describes the *K8s-deployed* target state. The live bare-metal dev servers do **not** yet implement per-request auth, a shell command allowlist, or audit logging — see the security backlog in `OPERATIONS.md`, which is the actual current gap list.

## 9. Build Phases

- **Phase 1 — Foundation:** ✅ substantially complete. All 4 non-critical servers implemented and running locally; orchestrator wiring (locks, preflight, file persistence) done; Claude Desktop bridge working.
- **Phase 2 — Bootloader hardening + K8s:** partial. `preflight_flash` / HITL-gated `resume_flash` implemented. USB device plugin, K8s deploy, ConfigMap persistence, Prometheus wiring: not started.
- **Phase 3 — BootROM tier:** scaffold only. Redirected toward a host-native `mtk-edge-daemon` design; `write_raw_block` deliberately deferred pending security audit.
- **Phase 4 — Observability & hardening:** not started (Prometheus/Grafana configs exist as scaffolds under `monitoring/`).

## References

Full technical detail — K8s YAML specs, Mermaid sequence diagrams, Prometheus metric names, the full USB decision tree — lives in the archived originals: `archive/REASONING.md` and `archive/ARCHITECTURAL_SYNTHESIS_INTEGRATION.md`. Pull those back up if you need manifest-level detail; this doc is the map, not the territory.
