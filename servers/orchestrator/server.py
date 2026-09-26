#!/usr/bin/env python3
"""
K8s Cluster Orchestrator MCP Server

Manages device state machine, lock coordination, and cluster health.
File-backed persistence for dev / single-node deployments.
"""

import os
import sys
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict, fields

# Allow imports from servers/common
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from common.mcp_response import mcp_ok, mcp_err
from common.persistence import load_devices, save_devices
from common.preflight_store import store as store_preflight_record, get as get_preflight_record, delete as delete_preflight_record
from common.staging import device_staging_dir, ensure_staging_dirs


@dataclass
class DeviceState:
    serial: str
    model: Optional[str] = None
    current_state: str = "CONNECTED"
    lock_holder: Optional[str] = None
    lock_acquired_at: Optional[str] = None
    lock_expires_at: Optional[str] = None
    edge_node: Optional[str] = None
    last_heartbeat: Optional[str] = None
    current_slot: Optional[str] = None
    health_status: str = "GREEN"
    staging_path: Optional[str] = None
    last_preflight_sha256: Optional[str] = None
    battery_pct: Optional[int] = None
    last_usb_seen: Optional[str] = None
    brick_risk_flags: Optional[List[str]] = None
    custom_metadata: Optional[Dict] = None


class DeviceStateManager:
    def __init__(self):
        self.devices: Dict[str, DeviceState] = {}
        self.lock_timeout_seconds = int(os.getenv("ORCHESTRATOR_LOCK_TIMEOUT", "300"))
        self.edge_node = os.getenv("ANDROIDMCP_EDGE_NODE", os.uname().nodename)

    async def initialize(self):
        raw = load_devices()
        self.devices = {}
        for serial, blob in raw.items():
            known = {f.name for f in fields(DeviceState)}
            filtered = {k: v for k, v in blob.items() if k in known}
            filtered["serial"] = serial
            self.devices[serial] = DeviceState(**filtered)

    def _persist(self):
        save_devices({s: asdict(d) for s, d in self.devices.items()})

    async def get_device_state(self, serial: str) -> Optional[DeviceState]:
        return self.devices.get(serial)

    async def list_devices(self) -> List[DeviceState]:
        return list(self.devices.values())

    def _lock_expired(self, device: DeviceState) -> bool:
        if not device.lock_expires_at:
            return True
        return datetime.fromisoformat(device.lock_expires_at) < datetime.now()

    async def acquire_lock(
        self,
        serial: str,
        requesting_server: str,
        target_state: str,
        timeout_seconds: int = 300,
    ) -> tuple[bool, str]:
        device = self.devices.get(serial)
        if not device:
            ensure_staging_dirs(serial)
            device = DeviceState(
                serial=serial,
                edge_node=self.edge_node,
                staging_path=str(device_staging_dir(serial)),
            )
            self.devices[serial] = device

        if device.lock_holder and device.lock_holder != requesting_server:
            if not self._lock_expired(device):
                return False, "LOCK_HELD"

        now = datetime.now()
        device.lock_holder = requesting_server
        device.lock_acquired_at = now.isoformat()
        device.lock_expires_at = (now + timedelta(seconds=timeout_seconds)).isoformat()
        device.current_state = target_state
        device.edge_node = self.edge_node
        if not device.staging_path:
            device.staging_path = str(device_staging_dir(serial))
        self._persist()
        return True, "LOCK_ACQUIRED"

    async def release_lock(self, serial: str, releasing_server: str) -> tuple[bool, str]:
        device = self.devices.get(serial)
        if not device or device.lock_holder != releasing_server:
            return False, "LOCK_NOT_HELD"
        device.lock_holder = None
        device.lock_acquired_at = None
        device.lock_expires_at = None
        device.current_state = "CONNECTED"
        self._persist()
        return True, "LOCK_RELEASED"

    async def heartbeat(self, serial: str, server_name: str) -> tuple[bool, str]:
        device = self.devices.get(serial)
        if not device or device.lock_holder != server_name:
            return False, "LOCK_NOT_HELD"
        now = datetime.now()
        device.lock_expires_at = (
            now + timedelta(seconds=self.lock_timeout_seconds)
        ).isoformat()
        device.last_heartbeat = now.isoformat()
        self._persist()
        return True, "HEARTBEAT_OK"

    async def update_device_fields(self, serial: str, **kwargs: Any) -> bool:
        device = self.devices.get(serial)
        if not device:
            device = DeviceState(serial=serial)
            self.devices[serial] = device
        for key, val in kwargs.items():
            if hasattr(device, key):
                setattr(device, key, val)
        self._persist()
        return True

    async def check_state_transition_validity(
        self, serial: str, from_state: str, to_state: str, requesting_server: str
    ) -> bool:
        device = self.devices.get(serial)
        if not device or device.lock_holder != requesting_server:
            return False
        if device.current_state != from_state:
            return False
        valid_transitions = {
            "CONNECTED": ["ANDROID_OS", "FASTBOOT_MODE", "BROM_MODE", "OFFLINE"],
            "ANDROID_OS": ["FASTBOOT_MODE", "OFFLINE"],
            "FASTBOOT_MODE": ["ANDROID_OS", "BROM_MODE", "OFFLINE"],
            "BROM_MODE": ["OFFLINE"],
            "OFFLINE": ["CONNECTED"],
        }
        return to_state in valid_transitions.get(from_state, [])


