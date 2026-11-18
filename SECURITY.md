# Security Policy

## Reporting a Vulnerability

We take the security of TunnelSats seriously. If you discover a potential vulnerability, we encourage you to report it to us responsibly.

**How to Report a Vulnerability:**

Please use one of the following methods to report a security vulnerability:

* **Email:** Send an email to security at tunnelsats.com .
* **Telegram:** Join our Telegram channel (link on our homepage, available via Tor and Clearnet) and send a direct message to an administrator.
* **X (Twitter):** Send a direct message to [@TunnelSats](https://x.com/TunnelSats).
* **Nostr:** Send a direct message to [TunnelSats on Nostr](https://snort.social/p/npub1n9z4y3xjramqes8fp9rl96x5e4nl0hff57ynw7vqnjpq370tq78sljsp8y).

**What to Include in Your Report:**

To help us investigate and address the vulnerability effectively, please include the following information in your report:

* A clear description of the vulnerability.
* Steps to reproduce the vulnerability.
* The potential impact of the vulnerability.
* The affected version(s) of TunnelSats.
* Your contact information (if you wish to be contacted).

**Our Commitment:**

* We will acknowledge receipt of your report within 5 business days.
* We will investigate the reported vulnerability and take appropriate action to address it.
* We appreciate responsible disclosure and will work with you to resolve the issue.

**Supported Versions:**

As TunnelSats is under active development, we are committed to addressing security vulnerabilities in the latest releases. Older versions may not receive security updates.

* Latest Main Branch: Supported (Security updates will be applied)
* Previous Releases: Limited (Security updates are not guaranteed)

**Important Notes:**

* Please do not publicly disclose the vulnerability until we have had a chance to address it.
* We appreciate your cooperation in helping us keep TunnelSats secure.
* Please check the main page of the TunnelSats repository for the most up to date contact information.

---

## Zero-Sudo Privilege Separation & Dual Execution Modes

`ts-mynode` runs its web controller (`bridge.py`) as the unprivileged `tunnelsats` Linux user bound strictly to `127.0.0.1:18739` behind myNode's authenticated nginx reverse proxy (`mynode_session_auth.conf` + `auth_request /mynode_auth_check`). The `tunnelsats` user has **no `sudo` rules** and never executes root privileges directly.

All privileged host dataplane scripts (`reconcile_mynode.sh` and `tunnelsats.sh`) live in the root-owned myNode package directory (`/usr/share/mynode_apps/tunnelsats/root_scripts/`, installed to `/usr/local/sbin/tunnelsats-reconcile` and `/usr/local/sbin/tunnelsats` with `root:root` `0755` permissions). Root never executes scripts from `/opt/mynode/tunnelsats` or honors caller environment overrides.

### Mode A: Integrated Mode (`SECURE_MODE=false`, default)
- The web controller validates WireGuard configurations against a strict key allowlist (rejecting `PreUp`, `PostUp`, `PreDown`, `PostDown`, `SaveConfig`, `Table`, `FwMark`, and `ListenPort`) and writes `/mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf` (`0600`) plus `/mnt/hdd/mynode/tunnelsats/desired-state.json` (`0600`).
- When the root reconciler runs (on `tunnelsats.service` start/restart via `ExecStartPre=+` `boot-sync` or via a host root trigger), `/usr/local/sbin/tunnelsats-reconcile` snapshots and re-validates `tunnelsatsv2.conf`, renders `/etc/wireguard/tunnelsatsv2.conf` from validated scalar fields only, arms `tunnelsats.slice` + `tunnelsats-killswitch.service` first, and converges `/mnt/hdd/mynode/settings/lnd_extra_config.conf` without unnecessary `lnd.service` restarts.

### Mode B: Secure Manual CLI Mode (`SECURE_MODE=true`)
- Operators can enable `SECURE_MODE=true` from the dashboard toggle (`POST /api/mynode/mode`) or lock Mode B permanently as `root` on the host so the web service cannot re-enable Mode A:
  ```bash
  sudo /usr/local/sbin/tunnelsats-reconcile enable-secure-mode
  ```
- When `SECURE_MODE=true` (or `/etc/tunnelsats/secure_mode`) is active, `tunnelsats-reconcile` refuses automated `apply`, `restore`, `sync`, `block-insert`, and `block-remove` operations with exit code `7`.
- Operators execute dataplane changes manually over SSH using the root-owned binaries:

```bash
# Apply via the root-owned reconciler (arms tunnelsats.slice + kill switch first, then updates lnd_extra_config.conf):
sudo /usr/local/sbin/tunnelsats-reconcile apply

# Or invoke the root-owned tunnelsats CLI directly:
sudo /usr/local/sbin/tunnelsats install --managed mynode --impl lnd --non-interactive --yes --config /mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf

# Verify live kernel dataplane and kill-switch state:
sudo /usr/local/sbin/tunnelsats verify --json

# Restore LND to Tor-only and remove the managed dataplane:
sudo /usr/local/sbin/tunnelsats-reconcile restore
```
