"""Edge-local image staging paths (no Tailscale bulk transfer).

Image paths are confined to the staging root (plus any directories listed in
ANDROIDMCP_IMAGE_ROOTS, separated by os.pathsep). Symlinks are resolved before
the check, so a link inside staging cannot point outside it.
"""

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


def allowed_image_roots() -> list[Path]:
    roots = [staging_root()]
    for part in os.getenv("ANDROIDMCP_IMAGE_ROOTS", "").split(os.pathsep):
        if part.strip():
            roots.append(Path(part).expanduser().resolve())
    return roots


def _confine(path: Path) -> Path:
    resolved = path.resolve()
    for root in allowed_image_roots():
        if resolved == root or root in resolved.parents:
            return resolved
    raise ValueError(
        "image path must be inside the staging directory "
        "(or a directory listed in ANDROIDMCP_IMAGE_ROOTS)"
    )


def resolve_staging_path(serial: str, image_path: str) -> str:
    """Resolve an image path and confine it to the allowed roots.

    Absolute paths are accepted only if they land inside an allowed root;
    relative paths are taken relative to the device's staging directory.
    """
    p = Path(image_path)
    if p.is_absolute():
        return str(_confine(p))
    return str(_confine(device_staging_dir(serial) / image_path))
