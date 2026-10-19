"""Short-lived flash/unlock preflight records.

Hardening over the original version:
* atomic writes, owner-only permissions, cross-process file locking
* shorter default TTL (ANDROIDMCP_PREFLIGHT_TTL, default 600 s)
* constant-time token comparison with a bounded number of attempts
"""

from __future__ import annotations

import fcntl
import hmac
import json
import os
import secrets
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional

MAX_TOKEN_ATTEMPTS = int(os.getenv("ANDROIDMCP_MAX_TOKEN_ATTEMPTS", "5"))
DEFAULT_TTL_SECONDS = int(os.getenv("ANDROIDMCP_PREFLIGHT_TTL", "600"))


def generate_confirm_token() -> str:
    """6-digit human-relayable confirmation code (not a boolean flag)."""
    return f"{secrets.randbelow(900000) + 100000}"


def preflight_file_path() -> Path:
    custom = os.getenv("ANDROIDMCP_PREFLIGHT_FILE")
    if custom:
        return Path(custom).expanduser().resolve()
    return Path.home() / ".cache" / "androidmcp" / "preflights.json"


@contextmanager
def _locked() -> Iterator[None]:
    path = preflight_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


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
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".preflight-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def store(preflight_id: str, payload: dict[str, Any], ttl_seconds: Optional[int] = None) -> None:
    ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    payload = dict(payload)
    payload["expires_at"] = (datetime.now() + timedelta(seconds=ttl)).isoformat()
    payload["stored_at"] = datetime.now().isoformat()
    payload.setdefault("attempts", 0)
    with _locked():
        data = _load_all()
        data[preflight_id] = payload
        _save_all(data)


def get(preflight_id: str) -> Optional[dict[str, Any]]:
    with _locked():
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
    with _locked():
        data = _load_all()
        if data.pop(preflight_id, None) is not None:
            _save_all(data)


def verify_confirm_token(preflight_id: str, supplied: str, expected: str) -> bool:
    """Constant-time check with an attempt limit.

    A wrong guess increments the record's attempt counter; once the limit is
    reached the preflight is revoked and must be re-issued. If the record is
    not in the local store (e.g. it lives in a remote orchestrator) the
    comparison still runs, just without attempt counting.
    """
    supplied_b = str(supplied).encode("utf-8")
    expected_b = str(expected).encode("utf-8")
    with _locked():
        data = _load_all()
        rec = data.get(preflight_id)
        if rec is None:
            return hmac.compare_digest(supplied_b, expected_b)
        if int(rec.get("attempts", 0)) >= MAX_TOKEN_ATTEMPTS:
            data.pop(preflight_id, None)
            _save_all(data)
            return False
        if hmac.compare_digest(supplied_b, expected_b):
            return True
        rec["attempts"] = int(rec.get("attempts", 0)) + 1
        if rec["attempts"] >= MAX_TOKEN_ATTEMPTS:
            data.pop(preflight_id, None)
        _save_all(data)
        return False
