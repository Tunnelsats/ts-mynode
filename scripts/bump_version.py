#!/usr/bin/env python3
"""Transactional version bumper for ts-mynode."""

import argparse
from datetime import datetime, timezone
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_JSON_PATH = os.path.join(REPO_ROOT, "version.json")
MYNODE_JSON_PATH = os.path.join(REPO_ROOT, "mynode_app", "tunnelsats", "tunnelsats.json")
CHANGELOG_PATH = os.path.join(REPO_ROOT, "CHANGELOG.md")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def bump_version(raw_version, notes="", sha256=None):
    semver = raw_version.lstrip("v").strip()
    if not SEMVER_RE.match(semver):
        raise ValueError(f"Invalid semantic version: {raw_version}")
    tag_version = f"v{semver}"

    with open(VERSION_JSON_PATH, "r", encoding="utf-8") as f:
        version_doc = json.load(f)
    version_doc["version"] = semver
    version_doc["semver"] = semver

    with open(MYNODE_JSON_PATH, "r", encoding="utf-8") as f:
        mynode_doc = json.load(f)
    old_pin = mynode_doc.get("download_source_sha256", "")
    old_parts = old_pin.split()
    pin_hash = sha256 or (old_parts[1] if len(old_parts) == 2 else "0" * 64)
    mynode_doc["latest_version"] = tag_version
    mynode_doc["download_source_sha256"] = f"{tag_version} {pin_hash}"

    with open(VERSION_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(version_doc, f, indent=2)
        f.write("\n")

    with open(MYNODE_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(mynode_doc, f, indent=4)
        f.write("\n")

    if notes and os.path.isfile(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
            changelog = f.read()
        header = f"## [{tag_version}] - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        if f"## [{tag_version}]" not in changelog:
            entry = f"{header}\n\n- {notes.strip()}\n\n"
            idx = changelog.find("## [")
            if idx != -1:
                changelog = changelog[:idx] + entry + changelog[idx:]
            else:
                changelog = changelog.rstrip() + "\n\n" + entry
            with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
                f.write(changelog)


def main():
    parser = argparse.ArgumentParser(description="Bump ts-mynode version across all manifests")
    parser.add_argument("version", help="New semantic version (e.g. 0.2.0 or v0.2.0)")
    parser.add_argument("--notes", default="", help="Single-line release note summary")
    parser.add_argument("--sha256", default=None, help="Optional 64-char hex source tarball SHA-256")
    args = parser.parse_args()

    try:
        bump_version(args.version, notes=args.notes, sha256=args.sha256)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Synchronized version v{args.version.lstrip('v')}")


if __name__ == "__main__":
    main()
