#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT_DIR/deploy/cicd-security-tools"
REPO_DIR="$PWD"
OUTPUT_DIR="$PWD/scan-output"
TARGET_URL=""
MODE="gate"

usage() {
  cat <<'EOF'
Usage:
  cicd_security_tools.sh gate --repo <repo> [--target-url <url>] [--output <dir>]
  cicd_security_tools.sh pull
  cicd_security_tools.sh versions

Runs Semgrep, Trivy, OWASP ZAP, and Nuclei using Docker Compose scanner images.
No secrets are required or stored.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    gate|pull|versions)
      MODE="$1"; shift ;;
    --repo)
      REPO_DIR="$2"; shift 2 ;;
    --target-url)
      TARGET_URL="$2"; shift 2 ;;
    --output)
      OUTPUT_DIR="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

mkdir -p "$OUTPUT_DIR"

compose() {
  HOST_REPO="$REPO_DIR" HOST_OUTPUT="$OUTPUT_DIR" DAST_TARGET_URL="$TARGET_URL" \
    docker compose -f "$COMPOSE_DIR/docker-compose.yml" "$@"
}

if [[ "$MODE" == "pull" ]]; then
  compose --profile gate --profile dast pull
  exit 0
fi

if [[ "$MODE" == "versions" ]]; then
  docker run --rm semgrep/semgrep:latest semgrep --version || true
  docker run --rm aquasec/trivy:latest trivy --version || true
  docker run --rm ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -h >/dev/null || true
  docker run --rm projectdiscovery/nuclei:latest -version || true
  exit 0
fi

if [[ "$MODE" != "gate" ]]; then
  usage
  exit 2
fi

profiles=(--profile gate)
if [[ -n "$TARGET_URL" ]]; then
  profiles+=(--profile dast)
fi

set +e
compose "${profiles[@]}" run --rm semgrep
semgrep_rc=$?
compose "${profiles[@]}" run --rm trivy
trivy_rc=$?
zap_rc=0
nuclei_rc=0
if [[ -n "$TARGET_URL" ]]; then
  compose "${profiles[@]}" run --rm zap
  zap_rc=$?
  compose "${profiles[@]}" run --rm nuclei
  nuclei_rc=$?
fi
set -e

python3 "$ROOT_DIR/scripts/run_cicd_security_pipeline.py" \
  --execution artifacts \
  --provider gitlab \
  --repo "$REPO_DIR" \
  --repo-ref "${CI_PROJECT_PATH:-local/repo}" \
  --branch "${CI_COMMIT_REF_NAME:-}" \
  --commit-sha "${CI_COMMIT_SHA:-}" \
  ${TARGET_URL:+--target-url "$TARGET_URL"} \
  --artifact-dir "$OUTPUT_DIR" \
  --output "$OUTPUT_DIR/security-gate-result.json" \
  --safe-demo

if [[ $semgrep_rc -gt 1 || $trivy_rc -gt 1 || $zap_rc -gt 1 || $nuclei_rc -gt 1 ]]; then
  echo "One or more scanners errored; inspect $OUTPUT_DIR/security-gate-result.json" >&2
  exit 1
fi
