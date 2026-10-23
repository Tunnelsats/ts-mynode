#!/bin/bash
# Root Reconciler for TunnelSats on myNode BTC
# Manages /mnt/hdd/mynode/settings/lnd_extra_config.conf (# BEGIN TUNNELSATS ... # END TUNNELSATS)
# and orchestrates tunnelsats.sh --managed mynode.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUNNELSATS_DATA_DIR="${TUNNELSATS_DATA_DIR:-/mnt/hdd/mynode/tunnelsats}"
TUNNELSATS_CONF_PATH="${TUNNELSATS_CONF_PATH:-${TUNNELSATS_DATA_DIR}/tunnelsatsv2.conf}"
TUNNELSATS_APP_CONFIG="${TUNNELSATS_APP_CONFIG:-${TUNNELSATS_DATA_DIR}/config.json}"
MYNODE_SETTINGS_DIR="${MYNODE_SETTINGS_DIR:-/mnt/hdd/mynode/settings}"
LND_EXTRA_CONFIG="${LND_EXTRA_CONFIG:-${MYNODE_LND_EXTRA_CONF:-${MYNODE_SETTINGS_DIR}/lnd_extra_config.conf}}"
LND_MAIN_CONFIG="${LND_MAIN_CONFIG:-${MYNODE_LND_CONF:-/mnt/hdd/mynode/lnd/lnd.conf}}"
MYNODE_GEN_LND_CONFIG="${MYNODE_GEN_LND_CONFIG:-/usr/bin/mynode_gen_lnd_config.sh}"
WG_DIR="${WG_DIR:-/etc/wireguard}"
WG_CONF_DST="${WG_CONF_DST:-${WG_DIR}/tunnelsatsv2.conf}"
MANAGED_INVENTORY="${MANAGED_INVENTORY:-/etc/tunnelsats/managed.json}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-systemctl}"
SUDOERS_FILE="${SUDOERS_FILE:-/etc/sudoers.d/tunnelsats-reconcile}"
RECONCILE_SBIN="${RECONCILE_SBIN:-/usr/local/sbin/tunnelsats-reconcile}"

resolve_ts_sh_bin() {
    if [ -n "${TS_SH_BIN:-}" ]; then
        printf '%s\n' "$TS_SH_BIN"
        return 0
    fi
    if [ -n "${TUNNELSATS_SH:-}" ]; then
        printf '%s\n' "$TUNNELSATS_SH"
        return 0
    fi
    if [ -x "${SCRIPT_DIR}/tunnelsats.sh" ]; then
        printf '%s\n' "${SCRIPT_DIR}/tunnelsats.sh"
        return 0
    fi
    if [ -x "/opt/mynode/tunnelsats/scripts/tunnelsats.sh" ]; then
        printf '%s\n' "/opt/mynode/tunnelsats/scripts/tunnelsats.sh"
        return 0
    fi
    if [ -x "/usr/local/sbin/tunnelsats" ]; then
        printf '%s\n' "/usr/local/sbin/tunnelsats"
        return 0
    fi
    printf '%s\n' "${SCRIPT_DIR}/tunnelsats.sh"
}

is_secure_mode() {
    case "${SECURE_MODE:-}" in
        true|TRUE|1|yes|YES) return 0 ;;
        false|FALSE|0|no|NO) return 1 ;;
    esac
    if [ -f "$TUNNELSATS_APP_CONFIG" ] && grep -Eq '"(secure_mode|secureMode|secure-mode)"[[:space:]]*:[[:space:]]*true' "$TUNNELSATS_APP_CONFIG" 2>/dev/null; then
        return 0
    fi
    return 1
}

refuse_if_secure_mode() {
    local action="$1"
    if is_secure_mode; then
        echo "ERROR: SECURE_MODE is enabled; automated reconciler '${action}' is disabled. Run the TunnelSats CLI manually over SSH." >&2
        exit 7
    fi
}

