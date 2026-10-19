"""Append-only audit log of sensitive tool calls (best effort, never raises)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

_SECRET_HINTS = ("token", "secret", "password", "key")


def audit_path() -> Path:
    custom = os.getenv("ANDROIDMCP_AUDIT_FILE")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".cache" / "androidmcp" / "audit.log"


def audit(event: str, **fields) -> None:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event}
    for k, v in fields.items():
        if any(h in k.lower() for h in _SECRET_HINTS):
            continue
        s = str(v)
        rec[k] = s if len(s) <= 300 else s[:300] + "..."
    try:
        path = audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
