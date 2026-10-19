# GAP.md — ANDroidMCP gap analysis

Audit of the repository as of commit `a3df3a6` (initial public release).
Method: live runtime probes (listening sockets, unauthenticated MCP `initialize` + `tools/list`
against all four servers), `py_compile` / `bash -n` on every source file, and a manual code read of the
bootloader, userspace, orchestrator and common modules. Items marked **(verified)** were reproduced;
items marked **(code-read)** come from reading the source; **(to verify)** were not reproduced.

Severity: **Critical** = remote unauthenticated device/host control · **High** = bypasses a safety control or leaks data ·
**Medium** = reliability / correctness / hygiene · **Low** = polish.

Status values: `Open`, `Fixed` (in this branch), `Partial`, `Won't fix (by design)`.

## Test summary

| Check | Result |
|---|---|
| `py_compile` on all `servers/**/*.py` | Pass |
| `bash -n` on all `scripts/*.sh` | Pass |
| All 4 HTTP servers respond to MCP `initialize` / `tools/list` | Pass (**with no credentials**, see S1) |
| Automated tests in repo | None at audit time. After this branch: 24 unit tests, all pass, run in CI |
| Services survive reboot via systemd | No on the audited install (see O1) |
| Docker / K8s path | Never built / never applied |

**After the fixes:** 24 unit tests pass, and a 30-check integration run on throw-away ports (auth, validation, confinement, bind refusal, SSRF block, audit log) passed 30/30. The live stack on the production ports was not touched; it keeps running the old code until restarted. If you enable `MCP_AUTH_TOKEN`, configure the stdio bridge to send `Authorization: Bearer <token>` first.

## 1. Security

| ID | Sev | Finding | Evidence | Status |
|---|---|---|---|---|
| S1 | Critical | No authentication on any HTTP endpoint. Any client that can reach the port can list and call every tool, including `execute_shell_command`, `flash_partition`, `resume_flash`, `resume_unlock_bootloader`. | verified | Partial: auth is opt-in via `MCP_AUTH_TOKEN` (default is loopback-only, unauthenticated); the stdio bridge must send the header |
| S2 | Critical | All four servers bind `0.0.0.0` (ports 8110–8113), not loopback/VPN only. Comments claiming "only reachable via the VPN" are false. | verified | Fixed: loopback by default; non-loopback bind refused without a token |
| S3 | High | HITL confirmation token is returned to the *calling agent* in the preflight response (`confirmation_code` and inside `data.confirm_token`). "Relay to the human" is advisory; the same caller can complete flash/unlock. | code-read | Open (design): single-use + attempt limit added, but the code still travels through the calling agent |
| S4 | High | Token handling: not single-use on failure paths (record is only deleted after a successful flash), no attempt limit (6 digits = 900k guesses, unauthenticated), plain `!=` comparison, default TTL 3600 s, stored in plaintext in a cache file written with default umask, non-atomic write. | code-read | Fixed |
| S5 | High | Image path confinement: `resolve_staging_path` accepts any absolute path and does not confine `..` for relative paths. `preflight_flash` / `stage_image` therefore accept any readable file on the host. | code-read | Fixed: confined to staging root / `ANDROIDMCP_IMAGE_ROOTS`, symlinks resolved |
| S6 | Medium | No validation of `partition`, `serial`, `address` strings (leading `-` can be interpreted as a fastboot/adb option; no charset/length check). Mitigated only by `exec` (no shell). | code-read | Fixed: serial, partition and address validated at the tool-schema level |
| S7 | High | `lock_bootloader` and `stage_image` have no confirmation gate and no orchestrator lock. `DANGEROUS_PARTITIONS = {system, vendor, userdata, super}` omits `boot`, `init_boot`, `vendor_boot`, `recovery`, `vbmeta*`, `radio`, `bootloader`, `modem` and `preloader`; docs claim a different set. | code-read | Partial: `lock_bootloader` needs `confirm='LOCK'`, dangerous set expanded; `stage_image` still ungated, no orchestrator lock |
| S8 | High | `execute_shell_command`: arbitrary `adb shell`, caller-controlled unbounded `timeout`, full command echoed in the response, no allowlist/denylist, no audit log. | code-read | Partial: timeout capped at 300 s, audit log added; no allowlist |
| S9 | Medium | `install_apk` takes any host path with no validation; `capture_screen_and_hierarchy` writes to a caller-chosen `output_dir`. | code-read | Partial: `install_apk` validated, capture default dir fixed; `output_dir` still caller-chosen |
| S10 | Medium | `check_mcp_endpoint_reachability` takes an arbitrary URL (possible SSRF primitive). | to verify | Fixed: loopback/Tailscale-range hosts, MCP ports and `/mcp` path only |
| S11 | Medium | No rate limiting, no per-device ownership/consent registry, no audit trail of tool calls. | code-read | Partial: audit log added; no rate limiting or consent registry |
| S12 | Low | Bootloader log goes to a world-readable path under `/tmp`. | code-read | Open |
| S13 | Medium | `servers/tailscale/server.py` defaulted `TAILSCALE_AUTH_KEY` to a key-shaped literal in source and echoed its first 16 characters in tool output. | code-read | Fixed: empty default, value never echoed |