mcp = FastMCP("k8s-orchestrator", host="0.0.0.0", port=int(os.getenv("MCP_PORT", "8112")))
state_manager = DeviceStateManager()


class AcquireLockInput(BaseModel):
    serial: str
    requesting_server: str
    target_state: str
    timeout_seconds: int = 300


class ReleaseLockInput(BaseModel):
    serial: str
    releasing_server: str


class GetDeviceStateInput(BaseModel):
    serial: str


class ListDevicesInput(BaseModel):
    pass


class HeartbeatInput(BaseModel):
    serial: str
    server_name: str


class ValidateTransitionInput(BaseModel):
    serial: str
    from_state: str
    to_state: str
    requesting_server: str


class StorePreflightInput(BaseModel):
    serial: str
    preflight_id: str
    payload: dict


class GetPreflightInput(BaseModel):
    preflight_id: str


class RegisterDeviceHealthInput(BaseModel):
    serial: str
    battery_pct: Optional[int] = None
    last_usb_seen: Optional[str] = None
    brick_risk_flags: Optional[list[str]] = None
    health_status: str = "GREEN"


@mcp.tool()
async def acquire_lock(input: AcquireLockInput) -> str:
    """Acquire exclusive lock on Android device."""
    success, code = await state_manager.acquire_lock(
        input.serial,
        input.requesting_server,
        input.target_state,
        input.timeout_seconds,
    )
    if success:
        return mcp_ok(
            code=code,
            data={
                "serial": input.serial,
                "server": input.requesting_server,
                "target_state": input.target_state,
            },
        )
    return mcp_err(
        code=code,
        message="Lock held by another server",
        data={"serial": input.serial, "requesting_server": input.requesting_server},
        hints=["Call get_device_state", "Wait for lock expiry or release_lock"],
    )


@mcp.tool()
async def release_lock(input: ReleaseLockInput) -> str:
    """Release exclusive lock on Android device."""
    success, code = await state_manager.release_lock(
        input.serial, input.releasing_server
    )
    if success:
        return mcp_ok(code=code, data={"serial": input.serial})
    return mcp_err(
        code=code,
        message="Lock not held by this server",
        data={"serial": input.serial},
    )


@mcp.tool()
async def get_device_state(input: GetDeviceStateInput) -> str:
    """Get current state of a device."""
    device = await state_manager.get_device_state(input.serial)
    if not device:
        return mcp_err(
            code="DEVICE_UNKNOWN",
            message=f"Device {input.serial} not registered",
            hints=["Run preflight_flash or acquire_lock first"],
        )
    return mcp_ok(code="OK", data={"device": asdict(device)})


