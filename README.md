# TunnelSats for myNode BTC (`ts-mynode`)

Native TunnelSats VPN application and Managed Dataplane integration for **myNode BTC** (App SDK v2, Debian 12+, LND).

TunnelSats provides dedicated WireGuard VPN tunnels with static port forwarding for Lightning Network nodes, allowing your myNode LND daemon to route hybrid Clearnet + Tor traffic safely without exposing your residential IP address.

---

## Key Features

- **In-App Server Discovery**: Browse live TunnelSats regional endpoints (`eu-de`, `eu-ch`, `us-east`, `us-west`, `ap-sg`, `ap-jp`, `sa-br`, `oc-au`) directly from the dashboard.
- **Lightning-Native Checkout & Lifecycle**:
  - Purchase new subscriptions (1, 3, 6, or 12 months) via BOLT11 Lightning invoices.
  - Automatic invoice settlement polling and `/subscription/claim` provisioning.
  - One-click subscription renewal (`POST /subscription/renew`) and $1 bandwidth top-ups (`POST /subscription/bandwidth-reset/create`).
- **NIP-47 NWC Auto-Renewal**: Connect a Nostr Wallet Connect (`nostr+walletconnect://`) wallet with per-duration budget caps and optional Tor SOCKS5h routing (`127.0.0.1:9050`) for unattended renewals within 7 days of expiry.
- **Local X25519 Key Custody**: WireGuard private keys are generated locally on your myNode device (`0600` permissions in `/mnt/hdd/mynode/tunnelsats/`) and never transmitted to TunnelSats servers. Only the derived X25519 public key is sent during `/subscription/claim`.
- **Fail-Closed Managed Dataplane (`tunnelsats.sh --managed mynode`)**:
  - Isolates `lnd.service` inside a dedicated cgroup v2 slice (`tunnelsats.slice`).
  - Enforces an independent `inet tunnelsats` nftables kill switch (`tunnelsats-killswitch.service`) that blocks clearnet leaks even when `wg-quick@tunnelsatsv2.service` is down or restarting.
  - Routes `tunnelsats.slice` packets via policy routing table `51820` (`fwmark 0x01230000/0x00ff0000`) while keeping SSH, nginx, and LAN management traffic untouched on the host default route.
  - Continuously audits kernel state and kill-switch attestation via `tunnelsats-verifier.timer`.
- **Safe Tor-Only Rollback**: Restoring or uninstalling removes the `# BEGIN TUNNELSATS` ... `# END TUNNELSATS` block from `/mnt/hdd/mynode/settings/lnd_extra_config.conf` before tearing down the managed dataplane, ensuring `mynode_gen_lnd_config.sh` regenerates a clean Tor-only `/mnt/hdd/mynode/lnd/lnd.conf` without disabling `lnd.service`.

---

## Architecture & Dual-Mode Privilege Separation

```mermaid
flowchart LR
    Browser["Operator Browser (LAN / Tor)"] -->|"HTTP :8739 / HTTPS :8740"| Nginx["myNode nginx Reverse Proxy"]
    Nginx -->|"http://127.0.0.1:18739"| Bridge["bridge.py (User=tunnelsats)"]
    Bridge -->|"Atomic 0600 writes"| Storage["/mnt/hdd/mynode/tunnelsats/"]
    Bridge -->|"HTTPS v1 API"| API["api.tunnelsats.com"]
    Bridge -->|"SECURE_MODE=false: sudo -n"| Reconciler["/usr/local/sbin/tunnelsats-reconcile (root)"]
    Reconciler -->|"block-insert / block-remove"| ExtraConf["/mnt/hdd/mynode/settings/lnd_extra_config.conf"]
    Reconciler -->|"install/uninstall --managed mynode"| Managed["tunnelsats.sh --managed mynode"]
    Managed -->|"tunnelsats.slice + nftables + wg"| LND["lnd.service (Hybrid Clearnet + Tor)"]
```

### 1. Automated 1-Click Mode (`SECURE_MODE=false`, default)