## 2. Privacy and repository hygiene (repo is public)

| ID | Sev | Finding | Status |
|---|---|---|---|
| P1 | High | Tracked files contain hardcoded personal absolute home paths, a VPN IP address and a host name (docs, `scripts/*.sh`, `claude_desktop_config.json.template`, `servers/tailscale/server.py`, including a kubeconfig path). These are already in the pushed commit, so removing them from the tree does **not** remove them from history; a history rewrite (or accepting the exposure and rotating/renaming) is a maintainer decision. | Partial: tree scrubbed; the earlier commit still holds the old values, so history needs a maintainer decision (rewrite) and the exposed IP/host name should be treated as public |
| P2 | Medium | README/ARCHITECTURE/OPERATIONS linked to `STATUS_AND_HANDOFF.md` and `archive/`, which are gitignored and absent from the public repo (dead links). | Fixed |
| P3 | Medium | Backup files tracked: `scripts/start-servers.sh.bak`, `servers/tailscale/server.py.bak`, `servers/userspace/tools/adb_tools.py.bak`, `servers/userspace/tools/adb_tools.py.pre-fix-*`. | Fixed |
| P4 | Medium | No `LICENSE`, `SECURITY.md` or contribution notes, despite a "public release" commit. | Partial: `SECURITY.md` added; a `LICENSE` is the maintainer's choice |
| P5 | Low | `.gitignore` does not cover `*.bak`, `*.pre-fix-*`, `logs/`, `ZIP/`, `*.zip`, `.env*`. (Some are untracked today only by accident.) | Fixed |

## 3. Reliability and operations

| ID | Sev | Finding | Status |
|---|---|---|---|
| O1 | High | systemd user units run an external bridge script that is not part of this repo and does not start the backend servers. The running backends were started by hand, so the stack does not survive a reboot and the repo is not reproducible. | Fixed: script generates backend units (generation and lint verified; not installed live) |
| O2 | Medium | `scripts/dev-start.sh` `start_server()` captures its own status `echo` via `$(...)`, corrupting the PID variables and the exit trap. | Fixed (syntax-checked; not executed because it kills the running stack) |
| O3 | Medium | `capture_screen_and_hierarchy` defaults `output_dir` to `/workspace/captures` (a container path that does not exist on bare metal). | Fixed |
| O4 | Medium | State/preflight JSON files are shared by four processes with no file locking and non-atomic writes (lost-update / torn-read risk). | Partial: preflight and device-state writes are atomic and private, preflight store is flock-guarded; device-state file is not locked |
| O5 | Medium | Orchestrator locks are not acquired on every mutating bootloader path (`lock_bootloader`, `stage_image`). | Open |
| O6 | Low | Dockerfiles exist but builds failed historically; K8s manifests never applied; Prometheus/Grafana are config scaffolds with no `/metrics` endpoint. | Open |
| O7 | Low | Servers have no graceful shutdown handling for in-flight fastboot/adb child processes beyond per-call timeouts. | Open |
| O8 | Medium | Dockerfiles copy only `server.py` (not `servers/common/`), so the containers cannot import their own helpers; they also set neither `MCP_HOST` nor a token, and the K8s manifests have no auth Secret. Container/K8s path therefore needs rework before use. | Open |

