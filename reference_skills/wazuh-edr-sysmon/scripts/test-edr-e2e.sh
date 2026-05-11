#!/bin/bash
# ============================================================
# EDR E2E Test Runner
# Runs the complete end-to-end test suite
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo " Running EDR E2E Test Suite"
echo " $(date)"
echo "=========================================="

cd "$SCRIPT_DIR/.."
python3 tests/test_edr_sysmon_e2e.py
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "All E2E tests PASSED"
else
    echo ""
    echo "Some E2E tests FAILED"
fi

exit $EXIT_CODE
