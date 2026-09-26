"""Short-lived flash preflight records."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


def generate_confirm_token() -> str:
    """6-digit human-relayable confirmation code (not a boolean flag).

    Forces the calling agent to actually surface a value to the human and
    receive it back, rather than self-attesting with user_confirms=true.
    """
    return f"{secrets.randbelow(900000) + 100000}"


def preflight_file_path() -> Path:
    custom = os.getenv("ANDROIDMCP_PREFLIGHT_FILE")
    if custom:
        return Path(custom).expanduser().resolve()
    return Path.home() / ".cache" / "androidmcp" / "preflights.json"


def _load_all() -> dict[str, dict[str, Any]]:
    path = preflight_file_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict[str, dict[str, Any]]) -> None:
    path = preflight_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def store(preflight_id: str, payload: dict[str, Any], ttl_seconds: int = 3600) -> None:
    data = _load_all()
    payload = dict(payload)
    payload["expires_at"] = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
    payload["stored_at"] = datetime.now().isoformat()
    data[preflight_id] = payload
    _save_all(data)


def get(preflight_id: str) -> Optional[dict[str, Any]]:
    data = _load_all()
    rec = data.get(preflight_id)
    if not rec:
        return None
    exp = rec.get("expires_at")
    if exp and datetime.fromisoformat(exp) < datetime.now():
        data.pop(preflight_id, None)
        _save_all(data)
        return None
    return rec


def delete(preflight_id: str) -> None:
    data = _load_all()
    data.pop(preflight_id, None)
    _save_all(data)
