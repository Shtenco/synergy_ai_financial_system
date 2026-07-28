import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_polygon_balances.py"
SPEC = importlib.util.spec_from_file_location("check_polygon_balances", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class BalanceEncodingTest(unittest.TestCase):
    def test_balance_of_data(self):
        address = "0x6946999DBCE63b140B1bB9D475F7c357130909E5"
        encoded = MODULE.balance_of_data(address)
        self.assertEqual(encoded[:10], "0x70a08231")
        self.assertEqual(len(encoded), 74)
        self.assertEqual(encoded[-40:], address[2:].lower())

    def test_balance_of_rejects_invalid_address(self):
        with self.assertRaisesRegex(ValueError, "20 hexadecimal bytes"):
            MODULE.balance_of_data("0xnot-an-address")


class TLSContextTest(unittest.TestCase):
    def test_default_context_requires_certificate_verification(self):
        context = MODULE.make_ssl_context(None)
        self.assertEqual(context.verify_mode, MODULE.ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_connect_403_explains_that_tls_bypass_cannot_help(self):
        error = OSError("Tunnel connection failed: 403 Forbidden")
        message = MODULE.explain_connection_error(error)
        self.assertIn("before TLS started", message)
        self.assertIn("allowlist", message)
        self.assertIn("approved Polygon RPC endpoint", message)


if __name__ == "__main__":
    unittest.main()