@mcp.tool()
async def list_devices(input: ListDevicesInput = ListDevicesInput()) -> str:
    """List all known Android devices and their states."""
    devices = await state_manager.list_devices()
    return mcp_ok(
        code="OK",
        data={"devices": [asdict(d) for d in devices], "count": len(devices)},
    )


@mcp.tool()
async def heartbeat(input: HeartbeatInput) -> str:
    """Extend device lock timeout."""
    success, code = await state_manager.heartbeat(input.serial, input.server_name)
    if success:
        return mcp_ok(code=code, data={"serial": input.serial})
    return mcp_err(code=code, message="Heartbeat rejected", data={"serial": input.serial})


@mcp.tool()
async def validate_state_transition(input: ValidateTransitionInput) -> str:
    """Validate if a state transition is allowed."""
    valid = await state_manager.check_state_transition_validity(
        input.serial, input.from_state, input.to_state, input.requesting_server
    )
    code = "TRANSITION_ALLOWED" if valid else "TRANSITION_DENIED"
    if valid:
        return mcp_ok(code=code, data=asdict(input))
    return mcp_err(
        code=code,
        message="Transition not allowed",
        data=asdict(input),
    )


@mcp.tool()
async def store_preflight(input: StorePreflightInput) -> str:
    """Store a short-lived flash preflight record."""
    payload = dict(input.payload)
    payload["serial"] = input.serial
    store_preflight_record(input.preflight_id, payload)
    await state_manager.update_device_fields(
        input.serial,
        last_preflight_sha256=payload.get("image_sha256"),
        current_slot=payload.get("current_slot"),
    )
    return mcp_ok(
        code="PREFLIGHT_STORED",
        data={"preflight_id": input.preflight_id, "serial": input.serial},
    )


@mcp.tool()
async def get_preflight(input: GetPreflightInput) -> str:
    """Retrieve a preflight record by ID."""
    rec = get_preflight_record(input.preflight_id)
    if not rec:
        return mcp_err(
            code="PREFLIGHT_EXPIRED",
            message="Preflight not found or expired",
            data={"preflight_id": input.preflight_id},
            hints=["Run preflight_flash again"],
        )
    return mcp_ok(code="OK", data={"preflight": rec})


@mcp.tool()
async def register_device_health(input: RegisterDeviceHealthInput) -> str:
    """Update device health registry fields."""
    flags = input.brick_risk_flags or []
    status = input.health_status
    if flags:
        status = "RED" if any("brick" in f.lower() for f in flags) else "YELLOW"
    await state_manager.update_device_fields(
        input.serial,
        health_status=status,
        battery_pct=input.battery_pct,
        last_usb_seen=input.last_usb_seen or datetime.now().isoformat(),
        brick_risk_flags=flags,
        custom_metadata={
            "battery_pct": input.battery_pct,
            "last_usb_seen": input.last_usb_seen or datetime.now().isoformat(),
            "brick_risk_flags": flags,
        },
    )
    return mcp_ok(code="HEALTH_REGISTERED", data=asdict(input))


@mcp.tool()
async def cluster_health() -> str:
    """Orchestrator cluster health summary."""
    devices = await state_manager.list_devices()
    locked = [d for d in devices if d.lock_holder]
    expired = [d for d in locked if state_manager._lock_expired(d)]
    return mcp_ok(
        code="OK",
        data={
            "status": "healthy",
            "total_devices": len(devices),
            "locked_devices": len(locked),
            "expired_locks": len(expired),
            "state_file": str(os.getenv("ANDROIDMCP_STATE_FILE", "~/.cache/androidmcp/device_states.json")),
        },
    )


if __name__ == "__main__":
    asyncio.run(state_manager.initialize())
    mcp.run(transport="streamable-http")
