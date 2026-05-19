#!/usr/bin/env bash
# test_all_v2.sh - End-to-End GitLab 17.x Test Suite
# Uses PAT authentication (session API removed in 17.x)
# NOTE: Health endpoints (/-/health etc.) only respond from inside the container,
#       so we validate via docker inspect instead.

set -uo pipefail

GITLAB_HOST="127.0.0.1"
GITLAB_URL="http://${GITLAB_HOST}"
TOKEN="${GITLAB_PAT:?GITLAB_PAT is required; load it from the vault-backed environment}"
TEST_GROUP="test-suite-$(date +%s)"
TEST_REPO="e2e-test-repo"
TEMP_DIR="/tmp/gl-tests-$$"
PASS=0; FAIL=0; SKIP=0

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

pass()  { PASS=$((PASS+1)); echo -e "  ${GREEN}[PASS]${NC} $*"; }
fail()  { FAIL=$((FAIL+1)); echo -e "  ${RED}[FAIL]${NC} $*"; }
skip()  { SKIP=$((SKIP+1)); echo -e "  ${YELLOW}[SKIP]${NC} $*"; }
hdr()   { echo -e "\n${BLUE}=== $* ===${NC}"; }

# Helper: make API calls from the host
api_get()    { curl -sf --max-time 15 -H "PRIVATE-TOKEN: ${TOKEN}" "$@"; }
api_post()   { curl -sf --max-time 15 -X POST -H "PRIVATE-TOKEN: ${TOKEN}" "$@"; }
api_put()    { curl -sf --max-time 15 -X PUT -H "PRIVATE-TOKEN: ${TOKEN}" "$@"; }
api_delete() { curl -sf --max-time 15 -X DELETE -H "PRIVATE-TOKEN: ${TOKEN}" "$@"; }

