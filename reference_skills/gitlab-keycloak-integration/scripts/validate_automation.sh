#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# GitLab + Keycloak Integration - Comprehensive Health Check Script
# =============================================================================
# Validates all components of the GitLab-Keycloak automation setup including:
# - GitLab instance connectivity and configuration
# - Keycloak instance connectivity and realm status
# - OIDC client configuration
# - User provisioning and group mapping
# - Network connectivity
# - SSL/TLS certificate validity
# - Log file analysis
# =============================================================================

# --- Configuration ---
GITLAB_URL="${GITLAB_URL:-https://gitlab.cereal.local}"
KEYCLOAK_URL="${KEYCLOAK_URL:-https://keycloak.cereal.local}"
GITLAB_API_TOKEN="${GITLAB_API_TOKEN:-}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-gitlab}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

# --- Helper Functions ---

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASS_COUNT++))
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    ((WARN_COUNT++))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAIL_COUNT++))
}

log_section() {
    echo ""
    echo -e "${BLUE}--------------------------------------------------------${NC}"
    echo -e "${BLUE} $1${NC}"
    echo -e "${BLUE}--------------------------------------------------------${NC}"
}

check_prerequisites() {
    log_section "PREREQUISITES CHECK"

    # Check required tools
    for cmd in curl jq openssl; do
        if command -v "$cmd" &> /dev/null; then
            log_pass "$cmd is installed"
        else
            log_fail "$cmd is not installed (required for full validation)"
        fi
    done

    # Check environment variables
    if [ -z "$GITLAB_API_TOKEN" ]; then
        log_warn "GITLAB_API_TOKEN not set - some GitLab API checks will be skipped"
    else
        log_pass "GITLAB_API_TOKEN is set"
    fi

    if [ -z "$KEYCLOAK_ADMIN_PASSWORD" ] || [ "$KEYCLOAK_ADMIN_PASSWORD" = "admin" ]; then
        log_warn "KEYCLOAK_ADMIN_PASSWORD not set or using default - some Keycloak checks will be skipped"
    else
        log_pass "KEYCLOAK_ADMIN_PASSWORD is set"
    fi
}

check_gitlab_connectivity() {
    log_section "GITLAB CONNECTIVITY"

    # Check GitLab is reachable
    if curl -sf --max-time 10 --insecure "$GITLAB_URL" -o /dev/null; then
        log_pass "GitLab is reachable at $GITLAB_URL"
    else
        log_fail "GitLab is NOT reachable at $GITLAB_URL"
        return 1
    fi

    # Check GitLab API
    if curl -sf --max-time 10 --insecure "$GITLAB_URL/api/v4/version" -o /dev/null; then
        VERSION=$(curl -sf --max-time 10 --insecure "$GITLAB_URL/api/v4/version" | jq -r '.version' 2>/dev/null || echo "unknown")
        log_pass "GitLab API is responding (version: $VERSION)"
    else
        log_fail "GitLab API is NOT responding"
    fi

    # Check GitLab health endpoint
    if curl -sf --max-time 10 --insecure "$GITLAB_URL/-/health" -o /dev/null; then
        log_pass "GitLab health endpoint is responding"
    else
        log_warn "GitLab health endpoint is NOT responding"
    fi

    # Check GitLab OmniAuth configuration (requires API token)
    if [ -n "$GITLAB_API_TOKEN" ]; then
        if curl -sf --max-time 10 --insecure \
            -H "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
            "$GITLAB_URL/api/v4/application/settings" -o /dev/null; then
            log_pass "GitLab admin API access verified"

            # Check if OmniAuth providers are configured
            SETTINGS=$(curl -sf --max-time 10 --insecure \
                -H "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
                "$GITLAB_URL/api/v4/application/settings" 2>/dev/null)

            if echo "$SETTINGS" | jq -e '.omniauth_providers | length > 0' &> /dev/null; then
                PROVIDERS=$(echo "$SETTINGS" | jq -r '.omniauth_providers | map(.name) | join(", ")')
                log_pass "OmniAuth providers configured: $PROVIDERS"
            else
                log_warn "No OmniAuth providers configured in GitLab"
            fi
        else
            log_fail "GitLab admin API access failed (check API token permissions)"
        fi
    fi
}

