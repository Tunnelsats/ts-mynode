#!/usr/bin/env python3
"""Standalone linter for mynode_app/tunnelsats implementing all checks from
mynodebtc/mynode's app_sdk/create.py check tunnelsats plus repository hygiene."""

import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_APP_DIR = os.path.join(REPO_ROOT, "mynode_app", "tunnelsats")
PORT_MAPPING_RE = re.compile(r"((?:\d{1,3}(?:\.\d{1,3}){3}:)?\d+:\d+(?:/[a-z]+)?)")
SHA256_PIN_RE = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\s+[0-9a-fA-F]{64}$")


def to_port(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_internal_port(app_data):
    if "internal_port" in app_data:
        return to_port(app_data["internal_port"])
    http_port = to_port(app_data.get("http_port"))
    return http_port + 10000 if http_port is not None else None


def get_public_ports(app_data):
    ports = [app_data.get("http_port"), app_data.get("https_port")] + list(app_data.get("extra_ports") or [])
    return [to_port(p) for p in ports if to_port(p) is not None]


def find_docker_publishes(app_dir):
    found = []
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if not name.endswith((".service", ".sh", ".yml", ".yaml")):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.read().split("\n")
            except (UnicodeDecodeError, OSError):
                continue
            for line in lines:
                if line.lstrip().startswith("#"):
                    continue
                for m in re.finditer(r'(?:--publish|-p)[ =]["\']?' + PORT_MAPPING_RE.pattern, line):
                    found.append((os.path.relpath(path, app_dir), m.group(1)))
                if name.endswith((".yml", ".yaml")):
                    m = re.match(r'\s*-\s*["\']?' + PORT_MAPPING_RE.pattern + r'["\']?\s*$', line)
                    if m:
                        found.append((os.path.relpath(path, app_dir), m.group(1)))
    return found


def check_app_ports(short_name, app_dir, app_data):
    errors = []
    warnings = []
    internal_port = get_internal_port(app_data)
    public_ports = get_public_ports(app_data)

    for path, mapping in find_docker_publishes(app_dir):
        parts = mapping.split("/")[0].split(":")
        if len(parts) == 2:
            errors.append(
                f"{path} publishes port {parts[0]} on all interfaces; publish it on 127.0.0.1:{internal_port}"
            )
        elif parts[0] != "127.0.0.1":
            errors.append(f"{path} publishes port {parts[1]} on {parts[0]}; publish it on 127.0.0.1")
        elif internal_port is None:
            errors.append(f"{path} publishes 127.0.0.1:{parts[1]} but internal_port is not set")
        elif int(parts[1]) != internal_port:
            errors.append(f"{path} publishes 127.0.0.1:{parts[1]} but internal_port is {internal_port}")

    nginx_file = f"nginx/https_{short_name}.conf"
    nginx_path = os.path.join(app_dir, nginx_file)
    try:
        with open(nginx_path, "r", encoding="utf-8") as f:
            nginx_conf = f.read()
    except OSError:
        nginx_conf = ""
        errors.append(f"Missing required file: {nginx_file}")

    nginx_ports = [int(p) for p in re.findall(r"^\s*listen\s+(?:\S+:)?(\d+)", nginx_conf, re.M)]
    if not nginx_ports:
        errors.append(f"{nginx_file} does not define any listen ports")
    for port in nginx_ports:
        if port not in public_ports:
            errors.append(f"{nginx_file} listens on {port}, which is not http_port, https_port or in extra_ports")
    for expected_port in public_ports:
        if expected_port not in nginx_ports:
            errors.append(f"{nginx_file} does not listen on declared port {expected_port}")

    proxied_ports = sorted(
        set(re.findall(r"proxy_pass\s+https?://(?:127\.0\.0\.1|localhost):(\d+)", nginx_conf))
    )
    if not proxied_ports:
        errors.append(f"{nginx_file} does not proxy_pass to 127.0.0.1:{internal_port}")
    for port_str in proxied_ports:
        port = int(port_str)
        if internal_port is None or port == internal_port or port in nginx_ports:
            continue
        errors.append(f"{nginx_file} proxies to port {port}, not internal_port {internal_port}")

    service_file = f"{short_name}.service"
    service_path = os.path.join(app_dir, service_file)
    try:
        with open(service_path, "r", encoding="utf-8") as f:
            service_src = f.read()
    except OSError:
        service_src = ""
        errors.append(f"Missing required file: {service_file}")

    if service_src:
        if f"--host 127.0.0.1 --port {internal_port}" not in service_src:
            errors.append(
                f"{service_file} ExecStart must bind strictly to --host 127.0.0.1 --port {internal_port}"
            )
        if f"User={app_data.get('linux_user', short_name)}" not in service_src:
            errors.append(f"{service_file} must set User={app_data.get('linux_user', short_name)}")
        if "ExecStartPre=+" not in service_src:
            errors.append(f"{service_file} must run pre_{short_name}.sh with ExecStartPre=+ root prefix")

    return errors, warnings


def check_mynode_app(app_dir=DEFAULT_APP_DIR, short_name="tunnelsats", strict_warnings=True):
    errors = []
    warnings = []

    if not os.path.isdir(app_dir):
        return [f"No app directory found at {app_dir}"], warnings

    json_path = os.path.join(app_dir, f"{short_name}.json")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            app_data = json.load(f)
    except OSError:
        return [f"Missing required file: {short_name}.json"], warnings
    except ValueError as e:
        return [f"{short_name}.json is not valid JSON: {e}"], warnings

    if app_data.get("short_name") != short_name:
        errors.append(f'short_name in {short_name}.json must be "{short_name}"')
    if app_data.get("sdk_version") != 2:
        errors.append(f"sdk_version in {short_name}.json must be 2")
    if app_data.get("app_type") != "custom":
        errors.append(f'app_type in {short_name}.json must be "custom"')
    if app_data.get("http_port") != 8739 or app_data.get("https_port") != 8740 or app_data.get("internal_port") != 18739:
        errors.append(f"{short_name}.json must declare http_port=8739, https_port=8740, internal_port=18739")

    required_files = [
        f"{short_name}.png",
        f"{short_name}.service",
        f"nginx/https_{short_name}.conf",
        f"scripts/install_{short_name}.sh",
        f"scripts/pre_{short_name}.sh",
        f"scripts/post_{short_name}.sh",
        f"scripts/uninstall_{short_name}.sh",
        f"www/python/{short_name}.py",
        f"www/templates/{short_name}.html",
        "screenshots/1.png",
    ]
    for rel_path in required_files:
        if not os.path.isfile(os.path.join(app_dir, rel_path)):
            errors.append(f"Missing required file: {rel_path}")

    for root, dirs, files in os.walk(app_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "FILL_IN" in content:
                    msg = f"Placeholder FILL_IN value in {os.path.relpath(path, app_dir)}"
                    if strict_warnings:
                        errors.append(msg)
                    else:
                        warnings.append(msg)
            except (UnicodeDecodeError, OSError):
                pass

    if not app_data.get("download_skip", False) and app_data.get("download_type", "source") == "source":
        pinned = app_data.get("download_source_sha256", "")
        if not pinned or not SHA256_PIN_RE.match(pinned):
            errors.append("download_source_sha256 must match '<version> <64-char-hex-sha256>'")
        elif pinned.split()[0] != app_data.get("latest_version"):
            errors.append("download_source_sha256 version prefix does not match latest_version")

    port_errors, port_warnings = check_app_ports(short_name, app_dir, app_data)
    errors.extend(port_errors)
    if strict_warnings:
        errors.extend(port_warnings)
    else:
        warnings.extend(port_warnings)

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Validate myNode App SDK v2 package")
    parser.add_argument("--app-dir", default=DEFAULT_APP_DIR, help="Path to mynode_app/tunnelsats")
    parser.add_argument("--short-name", default="tunnelsats", help="Application short_name")
    args = parser.parse_args()

    errors, warnings = check_mynode_app(app_dir=args.app_dir, short_name=args.short_name)
    for w in warnings:
        print(f"Warning: {w}")
    for e in errors:
        print(f"Error: {e}")
    if errors:
        sys.exit(1)
    print(f"{args.short_name} looks good!")


if __name__ == "__main__":
    main()
