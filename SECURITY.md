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

## Dual-Mode Privilege Separation (`SECURE_MODE`)

`ts-mynode` runs its web controller (`bridge.py`) as the unprivileged `tunnelsats` Linux user bound strictly to `127.0.0.1:18739` behind myNode's nginx reverse proxy.

### Mode A: Integrated 1-Click Mode (`SECURE_MODE=false`, default)
- `pre_tunnelsats.sh` installs `/usr/local/sbin/tunnelsats-reconcile` (`root:root`, `0755`) and a dedicated sudoers drop-in (`/etc/sudoers.d/tunnelsats-reconcile`) allowing user `tunnelsats` to run only `/usr/local/sbin/tunnelsats-reconcile`.
- Reconciler invocations validate `/mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf` (`0600` permissions and strict WireGuard key/endpoint syntax) and run `tunnelsats.sh install --managed mynode --impl "${TUNNELSATS_LN_IMPL:-lnd}" --non-interactive --yes --config /mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf`.

### Mode B: Manual / CLI Mode (`SECURE_MODE=true`)
- Operators who want zero privileged execution from the web UI can enable `SECURE_MODE=true` via the dashboard toggle (`POST /api/mynode/mode`) or `/mnt/hdd/mynode/tunnelsats/config.json` (`{"secure-mode": true}`).
- When `SECURE_MODE=true` is active, `reconcile_mynode.sh` refuses `apply`, `restore`, `block-insert`, and `block-remove` with exit code `7` (`HTTP 403` from `/api/mynode/reconcile`), and `pre_tunnelsats.sh` removes `/etc/sudoers.d/tunnelsats-reconcile`.
- Operators execute dataplane changes manually over SSH:

```bash
# Apply via the root reconciler (manages lnd_extra_config.conf + tunnelsats.sh --managed mynode --impl lnd):
sudo VPN_EXTERNAL_HOST=<vpn-server-host> VPN_PORT=<port> /opt/mynode/tunnelsats/scripts/reconcile_mynode.sh apply /mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf

# Or invoke tunnelsats.sh directly (--impl lnd is required when both lnd.service and lit.service exist on myNode):
sudo /opt/mynode/tunnelsats/scripts/tunnelsats.sh install --managed mynode --impl lnd --non-interactive --yes --config /mnt/hdd/mynode/tunnelsats/tunnelsatsv2.conf

# Verify live kernel dataplane and kill-switch state:
sudo /opt/mynode/tunnelsats/scripts/tunnelsats.sh verify --json

# Restore LND to Tor-only and remove the managed dataplane:
sudo /opt/mynode/tunnelsats/scripts/reconcile_mynode.sh restore
```
