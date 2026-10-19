"""HTTP transport hardening for the ANDroidMCP servers.

* Binds to loopback by default (override with ``MCP_HOST``).
* Optional static bearer-token auth (``MCP_AUTH_TOKEN``).
* Refuses to listen on a non-loopback interface without a token.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import sys

_LOOPBACK_NAMES = {"localhost"}


def bind_host() -> str:
    """Interface to bind. Loopback unless MCP_HOST says otherwise."""
    return os.getenv("MCP_HOST", "127.0.0.1")


def is_loopback(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class BearerAuth:
    """Minimal ASGI middleware: require ``Authorization: Bearer <token>``."""

    def __init__(self, app, token: str):
        self.app = app
        self._expected = f"Bearer {token}".encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            supplied = b""
            for key, value in scope.get("headers", []):
                if key == b"authorization":
                    supplied = value
                    break
            if not hmac.compare_digest(supplied, self._expected):
                body = b'{"error":"unauthorized"}'
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def build_app(mcp, host: str | None = None):
    """Return the ASGI app for ``mcp``, wrapped with auth when a token is set."""
    host = host or mcp.settings.host
    token = os.getenv("MCP_AUTH_TOKEN", "")
    if not is_loopback(host) and not token:
        raise SystemExit(
            f"Refusing to listen on {host}: set MCP_AUTH_TOKEN, or bind to "
            "loopback (unset MCP_HOST)."
        )
    app = mcp.streamable_http_app()
    return BearerAuth(app, token) if token else app


def serve(mcp) -> None:
    """Run ``mcp`` over streamable HTTP with the hardening above."""
    import uvicorn

    app = build_app(mcp)
    uvicorn.run(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=str(mcp.settings.log_level).lower(),
    )


if __name__ == "__main__":  # pragma: no cover
    print("import this module; it has no CLI", file=sys.stderr)
