"""Standard MCP tool response envelope for LLM-friendly outputs."""

from __future__ import annotations

import json
from typing import Any, Optional


def mcp_ok(
    code: str = "OK",
    data: Optional[dict] = None,
    hints: Optional[list[str]] = None,
    **legacy: Any,
) -> str:
    """Return success JSON (includes legacy ``success: true`` for older clients)."""
    payload: dict[str, Any] = {
        "ok": True,
        "success": True,
        "code": code,
        "data": data or {},
        "error": None,
        "hints": hints or [],
    }
    if legacy:
        payload.update(legacy)
    return json.dumps(payload, indent=2)


def mcp_err(
    code: str,
    message: str,
    data: Optional[dict] = None,
    raw: Optional[str] = None,
    hints: Optional[list[str]] = None,
    **legacy: Any,
) -> str:
    """Return error JSON (includes legacy ``success: false``)."""
    payload: dict[str, Any] = {
        "ok": False,
        "success": False,
        "code": code,
        "data": data or {},
        "error": {"message": message, "raw": raw},
        "hints": hints or [],
    }
    if legacy:
        payload.update(legacy)
    return json.dumps(payload, indent=2)


def mcp_json(obj: dict) -> str:
    """Serialize dict; ensure ok/success/code exist when missing."""
    if "ok" not in obj and "success" in obj:
        obj["ok"] = obj["success"]
    if "code" not in obj:
        obj["code"] = "OK" if obj.get("ok") else "ERROR"
    return json.dumps(obj, indent=2)