valid_dns_or_ip() {
    local host="$1"
    if [ -z "$host" ] || [ "${#host}" -gt 253 ]; then
        return 1
    fi
    if [[ ! "$host" =~ ^[A-Za-z0-9.-]+$ ]]; then
        return 1
    fi
    if [[ "$host" == .* ]] || [[ "$host" == *. ]] || [[ "$host" == *..* ]]; then
        return 1
    fi
    return 0
}

valid_port() {
    local port="$1"
    if [[ ! "$port" =~ ^[0-9]{1,5}$ ]]; then
        return 1
    fi
    if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
        return 1
    fi
    return 0
}

block_insert() {
    local dns="${1:-}"
    local port="${2:-}"
    if [ -z "$port" ] && [[ "$dns" == *:* ]]; then
        port="${dns##*:}"
        dns="${dns%:*}"
    fi
    if ! valid_dns_or_ip "$dns"; then
        echo "ERROR: Invalid VPN DNS/host '${dns}'" >&2
        return 8
    fi
    if ! valid_port "$port"; then
        echo "ERROR: Invalid VPN port '${port}'" >&2
        return 8
    fi

    local dir
    dir="$(dirname "$LND_EXTRA_CONFIG")"
    mkdir -p "$dir"

    local tmp
    tmp="$(mktemp "${LND_EXTRA_CONFIG}.tmp.XXXXXX")"

    local block
    block=$(cat <<EOF
# BEGIN TUNNELSATS
[Application Options]
listen=0.0.0.0:9735
externalhosts=${dns}:${port}
[Tor]
tor.skip-proxy-for-clearnet-targets=true
tor.streamisolation=false
[Application Options]
# END TUNNELSATS
EOF
)

    if [ -f "$LND_EXTRA_CONFIG" ]; then
        awk -v new_block="$block" '
            BEGIN { in_block = 0; replaced = 0 }
            /^[[:space:]]*#[[:space:]]*BEGIN TUNNELSATS[[:space:]]*$/ {
                if (!replaced) {
                    print new_block
                    replaced = 1
                }
                in_block = 1
                next
            }
            /^[[:space:]]*#[[:space:]]*END TUNNELSATS[[:space:]]*$/ {
                in_block = 0
                next
            }
            !in_block { print }
            END {
                if (!replaced) {
                    if (NR > 0) print ""
                    print new_block
                }
            }
        ' "$LND_EXTRA_CONFIG" > "$tmp"
    else
        printf '%s\n' "$block" > "$tmp"
    fi

    chmod 0644 "$tmp"
    if [ "$(id -u)" -eq 0 ] && id -u bitcoin >/dev/null 2>&1; then
        chown bitcoin:bitcoin "$tmp" 2>/dev/null || true
    fi
    mv -f "$tmp" "$LND_EXTRA_CONFIG"
}

block_remove() {
    if [ ! -f "$LND_EXTRA_CONFIG" ]; then
        return 0
    fi
    local tmp
    tmp="$(mktemp "${LND_EXTRA_CONFIG}.tmp.XXXXXX")"
    awk '
        BEGIN { in_block = 0 }
        /^[[:space:]]*#[[:space:]]*BEGIN TUNNELSATS[[:space:]]*$/ { in_block = 1; next }
        /^[[:space:]]*#[[:space:]]*END TUNNELSATS[[:space:]]*$/ { in_block = 0; next }
        !in_block { print }
    ' "$LND_EXTRA_CONFIG" > "$tmp"
    chmod 0644 "$tmp"
    if [ "$(id -u)" -eq 0 ] && id -u bitcoin >/dev/null 2>&1; then
        chown bitcoin:bitcoin "$tmp" 2>/dev/null || true
    fi
    mv -f "$tmp" "$LND_EXTRA_CONFIG"
}

