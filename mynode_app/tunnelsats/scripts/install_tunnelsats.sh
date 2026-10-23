#!/bin/bash
# shellcheck disable=SC1091

if [ -f /usr/share/mynode/mynode_device_info.sh ]; then
    source /usr/share/mynode/mynode_device_info.sh
fi
if [ -f /usr/share/mynode/mynode_app_versions.sh ]; then
    source /usr/share/mynode/mynode_app_versions.sh
fi
if [ -f /usr/share/mynode/mynode_functions.sh ]; then
    source /usr/share/mynode/mynode_functions.sh
fi

set -x
set -e

echo "==================== INSTALLING APP ===================="

INSTALL_DIR="${INSTALL_FOLDER:-/opt/mynode/tunnelsats}"
STORAGE_DIR="${STORAGE_FOLDER:-/mnt/hdd/mynode/tunnelsats}"

mkdir -p "$INSTALL_DIR"
mkdir -p "$STORAGE_DIR"
chmod 0700 "$STORAGE_DIR"

chmod +x "$INSTALL_DIR/bridge.py" 2>/dev/null || true
chmod +x "$INSTALL_DIR/scripts/"*.sh 2>/dev/null || true

echo "================== DONE INSTALLING APP ================="