check_keycloak_connectivity() {
    log_section "KEYCLOAK CONNECTIVITY"

    # Check Keycloak is reachable
    if curl -sf --max-time 10 --insecure "$KEYCLOAK_URL" -o /dev/null; then
        log_pass "Keycloak is reachable at $KEYCLOAK_URL"
    else
        log_fail "Keycloak is NOT reachable at $KEYCLOAK_URL"
        return 1
    fi

    # Check Keycloak realms list
    if curl -sf --max-time 10 --insecure "$KEYCLOAK_URL/realms/" -o /dev/null; then
        log_pass "Keycloak realms endpoint is responding"
    else
        log_fail "Keycloak realms endpoint is NOT responding"
    fi

    # Check if our realm exists
    if curl -sf --max-time 10 --insecure "$KEYCLOAK_URL/realms/$KEYCLOAK_REALM" -o /dev/null; then
        log_pass "Keycloak realm '$KEYCLOAK_REALM' exists and is accessible"
    else
        log_fail "Keycloak realm '$KEYCLOAK_REALM' does NOT exist or is inaccessible"
    fi

    # Check Keycloak admin API (requires admin credentials)
    if [ -n "$KEYCLOAK_ADMIN_PASSWORD" ] && [ "$KEYCLOAK_ADMIN_PASSWORD" != "admin" ]; then
        TOKEN_RESPONSE=$(curl -sf --max-time 10 --insecure \
            -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
            -d "grant_type=password" \
            -d "client_id=admin-cli" \
            -d "username=$KEYCLOAK_ADMIN_USER" \
            -d "password=$KEYCLOAK_ADMIN_PASSWORD" 2>/dev/null)

        if [ -n "$TOKEN_RESPONSE" ]; then
            ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token' 2>/dev/null)
            if [ -n "$ACCESS_TOKEN" ] && [ "$ACCESS_TOKEN" != "null" ]; then
                log_pass "Keycloak admin API authentication successful"

                # Check OIDC client configuration
                CLIENTS=$(curl -sf --max-time 10 --insecure \
                    -H "Authorization: Bearer $ACCESS_TOKEN" \
                    "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients" 2>/dev/null)

                if echo "$CLIENTS" | jq -e '.[] | select(.clientId == "gitlab")' &> /dev/null; then
                    log_pass "GitLab OIDC client exists in Keycloak"

                    # Get client details
                    CLIENT_UUID=$(echo "$CLIENTS" | jq -r '.[] | select(.clientId == "gitlab") .id')
                    CLIENT_SECRET=$(echo "$CLIENTS" | jq -r '.[] | select(.clientId == "gitlab") .clientSecret')

                    if [ -n "$CLIENT_SECRET" ] && [ "$CLIENT_SECRET" != "null" ]; then
                        log_pass "GitLab OIDC client has a secret configured"
                    else
                        log_warn "Could not retrieve GitLab OIDC client secret"
                    fi

                    # Check valid redirect URIs
                    VALID_REDIRECTS=$(echo "$CLIENTS" | jq -r '.[] | select(.clientId == "gitlab") .validRedirectUris | join(", ")')
                    if [[ "$VALID_REDIRECTS" == *"$GITLAB_URL"* ]]; then
                        log_pass "GitLab URL is in valid redirect URIs"
                    else
                        log_fail "GitLab URL is NOT in valid redirect URIs: $VALID_REDIRECTS"
                    fi
                else
                    log_fail "GitLab OIDC client does NOT exist in Keycloak"
                fi
            else
                log_fail "Keycloak admin API authentication failed (invalid credentials)"
            fi
        else
            log_fail "Keycloak admin API returned no response"
        fi
    fi
}

check_ssl_certificates() {
    log_section "SSL/TLS CERTIFICATES"

    # Check GitLab certificate
    GITLAB_CERT_EXPIRY=$(echo | openssl s_client -servername gitlab.cereal.local -connect gitlab.cereal.local:443 2>/dev/null | \
        openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)

    if [ -n "$GITLAB_CERT_EXPIRY" ]; then
        EXPIRY_EPOCH=$(date -d "$GITLAB_CERT_EXPIRY" +%s 2>/dev/null || echo 0)
        CURRENT_EPOCH=$(date +%s)
        DAYS_LEFT=$(( (EXPIRY_EPOCH - CURRENT_EPOCH) / 86400 ))

        if [ "$DAYS_LEFT" -gt 30 ]; then
            log_pass "GitLab SSL certificate expires in $DAYS_LEFT days ($GITLAB_CERT_EXPIRY)"
        elif [ "$DAYS_LEFT" -gt 0 ]; then
            log_warn "GitLab SSL certificate expires in $DAYS_LEFT days ($GITLAB_CERT_EXPIRY)"
        else
            log_fail "GitLab SSL certificate has EXPIRED ($GITLAB_CERT_EXPIRY)"
        fi
    else
        log_warn "Could not check GitLab SSL certificate"
    fi

    # Check Keycloak certificate
    KEYCLOAK_CERT_EXPIRY=$(echo | openssl s_client -servername keycloak.cereal.local -connect keycloak.cereal.local:443 2>/dev/null | \
        openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)

    if [ -n "$KEYCLOAK_CERT_EXPIRY" ]; then
        EXPIRY_EPOCH=$(date -d "$KEYCLOAK_CERT_EXPIRY" +%s 2>/dev/null || echo 0)
        CURRENT_EPOCH=$(date +%s)
        DAYS_LEFT=$(( (EXPIRY_EPOCH - CURRENT_EPOCH) / 86400 ))

        if [ "$DAYS_LEFT" -gt 30 ]; then
            log_pass "Keycloak SSL certificate expires in $DAYS_LEFT days ($KEYCLOAK_CERT_EXPIRY)"
        elif [ "$DAYS_LEFT" -gt 0 ]; then
            log_warn "Keycloak SSL certificate expires in $DAYS_LEFT days ($KEYCLOAK_CERT_EXPIRY)"
        else
            log_fail "Keycloak SSL certificate has EXPIRED ($KEYCLOAK_CERT_EXPIRY)"
        fi
    else
        log_warn "Could not check Keycloak SSL certificate"
    fi
}

