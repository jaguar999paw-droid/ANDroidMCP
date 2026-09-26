#!/usr/bin/env python3
"""
Network Tailscale MCP Server  —  ANDroidMCP
============================================
Risk Level : LOW  🟢
Transport  : streamable-http
Port       : 8113
"""

import os, json, asyncio
from datetime import datetime
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "network-tailscale",
    host="0.0.0.0",
    port=int(os.getenv("MCP_PORT", "8113")),
)

TAILSCALE_AUTH_KEY = os.getenv(
    "TAILSCALE_AUTH_KEY",
    "tskey-[REDACTED]",
)
DIZASTER_TS_IP = os.getenv("DIZASTER_TS_IP", "100.118.209.46")
MCP_ENDPOINTS: dict[str, int] = {
    "android-userspace": 8110,
    "android-bootloader": 8111,
    "android-orchestrator": 8112,
    "android-network": 8113,
}
NODE_TAG = "tag:android"
BRING_UP_SCRIPT = os.path.expanduser("~/ANDroidMCP/scripts/android-node-up.sh")


async def _run(*cmd: str, timeout: int = 15) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


async def _own_ip() -> str | None:
    rc, out, _ = await _run("tailscale", "ip", "--4")
    return out if rc == 0 and out else None


@mcp.tool()
async def get_tailscale_status() -> dict:
    """Get current Tailscale status for dizaster (own IP, peers, routes)."""
    rc, out, err = await _run("tailscale", "status", "--json")
    return {"status": "ok", "data": json.loads(out)} if rc == 0 else {"status": "error", "error": err}


@mcp.tool()
async def get_own_tailscale_ip() -> dict:
    """Get dizaster's Tailscale IP and derive all ANDroidMCP endpoint URLs."""
    ip = await _own_ip()
    if not ip:
        return {"status": "error", "error": "Could not determine Tailscale IP"}
    return {
        "status": "ok",
        "tailscale_ip": ip,
        "mcp_endpoints": {n: f"http://{ip}:{p}/mcp" for n, p in MCP_ENDPOINTS.items()},
    }


@mcp.tool()
async def check_mcp_endpoint_reachability(endpoint_url: str) -> dict:
    """
    Check if an ANDroidMCP HTTP endpoint is reachable over Tailscale.

    Args:
        endpoint_url: Full URL e.g. http://100.118.209.46:8110/mcp
    """
    rc, out, _ = await _run(
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}|%{time_total}",
        "--max-time", "6", "-H", "Accept: text/event-stream", endpoint_url, timeout=10,
    )
    parts = out.split("|")
    code = parts[0] if parts else "0"
    latency_ms = round(float(parts[1]) * 1000, 1) if len(parts) > 1 else -1
    return {
        "status": "ok", "endpoint": endpoint_url,
        "reachable": code in ("200", "400", "405"),
        "http_code": code, "latency_ms": latency_ms,
    }


