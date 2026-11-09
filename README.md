<p align="center">
  <img src="https://raw.githubusercontent.com/Tunnelsats/tunnelsats/ffb4732328045922dc90eb5580654077e8d3f246/images/brand/logos/ts_logo_rectangle.svg" alt="TunnelSats Logo" width="400"/>
</p>

<h3 align="center">Clearnet Lightning Over Encrypted VPN for myNode BTC</h3>

<p align="center">
  <a href="https://github.com/Tunnelsats/ts-mynode/actions/workflows/test.yml"><img src="https://github.com/Tunnelsats/ts-mynode/actions/workflows/test.yml/badge.svg" alt="Tests"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"/></a>
  <img src="https://img.shields.io/badge/For%20myNode%20BTC-App%20SDK%20v2-0EA5E9.svg" alt="For myNode BTC"/>
  <a href="https://tunnelsats.com/join-telegram"><img src="https://img.shields.io/badge/Telegram-Community-26A5E4?logo=telegram" alt="Telegram Community"/></a>
</p>

---

# TunnelSats for myNode BTC (`ts-mynode`)

Native TunnelSats application, **MyNode UI**, and Managed Dataplane integration for **myNode BTC** (App SDK v2, Debian 12+, LND).

TunnelSats provides dedicated WireGuard VPN tunnels with static port forwarding for Lightning Network nodes, allowing your myNode LND daemon (`lnd.service`) to route hybrid Clearnet + Tor traffic safely without exposing your residential IP address.

---

## Quick Install on myNode

Until the TunnelSats marketplace package is merged into the upstream `mynodebtc/mynode` App Store, you can install or update TunnelSats on any running myNode device in one step from your workstation:

```bash
git clone https://github.com/Tunnelsats/ts-mynode.git
cd ts-mynode
./scripts/deploy_mynode.sh <MYNODE_IP> admin
```

- **Open the MyNode UI**: Navigate to `https://mynode.local:8740` (or `http://<MYNODE_IP>:8739`), or open `https://mynode.local/app/tunnelsats/info` on your myNode dashboard.
- **Back up your config before uninstalling**: Use the **Backup .conf** button in the top header of the MyNode UI to download a copy of your `tunnelsatsv2.conf` (containing your WireGuard private key) before uninstalling or reflashing your device.
- **Uninstall**: Run `sudo mynode-manage-apps uninstall tunnelsats` on your myNode device (or click **Uninstall** on `/app/tunnelsats/info`).

---

## Key Features

- **In-App Server Discovery**: Browse live TunnelSats regional endpoints (`eu-de`, `eu-ch`, `us-east`, `us-west`, `ap-sg`, `ap-jp`, `sa-br`, `oc-au`) directly from the MyNode UI.
- **Lightning-Native Checkout & Lifecycle**:
  - Purchase new subscriptions (1, 3, 6, or 12 months) via BOLT11 Lightning invoices.
  - Automatic invoice settlement polling and `/subscription/claim` provisioning.
  - One-click subscription renewal (`POST /subscription/renew`) and $1 bandwidth top-ups (`POST /subscription/bandwidth-reset/create`).
- **NIP-47 NWC Auto-Renewal**: Connect a Nostr Wallet Connect (`nostr+walletconnect://`) wallet with per-duration budget caps and optional Tor SOCKS5h routing (`127.0.0.1:9050`) for unattended renewals within 7 days of expiry.
- **Local X25519 Key Custody & 1-Click Backup**: WireGuard private keys are generated locally on your myNode device (`0600` permissions in `/mnt/hdd/mynode/tunnelsats/`) and never transmitted to TunnelSats servers. Only the derived X25519 public key is sent during `/subscription/claim`. Export your `.conf` anytime via the **Backup .conf** button.
- **Fail-Closed Managed Dataplane (`tunnelsats.sh --managed mynode`)**:
  - Isolates `lnd.service` inside a dedicated cgroup v2 slice (`tunnelsats.slice`).
  - Enforces an independent `inet tunnelsats` nftables kill switch (`tunnelsats-killswitch.service`) that blocks clearnet leaks even when `wg-quick@tunnelsatsv2.service` is down or restarting.
  - Routes `tunnelsats.slice` packets via policy routing table `51820` while keeping SSH, nginx, and LAN management traffic untouched on the host default route.
  - Continuously audits kernel state and kill-switch attestation via `tunnelsats-verifier.timer`.
- **Safe Tor-Only Rollback**: Restoring or uninstalling removes the `# BEGIN TUNNELSATS` ... `# END TUNNELSATS` block from `/mnt/hdd/mynode/settings/lnd_extra_config.conf` before tearing down the managed dataplane, ensuring `mynode_gen_lnd_config.sh` regenerates a clean Tor-only `/mnt/hdd/mynode/lnd/lnd.conf` without disabling `lnd.service`.

---

## Architecture & Zero-Sudo Privilege Separation

