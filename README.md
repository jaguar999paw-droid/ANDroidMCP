# ANDroidMCP — Hardware-Sovereign AI Orchestration Platform

Claude, via MCP, gets authenticated, audited access to Android hardware on devices attached to **dizaster** — from UI automation (ADB) down to raw BootROM silicon — without needing physical presence for most operations.

⚠️ **This is not a fire-and-forget system.** Flashing and BootROM operations require explicit confirmation and, at some steps, physical device interaction. See `OPERATIONS.md` §4 before running anything destructive.

## Documentation

Docs were consolidated from 16 scattered session files down to three, plus this README. The originals are preserved in `archive/` if you need manifest-level or session-by-session detail.

| Doc | What's in it |
|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Why it's built this way: risk-tier design, USB passthrough strategy, device state machine, Tailscale pattern, K8s target state, threat model, build phases |
| **[OPERATIONS.md](OPERATIONS.md)** | How to run it day-to-day: start/stop, tools inventory, safe flash workflow, HITL model, CLI reference, security backlog, troubleshooting |
| **[STATUS_AND_HANDOFF.md](STATUS_AND_HANDOFF.md)** | Current live state, what's built vs scaffolded, session history, known-bug fixes, immediate next steps |

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
Before assuming everything's running, check **[STATUS_AND_HANDOFF.md](STATUS_AND_HANDOFF.md)** — it has the last verified live-state snapshot and what's currently broken/off.

## Repo Layout

```
~/ANDroidMCP/
├── README.md                 (this file)
├── ARCHITECTURE.md
├── OPERATIONS.md
├── STATUS_AND_HANDOFF.md
├── archive/                  (16 original session/design docs)
├── k8s/                      (manifests — written, not yet applied; see ARCHITECTURE.md §6)
├── servers/{userspace,bootloader,orchestrator,tailscale,bootrom}/
├── monitoring/                (Prometheus/Grafana scaffolds — not deployed)
├── scripts/
└── staging/{serial}/          (local flash images — never streamed over Tailscale)
```

## Security Note

The dev servers currently run **unauthenticated on `0.0.0.0:8110-8113`** with no shell command allowlist and no audit logging. Treat this as trusted-localhost-only until the backlog in `OPERATIONS.md` §6 is addressed — don't expose it beyond your own Tailscale tailnet.

---

**Last updated:** 2026-08-19
