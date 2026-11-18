#!/usr/bin/env python3
"""Unit tests for the MyNode App SDK v2 package structure, version bumper, and repo hygiene."""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_mynode_app  # noqa: E402


class TestMyNodeAppSDK(unittest.TestCase):
    def test_validate_repository_mynode_app(self):
        app_dir = REPO_ROOT / "mynode_app" / "tunnelsats"
        errors, warnings = check_mynode_app.check_mynode_app(str(app_dir))
        self.assertEqual(errors, [], f"Unexpected MyNode SDK validation errors: {errors}")
        self.assertEqual(warnings, [], f"Unexpected MyNode SDK validation warnings: {warnings}")

    def test_detects_port_mismatch_and_invalid_schema(self):
        src_app = REPO_ROOT / "mynode_app" / "tunnelsats"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_app = pathlib.Path(tmp) / "tunnelsats"
            shutil.copytree(src_app, tmp_app)
            manifest_path = tmp_app / "tunnelsats.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["http_port"] = 9999
            data["sdk_version"] = 1
            manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

            errors, _warnings = check_mynode_app.check_mynode_app(str(tmp_app))
            self.assertTrue(any("sdk_version" in e for e in errors))
            self.assertTrue(any("9999" in e or "http_port=8739" in e for e in errors))

    def test_bump_version_updates_both_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = pathlib.Path(tmp)
            (tmp_root / "scripts").mkdir(parents=True)
            (tmp_root / "mynode_app" / "tunnelsats").mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "scripts" / "bump_version.py", tmp_root / "scripts" / "bump_version.py")
            shutil.copy2(REPO_ROOT / "version.json", tmp_root / "version.json")
            shutil.copy2(
                REPO_ROOT / "mynode_app" / "tunnelsats" / "tunnelsats.json",
                tmp_root / "mynode_app" / "tunnelsats" / "tunnelsats.json",
            )

            proc = subprocess.run(
                [sys.executable, str(tmp_root / "scripts" / "bump_version.py"), "0.2.0"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("0.2.0", proc.stdout)
            v_data = json.loads((tmp_root / "version.json").read_text(encoding="utf-8"))
            m_data = json.loads(
                (tmp_root / "mynode_app" / "tunnelsats" / "tunnelsats.json").read_text(encoding="utf-8")
            )
            self.assertEqual(v_data["version"], "0.2.0")
            self.assertEqual(v_data["semver"], "0.2.0")
            self.assertEqual(m_data["latest_version"], "v0.2.0")
            self.assertTrue(m_data["download_source_sha256"].startswith("v0.2.0 "))

    def test_zero_em_dashes_across_repository(self):
        text_exts = {
            ".py", ".sh", ".md", ".html", ".css", ".js", ".json",
            ".yml", ".yaml", ".conf", ".service", ".bats", ".txt",
        }
        offenders = []
        for path in REPO_ROOT.rglob("*"):
            if ".git" in path.parts or not path.is_file():
                continue
            if path.suffix.lower() in text_exts or path.name in ("LICENSE", ".gitignore"):
                content = path.read_text(encoding="utf-8")
                if "\u2014" in content:
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(offenders, [], f"Found forbidden U+2014 em dashes in: {offenders}")

    def test_mynode_version_tracking_and_readme_branding(self):
        for rel in (
            "scripts/deploy_mynode.sh",
            "mynode_app/tunnelsats/scripts/install_tunnelsats.sh",
            "mynode_app/tunnelsats/scripts/pre_tunnelsats.sh",
            "mynode_app/tunnelsats/scripts/uninstall_tunnelsats.sh",
        ):
            content = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("/home/bitcoin/.mynode/tunnelsats_version", content, f"Missing version file in {rel}")
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("ts_logo_rectangle.svg", readme)
        self.assertIn("myNode is a trademark of MyNode LLC", readme)

    def test_mynode_app_zero_sudo_and_session_auth_contract(self):
        app_dir = REPO_ROOT / "mynode_app" / "tunnelsats"
        nginx_conf = (app_dir / "nginx" / "https_tunnelsats.conf").read_text(encoding="utf-8")
        self.assertGreaterEqual(nginx_conf.count("include /etc/nginx/mynode/mynode_session_auth.conf;"), 2)
        self.assertGreaterEqual(nginx_conf.count("auth_request /mynode_auth_check;"), 2)
        self.assertIn("proxy_set_header Cookie $mynode_proxy_cookie;", nginx_conf)

        svc_text = (app_dir / "tunnelsats.service").read_text(encoding="utf-8")
        self.assertNotIn("ExecStopPost", svc_text)
        self.assertNotIn("wait_on_lnd.sh", svc_text)
        self.assertNotIn("wait_on_bitcoin.sh", svc_text)

        pre_text = (app_dir / "scripts" / "pre_tunnelsats.sh").read_text(encoding="utf-8")
        uninstall_text = (app_dir / "scripts" / "uninstall_tunnelsats.sh").read_text(encoding="utf-8")
        self.assertNotIn("NOPASSWD", pre_text)
        self.assertNotIn("env_keep", pre_text)
        self.assertNotIn("chown -R", pre_text)
        self.assertNotIn("sudo ", uninstall_text)

        for script_name in ("reconcile_mynode.sh", "tunnelsats.sh"):
            root_copy = app_dir / "root_scripts" / script_name
            repo_copy = REPO_ROOT / "scripts" / script_name
            self.assertTrue(root_copy.is_file(), f"Missing root_scripts/{script_name}")
            self.assertEqual(
                root_copy.read_bytes(),
                repo_copy.read_bytes(),
                f"root_scripts/{script_name} drifted from scripts/{script_name}",
            )

    def test_reconcile_mynode_rejects_hooks_converges_and_orders_killswitch_first(self):
        reconciler = REPO_ROOT / "scripts" / "reconcile_mynode.sh"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            data_dir = tmp_path / "tunnelsats"
            wg_dir = tmp_path / "wireguard"
            run_dir = tmp_path / "run"
            data_dir.mkdir(mode=0o700)
            wg_dir.mkdir(mode=0o700)
            run_dir.mkdir(mode=0o755)

            conf_path = data_dir / "tunnelsatsv2.conf"
            lnd_extra = tmp_path / "lnd_extra_config.conf"
            lnd_main = tmp_path / "lnd.conf"
            lnd_main.write_text("[Application Options]\n[Tor]\n", encoding="utf-8")
            managed_inv = tmp_path / "managed.json"
            status_out = run_dir / "reconcile-status.json"
            lock_file = run_dir / "reconcile.lock"

            order_log = tmp_path / "order.log"
            mock_ts = tmp_path / "mock_ts.sh"
            mock_ts.write_text(
                f"""#!/usr/bin/env bash
if [ -f "{lnd_extra}" ] && grep -q "BEGIN TUNNELSATS" "{lnd_extra}"; then
  echo "ts_after_extra" >> "{order_log}"
else
  echo "ts_before_extra" >> "{order_log}"
fi
echo "ts:$*" >> "{order_log}"
exit 0
""",
                encoding="utf-8",
            )
            mock_ts.chmod(0o755)

            mock_sys = tmp_path / "mock_systemctl.sh"
            mock_sys.write_text(
                f"""#!/usr/bin/env bash
if [ "$1" = "is-active" ]; then
  exit 0
fi
if [ "$1" = "show" ]; then
  echo "ControlGroup=/tunnelsats.slice/lnd.service"
  echo "DropInPaths=/etc/systemd/system/lnd.service.d/tunnelsats-managed.conf"
  echo "NeedDaemonReload=no"
  exit 0
fi
echo "systemctl:$*" >> "{order_log}"
exit 0
""",
                encoding="utf-8",
            )
            mock_sys.chmod(0o755)

            env = dict(os.environ)
            env.update(
                {
                    "TUNNELSATS_TEST_MODE": "1",
                    "TUNNELSATS_DATA_DIR": str(data_dir),
                    "TUNNELSATS_CONF_PATH": str(conf_path),
                    "TUNNELSATS_APP_CONFIG": str(data_dir / "config.json"),
                    "LND_EXTRA_CONFIG": str(lnd_extra),
                    "LND_MAIN_CONFIG": str(lnd_main),
                    "WG_DIR": str(wg_dir),
                    "WG_CONF_DST": str(wg_dir / "tunnelsatsv2.conf"),
                    "MANAGED_INVENTORY": str(managed_inv),
                    "RECONCILE_STATUS_FILE": str(status_out),
                    "RECONCILE_LOCK_FILE": str(lock_file),
                    "TS_SH_BIN": str(mock_ts),
                    "SYSTEMCTL_BIN": str(mock_sys),
                }
            )

            # 1. Reject PostUp hook even when managed.json is already "installed"
            managed_inv.write_text(
                json.dumps({"schema": 1, "state": "installed", "profile": "mynode", "impl": "lnd", "unit": "lnd.service"}),
                encoding="utf-8",
            )
            bad_conf = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Address = 10.9.0.42/32
PostUp = touch /tmp/should_never_run
# Server: eu1.tunnelsats.com
# Port Forwarding: 34567

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
Endpoint = eu1.tunnelsats.com:51820
AllowedIPs = 0.0.0.0/0, ::/0
"""
            conf_path.write_text(bad_conf, encoding="utf-8")
            conf_path.chmod(0o600)
            res_bad = subprocess.run(["/bin/bash", str(reconciler), "apply"], env=env, capture_output=True, text=True)
            self.assertEqual(res_bad.returncode, 8, f"Expected hook rejection: {res_bad.stderr}")
            self.assertFalse((wg_dir / "tunnelsatsv2.conf").exists())

            # 2. First-time apply runs tunnelsats.sh BEFORE inserting lnd_extra_config.conf
            managed_inv.unlink()
            good_conf = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Address = 10.9.0.42/32
DNS = 8.8.8.8
# Server: eu1.tunnelsats.com
# Port Forwarding: 34567

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
Endpoint = eu1.tunnelsats.com:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
            conf_path.write_text(good_conf, encoding="utf-8")
            conf_path.chmod(0o600)
            res_first = subprocess.run(["/bin/bash", str(reconciler), "apply"], env=env, capture_output=True, text=True)
            self.assertEqual(res_first.returncode, 0, res_first.stderr)
            log_lines = order_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("ts_before_extra", log_lines)
            self.assertNotIn("ts_after_extra", log_lines)

            # 3. Converged boot-sync performs ZERO systemctl restarts
            managed_inv.write_text(
                json.dumps({"schema": 1, "state": "installed", "profile": "mynode", "impl": "lnd", "unit": "lnd.service"}),
                encoding="utf-8",
            )
            # First apply to populate WG_CONF_DST and lnd_extra_config.conf
            res_conv1 = subprocess.run(["/bin/bash", str(reconciler), "apply"], env=env, capture_output=True, text=True)
            self.assertEqual(res_conv1.returncode, 0, res_conv1.stderr)
            lnd_main.write_text(
                "[Application Options]\nlisten=0.0.0.0:9735\nexternalhosts=eu1.tunnelsats.com:34567\n[Tor]\ntor.skip-proxy-for-clearnet-targets=true\ntor.streamisolation=false\n",
                encoding="utf-8",
            )
            order_log.write_text("", encoding="utf-8")
            res_boot = subprocess.run(["/bin/bash", str(reconciler), "boot-sync"], env=env, capture_output=True, text=True)
            self.assertEqual(res_boot.returncode, 0, res_boot.stderr)
            self.assertEqual(order_log.read_text(encoding="utf-8").strip(), "", "Expected zero restarts on converged boot-sync")

            # 4. CLI restore persists desired="tor-only" so subsequent boot-sync does not re-enable VPN
            res_rest = subprocess.run(["/bin/bash", str(reconciler), "restore"], env=env, capture_output=True, text=True)
            self.assertEqual(res_rest.returncode, 0, res_rest.stderr)
            desired_doc = json.loads((data_dir / "desired-state.json").read_text(encoding="utf-8"))
            self.assertEqual(desired_doc["desired"], "tor-only")
            self.assertNotIn("BEGIN TUNNELSATS", lnd_extra.read_text(encoding="utf-8"))

            res_boot_after_restore = subprocess.run(["/bin/bash", str(reconciler), "boot-sync"], env=env, capture_output=True, text=True)
            self.assertEqual(res_boot_after_restore.returncode, 0, res_boot_after_restore.stderr)
            self.assertNotIn("BEGIN TUNNELSATS", lnd_extra.read_text(encoding="utf-8"))

            # 5. CLI apply after restore updates desired="active" so boot-sync preserves active tunnel
            managed_inv.unlink(missing_ok=True)
            res_reapply = subprocess.run(["/bin/bash", str(reconciler), "apply"], env=env, capture_output=True, text=True)
            self.assertEqual(res_reapply.returncode, 0, res_reapply.stderr)
            self.assertEqual(json.loads((data_dir / "desired-state.json").read_text(encoding="utf-8"))["desired"], "active")

            # 6. cmd_status requires state == "installed" in managed.json
            managed_inv.write_text(json.dumps({"schema": 1, "state": "installing"}), encoding="utf-8")
            res_st_installing = subprocess.run(["/bin/bash", str(reconciler), "status"], env=env, capture_output=True, text=True)
            self.assertEqual(res_st_installing.returncode, 0)
            self.assertFalse(json.loads(res_st_installing.stdout)["managed_installed"])

            # 7. Fast-path apply fails closed before writing lnd_extra_config.conf when killswitch fails to start
            lnd_extra.write_text("", encoding="utf-8")
            managed_inv.write_text(
                json.dumps({"schema": 1, "state": "installed", "profile": "mynode", "impl": "lnd", "unit": "lnd.service"}),
                encoding="utf-8",
            )
            mock_sys_fail_ks = tmp_path / "mock_systemctl_fail_ks.sh"
            mock_sys_fail_ks.write_text(
                "#!/bin/bash\n"
                "if [ \"${1:-}\" = \"is-active\" ] && [ \"${3:-}\" = \"tunnelsats-killswitch.service\" ]; then exit 3; fi\n"
                "if [ \"${1:-}\" = \"restart\" ] && [ \"${2:-}\" = \"tunnelsats-killswitch.service\" ]; then exit 1; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            mock_sys_fail_ks.chmod(0o755)
            env_fail = dict(env)
            env_fail["SYSTEMCTL_BIN"] = str(mock_sys_fail_ks)
            res_ks_fail = subprocess.run(["/bin/bash", str(reconciler), "apply"], env=env_fail, capture_output=True, text=True)
            self.assertNotEqual(res_ks_fail.returncode, 0)
            self.assertNotIn("BEGIN TUNNELSATS", lnd_extra.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(status_out.read_text(encoding="utf-8"))["status"], "error")

            # 8. scripts/tunnelsats.sh keeps /run/tunnelsats at 0755 (never 0700)
            ts_sh_text = (REPO_ROOT / "scripts" / "tunnelsats.sh").read_text(encoding="utf-8")
            self.assertNotIn('install -d -m 0700 "$stage_dir"', ts_sh_text)
            self.assertIn('install -d -m 0755 "$stage_dir"', ts_sh_text)


if __name__ == "__main__":
    unittest.main()