- The web controller (`bridge.py`) runs as the unprivileged `tunnelsats` Linux user bound strictly to `127.0.0.1:18739` behind myNode's nginx reverse proxy (`8739` HTTP / `8740` HTTPS).
- `/api/status` (with `/api/health` as a route alias) serves as the canonical health and operational telemetry endpoint (`200 OK` JSON status), while `/api/dashboard` returns the full UI read model.
- Validated WireGuard configurations (`tunnelsatsv2.conf`), subscription metadata (`tunnelsats-meta.json`), and NWC secrets (`nwc-wallet.json`) are stored in `/mnt/hdd/mynode/tunnelsats/` with `0600` permissions.
- When `pre_tunnelsats.sh` runs as root (`ExecStartPre=+`), it installs `/usr/local/sbin/tunnelsats-reconcile` (`root:root`, `0755`) and a tightly scoped `/etc/sudoers.d/tunnelsats-reconcile` rule permitting user `tunnelsats` to invoke only `/usr/local/sbin/tunnelsats-reconcile`.
- Applying a tunnel from the Web UI invokes `reconcile_mynode.sh apply`, which:
  1. Validates `/mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf` (`0600` permissions and strict WireGuard key/endpoint syntax).
  2. Atomically inserts/updates the `# BEGIN TUNNELSATS` ... `# END TUNNELSATS` block in `/mnt/hdd/mynode/settings/lnd_extra_config.conf`.
  3. Installs or refreshes `tunnelsats.sh install --managed mynode --impl "${TUNNELSATS_LN_IMPL:-lnd}"` (`tunnelsats.slice`, `tunnelsats-killswitch.service`, `wg-quick@tunnelsatsv2.service`, `tunnelsats-verifier.timer`) and restarts `lnd.service`.

### 2. Manual / CLI Mode (`SECURE_MODE=true`)

- Operators who prefer zero privileged helper execution from the web service can enable `SECURE_MODE=true` via the dashboard toggle or `/mnt/hdd/mynode/tunnelsats/config.json` (`{"secure-mode": true}`).
- In Manual Mode, `reconcile_mynode.sh` refuses automated `apply`/`restore` actions and `pre_tunnelsats.sh` removes `/etc/sudoers.d/tunnelsats-reconcile`.
- The Web UI continues to handle server discovery, BOLT11 checkout, claim, renewal, bandwidth top-ups, NWC auto-renewal, and `.conf` staging at `/mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf`, while presenting exact copy-paste one-liner CLI commands for SSH execution:

```bash
# Apply TunnelSats managed dataplane and LND hybrid config over SSH (via reconciler):
sudo VPN_EXTERNAL_HOST=<vpn-server-host> VPN_PORT=<port> /opt/mynode/tunnelsats/scripts/reconcile_mynode.sh apply /mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf

# Or invoke tunnelsats.sh directly (pass --impl lnd to disambiguate when both lnd.service and lit.service exist on myNode):
sudo /opt/mynode/tunnelsats/scripts/tunnelsats.sh install --managed mynode --impl lnd --non-interactive --yes --config /mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf

# Verify live kernel dataplane and kill-switch attestation:
sudo /opt/mynode/tunnelsats/scripts/tunnelsats.sh verify --json

# Restore LND to Tor-only and remove managed dataplane:
sudo /opt/mynode/tunnelsats/scripts/reconcile_mynode.sh restore
```

---

## Sideloading on a myNode Device

### Option A: Using `scripts/deploy_mynode.sh` (from this repository)

```bash
# Deploy and install TunnelSats onto a running myNode VM/device over SSH:
./scripts/deploy_mynode.sh <MYNODE_IP> admin

# Uninstall TunnelSats cleanly on the myNode VM/device:
sudo mynode-manage-apps uninstall tunnelsats
```

### Option B: Using `mynodebtc/mynode` App SDK v2 (`app_sdk/create.py`)

If you have a checkout of `mynodebtc/mynode`:

```bash
cp -r mynode_app/tunnelsats /path/to/mynode/rootfs/standard/usr/share/mynode_apps/
cd /path/to/mynode
./app_sdk/create.py check tunnelsats
./app_sdk/create.py push tunnelsats <mynode_ip> --reinstall
```

---

## Upstream `mynodebtc/mynode` Marketplace Submission

1. Tag and release a new version in `Tunnelsats/ts-mynode` (e.g., `v0.1.0`).
2. Copy `mynode_app/tunnelsats/` to `rootfs/standard/usr/share/mynode_apps/tunnelsats/` in your `mynodebtc/mynode` fork and add `tunnelsats` to `MARKETPLACE_APPS` in `scripts/print_app_download_hashes.sh`.
3. Run `scripts/print_app_download_hashes.sh tunnelsats` in `mynodebtc/mynode` and update `download_source_sha256` in `tunnelsats.json`.
4. Verify with `./app_sdk/create.py check tunnelsats` and open a Pull Request to `mynodebtc/mynode`.

---

## License

Released under the [MIT License](LICENSE).
