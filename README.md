# ANDroidMCP — Android device operations through MCP

ANDroidMCP exposes Android device tools to an MCP client. The four operational
servers run on the machine that can reach the device (the **edge host**); a
separate stdio-to-HTTP bridge can let a desktop MCP client call those servers.
The bridge is not included in this repository.

> **This is not a remote USB tunnel or a fire-and-forget flasher.** MCP requests
> can be sent remotely, but USB stays attached to the edge host. Fastboot
> flashing and bootloader unlock are destructive and require explicit
> confirmation; a person may also need to interact with the device.

## What runs today

| MCP server | Port | What it does | Device/tool requirement |
|---|---:|---|---|
| `android-userspace` | 8110 | Android OS operations: device listing, screenshots/UI hierarchy, shell, logcat, install, taps, text, properties, health, and ADB-over-TCP connect/disconnect | `adb` and an ADB server reachable from the edge host; device must be in an ADB-capable state and authorized |
| `android-bootloader` | 8111 | Fastboot device/status checks, image staging, preflight, flash, unlock and relock | `fastboot` on the edge host and a USB-connected device in fastboot/bootloader mode |
| `android-orchestrator` | 8112 | Per-serial state records, locks, preflight records and health coordination | File-backed, single-host development implementation; not a distributed K8s control plane |
| `android-network` | 8113 | Tailscale status, route and endpoint checks, and node/config helpers | Tailscale CLI and host permissions for operations such as route advertisement |

The servers use streamable HTTP MCP. `./scripts/dev-start.sh` starts these four
services; it does **not** start the BootROM server. The K8s manifests are
scaffolding and are not the current runtime.

## ADB, Fastboot and MediaTek are different modes

These tools are not interchangeable compatibility layers. The Android device
must be in the matching mode, and the required host-side tool must be available.

| Mode/tool | Use it when | Compatibility boundary |
|---|---|---|
| **ADB** (`adb`) | Android is booted (or in a recovery that exposes ADB). USB debugging must be enabled and the host authorized. The userspace server defaults to an ADB server at `localhost:5037`; `ADB_SERVER_HOST` and `ADB_SERVER_PORT` can point it elsewhere. `connect_tcp_device` can connect to a device over a reachable network when Android's ADB-over-TCP is enabled. | ADB shell/UI/file operations do not work while the device is in ordinary bootloader fastboot or MediaTek BootROM mode. |
| **Fastboot** (`fastboot`) | The device has been rebooted into a bootloader that implements Fastboot. Fastboot commands run as a local process on the edge host and need direct USB access there. Flashing uses the `preflight_flash` → confirmation → `resume_flash` flow. | Fastboot does not use the ADB server and is not a substitute for a MediaTek BootROM download agent. Device/OEM support for partitions and fastboot commands varies. |
| **MediaTek BootROM / MTKClient** | Only when a separately implemented and carefully secured BootROM toolchain exists for that chipset/device. | **Not supported by this runtime.** `servers/bootrom/server.py` is a scaffold: MTKClient is not integrated, detection returns no device, dump/write methods are stubs, and token verification denies writes. It is not started by the dev launcher or included in the release build. Do not treat its advertised tools as working MTK or Qualcomm EDL support. |

Qualcomm EDL is a separate low-level protocol from both Fastboot and MTK
BootROM; it is also not implemented here. Changing Android mode normally
requires rebooting the device into the appropriate mode, and the first ADB
authorization, enabling debugging, USB connection, or bootloader-unlock
confirmation can require someone physically present.

## Local and remote access

The request path is:

```text
MCP client → stdio/HTTP bridge → HTTP MCP server on edge host → adb or fastboot → device
```

By default, the HTTP servers bind to `127.0.0.1` (ports 8110–8113). This is
appropriate when the bridge runs on the same host, but a client on another
computer cannot reach those loopback listeners. Tailscale status tools and
printed Tailscale URLs do not by themselves change the bind address or create a
USB tunnel.

For a remote client, prefer an SSH tunnel to the edge host and leave the MCP
servers on loopback. For example, keep this running on the client machine:

```bash
ssh -N \
  -L 8110:127.0.0.1:8110 \
  -L 8111:127.0.0.1:8111 \
  -L 8112:127.0.0.1:8112 \
  -L 8113:127.0.0.1:8113 \
  user@edge-host
```

Point the local bridge at `127.0.0.1` on the forwarded ports. The client and
edge host must have a secure SSH path between them (for example, SSH over a
tailnet). Alternatively, a direct tailnet listener requires binding only to
the edge host's Tailscale interface with `MCP_HOST` **and** setting a strong
`MCP_AUTH_TOKEN`; the MCP client/bridge must send that bearer token. Do not bind
to `0.0.0.0` or expose these privileged endpoints to the public internet.

Remote MCP calls operate the devices attached to the edge host. They do not
transport USB over Tailscale. ADB-over-TCP is a separate device connection and
requires its own Android-side setup and network reachability. For Fastboot,
keep the device USB-connected to the edge host and stage the image on that host
under `staging/<serial>/`; the flash tool receives a host-local path, not image
bytes from the MCP client.

## Quick start

```bash
cd ~/ANDroidMCP
./scripts/dev-start.sh
```

