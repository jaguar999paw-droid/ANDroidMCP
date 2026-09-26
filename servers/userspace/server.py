#!/usr/bin/env python3
"""
Android Userspace MCP Server

Provides access to Android device interaction via ADB and UI automation.
Implements FastMCP with proper error handling and metrics.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional

# FastMCP imports
# Allow imports from servers/common
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Allow imports from repository root for common modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
# FastMCP imports
from mcp.server.fastmcp import FastMCP

from pydantic import BaseModel

# Local imports
from tools.adb_tools import ADBManager, ADBDevice
from tools.lifecycle_tools import LifecycleManager
from common.orchestrator_client import OrchestratorClient

# Initialize FastMCP server
mcp = FastMCP("android-userspace", host="0.0.0.0", port=int(os.getenv("MCP_PORT", "8110")))
orchestrator_client = OrchestratorClient()

# Initialize managers
adb_manager = ADBManager(
    adb_server_host=os.getenv("ADB_SERVER_HOST", "localhost"),
    adb_server_port=int(os.getenv("ADB_SERVER_PORT", "5037"))
)
lifecycle_manager = LifecycleManager(adb_manager)


class GetConnectedDevicesInput(BaseModel):
    """Input schema for get_connected_devices tool."""
    pass


class CaptureScreenInput(BaseModel):
    """Input schema for capture_screen_and_hierarchy tool."""
    serial: str
    output_dir: str = "/workspace/captures"


class ShellCommandInput(BaseModel):
    """Input schema for execute_shell_command tool."""
    serial: str
    command: str
    timeout: int = 30


class GetLogcatInput(BaseModel):
    """Input schema for get_logcat tool."""
    serial: str
    lines: int = 100
    filter_spec: Optional[str] = None


class InstallApkInput(BaseModel):
    """Input schema for install_apk tool."""
    serial: str
    apk_path: str


class TapInput(BaseModel):
    """Input schema for tap tool."""
    serial: str
    x: int
    y: int


class TypeTextInput(BaseModel):
    """Input schema for type_text tool."""
    serial: str
    text: str


class GetPropertiesInput(BaseModel):
    """Input schema for get_device_properties tool."""
    serial: str


class ConnectTcpDeviceInput(BaseModel):
    serial: Optional[str] = None
    address: str


class DisconnectTcpDeviceInput(BaseModel):
    address: str


class GetDeviceHealthInput(BaseModel):
    serial: str


@mcp.tool()
async def get_connected_devices(input: GetConnectedDevicesInput = GetConnectedDevicesInput()) -> str:
    """
    Get list of all connected Android devices.
    
    Returns a JSON array of device information including serial, state, model, and device type.
    """
    try:
        devices = await adb_manager.get_connected_devices()
        
        device_list = []
        for device in devices:
            device_list.append({
                "serial": device.serial,
                "state": device.state,
                "model": device.model,
                "device": device.device,
                "transport_id": device.transport_id
            })
        
        return json.dumps({
            "success": True,
            "devices": device_list,
            "count": len(device_list)
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def capture_screen_and_hierarchy(input: CaptureScreenInput) -> str:
    """
    Capture current device screen as PNG and get UI hierarchy as XML.
    
    Returns JSON with paths to saved files and hierarchy information.
    """
    try:
        serial = input.serial
        output_dir = Path(input.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Capture screenshot
        screenshot_path = output_dir / f"{serial}_screenshot.png"
        await lifecycle_manager.capture_screenshot(serial, str(screenshot_path))
        
        # Get UI hierarchy
        hierarchy = await lifecycle_manager.get_screen_hierarchy(serial)
        
        hierarchy_path = output_dir / f"{serial}_hierarchy.xml"
        hierarchy_path.write_text(hierarchy.xml)
        
        return json.dumps({
            "success": True,
            "serial": serial,
            "screenshot": str(screenshot_path),
            "hierarchy": str(hierarchy_path),
            "screen_dimensions": {
                "width": hierarchy.width,
                "height": hierarchy.height
            }
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def execute_shell_command(input: ShellCommandInput) -> str:
    """
    Execute arbitrary shell command on Android device.
    
    Args:
        serial: Device serial number
        command: Shell command to execute
        timeout: Command timeout in seconds
    
    Returns JSON with command output or error.
    """
    try:
        result = await adb_manager.shell(input.serial, input.command, input.timeout)
        
        return json.dumps({
            "success": True,
            "serial": input.serial,
            "command": input.command,
            "output": result
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def get_logcat(input: GetLogcatInput) -> str:
    """
    Get logcat output from device.
    
    Args:
        serial: Device serial number
        lines: Number of recent lines to retrieve
        filter_spec: Optional filter specification
    
    Returns JSON with logcat output.
    """
    try:
        output = await lifecycle_manager.get_logcat(
            input.serial,
            input.lines,
            input.filter_spec
        )
        
        return json.dumps({
            "success": True,
            "serial": input.serial,
            "lines_returned": len(output.split('\n')),
            "output": output
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def connect_tcp_device(input: ConnectTcpDeviceInput) -> str:
    """Connect to an Android device over TCP using adb."""
    try:
        reply = await adb_manager.connect_tcp(input.address)
        return json.dumps({
            "success": True,
            "address": input.address,
            "output": reply,
            "serial": input.serial,
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def disconnect_tcp_device(input: DisconnectTcpDeviceInput) -> str:
    """Disconnect a remote TCP Android device."""
    try:
        reply = await adb_manager.disconnect(input.address)
        return json.dumps({
            "success": True,
            "address": input.address,
            "output": reply,
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def get_device_health(input: GetDeviceHealthInput) -> str:
    """Collect battery and USB state telemetry from the Android device."""
    try:
        telemetry = await adb_manager.get_device_health(input.serial)
        return json.dumps({
            "success": True,
            "serial": input.serial,
            "telemetry": telemetry,
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def install_apk(input: InstallApkInput) -> str:
    """
    Install APK package on device.
    
    Args:
        serial: Device serial number
        apk_path: Local path to APK file
    
    Returns JSON with installation status.
    """
    try:
        await lifecycle_manager.install_apk(input.serial, input.apk_path)
        
        return json.dumps({
            "success": True,
            "serial": input.serial,
            "apk_path": input.apk_path,
            "message": "APK installed successfully"
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def tap(input: TapInput) -> str:
    """
    Tap at specified coordinates on device screen.
    
    Args:
        serial: Device serial number
        x: X coordinate
        y: Y coordinate
    
    Returns JSON with tap status.
    """
    try:
        await lifecycle_manager.tap(input.serial, input.x, input.y)
        
        return json.dumps({
            "success": True,
            "serial": input.serial,
            "x": input.x,
            "y": input.y,
            "message": "Tap executed successfully"
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def type_text(input: TypeTextInput) -> str:
    """
    Type text on device.
    
    Args:
        serial: Device serial number
        text: Text to type
    
    Returns JSON with type status.
    """
    try:
        await lifecycle_manager.type_text(input.serial, input.text)
        
        return json.dumps({
            "success": True,
            "serial": input.serial,
            "text": input.text,
            "message": "Text typed successfully"
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def get_device_properties(input: GetPropertiesInput) -> str:
    """
    Get all device properties.
    
    Args:
        serial: Device serial number
    
    Returns JSON with all getprop output.
    """
    try:
        properties = await adb_manager.get_device_properties(input.serial)
        
        return json.dumps({
            "success": True,
            "serial": input.serial,
            "properties": properties,
            "count": len(properties)
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def report_device_health(input: GetDeviceHealthInput) -> str:
    """Collect device health telemetry and send it to the orchestrator."""
    try:
        telemetry = await adb_manager.get_device_health(input.serial)
        battery_pct = None
        battery = telemetry.get("battery", {})
        if "level" in battery:
            try:
                battery_pct = int(battery["level"])
            except ValueError:
                battery_pct = None

        register_response = await orchestrator_client.call_tool(
            "register_device_health",
            {
                "serial": input.serial,
                "battery_pct": battery_pct,
                "last_usb_seen": battery.get("status"),
                "brick_risk_flags": [],
                "health_status": "GREEN",
            },
        )

        return json.dumps({
            "success": True,
            "serial": input.serial,
            "telemetry": telemetry,
            "orchestrator_response": register_response,
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


@mcp.tool()
async def health_check() -> str:
    """
    Health check for the MCP server.
    
    Returns JSON with server status.
    """
    try:
        # Try to connect to ADB
        devices = await adb_manager.get_connected_devices()
        
        return json.dumps({
            "status": "healthy",
            "adb_reachable": True,
            "connected_devices": len(devices),
            "version": "1.0.0"
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "status": "unhealthy",
            "error": str(e),
            "version": "1.0.0"
        }, indent=2)


if __name__ == "__main__":
    # Run the MCP server
    mcp.run(transport="streamable-http")
