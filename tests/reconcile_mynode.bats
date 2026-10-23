#!/usr/bin/env bats
# BATS integration tests for scripts/reconcile_mynode.sh

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  RECONCILER="${REPO_ROOT}/scripts/reconcile_mynode.sh"
  export TEST_TMPDIR="$(mktemp -d)"
  export LND_EXTRA_CONFIG="${TEST_TMPDIR}/lnd_extra_config.conf"
  export MYNODE_LND_EXTRA_CONF="${TEST_TMPDIR}/lnd_extra_config.conf"
  export LND_MAIN_CONFIG="${TEST_TMPDIR}/lnd.conf"
  export TUNNELSATS_DATA_DIR="${TEST_TMPDIR}/tunnelsats"
  export TUNNELSATS_CONF_PATH="${TUNNELSATS_DATA_DIR}/tunnelsatsv2.conf"
  export TUNNELSATS_APP_CONFIG="${TUNNELSATS_DATA_DIR}/config.json"
  export WG_DIR="${TEST_TMPDIR}/wireguard"
  export WG_CONF_DST="${WG_DIR}/tunnelsatsv2.conf"
  export MANAGED_INVENTORY="${TEST_TMPDIR}/managed.json"
  export SUDOERS_FILE="${TEST_TMPDIR}/sudoers-tunnelsats"
  export RECONCILE_SBIN="${TEST_TMPDIR}/tunnelsats-reconcile"
  mkdir -p "${TUNNELSATS_DATA_DIR}" "${WG_DIR}"
}

teardown() {
  rm -rf "${TEST_TMPDIR}"
}

@test "block-insert creates bounded TUNNELSATS block in lnd_extra_config.conf" {
  run "${RECONCILER}" block-insert "eu1.tunnelsats.com" "34567"
  [ "$status" -eq 0 ]
  [ -f "${LND_EXTRA_CONFIG}" ]

  run "${RECONCILER}" block-status
  [ "$status" -eq 0 ]
  [[ "$output" == *'"present":true'* ]]
  [[ "$output" == *'"externalhosts":"eu1.tunnelsats.com:34567"'* ]]

  grep -q "^# BEGIN TUNNELSATS$" "${LND_EXTRA_CONFIG}"
  grep -q "^externalhosts=eu1.tunnelsats.com:34567$" "${LND_EXTRA_CONFIG}"
  grep -q "^tor.streamisolation=false$" "${LND_EXTRA_CONFIG}"
  grep -q "^tor.skip-proxy-for-clearnet-targets=true$" "${LND_EXTRA_CONFIG}"
  grep -q "^# END TUNNELSATS$" "${LND_EXTRA_CONFIG}"
}

@test "block-insert is idempotent and preserves user settings outside block" {
  cat > "${LND_EXTRA_CONFIG}" <<'EOF'
# Custom user setting before
maxpendingchannels=5
EOF

  run "${RECONCILER}" block-insert "eu1.tunnelsats.com:34567"
  [ "$status" -eq 0 ]

  run "${RECONCILER}" block-insert "us1.tunnelsats.com" "45678"
  [ "$status" -eq 0 ]

  begin_count="$(grep -c "^# BEGIN TUNNELSATS$" "${LND_EXTRA_CONFIG}")"
  end_count="$(grep -c "^# END TUNNELSATS$" "${LND_EXTRA_CONFIG}")"
  [ "$begin_count" -eq 1 ]
  [ "$end_count" -eq 1 ]

  grep -q "^maxpendingchannels=5$" "${LND_EXTRA_CONFIG}"
  grep -q "^externalhosts=us1.tunnelsats.com:45678$" "${LND_EXTRA_CONFIG}"
  ! grep -q "eu1.tunnelsats.com" "${LND_EXTRA_CONFIG}"
}

@test "block-remove deletes only the TUNNELSATS block and preserves surrounding lines" {
  cat > "${LND_EXTRA_CONFIG}" <<'EOF'
alias=mynode-btc
# BEGIN TUNNELSATS
[Application Options]
listen=0.0.0.0:9735
externalhosts=eu1.tunnelsats.com:34567
[Tor]
tor.skip-proxy-for-clearnet-targets=true
tor.streamisolation=false
[Application Options]
# END TUNNELSATS
minchansize=100000
EOF

  run "${RECONCILER}" block-remove
  [ "$status" -eq 0 ]

  run "${RECONCILER}" block-status
  [ "$status" -eq 0 ]
  [[ "$output" == *'"present":false'* ]]

  grep -q "^alias=mynode-btc$" "${LND_EXTRA_CONFIG}"
  grep -q "^minchansize=100000$" "${LND_EXTRA_CONFIG}"
  ! grep -q "TUNNELSATS" "${LND_EXTRA_CONFIG}"
  ! grep -q "externalhosts=" "${LND_EXTRA_CONFIG}"
}

@test "apply and restore refuse execution when SECURE_MODE=true" {
  export SECURE_MODE="true"
  conf_file="${TEST_TMPDIR}/test.conf"
  echo "[Interface]" > "${conf_file}"
  chmod 0600 "${conf_file}"

  run "${RECONCILER}" apply "${conf_file}"
  [ "$status" -eq 7 ]
  [[ "$output" == *"SECURE_MODE is enabled"* ]]

  run "${RECONCILER}" restore
  [ "$status" -eq 7 ]
  [[ "$output" == *"SECURE_MODE is enabled"* ]]
}

@test "apply and restore orchestrate tunnelsats.sh --managed mynode and clean Tor-only restore" {
  cat > "${TUNNELSATS_CONF_PATH}" <<'EOF'
[Interface]
PrivateKey = cGxlYXNlRG9Ob3RVc2VUaGlzVGVzdEtleUluUHJvZDA=
Address = 10.9.0.42/32
# Server: eu1.tunnelsats.com
# Port Forwarding: 34567

[Peer]
PublicKey = dGVzdFNlcnZlclB1YmxpY0tleVZhbHVlMTIzNDU2Nzg=
Endpoint = eu1.tunnelsats.com:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
EOF
  chmod 0600 "${TUNNELSATS_CONF_PATH}"

  export TS_SH_BIN="${TEST_TMPDIR}/mock_ts.sh"
  cat > "${TS_SH_BIN}" <<'EOF'
#!/usr/bin/env bash
echo "mock_ts: $*" >> "${TEST_TMPDIR}/ts_calls.log"
exit 0
EOF
  chmod +x "${TS_SH_BIN}"

  export SYSTEMCTL_BIN="${TEST_TMPDIR}/mock_systemctl.sh"
  cat > "${SYSTEMCTL_BIN}" <<'EOF'
#!/usr/bin/env bash
echo "systemctl: $*" >> "${TEST_TMPDIR}/systemctl_calls.log"
exit 0
EOF
  chmod +x "${SYSTEMCTL_BIN}"

  run "${RECONCILER}" apply "${TUNNELSATS_CONF_PATH}"
  [ "$status" -eq 0 ]
  [[ "$output" == *'"status":"applied"'* ]]
  grep -q "^externalhosts=eu1.tunnelsats.com:34567$" "${LND_EXTRA_CONFIG}"
  grep -q "install --managed mynode --impl lnd --non-interactive --yes --config" "${TEST_TMPDIR}/ts_calls.log"

  run "${RECONCILER}" restore
  [ "$status" -eq 0 ]
  [[ "$output" == *'"status":"restored"'* ]]
  ! grep -q "TUNNELSATS" "${LND_EXTRA_CONFIG}"
  grep -q "uninstall --managed --non-interactive --yes" "${TEST_TMPDIR}/ts_calls.log"
}
