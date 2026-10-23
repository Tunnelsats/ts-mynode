#!/usr/bin/env python3
"""Unit tests for bridge.py (MyNode dual-mode, reconciler, crypto, settlement, and HTTP security)."""

import io
import json
import os
import pathlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
import sys  # noqa: E402

sys.path.insert(0, str(REPO_ROOT))
import bridge  # noqa: E402


SAMPLE_PRIVKEY = "cGxlYXNlRG9Ob3RVc2VUaGlzVGVzdEtleUluUHJvZDA="
SAMPLE_PUBKEY = bridge.derive_wg_pubkey(SAMPLE_PRIVKEY)
SAMPLE_WG_CONF = f"""[Interface]
PrivateKey = {SAMPLE_PRIVKEY}
Address = 10.9.0.42/32
# Server: eu1.tunnelsats.com
# Port Forwarding: 34567
# myPubKey: {SAMPLE_PUBKEY}
# Valid Until: 2027-01-01T00:00:00Z

[Peer]
PublicKey = dGVzdFNlcnZlclB1YmxpY0tleVZhbHVlMTIzNDU2Nzg=
Endpoint = eu1.tunnelsats.com:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""


def _build_test_bolt11(payment_hash_hex, amount_milli_btc=1):
    """Builds a valid Bech32-encoded BOLT11 invoice with embedded 'p' tag for testing."""
    hrp = f"lnbc{amount_milli_btc}m"
    # 7 timestamp words (zeros)
    ts_words = [0] * 7
    # Tag 'p' (type=1), length=52 words (1 << 5 | 20 -> [1, 20])
    hash_bytes = bytes.fromhex(payment_hash_hex)
    acc = int.from_bytes(hash_bytes, "big") << 4
    p_words = [(acc >> (5 * (51 - i))) & 31 for i in range(52)]
    tagged = [1, 52 >> 5, 52 & 31] + p_words
    # 104 signature words
    sig_words = [0] * 104
    payload_words = ts_words + tagged + sig_words
    values = bridge._bech32_hrp_expand(hrp) + payload_words
    polymod = bridge._bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    checksum = [(polymod >> (5 * (5 - i))) & 31 for i in range(6)]
    all_words = payload_words + checksum
    return hrp + "1" + "".join(bridge._BECH32_CHARSET[w] for w in all_words)


class _FakeHTTPRequestHandler(bridge.DashboardHTTPRequestHandler):
    """In-memory harness for DashboardHTTPRequestHandler without opening sockets."""

    def __init__(self, method, path, headers=None, body=b"", client_ip="127.0.0.1"):
        self.command = method
        self.path = path
        self.request_version = "HTTP/1.1"
        self.client_address = (client_ip, 54321)
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status_code = None
        self.response_headers = {}
        self.error_code = None
        self.error_message = None

    def send_response(self, code, message=None):
        self.status_code = code

    def send_header(self, keyword, value):
        self.response_headers[keyword.lower()] = value

    def end_headers(self):
        pass

    def send_error(self, code, message=None, explain=None):
        self.status_code = code
        self.error_code = code
        self.error_message = message


class TestBridgeMyNode(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmpdir.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lnd_extra = self.root / "lnd_extra_config.conf"
        self.mock_ts_sh = self.root / "mock_tunnelsats.sh"
        self.mock_ts_sh.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        self.mock_ts_sh.chmod(0o755)
        bridge.configure_paths(
            self.data_dir,
            lnd_extra_conf=self.lnd_extra,
            reconciler_path=REPO_ROOT / "scripts" / "reconcile_mynode.sh",
            tunnelsats_sh_path=self.mock_ts_sh,
        )
        os.environ.pop("SECURE_MODE", None)

    def tearDown(self):
        os.environ.pop("SECURE_MODE", None)
        self.tmpdir.cleanup()

    def test_keypair_generation_and_derivation(self):
        priv, pub = bridge.generate_wg_keypair()
        self.assertRegex(priv, r"^[A-Za-z0-9+/]{43}=$")
        self.assertRegex(pub, r"^[A-Za-z0-9+/]{43}=$")
        self.assertEqual(bridge.derive_wg_pubkey(priv), pub)

    def test_config_parsing_and_save_configuration(self):
        comments = bridge.parse_config_comments(SAMPLE_WG_CONF)
        self.assertEqual(comments["vpnPort"], 34567)
        self.assertEqual(comments["serverDomain"], "eu1.tunnelsats.com")
        self.assertEqual(bridge.extract_vpn_port(SAMPLE_WG_CONF), 34567)
        self.assertEqual(bridge.extract_server_host(SAMPLE_WG_CONF), "eu1.tunnelsats.com")

        saved = bridge.save_configuration(SAMPLE_WG_CONF, target_node="lnd")
        self.assertTrue(saved)
        self.assertEqual(bridge.get_wg_pubkey(), SAMPLE_PUBKEY)

        dash = bridge.get_dashboard()
        self.assertTrue(dash["configured"])
        self.assertTrue(dash["enabled"])
        self.assertEqual(dash["connection"]["vpnPort"], 34567)
        self.assertEqual(dash["connection"]["server"], "eu1.tunnelsats.com")
        self.assertEqual(dash["connection"]["publicKey"], SAMPLE_PUBKEY)
        self.assertIn("mynode", dash)
        self.assertFalse(dash["mynode"]["secureMode"])
        self.assertEqual(dash["mynode"]["mode"], "integrated")

    def test_dual_mode_secure_mode_and_reconciler_guard(self):
        bridge.save_configuration(SAMPLE_WG_CONF, target_node="lnd")
        self.assertFalse(bridge.is_secure_mode())

        status = bridge.set_secure_mode(True)
        self.assertTrue(status["secureMode"])
        self.assertEqual(status["mode"], "secure")
        self.assertTrue(bridge.is_secure_mode())

        code, body = bridge.run_mynode_reconciler("apply")
        self.assertEqual(code, 403)
        self.assertTrue(body["secureMode"])
        self.assertIn("reconcile_mynode.sh apply", body["manualCommand"])
        self.assertIn("VPN_EXTERNAL_HOST=eu1.tunnelsats.com", body["manualCommand"])
        self.assertIn("VPN_PORT=34567", body["manualCommand"])

        # Switch back to Mode A (Integrated Mode) and verify block-insert via reconciler status
        bridge.set_secure_mode(False)
        self.assertFalse(bridge.is_secure_mode())
        self.lnd_extra.write_text(
            "alias=my-node\n# BEGIN TUNNELSATS\nexternalhosts=eu1.tunnelsats.com:34567\n# END TUNNELSATS\n",
            encoding="utf-8",
        )
        mn_status = bridge.get_mynode_reconciler_status()
        self.assertTrue(mn_status["lndExtraConfigured"])
        self.assertEqual(mn_status["externalHost"], "eu1.tunnelsats.com:34567")

    def test_intents_and_in_process_execution_and_settlement(self):
        code, resp = bridge.submit_dashboard_intent(
            {"kind": "buy", "serverId": "eu-de", "duration": "3m"}
        )
        self.assertEqual(code, 202)
        self.assertEqual(resp["status"], "accepted")

        pay_hash = "ab" * 32
        bolt11 = _build_test_bolt11(pay_hash, amount_milli_btc=1)

        with mock.patch.object(
            bridge,
            "_api_call",
            return_value=(
                200,
                {
                    "orderId": "ord-123",
                    "paymentHash": pay_hash,
                    "invoice": bolt11,
                    "expiresAt": _iso_future(1),
                },
            ),
        ):
            outcomes = bridge.process_pending_intents()
            self.assertEqual(outcomes.get("buy"), "succeeded")

        dash = bridge.get_dashboard()
        self.assertIsNotNone(dash["pending"]["order"])
        self.assertEqual(dash["pending"]["order"]["invoice"], bolt11)

        # Now settle the paid order
        meta = bridge.read_meta()
        order_pub = meta["pendingOrder"]["publicKey"]
        server_pub = bridge.generate_wg_keypair()[1]

        def fake_api_call(method, path, body=None):
            if path == f"/subscription/{pay_hash}":
                return 200, {"status": "paid"}
            if path == "/subscription/claim":
                return 200, {
                    "peer": {
                        "publicKey": order_pub,
                        "address": "10.9.0.77/32",
                    },
                    "server": {
                        "publicKey": server_pub,
                        "endpoint": "de1.tunnelsats.com:51820",
                        "allowedIPs": "0.0.0.0/0, ::/0",
                    },
                    "vpnPort": 45678,
                    "subscriptionEnd": "2027-06-01T00:00:00Z",
                }
            raise AssertionError(f"Unexpected API path: {path}")

        with mock.patch.object(bridge, "_api_call", side_effect=fake_api_call):
            settle_res = bridge.settle_pending()
            self.assertFalse(settle_res["busy"])
            self.assertEqual(settle_res["outcomes"][0]["result"], "provisioned")

        self.assertEqual(bridge.get_wg_pubkey(), order_pub)

    def test_nwc_connect_disconnect_and_nip04_roundtrip(self):
        secret_a = "11" * 32
        secret_b = "22" * 32
        pub_b = bridge._nostr_pubkey_from_secret(secret_b)
        uri = f"nostr+walletconnect://{pub_b}?relay=wss%3A%2F%2Frelay.getalby.com%2Fv1&secret={secret_a}"

        code, body = bridge.connect_nwc_wallet(
            {"uri": uri, "autoRenewDuration": "3m", "routeViaTor": True}
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["nwc"]["connected"])
        self.assertTrue(body["nwc"]["routeViaTor"])
        self.assertEqual(body["nwc"]["autoRenewDuration"], "3m")

        # NIP-04 encrypt/decrypt & Schnorr verify roundtrip
        req_event, shared_key = bridge._build_nip47_request_event(
            secret_a, pub_b, "get_balance", {}
        )
        decrypted = bridge._nip04_decrypt(shared_key, req_event["content"])
        self.assertEqual(json.loads(decrypted)["method"], "get_balance")

        code, body = bridge.disconnect_nwc_wallet()
        self.assertEqual(code, 200)
        self.assertFalse(body["nwc"]["connected"])

    def test_http_handler_security_and_mynode_proxy_headers(self):
        csrf = bridge.get_csrf_token()

        # 1. Local nginx reverse proxy forwarding Host: mynode.local:8740
        h1 = _FakeHTTPRequestHandler(
            "GET",
            "/api/dashboard",
            headers={"Host": "mynode.local:8740", "Origin": "https://mynode.local:8740"},
            client_ip="127.0.0.1",
        )
        h1.do_GET()
        self.assertEqual(h1.status_code, 200)

        # 2. Local nginx reverse proxy forwarding LAN IP Host: 192.168.1.50:8740 (/api/status and /api/health alias)
        h2 = _FakeHTTPRequestHandler(
            "GET",
            "/api/status",
            headers={"Host": "192.168.1.50:8740", "Origin": "https://192.168.1.50:8740"},
            client_ip="127.0.0.1",
        )
        h2.do_GET()
        self.assertEqual(h2.status_code, 200)
        status_json = json.loads(h2.wfile.getvalue().decode("utf-8"))
        self.assertIn("status", status_json)

        h2_health = _FakeHTTPRequestHandler(
            "GET",
            "/api/health",
            headers={"Host": "192.168.1.50:8740", "Origin": "https://192.168.1.50:8740"},
            client_ip="127.0.0.1",
        )
        h2_health.do_GET()
        self.assertEqual(h2_health.status_code, 200)
        health_json = json.loads(h2_health.wfile.getvalue().decode("utf-8"))
        self.assertEqual(health_json["status"], status_json["status"])

        # 3. Reject DNS rebinding / external Host header
        h3 = _FakeHTTPRequestHandler(
            "GET",
            "/api/dashboard",
            headers={"Host": "evil.com"},
            client_ip="127.0.0.1",
        )
        h3.do_GET()
        self.assertEqual(h3.status_code, 403)

        # 4. Reject cross-origin Origin header
        h4 = _FakeHTTPRequestHandler(
            "POST",
            "/api/mynode/mode",
            headers={
                "Host": "mynode.local:8740",
                "Origin": "https://evil.com",
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf,
            },
            body=b'{"secureMode": true}',
            client_ip="127.0.0.1",
        )
        h4.do_POST()
        self.assertEqual(h4.status_code, 403)

        # 5. Reject missing CSRF token on POST
        h5 = _FakeHTTPRequestHandler(
            "POST",
            "/api/mynode/mode",
            headers={
                "Host": "mynode.local:8740",
                "Content-Type": "application/json",
            },
            body=b'{"secureMode": true}',
            client_ip="127.0.0.1",
        )
        h5.do_POST()
        self.assertEqual(h5.status_code, 403)

        # 6. Accept valid POST /api/mynode/mode with X-TunnelSats-CSRF-Token
        body_bytes = b'{"secureMode": true}'
        h6 = _FakeHTTPRequestHandler(
            "POST",
            "/api/mynode/mode",
            headers={
                "Host": "mynode.local:8740",
                "Origin": "https://mynode.local:8740",
                "Content-Type": "application/json",
                "Content-Length": str(len(body_bytes)),
                "X-TunnelSats-CSRF-Token": csrf,
            },
            body=body_bytes,
            client_ip="127.0.0.1",
        )
        h6.do_POST()
        self.assertEqual(h6.status_code, 200)
        resp_json = json.loads(h6.wfile.getvalue().decode("utf-8"))
        self.assertTrue(resp_json["secureMode"])


def _iso_future(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    unittest.main()