block_status() {
    if [ ! -f "$LND_EXTRA_CONFIG" ]; then
        printf '{"present":false,"externalhosts":null,"listen":null,"skip_proxy":false,"streamisolation_false":false,"file":"%s"}\n' "$LND_EXTRA_CONFIG"
        return 0
    fi

    local in_block=0 present="false" exthosts="" listen_val="" skip_proxy="false" stream_iso="false"
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        if [[ "$line" =~ ^[[:space:]]*#[[:space:]]*BEGIN\ TUNNELSATS[[:space:]]*$ ]]; then
            in_block=1
            present="true"
            continue
        fi
        if [[ "$line" =~ ^[[:space:]]*#[[:space:]]*END\ TUNNELSATS[[:space:]]*$ ]]; then
            in_block=0
            continue
        fi
        if [ "$in_block" -eq 1 ]; then
            case "$line" in
                externalhosts=*) exthosts="${line#externalhosts=}" ;;
                listen=*) listen_val="${line#listen=}" ;;
                tor.skip-proxy-for-clearnet-targets=true|tor.skip-proxy-for-clearnet-targets=1) skip_proxy="true" ;;
                tor.streamisolation=false|tor.streamisolation=0) stream_iso="true" ;;
            esac
        fi
    done < "$LND_EXTRA_CONFIG"

    local ext_json="null"
    if [ -n "$exthosts" ]; then
        ext_json="\"${exthosts}\""
    fi
    local listen_json="null"
    if [ -n "$listen_val" ]; then
        listen_json="\"${listen_val}\""
    fi
    printf '{"present":%s,"externalhosts":%s,"listen":%s,"skip_proxy":%s,"streamisolation_false":%s,"file":"%s"}\n' \
        "$present" "$ext_json" "$listen_json" "$skip_proxy" "$stream_iso" "$LND_EXTRA_CONFIG"
}

