#!/usr/bin/env bash
# test_integration.sh - E2E test suite for GitLab + Keycloak OIDC integration
# Tests: OIDC endpoints, auth flows, GitLab operations, fail-safety
set -euo pipefail

TOTAL=0; PASS=0; FAIL=0; SKIP=0
GITLAB_PAT="${GITLAB_PAT:-glpat-uyTtfbshu1wUzA5sBd4y}"
GITLAB_URL="http://localhost"
KC_URL="https://localhost:8443"

assert() { local name="$1"; result="$2"; msg="$3";
  TOTAL=$((TOTAL + 1));
  if [[ "$result" == "0" ]]; then echo "  PASS: $name"; PASS=$((PASS + 1))
  else echo "  FAIL: $name - $msg"; FAIL=$((FAIL + 1)); fi;
}

assert_skip() { local name="$1"; TOTAL=$((TOTAL + 1)); SKIP=$((SKIP + 1)); echo "  SKIP: $name"; }

echo "========================================"
echo " GitLab + Keycloak Integration Tests"
echo "========================================"

# --- TEST 1: Keycloak container health ---
echo -e "\n[Group] Keycloak Health"
set +e; docker inspect --format='{{.State.Status}}' keycloak 2>/dev/null | grep -q running; rc=$?; set -e
assert "Keycloak container running" "$rc" "container not running"

set +e; curl -sk "$KC_URL/realms/gitlab/.well-known/openid-configuration" -o /dev/null -w "%{http_code}" 2>/dev/null | grep -q 200; rc=$?; set -e
assert "OIDC discovery endpoint 200" "$rc" "discovery endpoint failed"

set +e; curl -sk "$KC_URL/realms/gitlab/.well-known/openid-configuration" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'https' in d['issuer']; sys.exit(0)" 2>/dev/null; rc=$?; set -e
assert "Issuer URL is HTTPS" "$rc" "issuer not HTTPS"

set +e; curl -sk "$KC_URL/realms/gitlab/.well-known/openid-configuration" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'authorization_endpoint' in d; sys.exit(0)" 2>/dev/null; rc=$?; set -e
assert "Authorization endpoint present" "$rc" "missing auth endpoint"

set +e; curl -sk "$KC_URL/realms/gitlab/.well-known/openid-configuration" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'token_endpoint' in d; sys.exit(0)" 2>/dev/null; rc=$?; set -e
assert "Token endpoint present" "$rc" "missing token endpoint"

set +e; curl -sk "$KC_URL/realms/gitlab/.well-known/openid-configuration" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'userinfo_endpoint' in d; sys.exit(0)" 2>/dev/null; rc=$?; set -e
assert "UserInfo endpoint present" "$rc" "missing userinfo endpoint"

# --- TEST 2: Nginx proxy health ---
echo -e "\n[Group] Nginx Proxy"
set +e; docker inspect --format='{{.State.Status}}' keycloak-nginx 2>/dev/null | grep -q running; rc=$?; set -e
assert "Nginx container running" "$rc" "nginx not running"

set +e; curl -sk "$KC_URL/nginx-health" 2>/dev/null | grep -q ok; rc=$?; set -e
assert "Nginx health endpoint" "$rc" "health check failed"

set +e; curl -sk "$KC_URL/realms/gitlab" -o /dev/null -w "%{http_code}" 2>/dev/null | grep -q 200; rc=$?; set -e
assert "Keycloak via proxy 200" "$rc" "proxy returned error"

# --- TEST 3: GitLab services ---
echo -e "\n[Group] GitLab Services"
set +e; docker inspect --format='{{.State.Status}}' gitlab 2>/dev/null | grep -q running; rc=$?; set -e
assert "GitLab container running" "$rc" "gitlab not running"

set +e; gl_status=$(docker exec gitlab gitlab-ctl status 2>/dev/null); echo "$gl_status" | grep -q "run:"; rc=$?; set -e
assert "GitLab services running" "$rc" "services down"

set +e; curl -s "$GITLAB_URL/users/sign_in" 2>/dev/null | grep -q "Sign in"; rc=$?; set -e
assert "GitLab login page loads" "$rc" "login page failed"

# --- TEST 4: OIDC integration ---
echo -e "\n[Group] OIDC Integration"
set +e; curl -s "$GITLAB_URL/users/sign_in" 2>/dev/null | grep -q "Keycloak"; rc=$?; set -e
assert "Keycloak button on login page" "$rc" "button missing"

set +e; curl -s "$GITLAB_URL/users/sign_in" 2>/dev/null | grep -q "openid_connect"; rc=$?; set -e
assert "OIDC form action present" "$rc" "form action missing"

set +e; docker exec gitlab grep -q 'openid_connect' /etc/gitlab/gitlab.rb 2>/dev/null; rc=$?; set -e
assert "OIDC in gitlab.rb" "$rc" "not configured"

