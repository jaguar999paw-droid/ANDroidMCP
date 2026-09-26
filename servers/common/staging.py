"""Edge-local image staging paths (no Tailscale bulk transfer)."""

from __future__ import annotations

import os
from pathlib import Path


def staging_root() -> Path:
    return Path(
        os.getenv(
            "ANDROIDMCP_STAGING_ROOT",
            os.path.expanduser("~/ANDroidMCP/staging"),
        )
    ).resolve()


def device_staging_dir(serial: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in serial)
    return staging_root() / safe


def ensure_staging_dirs(serial: str | None = None) -> Path:
    root = staging_root()
    root.mkdir(parents=True, exist_ok=True)
    if serial:
        d = device_staging_dir(serial)
        d.mkdir(parents=True, exist_ok=True)
        return d
    return root


def resolve_staging_path(serial: str, image_path: str) -> str:
    """
    Resolve image path: absolute as-is; relative paths under device staging dir.
    """
    p = Path(image_path)
    if p.is_absolute():
        return str(p.resolve())
    return str((device_staging_dir(serial) / image_path).resolve())