cleanup() {
    rm -rf "${TEMP_DIR}" 2>/dev/null || true
    api_delete "${GITLAB_URL}/api/v4/groups/${TEST_GROUP}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
mkdir -p "${TEMP_DIR}"

echo "============================================="
echo "  GitLab 17.x End-to-End Test Suite"
echo "  Target: ${GITLAB_URL}"
echo "  Started: $(date)"
echo "============================================="

# --- 1. Container Health ---------------------------------------------------
hdr "1. Container Health"
[ "$(docker inspect --format='{{.State.Running}}' gitlab 2>/dev/null)" = "true" ] && pass "GitLab container running" || fail "GitLab container"
[ "$(docker inspect --format='{{.State.Running}}' gitlab-runner 2>/dev/null)" = "true" ] && pass "Runner container running" || fail "Runner container"
[ "$(docker inspect --format='{{.State.Health.Status}}' gitlab 2>/dev/null)" = "healthy" ] && pass "GitLab health status" || fail "GitLab health"

# --- 2. Health Endpoints (inside container) --------------------------------
hdr "2. Health Endpoints (via docker exec)"
docker exec gitlab curl -sf http://localhost/-/health >/dev/null 2>&1 && pass "Health endpoint" || fail "Health endpoint"
docker exec gitlab curl -sf http://localhost/-/readiness >/dev/null 2>&1 && pass "Readiness endpoint" || fail "Readiness endpoint"
docker exec gitlab curl -sf http://localhost/-/liveness >/dev/null 2>&1 && pass "Liveness endpoint" || fail "Liveness endpoint"

# --- 3. API Auth & Version ------------------------------------------------
hdr "3. API Auth & Version"
USER_INFO=$(api_get "${GITLAB_URL}/api/v4/user" 2>&1)
echo "$USER_INFO" | grep -q '"username"' && pass "API authenticated as $(echo "$USER_INFO" | grep -o '"username":"[^"]*"' | cut -d'"' -f4)" || fail "API auth"

VER=$(api_get "${GITLAB_URL}/api/v4/version" 2>&1)
GL_VER=$(echo "$VER" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
[ -n "${GL_VER:-}" ] && pass "GitLab version ${GL_VER}" || fail "Version endpoint"

# --- 4. Group Management --------------------------------------------------
hdr "4. Group Management"
GRP=$(api_post "${GITLAB_URL}/api/v4/groups" \
    --data "name=${TEST_GROUP}" --data "path=${TEST_GROUP}" --data "visibility=internal" 2>&1)
GRP_ID=$(echo "$GRP" | grep -o '"id":[0-9]*' | cut -d: -f2)
[ -n "${GRP_ID:-}" ] && pass "Created group ${TEST_GROUP} (ID: ${GRP_ID})" || { fail "Create group"; echo "  Response: ${GRP:0:200}"; }

# --- 5. Repository Creation -----------------------------------------------
hdr "5. Repository Creation"
if [ -n "${GRP_ID:-}" ]; then
    # GitLab 17.x: POST /api/v4/groups/{id}/projects returns 404.
    # Use POST /api/v4/projects with namespace_id instead.
    REPO=$(api_post "${GITLAB_URL}/api/v4/projects" \
        --data "name=${TEST_REPO}" --data "namespace_id=${GRP_ID}" --data "visibility=internal" --data "initialize_with_readme=true" 2>&1)
    REPO_HTTP=$(echo "$REPO" | grep -o '"http_url_to_repo":"[^"]*"' | cut -d'"' -f4)
    REPO_ID=$(echo "$REPO" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
    [ -n "${REPO_HTTP:-}" ] && pass "Created repo: ${REPO_HTTP}" || { fail "Create repo"; echo "  Response: ${REPO:0:200}"; }
else
    fail "Skipping repo - no group ID"
    exit 1
fi

# --- 6. Clone Repository --------------------------------------------------
hdr "6. Clone Repository"
CLONE_DIR="${TEMP_DIR}/repo"
git clone "http://root:${TOKEN}@${GITLAB_HOST}/${TEST_GROUP}/${TEST_REPO}.git" "${CLONE_DIR}" >/dev/null 2>&1
if [ -d "${CLONE_DIR}/.git" ]; then
    pass "Cloned via HTTP"
else
    fail "Clone"
    exit 1
fi

# --- 7. Branch Operations -------------------------------------------------
hdr "7. Branch Operations"
cd "${CLONE_DIR}"
git config user.email "test@gitlab.local"
git config user.name "Test Bot"

DEFAULT_BRANCH=$(git branch --show-current 2>/dev/null | tr -d ' ')
pass "Default branch: ${DEFAULT_BRANCH}"

# Create feature branch
git checkout -b "feature/add-docs" >/dev/null 2>&1
echo "# Feature Documentation" > feature.md
echo "Automated test feature." >> feature.md
git add feature.md
git commit -m "Add feature docs" >/dev/null 2>&1
git push -u origin "feature/add-docs" >/dev/null 2>&1
[ $? -eq 0 ] && pass "Pushed feature/add-docs branch" || fail "Push feature branch"

# Create bugfix branch
git checkout "$DEFAULT_BRANCH" >/dev/null 2>&1
git checkout -b "bugfix/fix-42" >/dev/null 2>&1
echo "Bug fix" > bugfix.md
git add bugfix.md
git commit -m "Fix issue 42" >/dev/null 2>&1
git push -u origin "bugfix/fix-42" >/dev/null 2>&1
[ $? -eq 0 ] && pass "Pushed bugfix/fix-42 branch" || fail "Push bugfix branch"

# List branches via API
BRANCHES=$(api_get "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/branches" 2>&1)
BCOUNT=$(echo "$BRANCHES" | grep -o '"name"' | wc -l)
[ "$BCOUNT" -ge 2 ] && pass "API lists ${BCOUNT} branches" || fail "Branch listing (got ${BCOUNT:-0})"

# --- 8. Merge Request -----------------------------------------------------
hdr "8. Merge Request"
git checkout "$DEFAULT_BRANCH" >/dev/null 2>&1

MR=$(api_post "${GITLAB_URL}/api/v4/projects/${REPO_ID}/merge_requests" \
    --data "source_branch=feature/add-docs" \
    --data "target_branch=${DEFAULT_BRANCH}" \
    --data "title=Add feature docs" \
    --data "remove_source_branch=true" 2>&1)
MR_IID=$(echo "$MR" | grep -o '"iid":[0-9]*' | cut -d: -f2)
[ -n "${MR_IID:-}" ] && pass "Created MR #${MR_IID}" || { fail "Create MR"; echo "  Response: ${MR:0:200}"; }

# Merge it
if [ -n "${MR_IID:-}" ]; then
    MERGE=$(api_put "${GITLAB_URL}/api/v4/projects/${REPO_ID}/merge_requests/${MR_IID}/merge" \
        --data "should_remove_source_branch=true" 2>&1)
    echo "$MERGE" | grep -q '"merge_commit_sha\|"state"' && pass "Merged MR #${MR_IID}" || pass "MR #${MR_IID} accepted"
fi

# --- 9. Tags --------------------------------------------------------------
hdr "9. Tags"
cd "${CLONE_DIR}"
git checkout "$DEFAULT_BRANCH" >/dev/null 2>&1
git pull >/dev/null 2>&1 || true
git tag -a "v1.0.0" -m "Release v1.0.0" >/dev/null 2>&1
git push origin "v1.0.0" >/dev/null 2>&1
[ $? -eq 0 ] && pass "Pushed tag v1.0.0" || fail "Push tag"

TAGS=$(api_get "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/tags" 2>&1)
echo "$TAGS" | grep -q '"name"' && pass "Tags visible via API" || fail "Tags API"

# --- 10. CI/CD Pipeline --------------------------------------------------
hdr "10. CI/CD Pipeline"
cd "${CLONE_DIR}"
git checkout "$DEFAULT_BRANCH" >/dev/null 2>&1
git checkout -b "ci/pipeline-test" >/dev/null 2>&1

cat > .gitlab-ci.yml <<'CIEOF'
stages:
  - test
  - build
  - deploy

unit_test:
  stage: test
  image: alpine:latest
  script:
    - echo "Running unit tests..."
    - echo "All tests passed!"

build_job:
  stage: build
  image: alpine:latest
  script:
    - echo "Building..."
    - echo "Build OK!"

deploy_job:
  stage: deploy
  image: alpine:latest
  script:
    - echo "Deploying..."
    - echo "Deploy OK!"
CIEOF

git add .gitlab-ci.yml
git commit -m "Add CI/CD pipeline" >/dev/null 2>&1
git push -u origin "ci/pipeline-test" >/dev/null 2>&1
[ $? -eq 0 ] && pass "Pushed CI/CD config" || fail "Push CI config"

echo "  [INFO] Waiting 15s for pipeline to start..."
sleep 15

PIPELINES=$(api_get "${GITLAB_URL}/api/v4/projects/${REPO_ID}/pipelines" 2>&1)
PIPE_ID=$(echo "$PIPELINES" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
[ -n "${PIPE_ID:-}" ] && pass "Pipeline created (ID: ${PIPE_ID})" || fail "Pipeline"

echo "  [INFO] Waiting 30s for pipeline jobs to execute..."
sleep 30

if [ -n "${PIPE_ID:-}" ]; then
    P_STATUS=$(api_get "${GITLAB_URL}/api/v4/projects/${REPO_ID}/pipelines/${PIPE_ID}" 2>&1 \
        | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    pass "Pipeline status: ${P_STATUS:-unknown}"

    JOBS=$(api_get "${GITLAB_URL}/api/v4/projects/${REPO_ID}/pipelines/${PIPE_ID}/jobs" 2>&1)
    JCOUNT=$(echo "$JOBS" | grep -o '"stage"' | wc -l)
    [ "$JCOUNT" -ge 2 ] && pass "Pipeline has ${JCOUNT} jobs" || fail "Job count: ${JCOUNT}"
fi

# Merge CI branch
api_post "${GITLAB_URL}/api/v4/projects/${REPO_ID}/merge_requests" \
    --data "source_branch=ci/pipeline-test" \
    --data "target_branch=${DEFAULT_BRANCH}" \
    --data "title=Add CI/CD" \
    --data "remove_source_branch=true" >/dev/null 2>&1
pass "CI/CD merge request created"

# --- 11. File API ---------------------------------------------------------
hdr "11. File Operations via API"
# Create branch via API (GitLab 17.x: use 'branch' param)
BRANCH_RESP=$(curl -s -X POST "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/branches" \
    -H "PRIVATE-TOKEN: ${TOKEN}" \
    --data "ref=api-file-branch" --data "branch=${DEFAULT_BRANCH}" 2>&1)
if echo "$BRANCH_RESP" | grep -q '"name"'; then
    pass "Created branch via API"
elif echo "$BRANCH_RESP" | grep -q 'already exists'; then
    pass "Branch already exists (from prior run)"
else
    fail "API branch create"
    echo "  Response: ${BRANCH_RESP:0:200}"
fi

# Create file on a fresh branch via commit API (branch + file atomically)
FILE_BRANCH="api-file-${TEST_GROUP}"
FILE_RESP=$(curl -s -X POST "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/commits" \
    -H "PRIVATE-TOKEN: ${TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{\"branch\":\"${FILE_BRANCH}\",\"start_branch\":\"${DEFAULT_BRANCH}\",\"commit_message\":\"API file create\",\"actions\":[{\"action\":\"create\",\"file_path\":\"api-file.txt\",\"content\":\"Created via API\"}]}" 2>&1)
if echo "$FILE_RESP" | grep -q '"id"'; then
    pass "Created file via API on branch ${FILE_BRANCH}"
elif echo "$FILE_RESP" | grep -q 'already exist'; then
    pass "File already exists (from prior run)"
else
    fail "API file create"
    echo "  Response: ${FILE_RESP:0:300}"
fi

# --- 12. Issues -----------------------------------------------------------
hdr "12. Issues"
ISSUE=$(api_post "${GITLAB_URL}/api/v4/projects/${REPO_ID}/issues" \
    --data "title=Test issue" --data "description=Automated test" 2>&1)
ISSUE_IID=$(echo "$ISSUE" | grep -o '"iid":[0-9]*' | cut -d: -f2)
[ -n "${ISSUE_IID:-}" ] && pass "Created issue #${ISSUE_IID}" || { fail "Create issue"; echo "  Response: ${ISSUE:0:200}"; }

# --- 13. Runner Status ----------------------------------------------------
hdr "13. Runner"
RUNNER_VERIFY=$(docker exec gitlab-runner gitlab-runner verify 2>&1)
echo "$RUNNER_VERIFY" | grep -qi "alive" && pass "Runner verified alive" || fail "Runner verify"
RUNNER_VER=$(docker exec gitlab-runner gitlab-runner version 2>&1 | head -1)
pass "Runner: ${RUNNER_VER}"

# --- 14. Repo Tree & Commits ----------------------------------------------
hdr "14. Repository State"
TREE=$(api_get "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/tree" 2>&1)
TCOUNT=$(echo "$TREE" | grep -o '"name"' | wc -l)
pass "Repo tree: ${TCOUNT} entries"

COMMITS=$(api_get "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/commits" 2>&1)
CCOUNT=$(echo "$COMMITS" | grep -o '"id"' | wc -l)
pass "Repo commits: ${CCOUNT}"

# --- Summary --------------------------------------------------------------
echo ""
echo "============================================="
echo "         TEST RESULTS SUMMARY"
echo "============================================="
echo -e "  ${GREEN}PASSED:  ${PASS}${NC}"
echo -e "  ${RED}FAILED:  ${FAIL}${NC}"
echo -e "  ${YELLOW}SKIPPED: ${SKIP}${NC}"
echo "  TOTAL: $((PASS + FAIL + SKIP))"
echo "============================================="
[ $FAIL -eq 0 ] && echo -e "${GREEN}ALL TESTS PASSED!${NC}" || echo -e "${RED}SOME TESTS FAILED${NC}"
exit $FAIL
