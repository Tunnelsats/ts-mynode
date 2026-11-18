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
STAGE_REL=".cache/tunnelsats-deploy-$$"

echo "Staging TunnelSats app and runtime to ${TARGET}..."
# shellcheck disable=SC2029
ssh "$TARGET" "umask 077 && rm -rf ~/${STAGE_REL} && mkdir -p ~/${STAGE_REL}/app ~/${STAGE_REL}/src"

rsync -a --delete --exclude "__pycache__" --exclude ".DS_Store" \
    "${REPO_ROOT}/mynode_app/tunnelsats/" "${TARGET}:~/${STAGE_REL}/app/"

rsync -a --delete --exclude ".git" --exclude "__pycache__" --exclude "node_modules" --exclude ".DS_Store" \
    "${REPO_ROOT}/" "${TARGET}:~/${STAGE_REL}/src/"

REMOTE_SCRIPT=$(cat <<'EOF'
set -euo pipefail
STAGE_DIR="$1"
APP="tunnelsats"
DST="/usr/share/mynode_apps/${APP}"
INSTALL_DIR="/opt/mynode/${APP}"
STORAGE_DIR="/mnt/hdd/mynode/${APP}"

[ -d "$DST" ] || touch "${STAGE_DIR}/app/is_manually_added"
mkdir -p "$DST"
rsync -a --delete --exclude is_manually_added "${STAGE_DIR}/app/" "$DST/"
[ -f "${STAGE_DIR}/app/is_manually_added" ] && mv "${STAGE_DIR}/app/is_manually_added" "$DST/"
chown -hR root:root "$DST"
chmod -R go-w "$DST"
chmod 0755 "$DST/root_scripts/"*.sh

mynode-manage-apps init
[ ! -L "$INSTALL_DIR" ]
[ ! -L "$STORAGE_DIR" ]
install -d -o tunnelsats -g tunnelsats -m 0755 "$INSTALL_DIR"
install -d -o tunnelsats -g tunnelsats -m 0700 "$STORAGE_DIR"
rsync -a --delete "${STAGE_DIR}/src/" "$INSTALL_DIR/"
chown -hR tunnelsats:tunnelsats "$INSTALL_DIR"
rm -rf "$STAGE_DIR"

APP_VER=$(jq -r '.latest_version // "v1.0.0"' "$DST/tunnelsats.json" 2>/dev/null || echo "v1.0.0")
if id -u bitcoin >/dev/null 2>&1 && command -v runuser >/dev/null 2>&1; then
    runuser -u bitcoin -g bitcoin -- bash -c '
        set -euo pipefail
        mkdir -p /home/bitcoin/.mynode /mnt/hdd/mynode/settings
        [ ! -L /home/bitcoin/.mynode/tunnelsats_version ]
        [ ! -L /mnt/hdd/mynode/settings/tunnelsats_version ]
        [ ! -L /home/bitcoin/.mynode/install_tunnelsats ]
        printf "%s\n" "$1" > /home/bitcoin/.mynode/tunnelsats_version
        printf "%s\n" "$1" > /mnt/hdd/mynode/settings/tunnelsats_version
        touch /home/bitcoin/.mynode/install_tunnelsats
    ' _ "$APP_VER"
fi
rm -f /tmp/app_cache.json /etc/sudoers.d/tunnelsats-reconcile

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
ssh "${TTY_FLAG[@]}" "$TARGET" "STAGE_ABS=\$(cd ~/${STAGE_REL} && pwd) && sudo bash -c $(printf '%q' "$REMOTE_SCRIPT") _ \"\$STAGE_ABS\""
