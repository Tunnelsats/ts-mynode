# TunnelSats Developer Guide (myNode App SDK v2)

This guide covers the repository layout, local testing, version management, and upstream `mynodebtc/mynode` promotion workflow for `ts-mynode`.

## Directory Layout

| Path | Purpose |
| :--- | :--- |
| `bridge.py` | Unprivileged Python HTTP controller (`127.0.0.1:18739`), v1 API client, settlement engine, and NIP-47 NWC auto-renewer. |
| `web/` | Static frontend dashboard (Server picker, BOLT11 checkout, NWC settings, Dual-Mode toggle, Verify/CLI guide). |
| `scripts/reconcile_mynode.sh` | Root reconciler managing `/mnt/hdd/mynode/settings/lnd_extra_config.conf` and `tunnelsats.sh --managed mynode`. |
| `scripts/tunnelsats.sh` | Bundled TunnelSats Managed Dataplane engine supporting the `mynode` profile (`lnd.service` inside `tunnelsats.slice`). |
| `scripts/check_mynode_app.py` | Standalone linter enforcing all `mynodebtc/mynode` `app_sdk/create.py check tunnelsats` rules. |
| `scripts/bump_version.py` | Transactional version bumper keeping `version.json`, `mynode_app/tunnelsats/tunnelsats.json`, `bridge.py`, and `CHANGELOG.md` synchronized. |
| `scripts/deploy_mynode.sh` | Sideloading helper to push and install `mynode_app/tunnelsats` and application source onto a myNode test device over SSH. |
| `scripts/test.sh` | Unified test runner executing Python unit tests, MyNode SDK validation, BATS reconciler tests, and ShellCheck. |
| `mynode_app/tunnelsats/` | Canonical myNode App SDK v2 package (`tunnelsats.json`, `tunnelsats.service`, `nginx/`, `scripts/`, `www/`, `screenshots/`). |
| `tests/` | Unit and integration test suites (`test_bridge.py`, `test_mynode_sdk.py`, `reconcile_mynode.bats`). |

---

## Running the Local Test Suite

Run all verification suites before committing:

```bash
# Run the complete test suite (Python unit tests + SDK linter + BATS):
./scripts/test.sh

# Or run individual suites directly:
python3 -m unittest discover -s tests -p "test_*.py" -v
python3 scripts/check_mynode_app.py
npx -y bats tests/*.bats
```

---

## Version Bumping (`scripts/bump_version.py`)

Canonical version strings are synchronized across:
1. `version.json` (`"version": "X.Y.Z"`, `"semver": "X.Y.Z"`)
2. `mynode_app/tunnelsats/tunnelsats.json` (`"latest_version": "vX.Y.Z"` and `"download_source_sha256": "vX.Y.Z <sha256>"`)
3. `CHANGELOG.md` (`## [vX.Y.Z] - YYYY-MM-DD`)

To bump the version atomically:

```bash
python3 scripts/bump_version.py 0.2.0 --notes "Add new feature or fix"
```

---

## MyNode App SDK v2 Validation (`scripts/check_mynode_app.py`)

`scripts/check_mynode_app.py` implements all checks from `mynodebtc/mynode`'s `app_sdk/create.py check tunnelsats`:
- Validates `mynode_app/tunnelsats/tunnelsats.json` schema, port assignments (`http_port: 8739`, `https_port: 8740`, `internal_port: 18739`), and `download_source_sha256` pin format (`<latest_version> <64-hex-sha256>`).
- Verifies required files (`tunnelsats.png`, `tunnelsats.service`, `nginx/https_tunnelsats.conf`, `scripts/install_tunnelsats.sh`, `scripts/pre_tunnelsats.sh`, `scripts/post_tunnelsats.sh`, `scripts/uninstall_tunnelsats.sh`, `www/python/tunnelsats.py`, `www/templates/tunnelsats.html`, `screenshots/1.png`).
- Ensures zero `FILL_IN` placeholders exist anywhere under `mynode_app/tunnelsats/`.
- Verifies `nginx/https_tunnelsats.conf` listens only on `8739` and `8740` and proxies strictly to `http://127.0.0.1:18739`.
- Verifies `tunnelsats.service` binds strictly to `127.0.0.1:18739`.

---

## Promoting a Release to `mynodebtc/mynode`

1. Push a signed git tag `vX.Y.Z` to `Tunnelsats/ts-mynode`.
2. `.github/workflows/release.yml` automatically verifies that the tag matches `tunnelsats.json` `latest_version`, computes the SHA-256 of the GitHub source archive (`https://github.com/Tunnelsats/ts-mynode/archive/refs/tags/vX.Y.Z.tar.gz`), and publishes the exact `download_source_sha256` pin in the GitHub Release notes.
3. In your `mynodebtc/mynode` checkout:
   - Sync `mynode_app/tunnelsats/` into `rootfs/standard/usr/share/mynode_apps/tunnelsats/`.
   - Ensure `tunnelsats` is listed in `MARKETPLACE_APPS` inside `scripts/print_app_download_hashes.sh`.
   - Run `./scripts/print_app_download_hashes.sh tunnelsats` and paste the `<version> <sha256>` value into `rootfs/standard/usr/share/mynode_apps/tunnelsats/tunnelsats.json`.
   - Run `./app_sdk/create.py check tunnelsats` and `./app_sdk/create.py check_doc`.
4. Open a PR to `mynodebtc/mynode`.
