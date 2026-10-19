# Security policy

ANDroidMCP can flash firmware, unlock bootloaders and run shell commands on attached Android devices.
Treat every endpoint as privileged.

## Reporting a vulnerability

Please report privately through GitHub's **"Report a vulnerability"** (Security Advisories) on this repository
rather than opening a public issue. Include the affected component, reproduction steps and impact.

## Safe deployment

* The servers listen on `127.0.0.1` by default. Do not set `MCP_HOST` to a non-loopback address unless you also
  set `MCP_AUTH_TOKEN`; the servers refuse to start otherwise.
* Keep tokens and keys (`MCP_AUTH_TOKEN`, `TAILSCALE_AUTH_KEY`) in environment files with mode `600`, never in the repo.
* Flashing and unlocking use a preflight → confirmation-code flow. The code is returned to the calling
  client, so it is only a real human gate if your MCP client asks the human before relaying it. Keep tool-call
  approval enabled in your client.
* Review `~/.cache/androidmcp/audit.log` (override with `ANDROIDMCP_AUDIT_FILE`) after sensitive sessions.
* Only flash images you have verified (`expected_sha256` in `preflight_flash`).

## Known limitations

See [GAP.md](GAP.md) for the current list of open security items.
