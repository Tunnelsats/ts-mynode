# Changelog

All notable changes to the TunnelSats myNode application are documented in this file.

## [v0.1.0] - 2026-10-23

- Initial release of the native TunnelSats VPN app (`ts-mynode`) for myNode BTC (App SDK v2).
- Dual-mode architecture supporting 1-click Automated Mode (`SECURE_MODE=false`) via root reconciler (`scripts/reconcile_mynode.sh`) and Manual CLI Mode (`SECURE_MODE=true`).
- Managed dataplane integration (`tunnelsats.sh --managed mynode`) isolating `lnd.service` inside `tunnelsats.slice` with fail-closed `inet tunnelsats` nftables kill switch and policy routing (`table 51820`).
- Atomic management of `# BEGIN TUNNELSATS` ... `# END TUNNELSATS` hybrid settings block in `/mnt/hdd/mynode/settings/lnd_extra_config.conf`.
- In-app server region discovery, BOLT11 Lightning purchase/claim/renewal, $1 bandwidth top-ups, NIP-47 NWC auto-renewal, and local X25519 key custody.