This starts the four loopback HTTP backends. Configure and start the separate
stdio-to-HTTP bridge for the MCP client using
[`claude_desktop_config.json.template`](claude_desktop_config.json.template),
then ask the client to list connected devices. The template has placeholders
that must be set for your environment. See [`OPERATIONS.md`](OPERATIONS.md)
for service management, tool details and troubleshooting.

## Setup and usage

### Linux

**Option A — standalone release (recommended for use):**

1. Download and extract the Linux x64 release archive from the project's
   GitHub Releases page. The archive contains the server binaries,
   `platform-tools` (`adb` and `fastboot`), and the installer.
2. From the extracted directory, run:

   ```bash
   chmod +x install.sh
   ./install.sh
   ```

   The installer puts the files under
   `~/.local/share/androidmcp` by default and creates `systemd --user`
   services. Override the location with `ANDROIDMCP_INSTALL_DIR` if needed.
3. Connect the Android device to this Linux edge host. For USB ADB, enable
   USB debugging, accept the host authorization prompt, and make sure the
   current user has permission to access the USB device. Linux distributions
   may require Android USB udev rules; reconnect the device after installing
   or changing those rules.
4. Check the services with
   `systemctl --user status androidmcp-userspace androidmcp-bootloader androidmcp-orchestrator androidmcp-network`.
   Logs are under `~/.local/share/androidmcp/logs/`.

**Option B — run from source for development:**

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip adb fastboot
cd ~/ANDroidMCP
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
./scripts/dev-start.sh
```

Use your distribution's equivalent packages if it is not Debian/Ubuntu.
`dev-start.sh` starts the four HTTP backends in the foreground; use the
standalone installer for background services that start at login.

### Windows

Use the Windows x64 standalone release archive. The source development
launcher is a Bash script and is not a native Windows setup path.

1. Download and extract the Windows x64 release archive.
2. Open PowerShell in the extracted directory and run:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\install.ps1
   ```

   The installer defaults to
   `$env:LOCALAPPDATA\ANDroidMCP`; set `-InstallDir` to choose another
   location, for example:

   ```powershell
   .\install.ps1 -InstallDir "$env:USERPROFILE\ANDroidMCP"
   ```

   It registers four logon-triggered Scheduled Tasks for the current account.
   These are not Windows Services. Check them with
   `Get-ScheduledTask | Where-Object TaskName -like 'ANDroidMCP-*'`.
3. Install the Android USB driver appropriate for the device/OEM if Windows
   does not recognize it. Connect the device and authorize USB debugging for
   ADB. The release includes `adb` and `fastboot`; the device still needs to
   support the selected mode.
4. View logs in the install directory's `logs` folder. Start or stop a task
   from PowerShell with, for example,
   `Start-ScheduledTask -TaskName ANDroidMCP-userspace` or
   `Stop-ScheduledTask -TaskName ANDroidMCP-userspace`.

### Connect an MCP client and operate a device

The server release does not include the stdio-to-HTTP bridge. Install a
compatible bridge separately, then adapt
[`claude_desktop_config.json.template`](claude_desktop_config.json.template)
to point it at the local services. Replace every placeholder, keep
`ANDROID_SERVICE_HOST` as `127.0.0.1` for a local bridge, and restart the MCP
client after changing its configuration. If your client/bridge supports
streamable HTTP directly, configure it for the local `/mcp` endpoints instead.

Start by asking the MCP client to list connected devices. For ADB operations,
the Android device must be booted with USB debugging enabled, or separately
configured for ADB-over-TCP. For Fastboot operations, reboot the device into
its Fastboot/bootloader mode and keep it connected to the edge host. Before a
flash, place the image under `staging/<serial>/` on that host and use the
preflight/confirmation/resume workflow in [`OPERATIONS.md`](OPERATIONS.md).
Do not assume a successful ADB connection means Fastboot or MTK BootROM is
available.

For remote use, first establish SSH connectivity to the edge host, then forward
the local MCP ports. The same command syntax works in Windows PowerShell and
Linux shells:

```text
ssh -N -L 8110:127.0.0.1:8110 -L 8111:127.0.0.1:8111 -L 8112:127.0.0.1:8112 -L 8113:127.0.0.1:8113 user@edge-host
```

Keep that SSH session open and point the bridge on the client computer at its
own `127.0.0.1` forwarded ports. SSH can run over a tailnet; the MCP services
remain loopback-bound on the edge host. Remote MCP access does not carry USB
over the network.

## Safety and security

- Treat all device-control tools as privileged. Loopback is the default;
  non-loopback binding is refused unless `MCP_AUTH_TOKEN` is set.
- `execute_shell_command` permits arbitrary Android shell commands. A bearer
  token protects the HTTP endpoint but is not per-tool authorization.
- Flash/unlock preflight confirmation codes are returned through the calling
  MCP client. This is not an independent human-authentication boundary; review
  the operation yourself before confirming.
- Keep tokens, keys, device images, logs and local device state out of Git.
  See [`SECURITY.md`](SECURITY.md) and [`GAP.md`](GAP.md) for security details
  and known limitations.

## Repository map

```text
servers/       Four HTTP services plus the unimplemented BootROM scaffold
scripts/       Development, deployment and release helpers
k8s/           Deployment scaffolding; not currently applied
monitoring/    Prometheus/Grafana scaffolding; not deployed
staging/       Host-local firmware images; do not commit device images
tests/         Unit tests (python -m unittest discover -s tests)
```

---

**Last updated:** 2026-10-19