@mcp.tool()
async def check_all_endpoints() -> dict:
    """Check reachability of every ANDroidMCP server on dizaster in one call."""
    ip = DIZASTER_TS_IP
    results = {}
    for name, port in MCP_ENDPOINTS.items():
        results[name] = await check_mcp_endpoint_reachability(f"http://{ip}:{port}/mcp")
    return {
        "status": "ok",
        "all_reachable": all(r.get("reachable") for r in results.values()),
        "dizaster_ip": ip,
        "servers": results,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


@mcp.tool()
async def list_advertised_routes() -> dict:
    """List all Tailscale routes advertised and accepted on this node."""
    rc, out, _ = await _run("tailscale", "status")
    lines = out.splitlines()
    routes = [l for l in lines if "Routes" in l or "/" in l]
    return {"status": "ok", "routes": routes, "raw_lines": len(lines)}


@mcp.tool()
async def advertise_pod_cidr(pod_cidr: str = "10.42.0.0/16") -> dict:
    """
    Advertise K3s pod CIDR as a Tailscale subnet route (Pattern B / REASONING.md).

    Args:
        pod_cidr: CIDR to advertise (K3s default: 10.42.0.0/16)

    ⚠️  Requires sudo. Approve the route at login.tailscale.com/admin/machines after running.
    """
    rc, out, err = await _run(
        "sudo", "tailscale", "up",
        f"--advertise-routes={pod_cidr}", "--accept-routes", timeout=30,
    )
    if rc == 0:
        return {"status": "ok", "pod_cidr": pod_cidr,
                "message": f"Route {pod_cidr} advertised. Approve at https://login.tailscale.com/admin/machines"}
    return {"status": "error", "error": err}


@mcp.tool()
async def provision_android_node(suffix: str, skip_verify: bool = False) -> dict:
    """
    Provision a new ANDroid Tailscale node — the dynamic template for all ANDroidMCP onboarding.

    Runs android-node-up.sh targeting ANDroid-<suffix>, applies tag:android via
    the pre-authorized auth key, and verifies all MCP endpoints are reachable.

    Args:
        suffix:      Device identifier, e.g. "pixel9", "tab-s9", "emulator-01"
        skip_verify: Skip endpoint reachability check after joining
    """
    if not suffix or len(suffix) > 32:
        return {"status": "error", "error": "suffix must be 1–32 characters"}

    safe = "".join(c if c.isalnum() or c == "-" else "-" for c in suffix.lower())
    node_hostname = f"ANDroid-{safe}"

    args = [BRING_UP_SCRIPT, safe]
    if skip_verify:
        args.append("--skip-verify")

    os.chmod(BRING_UP_SCRIPT, 0o755)
    rc, out, err = await _run(*args, timeout=90)

    result: dict = {
        "status": "ok" if rc == 0 else "error",
        "node_hostname": node_hostname,
        "node_tag": NODE_TAG,
        "script_output": out,
    }
    if rc != 0:
        result["error"] = err or "Script exited non-zero"
        return result

    if not skip_verify:
        result["endpoint_check"] = await check_all_endpoints()

    result["claude_desktop_config"] = await generate_claude_desktop_config()
    return result


@mcp.tool()
async def get_android_onboarding_info() -> dict:
    """
    Return everything a new Android user needs to join the tailnet and connect to ANDroidMCP.

    Includes the bring-up command, auth key preview, hostname pattern, tag, and all endpoint URLs.
    """
    ip = await _own_ip() or DIZASTER_TS_IP
    masked = TAILSCALE_AUTH_KEY[:16] + "..." if TAILSCALE_AUTH_KEY else "(not set)"
    return {
        "status": "ok",
        "onboarding": {
            "step_1_copy_script": "scp kamau@dizaster:~/ANDroidMCP/scripts/android-node-up.sh .",
            "step_2_run": "bash android-node-up.sh <device-name>",
            "hostname_pattern": "ANDroid-<suffix>",
            "tag_applied": NODE_TAG,
            "auth_key_preview": masked,
            "tailnet": "euplectes-tegus.ts.net",
        },
        "dizaster_ip": ip,
        "mcp_endpoints": {n: f"http://{ip}:{p}/mcp" for n, p in MCP_ENDPOINTS.items()},
        "notes": [
            "Auth key is pre-authorized — no admin approval needed.",
            "tag:android is baked into the key; ACL rules apply automatically.",
            "All 4 ANDroidMCP servers are reachable via dizaster's Tailscale IP.",
            "Plug in USB *after* joining Tailscale — ADB will auto-detect.",
        ],
    }


@mcp.tool()
async def generate_claude_desktop_config() -> dict:
    """
    Generate a claude_desktop_config.json mcpServers snippet using dizaster's live Tailscale IP.

    Covers all Phase-1 ANDroidMCP servers plus the Phase-3 bootrom stdio placeholder.
    """
    ip = await _own_ip() or DIZASTER_TS_IP
    descriptions = {
        "android-userspace": "ADB / UI automation — LOW risk 🟢",
        "android-bootloader": "Fastboot — MEDIUM risk 🟡",
        "android-orchestrator": "Device state machine — LOW risk 🟢",
        "android-network": "Tailscale coordination — LOW risk 🟢",
    }
    config = {
        "mcpServers": {
            name: {"url": f"http://{ip}:{port}/mcp", "description": descriptions[name]}
            for name, port in MCP_ENDPOINTS.items()
        }
    }
    config["mcpServers"]["android-bootrom"] = {
        "command": "kubectl",
        "args": ["exec", "-n", "androidmcp-critical",
                 "deployment/android-bootrom-exploit-server",
                 "-it", "--", "/mcp-server", "--transport", "stdio", "--hitl-strict"],
        "env": {"KUBECONFIG": "/home/kamau/.kube/config"},
        "description": "Phase 3: CRITICAL — stdio only, requires HITL token",
    }
    return {"status": "ok", "dizaster_ip": ip, "config": config}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
