# ANDroidMCP — Hardware-Sovereign AI Orchestration Platform

Claude, via MCP, gets authenticated, audited access to Android hardware on devices attached to the host machine — from UI automation (ADB) down to raw BootROM silicon — without needing physical presence for most operations.

⚠️ **This is not a fire-and-forget system.** Flashing and BootROM operations require explicit confirmation and, at some steps, physical device interaction. See `OPERATIONS.md` §4 before running anything destructive.

## Documentation

Known bugs, security flaws, gaps and unimplemented pieces are tracked in **[GAP.md](GAP.md)**.

| Doc | What's in it |
|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Why it's built this way: risk-tier design, USB passthrough strategy, device state machine, Tailscale pattern, K8s target state, threat model, build phases |
| **[OPERATIONS.md](OPERATIONS.md)** | How to run it day-to-day: start/stop, tools inventory, safe flash workflow, HITL model, CLI reference, security backlog, troubleshooting |
| **[GAP.md](GAP.md)** | Audit of bugs, security flaws, gaps and unimplemented pieces, with status |

## Overview

| Tier | Server | Risk | Access |
|---|---|---|---|
| 🟢 | `android-userspace-server` (:8110) | Low | ADB — screenshots, shell, logcat, install, UI automation |
| 🟡 | `android-bootloader-server` (:8111) | Medium | Fastboot — partition flashing |
| 🟢 | `android-orchestrator-server` (:8112) | Low | Device state machine + lock coordination |
| 🟢 | `android-network-server` (:8113) | Low | Tailscale networking |
| 🔴 | `android-bootrom-exploit-server` | Critical | stdio-only — BootROM/EDL raw hardware, Phase 3, currently disabled |

## Quick Start

```bash
cd ~/ANDroidMCP && ./scripts/dev-start.sh   # start the 4 HTTP backends first
# then restart Claude Desktop — it spawns the http-to-stdio bridge per server
```

Then ask Claude: *"List connected Android devices and take a screenshot."*

Full startup, systemd management, and troubleshooting: **[OPERATIONS.md](OPERATIONS.md)**.
Check **[GAP.md](GAP.md)** for what is currently broken, off, or unimplemented.

## Repo Layout

```
~/ANDroidMCP/
├── README.md                 (this file)
├── ARCHITECTURE.md
├── OPERATIONS.md
├── GAP.md
├── k8s/                      (manifests — written, not yet applied; see ARCHITECTURE.md §6)
├── servers/{userspace,bootloader,orchestrator,tailscale,bootrom}/
├── monitoring/                (Prometheus/Grafana scaffolds — not deployed)
├── scripts/
├── tests/                    (unit tests: python -m unittest discover -s tests)
└── staging/{serial}/          (local flash images — never streamed over Tailscale)
```

## Security Note

The dev servers currently run **unauthenticated on `0.0.0.0:8110-8113`** with no shell command allowlist and no audit logging. Treat this as trusted-localhost-only until the backlog in `OPERATIONS.md` §6 is addressed — don't expose it beyond your own Tailscale tailnet.

---

**Last updated:** 2026-08-19
