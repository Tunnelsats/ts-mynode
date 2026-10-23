#!/bin/bash
# Runs as root prior to launching tunnelsats.service (ExecStartPre=+)
set -euo pipefail

INSTALL_DIR="/opt/mynode/tunnelsats"
COMPAT_LINK="/opt/mynode/ts-mynode"
STORAGE_DIR="/mnt/hdd/mynode/tunnelsats"
APP_CONFIG="${STORAGE_DIR}/config.json"
RECONCILE_SRC="${INSTALL_DIR}/scripts/reconcile_mynode.sh"
RECONCILE_SBIN="/usr/local/sbin/tunnelsats-reconcile"
SUDOERS_FILE="/etc/sudoers.d/tunnelsats-reconcile"

if [ -d "$INSTALL_DIR" ] && [ ! -e "$COMPAT_LINK" ]; then
    ln -sfn "$INSTALL_DIR" "$COMPAT_LINK"
elif [ -L "$COMPAT_LINK" ]; then
    ln -sfn "$INSTALL_DIR" "$COMPAT_LINK"
fi

mkdir -p "$STORAGE_DIR"
if id -u tunnelsats >/dev/null 2>&1; then
    chown -R tunnelsats:tunnelsats "$STORAGE_DIR"
fi
chmod 0700 "$STORAGE_DIR"

if [ -f "$RECONCILE_SRC" ]; then
    install -o root -g root -m 0755 "$RECONCILE_SRC" "$RECONCILE_SBIN"
fi

SECURE_MODE_ACTIVE="false"
if [ "${SECURE_MODE:-false}" = "true" ] || [ "${SECURE_MODE:-0}" = "1" ]; then
    SECURE_MODE_ACTIVE="true"
elif [ -f "$APP_CONFIG" ] && grep -Eq '"secure_mode"[[:space:]]*:[[:space:]]*true|"secureMode"[[:space:]]*:[[:space:]]*true' "$APP_CONFIG" 2>/dev/null; then
    SECURE_MODE_ACTIVE="true"
fi

if [ "$SECURE_MODE_ACTIVE" = "true" ]; then
    rm -f "$SUDOERS_FILE"
else
    cat <<'EOF' > "${SUDOERS_FILE}.tmp"
Defaults:tunnelsats !requiretty
tunnelsats ALL=(root) NOPASSWD: /usr/local/sbin/tunnelsats-reconcile *
EOF
    chown root:root "${SUDOERS_FILE}.tmp"
    chmod 0440 "${SUDOERS_FILE}.tmp"
    mv -f "${SUDOERS_FILE}.tmp" "$SUDOERS_FILE"
fi

if [ -x "$RECONCILE_SBIN" ]; then
    "$RECONCILE_SBIN" boot-sync || true
fi
