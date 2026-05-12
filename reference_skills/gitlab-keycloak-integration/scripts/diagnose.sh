#!/usr/bin/env bash
# diagnose.sh - Full diagnostic tool for GitLab + Keycloak OIDC integration
# Checks: container health, connectivity, OIDC config, proxy, certificates
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
PASS=0; WARN=0; FAIL=0

check() { local section="$1"; test="$2"; result="$3"; echo -e "  ${result} $test" ; }
header() { echo -e "\n${CYAN}=== $1 ===${NC}"; }

header "Container Status"
for c in keycloak keycloak-nginx gitlab gitlab-runner; do
  state=$(docker inspect --format='{{.State.Status}}' "$c" 2>/dev/null || echo "not found")
  health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$c" 2>/dev/null || echo "-")
  if [[ "$state" == "running" ]]; then
    check "$c" "$c status: $state" "$GREEN[PASS]"
    PASS=$((PASS + 1))
  elif [[ "$state" == "not found" ]]; then
    check "$c" "$c not found" "$RED[FAIL]"
    FAIL=$((FAIL + 1))
  else
    check "$c" "$c status: $state" "$YELLOW[WARN]"
    WARN=$((WARN + 1))
  fi
done

header "Keycloak OIDC Discovery"
issuer=$(curl -sk https://localhost:8443/realms/gitlab/.well-known/openid-configuration 2>/dev/null || echo "{}")
issuer=$(echo "$issuer" | python3 -c "import sys,json; print(json.load(sys.stdin).get('issuer',''))" 2>/dev/null || echo "")
if [[ "$issuer" == *"https"* ]]; then
  check "oidc" "Issuer URL: $issuer" "$GREEN[PASS]"; PASS=$((PASS + 1))
else
  check "oidc" "Issuer not HTTPS: $issuer" "$RED[FAIL]"; FAIL=$((FAIL + 1))
fi

header "Keycloak Realm & Client"
realm=$(curl -sk https://localhost:8443/realms/gitlab 2>/dev/null | grep -c "gitlab" || true)
if (( realm > 0 )); then
  check "realm" "gitlab realm accessible" "$GREEN[PASS]"; PASS=$((PASS + 1))
else
  check "realm" "gitlab realm not accessible" "$RED[FAIL]"; FAIL=$((FAIL + 1))
fi

header "Nginx Proxy"
proxy=$(curl -sk https://localhost:8443/nginx-health 2>/dev/null || echo "fail")
if [[ "$proxy" == "ok" ]]; then
  check "proxy" "nginx health: $proxy" "$GREEN[PASS]"; PASS=$((PASS + 1))
else
  check "proxy" "nginx health: $proxy" "$RED[FAIL]"; FAIL=$((FAIL + 1))
fi

header "GitLab Services"
gl_status=$(docker exec gitlab gitlab-ctl status 2>/dev/null || true)
if echo "$gl_status" | grep -q "run:"; then
  check "gitlab" "GitLab services running" "$GREEN[PASS]"; PASS=$((PASS + 1))
else
  check "gitlab" "GitLab services down" "$RED[FAIL]"; FAIL=$((FAIL + 1))
fi

header "GitLab OmniAuth Config"
oidc_config=$(docker exec gitlab grep -c 'openid_connect' /etc/gitlab/gitlab.rb 2>/dev/null || echo "0")
if (( oidc_config > 0 )); then
  check "omniauth" "OIDC provider configured (found $oidc_config ref)" "$GREEN[PASS]"; PASS=$((PASS + 1))
else
  check "omniauth" "OIDC provider not configured" "$RED[FAIL]"; FAIL=$((FAIL + 1))
fi

header "GitLab Login Page"
kc_button=$(curl -s http://localhost/users/sign_in 2>/dev/null | grep -c "Keycloak" || true)
if (( kc_button > 0 )); then
  check "login" "Keycloak button on login page" "$GREEN[PASS]"; PASS=$((PASS + 1))
else
  check "login" "Keycloak button missing" "$RED[FAIL]"; FAIL=$((FAIL + 1))
fi

header "GitLab Groups"
for g in gitlab-admins gitlab-developers gitlab-viewers; do
  exists=$(curl -s "http://localhost/api/v4/groups?search=$g" -H "PRIVATE-TOKEN: glpat-uyTtfbshu1wUzA5sBd4y" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if any(x['path']=='$g' for x in d) else 'no')" 2>/dev/null || echo "no")
  if [[ "$exists" == "yes" ]]; then
    check "groups" "$g group exists" "$GREEN[PASS]"; PASS=$((PASS + 1))
  else
    check "groups" "$g group missing" "$YELLOW[WARN]"; WARN=$((WARN + 1))
  fi
done

echo -e "\n${CYAN}================================${NC}"
echo -e "  Summary: ${GREEN}$PASS passed${NC} ${YELLOW}$WARN warnings${NC} ${RED}$FAIL failed${NC}"
echo -e "${CYAN}================================${NC}\n"
exit $FAIL
