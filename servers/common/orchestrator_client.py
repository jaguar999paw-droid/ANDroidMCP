"""Lightweight MCP JSON-RPC client for orchestrator tools.

Uses httpx (already available in the MCP venv) instead of aiohttp.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional

import httpx


class OrchestratorClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (
            base_url
            or os.getenv("ORCHESTRATOR_MCP_URL", "http://127.0.0.1:8112/mcp")
        ).rstrip("/")
        self._session_id: Optional[str] = None
        self._rpc_id = 0

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            h["mcp-session-id"] = self._session_id
        return h

    async def _ensure_session(self, client: httpx.AsyncClient) -> None:
        if self._session_id:
            return
        msg = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "android-bootloader", "version": "1.0"},
            },
        }
        resp = await client.post(self.base_url, json=msg, headers=self._headers())
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        if resp.status_code != 200:
            raise RuntimeError(
                f"Orchestrator initialize HTTP {resp.status_code}: {resp.text[:200]}"
            )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
            await self._ensure_session(client)
            wrapped = arguments if "input" in arguments else {"input": arguments}
            msg = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": wrapped},
            }
            resp = await client.post(
                self.base_url, json=msg, headers=self._headers()
            )
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self._session_id = sid
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Orchestrator tools/call HTTP {resp.status_code}: {resp.text[:300]}"
                )
            return self._parse_mcp_response(resp.text)

    def _parse_mcp_response(self, text: str) -> dict[str, Any]:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line[0] != "{":
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "result" in obj:
                result = obj["result"]
                if isinstance(result, dict) and "content" in result:
                    for block in result.get("content", []):
                        if block.get("type") == "text":
                            try:
                                return json.loads(block["text"])
                            except json.JSONDecodeError:
                                return {"raw": block["text"]}
                return result if isinstance(result, dict) else {"raw": result}
            if "error" in obj:
                raise RuntimeError(str(obj["error"]))
        raise RuntimeError(f"Unparseable orchestrator response: {text[:400]}")

    async def acquire_lock(
        self, serial: str, requesting_server: str, target_state: str,
        timeout_seconds: int = 300
    ) -> dict[str, Any]:
        return await self.call_tool(
            "acquire_lock",
            {
                "serial": serial,
                "requesting_server": requesting_server,
                "target_state": target_state,
                "timeout_seconds": timeout_seconds,
            },
        )

    async def release_lock(self, serial: str, releasing_server: str) -> dict[str, Any]:
        return await self.call_tool(
            "release_lock",
            {"serial": serial, "releasing_server": releasing_server},
        )

    async def store_preflight(
        self, serial: str, preflight_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.call_tool(
            "store_preflight",
            {"serial": serial, "preflight_id": preflight_id, "payload": payload},
        )

    async def get_preflight(self, preflight_id: str) -> dict[str, Any]:
        return await self.call_tool("get_preflight", {"preflight_id": preflight_id})