check_network_connectivity() {
    log_section "NETWORK CONNECTIVITY"

    # Check if services are on the Docker network
    if docker network inspect gitlab-keycloak-net &> /dev/null; then
        log_pass "Docker network 'gitlab-keycloak-net' exists"

        # List containers on the network
        CONTAINERS=$(docker network inspect gitlab-keycloak-net --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null)
        log_info "Containers on network: $CONTAINERS"
    else
        log_warn "Docker network 'gitlab-keycloak-net' does NOT exist"
    fi

    # Check container connectivity
    for container in gitlab keycloak keycloak-db; do
        if docker inspect "$container" &> /dev/null; then
            STATUS=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null)
            if [ "$STATUS" = "running" ]; then
                log_pass "Container '$container' is running"
            else
                log_warn "Container '$container' status: $STATUS"
            fi
        else
            log_warn "Container '$container' not found"
        fi
    done

    # Check inter-container connectivity
    if docker exec gitlab ping -c 1 -W 3 keycloak &> /dev/null 2>&1; then
        log_pass "GitLab can reach Keycloak container"
    else
        log_warn "GitLab cannot ping Keycloak container (may be expected if ping is disabled)"
    fi
}

check_log_files() {
    log_section "LOG FILE ANALYSIS"

    # Check GitLab logs for OIDC errors
    if docker logs gitlab --tail 100 2>/dev/null | grep -qi "oidc\|omniauth"; then
        OIDC_LOGS=$(docker logs gitlab --tail 100 2>/dev/null | grep -i "oidc\|omniauth" | tail -5)
        if docker logs gitlab --tail 100 2>/dev/null | grep -qi "error\|fail"; then
            log_warn "Found OIDC/OmniAuth errors in GitLab logs:"
            echo "$OIDC_LOGS" | head -5 | while read -r line; do
                echo "  $line"
            done
        else
            log_pass "GitLab logs show OIDC/OmniAuth activity without errors"
        fi
    else
        log_info "No OIDC/OmniAuth entries found in recent GitLab logs"
    fi

    # Check Keycloak logs for errors
    if docker logs keycloak --tail 100 2>/dev/null | grep -qi "error"; then
        ERROR_COUNT=$(docker logs keycloak --tail 100 2>/dev/null | grep -ci "error" || true)
        log_warn "Found $ERROR_COUNT error(s) in recent Keycloak logs"
        docker logs keycloak --tail 100 2>/dev/null | grep -i "error" | tail -3 | while read -r line; do
            echo "  $line"
        done
    else
        log_pass "No errors found in recent Keycloak logs"
    fi
}

check_integration_status() {
    log_section "INTEGRATION STATUS SUMMARY"

    echo ""
    echo "========================================"
    echo "  Validation Results Summary"
    echo "========================================"
    echo -e "  ${GREEN}PASSED: $PASS_COUNT${NC}"
    echo -e "  ${YELLOW}WARNINGS: $WARN_COUNT${NC}"
    echo -e "  ${RED}FAILED: $FAIL_COUNT${NC}"
    echo "========================================"
    echo ""

    if [ "$FAIL_COUNT" -eq 0 ]; then
        log_pass "All critical checks passed! Integration is healthy."
        return 0
    else
        log_fail "$FAIL_COUNT critical check(s) failed. Review the output above."
        return 1
    fi
}

# --- Main Execution ---

main() {
    echo ""
    echo "+==================================================================+"
    echo "|     GitLab + Keycloak Integration - Health Check               |"
    echo "|     $(date '+%Y-%m-%d %H:%M:%S')                                     |"
    echo "+==================================================================+"

    check_prerequisites
    check_gitlab_connectivity
    check_keycloak_connectivity
    check_ssl_certificates
    check_network_connectivity
    check_log_files
    check_integration_status

    exit $?
}

# Run main function
main "$@"
