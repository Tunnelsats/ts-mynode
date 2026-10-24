#!/bin/bash
# Sideload and deploy TunnelSats app + source directly onto a myNode device over SSH.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE="${1:-}"
SSH_USER="${2:-admin}"

if [ -z "$DEVICE" ]; then
    echo "Usage: $0 <mynode_ip_or_host> [ssh_user]" >&2
    exit 2
fi

python3 "${REPO_ROOT}/scripts/check_mynode_app.py"

TARGET="${SSH_USER}@${DEVICE}"
TMP_DIR="/tmp/mynode_tunnelsats_push"

echo "Staging TunnelSats app and runtime to ${TARGET}..."
# shellcheck disable=SC2029
ssh "$TARGET" "rm -rf ${TMP_DIR} && mkdir -p ${TMP_DIR}/app ${TMP_DIR}/src"

rsync -a --delete --exclude "__pycache__" --exclude ".DS_Store" \
    "${REPO_ROOT}/mynode_app/tunnelsats/" "${TARGET}:${TMP_DIR}/app/"

rsync -a --delete --exclude ".git" --exclude "__pycache__" --exclude "node_modules" --exclude ".DS_Store" \
    "${REPO_ROOT}/" "${TARGET}:${TMP_DIR}/src/"

REMOTE_SCRIPT=$(cat <<'EOF'
set -euo pipefail
APP="tunnelsats"
DST="/usr/share/mynode_apps/${APP}"
INSTALL_DIR="/opt/mynode/${APP}"
STORAGE_DIR="/mnt/hdd/mynode/${APP}"

[ -d "$DST" ] || touch /tmp/mynode_tunnelsats_push/app/is_manually_added
mkdir -p "$DST"
rsync -a --delete --exclude is_manually_added /tmp/mynode_tunnelsats_push/app/ "$DST/"
[ -f /tmp/mynode_tunnelsats_push/app/is_manually_added ] && mv /tmp/mynode_tunnelsats_push/app/is_manually_added "$DST/"
chown -R root:root "$DST"

mynode-manage-apps init
mkdir -p "$INSTALL_DIR" "$STORAGE_DIR"
rsync -a --delete /tmp/mynode_tunnelsats_push/src/ "$INSTALL_DIR/"
chown -R tunnelsats:tunnelsats "$INSTALL_DIR" "$STORAGE_DIR"
chmod 0700 "$STORAGE_DIR"
ln -sfn "$INSTALL_DIR" /opt/mynode/ts-mynode
rm -rf /tmp/mynode_tunnelsats_push

APP_VER=$(jq -r '.latest_version // "v0.1.0"' "$DST/tunnelsats.json" 2>/dev/null || echo "v0.1.0")
mkdir -p /home/bitcoin/.mynode /mnt/hdd/mynode/settings
printf '%s\n' "$APP_VER" > /home/bitcoin/.mynode/tunnelsats_version
printf '%s\n' "$APP_VER" > /mnt/hdd/mynode/settings/tunnelsats_version
chown bitcoin:bitcoin /home/bitcoin/.mynode/tunnelsats_version /mnt/hdd/mynode/settings/tunnelsats_version 2>/dev/null || true
touch /home/bitcoin/.mynode/install_tunnelsats
rm -f /tmp/app_cache.json

cp -f "$DST/tunnelsats.service" /etc/systemd/system/tunnelsats.service
systemctl daemon-reload
if [ -f "$DST/nginx/https_tunnelsats.conf" ]; then
    nginx -t && systemctl reload nginx
fi
systemctl restart www
systemctl enable --now tunnelsats.service
systemctl restart tunnelsats.service
echo "Successfully deployed TunnelSats to myNode!"
EOF
)

TTY_FLAG=()
if [ -t 0 ]; then
    TTY_FLAG=(-t)
fi
# shellcheck disable=SC2029
ssh "${TTY_FLAG[@]}" "$TARGET" "sudo bash -c $(printf '%q' "$REMOTE_SCRIPT")"
