"""Device lifecycle and UI automation tools."""

import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class UIHierarchy:
    """Represents the device UI hierarchy/layout."""
    xml: str
    height: int
    width: int


class LifecycleManager:
    """Manages device lifecycle and UI interactions."""
    
    def __init__(self, adb_manager):
        self.adb = adb_manager
    
    async def get_screen_hierarchy(self, serial: str) -> UIHierarchy:
        """
        Capture device screen hierarchy using uiautomator.
        
        Args:
            serial: Device serial number
            
        Returns:
            UIHierarchy object containing XML and dimensions
        """
        try:
            # Get window size
            size_output = await self.adb.shell(serial, "wm size")
            width, height = self._parse_wm_size(size_output)
            
            # Dump UI hierarchy
            hierarchy_output = await self.adb.shell(
                serial, 
                "uiautomator dump /sdcard/window_dump.xml && cat /sdcard/window_dump.xml"
            )
            
            return UIHierarchy(
                xml=hierarchy_output,
                width=width,
                height=height
            )
        except Exception as e:
            raise RuntimeError(f"Failed to get screen hierarchy from {serial}: {str(e)}")
    
    async def capture_screenshot(self, serial: str, local_path: str) -> None:
        """
        Capture a screenshot from the device.
        
        Args:
            serial: Device serial number
            local_path: Local path to save screenshot
        """
        try:
            # Take screenshot
            await self.adb.shell(serial, "screencap -p /sdcard/screenshot.png")
            # Pull to local
            await self.adb.pull(serial, "/sdcard/screenshot.png", local_path)
        except Exception as e:
            raise RuntimeError(f"Failed to capture screenshot from {serial}: {str(e)}")
    
    async def get_logcat(
        self, 
        serial: str, 
        lines: int = 100,
        filter_spec: Optional[str] = None
    ) -> str:
        """
        Get logcat output from device.
        
        Args:
            serial: Device serial number
            lines: Number of lines to retrieve
            filter_spec: Optional filter specification (e.g., "tag:V")
            
        Returns:
            Logcat output as string
        """
        try:
            cmd = f"logcat -d -t {lines}"
            if filter_spec:
                cmd += f" {filter_spec}"
            
            return await self.adb.shell(serial, cmd)
        except Exception as e:
            raise RuntimeError(f"Failed to get logcat from {serial}: {str(e)}")
    
    async def install_apk(self, serial: str, apk_path: str) -> None:
        """
        Install an APK on the device.
        
        Args:
            serial: Device serial number
            apk_path: Local path to APK file
        """
        try:
            # Push APK to device
            remote_path = "/sdcard/app.apk"
            await self.adb.push(serial, apk_path, remote_path)
            
            # Install APK
            result = await self.adb.shell(serial, f"pm install {remote_path}")
            
            if "Success" not in result:
                raise RuntimeError(f"APK installation failed: {result}")
        except Exception as e:
            raise RuntimeError(f"Failed to install APK on {serial}: {str(e)}")
    
    async def tap(self, serial: str, x: int, y: int) -> None:
        """
        Tap at coordinates on the device screen.
        
        Args:
            serial: Device serial number
            x: X coordinate
            y: Y coordinate
        """
        try:
            await self.adb.shell(serial, f"input tap {x} {y}")
        except Exception as e:
            raise RuntimeError(f"Failed to tap on {serial}: {str(e)}")
    
    async def type_text(self, serial: str, text: str) -> None:
        """
        Type text on the device.
        
        Args:
            serial: Device serial number
            text: Text to type
        """
        try:
            # Escape special characters
            escaped_text = text.replace(" ", "%s").replace("'", "\\'")
            await self.adb.shell(serial, f"input text '{escaped_text}'")
        except Exception as e:
            raise RuntimeError(f"Failed to type text on {serial}: {str(e)}")
    
    async def reboot_device(self, serial: str, mode: str = "system") -> None:
        """
        Reboot the device.
        
        Args:
            serial: Device serial number
            mode: Reboot mode (system, recovery, bootloader)
        """
        try:
            if mode in ["recovery", "bootloader"]:
                await self.adb.shell(serial, f"reboot {mode}")
            else:
                await self.adb.shell(serial, "reboot")
        except Exception as e:
            raise RuntimeError(f"Failed to reboot {serial}: {str(e)}")
    
    @staticmethod
    def _parse_wm_size(output: str) -> tuple:
        """Parse wm size output to get width and height."""
        try:
            # Output format: "Physical size: 1080x2340"
            for line in output.split('\n'):
                if "Physical size:" in line:
                    size_part = line.split(":")[-1].strip()
                    width, height = map(int, size_part.split("x"))
                    return width, height
        except:
            pass
        
        # Default fallback
        return 1080, 2340