## 4. Code quality and correctness

| ID | Sev | Finding | Status |
|---|---|---|---|
| Q1 | Medium | No automated tests; CI (`release.yml`) only runs on version tags and has no test/lint job. | Fixed: 24 unit tests + CI workflow |
| Q2 | Medium | Dependency spec drift: root pins `mcp==1.27.2`; per-server requirements use `mcp>=1.0.0`; no lockfile. | Partial: server requirements aligned with the root pin; no lockfile |
| Q3 | Medium | Documentation drift: `userspace` exposes 13 tools (docs: 9), `network` exposes 9 (docs: 6). | Open |
| Q4 | Low | Response envelope inconsistent: bootloader/orchestrator use `mcp_ok/mcp_err`, userspace/network return ad-hoc JSON. | Open |
| Q5 | Low | Success/failure classified by substring (`"OKAY"`, `"failed"`) on fastboot output; non-zero exit with "OKAY" in the text is treated as success. | Open |
| Q6 | Low | Hardcoded environment defaults (a VPN IP, project paths) instead of required config. | Partial: IP and home-path defaults removed |

## 5. Design fallacies

| ID | Fallacy | Reality |
|---|---|---|
| F1 | "A token the human must type back is a human-in-the-loop." | The token is delivered to the agent itself, so the agent can echo it. A real gate must be out-of-band (server console, log, OTP app) or enforced by the MCP client's own approval UI. |
| F2 | "Reachable only via the VPN." | Binding `0.0.0.0` exposes the ports on every interface (LAN, Wi-Fi, hotspot). |
| F3 | "Read-only tools are fully automated and safe." | `capture_screen_and_hierarchy` writes files to a caller-chosen directory; `get_logcat` can leak secrets from the device. |
| F4 | "Loopback / local mode implies trust." | Any local process (or SSRF) can reach an unauthenticated loopback port. |
| F5 | "Docs describe the system." | Tool counts, danger-tier lists and service status in docs have drifted from the code. |

## 6. Unimplemented / under-implemented

| ID | Item | State |
|---|---|---|
| U1 | BootROM/EDL server (`servers/bootrom`) | Stub, disabled: TOTP, device attestation, replay check, `mtkclient` integration, dump and write all `TODO` |
| U2 | `mtk-edge-daemon` (host-native, phase 3) | Not started |
| U3 | USB device plugin | `sleep infinity` stub |
| U4 | K8s ConfigMap-backed orchestrator state | Not started (file-backed today) |
| U5 | Device-owner consent registry (`devices.yaml`) | Not started |
| U6 | Audit logging, rate limiting | Not started |
| U7 | Prometheus/Grafana wiring | Config only |
| U8 | Structured error envelope for userspace/network | Not started |

## What this branch changes

* New: `servers/common/{security,validation,audit}.py`, `tests/`, `SECURITY.md`, `.github/workflows/ci.yml`.
* Rewritten: `common/preflight_store.py` (atomic, private, locked, attempt-limited), `common/staging.py` (confined paths),
  `common/persistence.py` (atomic write), `scripts/setup-systemd-services.sh`.
* Behaviour changes: servers bind loopback by default; `lock_bootloader` needs `confirm="LOCK"`; confirmation codes are
  single-use; boot-chain partitions are CRITICAL; images must live under the staging root.
* Hygiene: personal paths/IPs/host names removed from tracked files, backup files removed, `.gitignore` extended.

## Still open (suggested next)

1. S3 / F1: real out-of-band approval (server-console or OTP) for flash/unlock.
2. P1: decide on rewriting history for the already-pushed commit; add a `LICENSE`.
3. S7/S8/S9: ungated `stage_image`, shell allowlist, rate limiting, `capture_screen` output-dir confinement.
4. O5, O8: orchestrator locks on every mutating path; make the Docker/K8s path work (copy `common/`, auth Secret).
5. Q3-Q5, U1-U8: doc drift, uniform envelope, robust result parsing, and the unimplemented components.
