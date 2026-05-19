#!/usr/bin/env bash
# manage_integration.sh - Day-to-day management CLI for GitLab + Keycloak integration
set -euo pipefail

usage() {
  echo "Usage: $0 <command> [options]"
  echo ""
  echo "Commands:"
  echo "  status          Show status of all components"
  echo "  restart         Restart all services gracefully"
  echo "  restart-nginx   Restart only the nginx proxy"
  echo "  restart-keycloak Restart only Keycloak"
  echo "  restart-gitlab   Restart only GitLab"
  echo "  logs [service]  Show logs (keycloak|nginx|gitlab|runner)"
  echo "  diagnose        Run full diagnostics"
  echo "  test            Run E2E test suite"
  echo "  oidc-status     Show OIDC configuration status"
  echo "  certs-expiry    Show TLS certificate expiry"
  echo "  help            Show this help"
  echo ""
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

case "${1:-help}" in
  status)
    echo "=== Integration Status ==="
    for c in keycloak keycloak-nginx gitlab gitlab-runner; do
      state=$(docker inspect --format='{{.State.Status}}' "$c" 2>/dev/null || echo "not found")
      echo "  $c: $state"
    done
    echo ""
    issuer=$(curl -sk https://localhost:8443/realms/gitlab/.well-known/openid-configuration 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('issuer','N/A'))" 2>/dev/null || echo "N/A")
    echo "  OIDC Issuer: $issuer"
    ;;
  restart)
    echo "Restarting Keycloak..."
    docker restart keycloak
    echo "Restarting nginx proxy..."
    docker restart keycloak-nginx
    echo "Restarting GitLab..."
    docker restart gitlab
    echo "All services restarted."
    ;;
  restart-nginx)
    docker restart keycloak-nginx && echo "Nginx proxy restarted."
    ;;
  restart-keycloak)
    docker restart keycloak && echo "Keycloak restarted."
    ;;
  restart-gitlab)
    docker restart gitlab && echo "GitLab restarted."
    ;;
  logs)
    svc="${2:-}"
    if [[ -z "$svc" ]]; then
      echo "Specify a service: keycloak|nginx|gitlab|runner"
      exit 1
    fi
    case "$svc" in
      keycloak) docker logs --tail 50 keycloak ;;
      nginx)    docker logs --tail 50 keycloak-nginx ;;
      gitlab)   docker logs --tail 50 gitlab ;;
      runner)   docker logs --tail 50 gitlab-runner ;;
      *)        echo "Unknown service: $svc"; exit 1 ;;
    esac
    ;;
  diagnose)
    bash "$SCRIPT_DIR/diagnose.sh"
    ;;
  test)
    bash "$SCRIPT_DIR/test_integration.sh"
    ;;
  oidc-status)
    echo "=== OIDC Configuration ==="
    echo ""
    echo "Keycloak Discovery:"
    curl -sk https://localhost:8443/realms/gitlab/.well-known/openid-configuration 2>/dev/null | python3 -m json.tool 2>/dev/null | head -15 || echo "  Failed to reach discovery endpoint"
    echo ""
    echo "GitLab Config:"
    docker exec gitlab grep -A 3 'omniauth_providers\|omniauth_enabled\|omniauth_allow\|omniauth_block' /etc/gitlab/gitlab.rb 2>/dev/null | grep -v '^#' | head -10 || echo "  No OIDC config found"
    ;;
  certs-expiry)
    echo "=== Certificate Expiry ==="
    openssl x509 -in /opt/agentic-it/gitlab-keycloak-integration/certs/server-cert.pem -noout -dates 2>/dev/null || echo "  Cert not found at expected path"
    ;;
  help)
    usage
    ;;
  *)
    echo "Unknown command: $1"
    usage
    exit 1
    ;;
esac
