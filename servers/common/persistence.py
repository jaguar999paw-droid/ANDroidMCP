"""File-backed device state persistence (dev / single-node K3s)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def state_file_path() -> Path:
    custom = os.getenv("ANDROIDMCP_STATE_FILE")
    if custom:
        return Path(custom).expanduser().resolve()
    return Path.home() / ".cache" / "androidmcp" / "device_states.json"


def load_devices() -> dict[str, dict[str, Any]]:
    path = state_file_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_devices(devices: dict[str, dict[str, Any]]) -> None:
    path = state_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(devices, indent=2), encoding="utf-8")