```mermaid
flowchart LR
    Browser["Operator Browser (LAN / Tor)"] -->|"HTTPS :8740 (mynode_session_auth)"| Nginx["myNode nginx Reverse Proxy"]
    Nginx -->|"http://127.0.0.1:18739"| Bridge["bridge.py (User=tunnelsats, zero sudo)"]
    Bridge -->|"Atomic 0600 writes"| Storage["/mnt/hdd/mynode/tunnelsats/ (desired-state.json)"]
    Bridge -->|"HTTPS v1 API"| API["api.tunnelsats.com"]
    Storage -->|"Snapshot + strict allowlist"| Reconciler["/usr/local/sbin/tunnelsats-reconcile (root:root)"]
    Reconciler -->|"install/uninstall --managed mynode"| Managed["/usr/local/sbin/tunnelsats (root:root)"]
    Reconciler -->|"block-insert / block-remove"| ExtraConf["/mnt/hdd/mynode/settings/lnd_extra_config.conf"]
    Managed -->|"tunnelsats.slice + nftables + wg"| LND["lnd.service (Hybrid Clearnet + Tor)"]
```

### 1. Mode A: Integrated Mode (`SECURE_MODE=false`, default)

- The web controller (`bridge.py`) runs as the unprivileged `tunnelsats` Linux user (with zero `sudo` rules) bound strictly to `127.0.0.1:18739` behind myNode's session-authenticated nginx reverse proxy (`8740` HTTPS, `8739` HTTP -> HTTPS redirect).
- `/api/status` (with `/api/health` as a route alias) serves as the canonical health and operational telemetry endpoint (`200 OK` JSON status), while `/api/dashboard` returns the full MyNode UI read model.
- Validated WireGuard configurations (`tunnelsatsv2.conf`), desired-state manifests (`desired-state.json`), subscription metadata (`tunnelsats-meta.json`), and NWC secrets (`nwc-wallet.json`) are stored in `/mnt/hdd/mynode/tunnelsats/` with `0600` permissions.
- When `pre_tunnelsats.sh` runs as root (`ExecStartPre=+`), it installs `/usr/local/sbin/tunnelsats` and `/usr/local/sbin/tunnelsats-reconcile` (`root:root`, `0755`) exclusively from the root-owned package directory `/usr/share/mynode_apps/tunnelsats/root_scripts/` and executes an idempotent `boot-sync` convergence pass (zero `lnd.service` restarts when already converged).
- Applying a tunnel via the root reconciler (`/usr/local/sbin/tunnelsats-reconcile`):
  1. Snapshots and validates `/mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf` (`0600`, strict WireGuard key allowlist; all `wg-quick` hook directives rejected).
  2. Arms or refreshes `tunnelsats` (`tunnelsats.slice`, `tunnelsats-killswitch.service`, `wg-quick@tunnelsatsv2.service`, `tunnelsats-verifier.timer`) first so LND is protected before hybrid clearnet settings are enabled.
  3. Atomically converges the `# BEGIN TUNNELSATS` ... `# END TUNNELSATS` block in `/mnt/hdd/mynode/settings/lnd_extra_config.conf` and restarts `lnd.service` only when configuration or slice state actually changes.

### 2. Mode B: Secure Manual CLI Mode (`SECURE_MODE=true`)

- Operators who prefer manual-only host changes can enable `SECURE_MODE=true` via the MyNode UI toggle or lock Mode B permanently on the host via `sudo /usr/local/sbin/tunnelsats-reconcile enable-secure-mode` (`/etc/tunnelsats/secure_mode`).
- In Mode B, `tunnelsats-reconcile` refuses automated `apply`/`restore`/`sync` actions.
- The MyNode UI continues to handle server discovery, BOLT11 checkout, claim, renewal, bandwidth top-ups, NWC auto-renewal, `.conf` backup, and `.conf` staging at `/mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf`, while presenting exact copy-paste one-liner CLI commands for SSH execution:

```bash
# Apply TunnelSats managed dataplane and LND hybrid config over SSH (root-owned reconciler):
sudo /usr/local/sbin/tunnelsats-reconcile apply

# Or invoke the root-owned tunnelsats CLI directly:
sudo /usr/local/sbin/tunnelsats install --managed mynode --impl lnd --non-interactive --yes --config /mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf

# Verify live kernel dataplane and kill-switch attestation:
sudo /usr/local/sbin/tunnelsats verify --json

# Restore LND to Tor-only and remove managed dataplane:
sudo /usr/local/sbin/tunnelsats-reconcile restore
```

---

## Upstream `mynodebtc/mynode` Marketplace Submission

1. Tag and release a new version in `Tunnelsats/ts-mynode` (e.g., `v1.0.0`).
2. Copy `mynode_app/tunnelsats/` to `rootfs/standard/usr/share/mynode_apps/tunnelsats/` in your `mynodebtc/mynode` fork and add `tunnelsats` to `MARKETPLACE_APPS` in `scripts/print_app_download_hashes.sh`.
3. Run `scripts/print_app_download_hashes.sh tunnelsats` in `mynodebtc/mynode` and update `download_source_sha256` in `tunnelsats.json`.
4. Verify with `./app_sdk/create.py check tunnelsats` and open a Pull Request to `mynodebtc/mynode`.

---

## License

Released under the [MIT License](LICENSE).

<sub>myNode is a trademark of MyNode LLC. TunnelSats is an independent integration built for myNode BTC.</sub>
