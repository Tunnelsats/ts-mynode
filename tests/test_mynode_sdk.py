#!/usr/bin/env python3
"""Unit tests for the MyNode App SDK v2 package structure, version bumper, and repo hygiene."""

import json
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


if __name__ == "__main__":
    unittest.main()