validate_and_extract_wg_conf() {
    local conf="$1"
    if [ ! -f "$conf" ] || [ -L "$conf" ]; then
        echo "ERROR: WireGuard config not found or is a symlink: ${conf}" >&2
        return 8
    fi

    local perm
    perm="$(stat -c '%a' "$conf" 2>/dev/null || stat -f '%Lp' "$conf" 2>/dev/null || echo "")"
    if [ "$perm" != "600" ] && [ "$perm" != "400" ]; then
        echo "ERROR: WireGuard config ${conf} must have 0600 permissions (found ${perm})" >&2
        return 8
    fi

    local has_iface=0 has_peer=0 priv="" pub="" addr="" endpoint="" allowed_ok=0 vpn_dns="" vpn_port="9735"
    local section=""
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        if [[ "$line" =~ ^[[:space:]]*#[[:space:]]*(VPNPort|Port\ Forwarding):[[:space:]]*([0-9]+)[[:space:]]*$ ]]; then
            vpn_port="${BASH_REMATCH[2]}"
            continue
        fi
        if [[ "$line" =~ ^[[:space:]]*#[[:space:]]*Server:[[:space:]]*([A-Za-z0-9.-]+)[[:space:]]*$ ]]; then
            vpn_dns="${BASH_REMATCH[1]}"
            continue
        fi
        local trimmed="${line#"${line%%[![:space:]]*}"}"
        if [ -z "$trimmed" ] || [[ "$trimmed" == \#* ]] || [[ "$trimmed" == \;* ]]; then
            continue
        fi
        if [[ "$trimmed" =~ ^\[([A-Za-z]+)\]$ ]]; then
            section="${BASH_REMATCH[1],,}"
            if [ "$section" = "interface" ]; then has_iface=1; fi
            if [ "$section" = "peer" ]; then has_peer=1; fi
            continue
        fi
        if [[ "$trimmed" =~ ^([A-Za-z]+)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
            local key="${BASH_REMATCH[1],,}"
            local val="${BASH_REMATCH[2]%%#*}"
            val="${val%"${val##*[![:space:]]}"}"
            case "${section}:${key}" in
                interface:privatekey) priv="$val" ;;
                interface:address) addr="$val" ;;
                peer:publickey) pub="$val" ;;
                peer:endpoint) endpoint="$val" ;;
                peer:allowedips)
                    if [[ "$val" == *"0.0.0.0/0"* ]]; then
                        allowed_ok=1
                    fi
                    ;;
            esac
        fi
    done < "$conf"

    if [ "$has_iface" -ne 1 ] || [ "$has_peer" -ne 1 ]; then
        echo "ERROR: WireGuard config is missing [Interface] or [Peer] section" >&2
        return 8
    fi
    if [[ ! "$priv" =~ ^[A-Za-z0-9+/]{43}=$ ]] || [[ ! "$pub" =~ ^[A-Za-z0-9+/]{43}=$ ]]; then
        echo "ERROR: WireGuard config requires valid 44-char base64 PrivateKey and PublicKey" >&2
        return 8
    fi
    if [ -z "$addr" ]; then
        echo "ERROR: WireGuard config is missing Address" >&2
        return 8
    fi
    if [[ ! "$endpoint" =~ ^([A-Za-z0-9.-]+):([0-9]{1,5})$ ]]; then
        echo "ERROR: WireGuard config has invalid Endpoint '${endpoint}'" >&2
        return 8
    fi
    if [ -z "$vpn_dns" ]; then
        vpn_dns="${BASH_REMATCH[1]}"
    fi
    if [ "$allowed_ok" -ne 1 ]; then
        echo "ERROR: WireGuard config AllowedIPs must include 0.0.0.0/0" >&2
        return 8
    fi
    if ! valid_dns_or_ip "$vpn_dns" || ! valid_port "$vpn_port"; then
        echo "ERROR: Extracted VPN endpoint (${vpn_dns}:${vpn_port}) is invalid" >&2
        return 8
    fi

    EXTRACTED_VPN_DNS="$vpn_dns"
    EXTRACTED_VPN_PORT="$vpn_port"
    return 0
}

cmd_apply() {
    refuse_if_secure_mode "apply"

    local conf_path="${1:-$TUNNELSATS_CONF_PATH}"
    EXTRACTED_VPN_DNS=""
    EXTRACTED_VPN_PORT=""
    validate_and_extract_wg_conf "$conf_path"

    local ts_bin
    ts_bin="$(resolve_ts_sh_bin)"

    block_insert "$EXTRACTED_VPN_DNS" "$EXTRACTED_VPN_PORT"
    if [ -x "$MYNODE_GEN_LND_CONFIG" ]; then
        "$MYNODE_GEN_LND_CONFIG" || true
    fi

    if [ -f "$MANAGED_INVENTORY" ] && grep -Eq '"state"[[:space:]]*:[[:space:]]*"installed"' "$MANAGED_INVENTORY" 2>/dev/null; then
        mkdir -p "$WG_DIR"
        chmod 0700 "$WG_DIR"
        local tmp_wg
        tmp_wg="$(mktemp "${WG_CONF_DST}.tmp.XXXXXX")"
        cp -f "$conf_path" "$tmp_wg"
        chmod 0600 "$tmp_wg"
        mv -f "$tmp_wg" "$WG_CONF_DST"
        "$SYSTEMCTL_BIN" restart wg-quick@tunnelsatsv2.service
        "$SYSTEMCTL_BIN" restart lnd.service
    else
        if ! "$ts_bin" install --managed mynode --non-interactive --yes --config "$conf_path"; then
            block_remove || true
            if [ -x "$MYNODE_GEN_LND_CONFIG" ]; then
                "$MYNODE_GEN_LND_CONFIG" || true
            fi
            exit 1
        fi
        "$SYSTEMCTL_BIN" restart lnd.service
    fi

    printf '{"status":"applied","vpn_dns":"%s","vpn_port":%s,"lnd_extra_config":"%s"}\n' \
        "$EXTRACTED_VPN_DNS" "$EXTRACTED_VPN_PORT" "$LND_EXTRA_CONFIG"
}

cmd_restore_internal() {
    local mode="$1"
    local ts_bin
    ts_bin="$(resolve_ts_sh_bin)"

    # 1. Remove the hybrid clearnet block from lnd_extra_config.conf FIRST so lnd.conf is clean Tor-only
    block_remove

    if [ -x "$MYNODE_GEN_LND_CONFIG" ]; then
        "$MYNODE_GEN_LND_CONFIG" || true
    elif [ -f "$LND_MAIN_CONFIG" ]; then
        local tmp_lnd
        tmp_lnd="$(mktemp "${LND_MAIN_CONFIG}.tmp.XXXXXX")"
        awk '
            BEGIN { in_block = 0 }
            /^[[:space:]]*#[[:space:]]*BEGIN TUNNELSATS[[:space:]]*$/ { in_block = 1; next }
            /^[[:space:]]*#[[:space:]]*END TUNNELSATS[[:space:]]*$/ { in_block = 0; next }
            !in_block { print }
        ' "$LND_MAIN_CONFIG" > "$tmp_lnd"
        chmod 0644 "$tmp_lnd"
        mv -f "$tmp_lnd" "$LND_MAIN_CONFIG"
    fi

    # 2. Remove the managed dataplane (exit code 3 = not installed, which is fine)
    if [ -x "$ts_bin" ] || [ -f "$ts_bin" ]; then
        local rc=0
        bash "$ts_bin" uninstall --managed --non-interactive --yes || rc=$?
        if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ]; then
            echo "WARNING: tunnelsats uninstall --managed exited with code ${rc}" >&2
        fi
    fi

    # 3. Restart lnd.service in clean Tor-only mode if active
    if "$SYSTEMCTL_BIN" is-active --quiet lnd.service 2>/dev/null; then
        "$SYSTEMCTL_BIN" restart lnd.service || true
    fi

    if [ "$mode" = "uninstall" ]; then
        rm -f "$SUDOERS_FILE" "$RECONCILE_SBIN" || true
        printf '{"status":"uninstalled","lnd_extra_config":"%s"}\n' "$LND_EXTRA_CONFIG"
    else
        printf '{"status":"restored","lnd_extra_config":"%s"}\n' "$LND_EXTRA_CONFIG"
    fi
}

cmd_status() {
    local secure_str="false"
    if is_secure_mode; then
        secure_str="true"
    fi
    local managed_str="false"
    if [ -f "$MANAGED_INVENTORY" ]; then
        managed_str="true"
    fi
    local blk_json
    blk_json="$(block_status)"
    local ts_bin
    ts_bin="$(resolve_ts_sh_bin)"
    local verify_json="null"
    if [ -x "$ts_bin" ] || [ -f "$ts_bin" ]; then
        verify_json="$(bash "$ts_bin" verify --no-probe --json 2>/dev/null || echo "null")"
        if [ -z "$verify_json" ] || [[ "$verify_json" != \{* ]]; then
            verify_json="null"
        fi
    fi
    printf '{"secure_mode":%s,"managed_installed":%s,"lnd_extra_config":%s,"dataplane":%s}\n' \
        "$secure_str" "$managed_str" "$blk_json" "$verify_json"
}

cmd_boot_sync() {
    if is_secure_mode; then
        return 0
    fi
    if [ -f "$TUNNELSATS_CONF_PATH" ]; then
        if [ ! -f "$TUNNELSATS_APP_CONFIG" ] || ! grep -Eq '"enabled"[[:space:]]*:[[:space:]]*false' "$TUNNELSATS_APP_CONFIG" 2>/dev/null; then
            cmd_apply
        fi
    fi
}

cmd_on_service_stop() {
    # Keep the independent fail-closed tunnelsats.slice and kill switch active across normal
    # restarts of tunnelsats.service; full removal only happens on restore or uninstall.
    return 0
}

SUBCOMMAND="${1:-}"
case "$SUBCOMMAND" in
    block-insert)
        refuse_if_secure_mode "block-insert"
        block_insert "${2:-}" "${3:-}"
        ;;
    block-remove)
        refuse_if_secure_mode "block-remove"
        block_remove
        ;;
    block-status)
        block_status
        ;;
    apply)
        cmd_apply "${2:-}"
        ;;
    restore)
        refuse_if_secure_mode "restore"
        cmd_restore_internal "restore"
        ;;
    uninstall)
        cmd_restore_internal "uninstall"
        ;;
    status)
        cmd_status
        ;;
    boot-sync)
        cmd_boot_sync
        ;;
    on-service-stop)
        cmd_on_service_stop
        ;;
    *)
        echo "Usage: $0 {apply|restore|uninstall|status|boot-sync|on-service-stop|block-insert <dns> <port>|block-remove|block-status}" >&2
        exit 2
        ;;
esac
