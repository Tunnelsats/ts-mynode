#!/bin/bash
# Unified test suite runner for ts-mynode
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== 1. MyNode App SDK v2 Linter ==="
python3 scripts/check_mynode_app.py

echo "=== 2. Python Unit & Integration Tests ==="
python3 -m unittest discover -s tests -p "test_*.py" -v

echo "=== 3. BATS Reconciler Tests ==="
if command -v bats >/dev/null 2>&1; then
    bats tests/*.bats
else
    npx -y bats tests/*.bats
fi

if command -v shellcheck >/dev/null 2>&1; then
    echo "=== 4. ShellCheck ==="
    shellcheck -x \
        mynode_app/tunnelsats/scripts/*.sh \
        scripts/reconcile_mynode.sh \
        scripts/deploy_mynode.sh \
        scripts/test.sh
fi

echo "All ts-mynode checks passed!"
