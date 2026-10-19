"""Unit tests for the shared security helpers (stdlib unittest, no extra deps).

Run:  python -m unittest discover -s tests -v
"""

import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "servers"))

from common import preflight_store, staging, validation  # noqa: E402
from common.security import BearerAuth, bind_host, build_app, is_loopback  # noqa: E402


class ValidationTests(unittest.TestCase):
    def test_serial_accepts_normal_values(self):
        for s in ("ABC123", "emulator-5554", "192.168.1.5:5555", "R5CT21XXXXX"):
            self.assertEqual(validation.validate_serial(s), s)

    def test_serial_rejects_option_injection_and_junk(self):
        for s in ("-s", "--version", "", "a b", "a;b", "a" * 65, "../x"):
            with self.assertRaises(ValueError):
                validation.validate_serial(s)

    def test_partition(self):
        self.assertEqual(validation.validate_partition("boot_a"), "boot_a")
        for p in ("-x", "", "a/b", "a b", "x" * 33):
            with self.assertRaises(ValueError):
                validation.validate_partition(p)

    def test_address(self):
        self.assertEqual(validation.validate_address("10.0.0.2:5555"), "10.0.0.2:5555")
        for a in ("10.0.0.2", "10.0.0.2:0", "10.0.0.2:70000", "-h:1", "a b:1"):
            with self.assertRaises(ValueError):
                validation.validate_address(a)

    def test_dangerous_partitions_cover_boot_chain_and_slots(self):
        for p in ("boot", "boot_a", "vbmeta_b", "recovery", "userdata", "radio", "modem"):
            self.assertTrue(validation.is_dangerous_partition(p), p)
        self.assertFalse(validation.is_dangerous_partition("cache"))


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        os.environ["ANDROIDMCP_STAGING_ROOT"] = str(self.root)
        os.environ.pop("ANDROIDMCP_IMAGE_ROOTS", None)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("ANDROIDMCP_STAGING_ROOT", None)
        os.environ.pop("ANDROIDMCP_IMAGE_ROOTS", None)

    def test_relative_inside_ok(self):
        p = staging.resolve_staging_path("SER1", "boot.img")
        self.assertTrue(p.startswith(str(self.root)))

    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):
            staging.resolve_staging_path("SER1", "../../etc/passwd")

    def test_absolute_outside_rejected(self):
        with self.assertRaises(ValueError):
            staging.resolve_staging_path("SER1", "/etc/passwd")

    def test_symlink_escape_rejected(self):
        d = staging.ensure_staging_dirs("SER1")
        (d / "evil.img").symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            staging.resolve_staging_path("SER1", "evil.img")

    def test_extra_root_allowed(self):
        with tempfile.TemporaryDirectory() as other:
            os.environ["ANDROIDMCP_IMAGE_ROOTS"] = other
            f = Path(other).resolve() / "x.img"
            f.write_bytes(b"1")
            self.assertEqual(staging.resolve_staging_path("S", str(f)), str(f))


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["ANDROIDMCP_PREFLIGHT_FILE"] = str(Path(self.tmp.name) / "p.json")

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("ANDROIDMCP_PREFLIGHT_FILE", None)

    def test_roundtrip_and_delete(self):
        preflight_store.store("id1", {"confirm_token": "123456"})
        self.assertEqual(preflight_store.get("id1")["confirm_token"], "123456")
        preflight_store.delete("id1")
        self.assertIsNone(preflight_store.get("id1"))

    def test_expiry(self):
        preflight_store.store("id2", {"confirm_token": "1"}, ttl_seconds=-1)
        self.assertIsNone(preflight_store.get("id2"))

    def test_file_is_private(self):
        preflight_store.store("id3", {"confirm_token": "1"})
        mode = os.stat(preflight_store.preflight_file_path()).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_token_ok(self):
        preflight_store.store("id4", {"confirm_token": "654321"})
        self.assertTrue(preflight_store.verify_confirm_token("id4", "654321", "654321"))

    def test_attempt_limit_revokes_even_correct_token(self):
        preflight_store.store("id5", {"confirm_token": "654321"})
        for _ in range(preflight_store.MAX_TOKEN_ATTEMPTS):
            self.assertFalse(preflight_store.verify_confirm_token("id5", "000000", "654321"))
        self.assertIsNone(preflight_store.get("id5"))

    def test_remote_record_still_compares(self):
        self.assertTrue(preflight_store.verify_confirm_token("nope", "111111", "111111"))
        self.assertFalse(preflight_store.verify_confirm_token("nope", "111112", "111111"))

    def test_token_format(self):
        for _ in range(50):
            t = preflight_store.generate_confirm_token()
            self.assertEqual(len(t), 6)
            self.assertTrue(t.isdigit())


class AuthTests(unittest.TestCase):
    def _call(self, app, headers):
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            sent.append(msg)

        scope = {"type": "http", "headers": headers, "method": "POST", "path": "/mcp"}
        asyncio.run(app(scope, receive, send))
        return sent

    def _inner(self):
        async def inner(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        return inner

    def test_rejects_missing_and_wrong_token(self):
        app = BearerAuth(self._inner(), "s3cret")
        self.assertEqual(self._call(app, [])[0]["status"], 401)
        self.assertEqual(self._call(app, [(b"authorization", b"Bearer nope")])[0]["status"], 401)
        self.assertEqual(self._call(app, [(b"authorization", b"s3cret")])[0]["status"], 401)

    def test_accepts_right_token(self):
        app = BearerAuth(self._inner(), "s3cret")
        self.assertEqual(self._call(app, [(b"authorization", b"Bearer s3cret")])[0]["status"], 200)

    def test_loopback_detection(self):
        for h in ("127.0.0.1", "localhost", "::1"):
            self.assertTrue(is_loopback(h))
        for h in ("0.0.0.0", "192.168.1.2", "example.com"):
            self.assertFalse(is_loopback(h))

    def test_default_bind_is_loopback(self):
        os.environ.pop("MCP_HOST", None)
        self.assertEqual(bind_host(), "127.0.0.1")

    def test_refuses_public_bind_without_token(self):
        class S:  # minimal stand-in for FastMCP
            class settings:
                host = "0.0.0.0"
                port = 1

        os.environ.pop("MCP_AUTH_TOKEN", None)
        with self.assertRaises(SystemExit):
            build_app(S, "0.0.0.0")


class EndpointAllowlistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "ts_server", ROOT / "servers" / "tailscale" / "server.py"
        )
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_allowed(self):
        for u in ("http://127.0.0.1:8110/mcp", "http://localhost:8113/mcp",
                  "http://100.64.1.2:8111/mcp"):
            self.assertTrue(self.mod._endpoint_allowed(u), u)

    def test_blocked(self):
        for u in ("http://169.254.169.254/latest/meta-data", "http://127.0.0.1:22/mcp",
                  "http://example.com:8110/mcp", "file:///etc/passwd",
                  "http://127.0.0.1:8110/other", "http://10.0.0.5:8110/mcp"):
            self.assertFalse(self.mod._endpoint_allowed(u), u)


if __name__ == "__main__":
    unittest.main()
