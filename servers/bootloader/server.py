#!/usr/bin/env python3
"""
Android Bootloader MCP Server

Fastboot operations with orchestrator locks, preflight guards, and structured responses.

HITL model (updated 2026-08-19):
  Destructive ops (flash_partition, unlock_bootloader) require a two-step
  preflight -> resume flow. resume requires a 6-digit confirm_token that was
  generated server-side and must be relayed back through the human, not just
  a self-settable `user_confirms=true` boolean. CRITICAL-risk partitions
  (system/vendor/userdata/super) additionally require the partition name to
  be typed back exactly (partition_confirm). See OPERATIONS.md for details.
"""

import os
import sys
import json
import uuid
import hashlib
import asyncio
from typing import Optional, List, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from common.mcp_response import mcp_ok, mcp_err
from common.orchestrator_client import OrchestratorClient
from common.staging import resolve_staging_path, ensure_staging_dirs
from common.preflight_store import (
    get as get_preflight_local,
    delete as delete_preflight_local,
    store as store_preflight_local,
    generate_confirm_token,
)

SERVER_NAME = "android-bootloader-server"
DANGEROUS_PARTITIONS = {"system", "vendor", "userdata", "super"}


class FastbootManager:
    def __init__(self):
        self.orchestrator = OrchestratorClient()
        self.server_name = SERVER_NAME

    async def get_devices(self) -> List[dict]:
        result = await self._run_fastboot(["devices", "-l"])
        devices = []
        for line in result.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("List of"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices.append({"serial": parts[0], "state": parts[1]})
        return devices

    async def getvar(self, serial: str, name: str) -> Optional[str]:
        try:
            out = await self._run_fastboot(["-s", serial, "getvar", name], timeout=15)
            for line in (out or "").splitlines():
                line = line.strip()
                if name in line and ":" in line:
                    return line.split(":", 1)[1].strip()
            return None
        except Exception:
            return None

    async def get_bootloader_status(self, serial: str) -> dict:
        result = await self._run_fastboot(["-s", serial, "getvar", "all"], timeout=30)
        info: Dict[str, str] = {}
        for line in result.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                info[key.strip()] = val.strip()
        slot = info.get("current-slot") or await self.getvar(serial, "current-slot")
        unlocked = info.get("unlocked") or await self.getvar(serial, "unlocked")
        return {
            "vars": info,
            "current_slot": slot,
            "unlocked": unlocked,
        }

    async def flash_partition(self, serial: str, partition: str, image_path: str) -> str:
        return await self._run_fastboot(
            ["-s", serial, "flash", partition, image_path], timeout=600
        )

    async def unlock_bootloader(self, serial: str) -> str:
        return await self._run_fastboot(["-s", serial, "flashing", "unlock"], timeout=120)

    async def lock_bootloader(self, serial: str) -> str:
        return await self._run_fastboot(["-s", serial, "flashing", "lock"], timeout=60)

    async def stage_image(self, serial: str, image_path: str) -> str:
        return await self._run_fastboot(["-s", serial, "stage", image_path], timeout=300)

    async def reboot_bootloader(self, serial: str) -> str:
        return await self._run_fastboot(["-s", serial, "reboot-bootloader"], timeout=30)

    async def _run_fastboot(self, args: List[str], timeout: int = 60) -> str:
        cmd = ["fastboot"] + args
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError(f"Fastboot timed out after {timeout}s")

        out = stdout.decode("utf-8", errors="ignore")
        err = stderr.decode("utf-8", errors="ignore")
        combined = (out + "\n" + err).strip()

        if process.returncode != 0 and "OKAY" not in combined.upper():
            raise RuntimeError(f"Fastboot error: {err or out or 'unknown'}")
        return combined


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _risk_level(partition: str) -> str:
    return "CRITICAL" if partition in DANGEROUS_PARTITIONS else "MEDIUM"


mcp = FastMCP("android-bootloader", host="0.0.0.0", port=int(os.getenv("MCP_PORT", "8111")))
fastboot_manager = FastbootManager()


class GetDevicesInput(BaseModel):
    pass


class FlashPartitionInput(BaseModel):
    serial: str
    partition: str
    image_path: str
    preflight_id: str


class PreflightFlashInput(BaseModel):
    serial: str
    partition: str
    image_path: str
    expected_sha256: Optional[str] = None
    require_slot: Optional[str] = None


class ResumeFlashInput(BaseModel):
    serial: str
    partition: str
    preflight_id: str
    confirm_token: str
    user_confirms: bool = False
    partition_confirm: Optional[str] = None
    image_path: str = ""


class PreflightUnlockInput(BaseModel):
    serial: str


class ResumeUnlockInput(BaseModel):
    serial: str
    preflight_id: str
    confirm_token: str
    type_confirm: str
    user_confirms: bool = False


class LockBootloaderInput(BaseModel):
    serial: str


class GetBootloaderStatusInput(BaseModel):
    serial: str


class StageImageInput(BaseModel):
    serial: str
    image_path: str


class RebootBootloaderInput(BaseModel):
    serial: str


async def _validate_preflight(
    preflight_id: str, serial: str, key_field: str, key_value: str
) -> tuple[bool, str, Optional[dict]]:
    """key_field/key_value: e.g. ("partition", "boot") for flash, or
    ("operation", "unlock") for the unlock flow — cross-checks the record
    matches what the caller claims it's confirming."""
    rec = get_preflight_local(preflight_id)
    if not rec:
        try:
            resp = await fastboot_manager.orchestrator.get_preflight(preflight_id)
            if resp.get("ok"):
                rec = resp.get("data", {}).get("preflight")
        except Exception as e:
            return False, f"Preflight lookup failed: {e}", None
    if not rec:
        return False, "Invalid or expired preflight_id", None
    if rec.get("serial") != serial or rec.get(key_field) != key_value:
        return False, f"Preflight does not match serial/{key_field}", rec
    return True, "OK", rec


@mcp.tool()
async def get_fastboot_devices(input: GetDevicesInput = GetDevicesInput()) -> str:
    """List devices in fastboot mode."""
    try:
        devices = await fastboot_manager.get_devices()
        return mcp_ok(code="OK", data={"devices": devices, "count": len(devices)})
    except Exception as e:
        return mcp_err(code="FASTBOOT_DEVICES_FAILED", message=str(e))


@mcp.tool()
async def preflight_flash(input: PreflightFlashInput) -> str:
    """
    Run anti-brick preflight: orchestrator lock, slot/unlock checks, SHA256, staging path.
    Returns preflight_id AND a 6-digit confirmation_code for resume_flash.
    The confirmation_code MUST be relayed to the human and typed back — it is
    not satisfied by setting user_confirms=true alone.
    """
    try:
        resolved = resolve_staging_path(input.serial, input.image_path)
        ensure_staging_dirs(input.serial)

        if not os.path.isfile(resolved):
            return mcp_err(
                code="IMAGE_NOT_FOUND",
                message=f"Image not found: {resolved}",
                hints=[
                    f"Place images under {ensure_staging_dirs(input.serial)}",
                    "Use absolute path or filename relative to device staging dir",
                ],
            )
        size = os.path.getsize(resolved)
        if size == 0:
            return mcp_err(code="IMAGE_EMPTY", message="Image file is empty")

        lock_resp = await fastboot_manager.orchestrator.acquire_lock(
            input.serial, SERVER_NAME, "FASTBOOT_MODE"
        )
        if not lock_resp.get("ok"):
            return mcp_err(
                code=lock_resp.get("code", "LOCK_HELD"),
                message=lock_resp.get("error", {}).get("message", "Could not acquire lock"),
                data=lock_resp.get("data"),
            )

        devices = await fastboot_manager.get_devices()
        serials = [d["serial"] for d in devices]
        if input.serial not in serials:
            await fastboot_manager.orchestrator.release_lock(input.serial, SERVER_NAME)
            return mcp_err(
                code="DEVICE_NOT_IN_FASTBOOT",
                message=f"Serial {input.serial} not in fastboot list",
                data={"fastboot_devices": devices},
                hints=["adb reboot bootloader", "Verify USB connection"],
            )

        status = await fastboot_manager.get_bootloader_status(input.serial)
        current_slot = status.get("current_slot")
        unlocked = status.get("unlocked", "").lower() if status.get("unlocked") else None

        if input.require_slot and current_slot and input.require_slot != current_slot:
            await fastboot_manager.orchestrator.release_lock(input.serial, SERVER_NAME)
            return mcp_err(
                code="SLOT_MISMATCH",
                message=f"Expected slot {input.require_slot}, got {current_slot}",
                data={"current_slot": current_slot},
            )

        digest = _sha256_file(resolved)
        if input.expected_sha256 and input.expected_sha256.lower() != digest.lower():
            await fastboot_manager.orchestrator.release_lock(input.serial, SERVER_NAME)
            return mcp_err(
                code="HASH_MISMATCH",
                message="expected_sha256 does not match file",
                data={"expected": input.expected_sha256, "actual": digest},
            )

        risk = _risk_level(input.partition)
        confirm_token = generate_confirm_token()
        preflight_id = str(uuid.uuid4())
        payload = {
            "serial": input.serial,
            "partition": input.partition,
            "image_path": resolved,
            "image_sha256": digest,
            "image_size_bytes": size,
            "current_slot": current_slot,
            "unlocked": unlocked,
            "risk_level": risk,
            "confirm_token": confirm_token,
        }
        await fastboot_manager.orchestrator.store_preflight(
            input.serial, preflight_id, payload
        )
        # Also store locally so it works even if the orchestrator's own
        # store_preflight tool isn't wired to return it back verbatim.
        store_preflight_local(preflight_id, payload)

        hints = [
            "Relay confirmation_code to the user and have them confirm out loud",
            "Then call resume_flash with user_confirms=true and confirm_token=<the code>",
        ]
        if risk == "CRITICAL":
            hints.append(
                f"This is a CRITICAL partition — resume_flash also requires "
                f"partition_confirm='{input.partition}' (typed exactly)"
            )

        return mcp_ok(
            code="PREFLIGHT_OK",
            data={
                "preflight_id": preflight_id,
                "confirmation_code": confirm_token,
                **payload,
                "staging_dir": str(ensure_staging_dirs(input.serial)),
            },
            hints=hints,
            awaiting_user_confirmation=True,
            confirmation_required=f"Flash {input.partition} to {input.serial}?",
        )
    except Exception as e:
        try:
            await fastboot_manager.orchestrator.release_lock(input.serial, SERVER_NAME)
        except Exception:
            pass
        return mcp_err(code="PREFLIGHT_FAILED", message=str(e))


@mcp.tool()
async def flash_partition(input: FlashPartitionInput) -> str:
    """
    HITL summary step after preflight_flash. Requires a valid preflight_id.
    Surfaces the confirmation_code again; does not flash until resume_flash
    is called with matching confirm_token and user_confirms=true.
    """
    ok, msg, rec = await _validate_preflight(
        input.preflight_id, input.serial, "partition", input.partition
    )
    if not ok:
        return mcp_err(code="PREFLIGHT_INVALID", message=msg)

    resolved = rec.get("image_path", "")
    size = rec.get("image_size_bytes", 0)
    risk = rec.get("risk_level", _risk_level(input.partition))

    hints = [
        "Relay confirmation_code to the user, then call resume_flash with "
        "user_confirms=true and confirm_token=<the code>",
        "DO NOT unplug USB during flash",
    ]
    if risk == "CRITICAL":
        hints.append(f"resume_flash also requires partition_confirm='{input.partition}'")

    return mcp_err(
        code="AWAITING_USER_CONFIRMATION",
        message="User must confirm before resume_flash",
        data={
            "preflight_id": input.preflight_id,
            "confirmation_code": rec.get("confirm_token"),
            "serial": input.serial,
            "partition": input.partition,
            "image_path": resolved,
            "image_size_mb": round(size / (1024 * 1024), 2),
            "current_slot": rec.get("current_slot"),
            "unlocked": rec.get("unlocked"),
            "risk_level": risk,
            "image_sha256": rec.get("image_sha256"),
        },
        hints=hints,
        awaiting_user_confirmation=True,
    )


@mcp.tool()
async def resume_flash(input: ResumeFlashInput) -> str:
    """Execute flash after preflight, matching confirm_token, and explicit
    user_confirms=true. CRITICAL partitions additionally require
    partition_confirm to exactly equal the partition name."""
    if not input.user_confirms:
        return mcp_err(
            code="CONFIRMATION_REQUIRED",
            message="Set user_confirms=true after explicit user approval",
        )

    ok, msg, rec = await _validate_preflight(
        input.preflight_id, input.serial, "partition", input.partition
    )
    if not ok:
        return mcp_err(code="PREFLIGHT_INVALID", message=msg)

    expected_token = rec.get("confirm_token")
    if not expected_token or input.confirm_token != expected_token:
        return mcp_err(
            code="CONFIRM_TOKEN_MISMATCH",
            message="confirm_token does not match the code issued at preflight",
            hints=["Re-run preflight_flash / flash_partition to get the current code"],
        )

    risk = rec.get("risk_level", _risk_level(input.partition))
    if risk == "CRITICAL" and input.partition_confirm != input.partition:
        return mcp_err(
            code="PARTITION_CONFIRM_REQUIRED",
            message=f"CRITICAL partition — set partition_confirm='{input.partition}' exactly",
            data={"risk_level": risk, "partition": input.partition},
        )

    resolved = rec.get("image_path") or resolve_staging_path(
        input.serial, input.image_path or ""
    )

    try:
        result = await fastboot_manager.flash_partition(
            input.serial, input.partition, resolved
        )
        delete_preflight_local(input.preflight_id)
        await fastboot_manager.orchestrator.release_lock(input.serial, SERVER_NAME)

        if "failed" in result.lower() and "okay" not in result.lower():
            return mcp_err(
                code="FLASH_FAILED",
                message="Fastboot reported failure",
                raw=result,
                data={"serial": input.serial, "partition": input.partition},
            )

        return mcp_ok(
            code="FLASH_OK",
            data={
                "serial": input.serial,
                "partition": input.partition,
                "output": result,
            },
            hints=["Wait 30-60s for reboot", "Verify boot with userspace get_connected_devices"],
        )
    except Exception as e:
        return mcp_err(
            code="FLASH_EXCEPTION",
            message=str(e),
            hints=["Device may need recovery mode", "Check /tmp/androidmcp_bootloader.log"],
        )


@mcp.tool()
async def preflight_unlock_bootloader(input: PreflightUnlockInput) -> str:
    """
    Preflight step for bootloader unlock. Unlocking WIPES USER DATA — this is
    CRITICAL risk regardless of partition scope. Acquires the orchestrator
    lock and issues a confirm_token; does NOT unlock yet. Call
    resume_unlock_bootloader with the code and type_confirm='UNLOCK' to proceed.
    """
    try:
        lock_resp = await fastboot_manager.orchestrator.acquire_lock(
            input.serial, SERVER_NAME, "FASTBOOT_MODE"
        )
        if not lock_resp.get("ok"):
            return mcp_err(
                code=lock_resp.get("code", "LOCK_HELD"),
                message=lock_resp.get("error", {}).get("message", "Could not acquire lock"),
                data=lock_resp.get("data"),
            )

        devices = await fastboot_manager.get_devices()
        serials = [d["serial"] for d in devices]
        if input.serial not in serials:
            await fastboot_manager.orchestrator.release_lock(input.serial, SERVER_NAME)
            return mcp_err(
                code="DEVICE_NOT_IN_FASTBOOT",
                message=f"Serial {input.serial} not in fastboot list",
                data={"fastboot_devices": devices},
            )

        confirm_token = generate_confirm_token()
        preflight_id = str(uuid.uuid4())
        payload = {
            "serial": input.serial,
            "operation": "unlock",
            "risk_level": "CRITICAL",
            "confirm_token": confirm_token,
        }
        store_preflight_local(preflight_id, payload)
        try:
            await fastboot_manager.orchestrator.store_preflight(
                input.serial, preflight_id, payload
            )
        except Exception:
            pass  # local store is authoritative for this flow either way

        return mcp_ok(
            code="PREFLIGHT_OK",
            data={
                "preflight_id": preflight_id,
                "confirmation_code": confirm_token,
                "serial": input.serial,
                "risk_level": "CRITICAL",
                "warning": "Unlocking the bootloader WIPES ALL USER DATA on this device.",
            },
            hints=[
                "Relay confirmation_code to the user and have them confirm out loud",
                "Then call resume_unlock_bootloader with user_confirms=true, "
                "confirm_token=<the code>, and type_confirm='UNLOCK'",
                "After the fastboot command runs, the user must press the power "
                "button on-device within 30s to finish the unlock",
            ],
            awaiting_user_confirmation=True,
            confirmation_required=f"Unlock bootloader on {input.serial}? THIS WIPES USER DATA.",
        )
    except Exception as e:
        try:
            await fastboot_manager.orchestrator.release_lock(input.serial, SERVER_NAME)
        except Exception:
            pass
        return mcp_err(code="PREFLIGHT_FAILED", message=str(e))


@mcp.tool()
async def resume_unlock_bootloader(input: ResumeUnlockInput) -> str:
    """Execute bootloader unlock after preflight_unlock_bootloader, matching
    confirm_token, type_confirm='UNLOCK', and user_confirms=true."""
    if not input.user_confirms:
        return mcp_err(
            code="CONFIRMATION_REQUIRED",
            message="Set user_confirms=true after explicit user approval",
        )
    if input.type_confirm != "UNLOCK":
        return mcp_err(
            code="TYPE_CONFIRM_REQUIRED",
            message="Set type_confirm='UNLOCK' (typed exactly) to proceed",
        )

    ok, msg, rec = await _validate_preflight(
        input.preflight_id, input.serial, "operation", "unlock"
    )
    if not ok:
        return mcp_err(code="PREFLIGHT_INVALID", message=msg)

    expected_token = rec.get("confirm_token")
    if not expected_token or input.confirm_token != expected_token:
        return mcp_err(
            code="CONFIRM_TOKEN_MISMATCH",
            message="confirm_token does not match the code issued at preflight",
            hints=["Re-run preflight_unlock_bootloader to get the current code"],
        )

    try:
        result = await fastboot_manager.unlock_bootloader(input.serial)
        delete_preflight_local(input.preflight_id)
        await fastboot_manager.orchestrator.release_lock(input.serial, SERVER_NAME)
        return mcp_ok(
            code="UNLOCK_INITIATED",
            data={"serial": input.serial, "output": result},
            hints=["Press power on device within 30s to confirm on-device"],
            awaiting_user_input=True,
        )
    except Exception as e:
        try:
            await fastboot_manager.orchestrator.release_lock(input.serial, SERVER_NAME)
        except Exception:
            pass
        return mcp_err(code="UNLOCK_FAILED", message=str(e))


@mcp.tool()
async def lock_bootloader(input: LockBootloaderInput) -> str:
    try:
        result = await fastboot_manager.lock_bootloader(input.serial)
        await fastboot_manager.orchestrator.release_lock(input.serial, SERVER_NAME)
        return mcp_ok(code="LOCK_OK", data={"serial": input.serial, "output": result})
    except Exception as e:
        return mcp_err(code="LOCK_FAILED", message=str(e))


@mcp.tool()
async def get_bootloader_status(input: GetBootloaderStatusInput) -> str:
    """Fastboot variables with current_slot and unlocked at top level."""
    try:
        status = await fastboot_manager.get_bootloader_status(input.serial)
        return mcp_ok(
            code="OK",
            data={
                "serial": input.serial,
                "current_slot": status.get("current_slot"),
                "unlocked": status.get("unlocked"),
                "bootloader_vars": status.get("vars", {}),
            },
        )
    except Exception as e:
        return mcp_err(code="GETVAR_FAILED", message=str(e))


@mcp.tool()
async def stage_image(input: StageImageInput) -> str:
    try:
        resolved = resolve_staging_path(input.serial, input.image_path)
        result = await fastboot_manager.stage_image(input.serial, resolved)
        return mcp_ok(code="STAGE_OK", data={"serial": input.serial, "image": resolved, "output": result})
    except Exception as e:
        return mcp_err(code="STAGE_FAILED", message=str(e))


@mcp.tool()
async def health_check() -> str:
    try:
        devices = await fastboot_manager.get_devices()
        orch_url = os.getenv("ORCHESTRATOR_MCP_URL", "http://127.0.0.1:8112/mcp")
        return mcp_ok(
            code="OK",
            data={
                "fastboot_reachable": True,
                "fastboot_devices": len(devices),
                "orchestrator_url": orch_url,
            },
        )
    except Exception as e:
        return mcp_err(code="UNHEALTHY", message=str(e))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