set +e; docker exec gitlab grep -q 'keycloak.internal:8443' /etc/gitlab/gitlab.rb 2>/dev/null; rc=$?; set -e
assert "Correct issuer in config" "$rc" "wrong issuer"

set +e; docker exec gitlab grep -q 'omniauth_enabled.*true' /etc/gitlab/gitlab.rb 2>/dev/null; rc=$?; set -e
assert "OmniAuth enabled" "$rc" "omniauth disabled"

set +e; docker exec gitlab grep -q 'omniauth_block_auto_created_users.*true' /etc/gitlab/gitlab.rb 2>/dev/null; rc=$?; set -e
assert "Auto-created users blocked" "$rc" "not blocked"

# --- TEST 5: GitLab groups and projects ---
echo -e "\n[Group] GitLab Groups & Projects"
set +e; curl -s "$GITLAB_URL/api/v4/groups?search=gitlab-admins" -H "PRIVATE-TOKEN: $GITLAB_PAT" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); assert any(x['path']=='gitlab-admins' for x in d); sys.exit(0)" 2>/dev/null; rc=$?; set -e
assert "gitlab-admins group exists" "$rc" "group not found"

set +e; curl -s "$GITLAB_URL/api/v4/groups?search=gitlab-developers" -H "PRIVATE-TOKEN: $GITLAB_PAT" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); assert any(x['path']=='gitlab-developers' for x in d); sys.exit(0)" 2>/dev/null; rc=$?; set -e
assert "gitlab-developers group exists" "$rc" "group not found"

set +e; curl -s "$GITLAB_URL/api/v4/groups?search=gitlab-viewers" -H "PRIVATE-TOKEN: $GITLAB_PAT" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); assert any(x['path']=='gitlab-viewers' for x in d); sys.exit(0)" 2>/dev/null; rc=$?; set -e
assert "gitlab-viewers group exists" "$rc" "group not found"

# --- TEST 6: Protected branches ---
echo -e "\n[Group] Protected Branches"
set +e; PROJECT_ID=$(curl -s "$GITLAB_URL/api/v4/projects?search=test-project" -H "PRIVATE-TOKEN: $GITLAB_PAT" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print([x['id'] for x in d if x['name']=='test-project'][0])" 2>/dev/null)
if [[ -n "$PROJECT_ID" ]]; then
  set +e; curl -s "$GITLAB_URL/api/v4/projects/$PROJECT_ID/protected_branches" -H "PRIVATE-TOKEN: $GITLAB_PAT" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); assert any(x['name']=='main' for x in d); sys.exit(0)" 2>/dev/null; rc=$?; set -e
  assert "main branch protected" "$rc" "main not protected"

  set +e; curl -s "$GITLAB_URL/api/v4/projects/$PROJECT_ID/protected_branches" -H "PRIVATE-TOKEN: $GITLAB_PAT" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); assert any(x['name']=='develop' for x in d); sys.exit(0)" 2>/dev/null; rc=$?; set -e
  assert "develop branch protected" "$rc" "develop not protected"
else
  assert_skip "Protected branches (project not found)"
fi

# --- TEST 7: CI/CD pipeline ---
echo -e "\n[Group] CI/CD Pipeline"
if [[ -n "${PROJECT_ID:-}" ]]; then
  set +e; curl -s "$GITLAB_URL/api/v4/projects/$PROJECT_ID/repository/files/.gitlab-ci.yml/raw?ref=main" -H "PRIVATE-TOKEN: $GITLAB_PAT" 2>/dev/null | grep -q "stages:"; rc=$?; set -e
  assert ".gitlab-ci.yml exists with stages" "$rc" "CI file missing"
else
  assert_skip "CI/CD pipeline (project not found)"
fi

# --- TEST 8: Fail-safety ---
echo -e "\n[Group] Fail-Safety"
set +e; docker exec gitlab curl -s http://localhost/users/sign_in 2>/dev/null | grep -q "Sign in"; rc=$?; set -e
assert "GitLab works without proxy" "$rc" "GitLab depends on proxy"

set +e; curl -sL http://localhost:8080 2>/dev/null | grep -qi "login\|account\|keycloak"; rc=$?; set -e
assert "Keycloak accessible on 8080" "$rc" "direct access broken"

# --- TEST 9: GitLab Runner ---
echo -e "\n[Group] GitLab Runner"
set +e; docker inspect --format='{{.State.Status}}' gitlab-runner 2>/dev/null | grep -q running; rc=$?; set -e
assert "GitLab Runner running" "$rc" "runner not running"

echo -e "\n========================================"
echo -e " Total: $TOTAL | Passed: $PASS | Failed: $FAIL | Skipped: $SKIP"
echo "========================================"
exit $FAIL
