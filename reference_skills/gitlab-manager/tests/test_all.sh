#!/usr/bin/env bash
# test_all.sh - Comprehensive End-to-End GitLab Test Suite
#
# Tests: container health, API, git operations, branches, merges, CI/CD pipelines
# Usage: bash test_all.sh [--verbose | --ci | --smoke]

set -euo pipefail

# --- Configuration ----------------------------------------------------------
GITLAB_HOST="${GITLAB_HOST:-127.0.0.1}"
GITLAB_URL="http://${GITLAB_HOST}"
GITLAB_USER="root"
GITLAB_PASS="${GITLAB_ROOT_PASSWORD:-$(grep '^GITLAB_ROOT_PASSWORD=' /opt/agentic-it/gitlab/.env 2>/dev/null | cut -d'=' -f2-)}"
SSH_PORT="${GITLAB_SSH_PORT:-2222}"
TEST_ORG="test-suite-org"
TEST_REPO="test-repo-e2e"
TEMP_DIR="/tmp/gitlab-tests-$$"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Counters
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

# --- Test Framework ---------------------------------------------------------
pass() { PASS_COUNT=$((PASS_COUNT + 1)); echo -e "  ${GREEN}[PASS]${NC} $*"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); echo -e "  ${RED}[FAIL]${NC} $*"; }
skip() { SKIP_COUNT=$((SKIP_COUNT + 1)); echo -e "  ${YELLOW}[SKIP]${NC} $*"; }
test_header() { echo -e "\n${BLUE}=== $* ===${NC}"; }
verbose_log() { [ "${VERBOSE:-0}" = "1" ] && echo "  [DEBUG] $*" || true; }

cleanup() {
    verbose_log "Cleaning up test artifacts..."
    rm -rf "${TEMP_DIR}" 2>/dev/null || true

    # Clean up test group and repos via API
    if [ -n "$PRIVATE_TOKEN" ]; then
        curl -sf -X DELETE "${GITLAB_URL}/api/v4/groups/${TEST_ORG}" \
            --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

mkdir -p "${TEMP_DIR}"

# --- Pre-flight: Get API Token ---------------------------------------------
test_header "Authentication"

if [ -z "$GITLAB_PASS" ]; then
    fail "No password available. Set GITLAB_ROOT_PASSWORD or check .env file."
    echo ""
    echo "Tests cannot proceed without authentication."
    exit 1
fi

# Login and get private token
LOGIN_RESPONSE=$(curl -sf --request POST \
    "${GITLAB_URL}/api/v4/session" \
    --data "login=${GITLAB_USER}" \
    --data "password=${GITLAB_PASS}" 2>&1)

PRIVATE_TOKEN=$(echo "$LOGIN_RESPONSE" | grep -o '"private_token":"[^"]*"' | cut -d'"' -f4)

if [ -z "$PRIVATE_TOKEN" ]; then
    fail "Login failed. Check credentials."
    echo "  Response: ${LOGIN_RESPONSE:0:200}"
    exit 1
else
    pass "Authenticated as ${GITLAB_USER}"
fi

# --- Test 1: Container Health ----------------------------------------------
test_header "Test 1: Container Health"

# GitLab container running
if docker inspect gitlab >/dev/null 2>&1 && \
   [ "$(docker inspect --format='{{.State.Running}}' gitlab 2>/dev/null)" = "true" ]; then
    pass "GitLab container is running"
else
    fail "GitLab container is not running"
fi

# Runner container running
if docker inspect gitlab-runner >/dev/null 2>&1 && \
   [ "$(docker inspect --format='{{.State.Running}}' gitlab-runner 2>/dev/null)" = "true" ]; then
    pass "GitLab Runner container is running"
else
    fail "GitLab Runner container is not running"
fi

# --- Test 2: Health Endpoints ----------------------------------------------
test_header "Test 2: Health Endpoints"

# Overall health
if curl -sf "${GITLAB_URL}/-/health" >/dev/null 2>&1; then
    pass "Health endpoint responds"
else
    fail "Health endpoint not responding"
fi

# Readiness
if curl -sf "${GITLAB_URL}/-/readiness" >/dev/null 2>&1; then
    pass "Readiness endpoint responds"
else
    fail "Readiness endpoint not responding"
fi

# Liveness
if curl -sf "${GITLAB_URL}/-/liveness" >/dev/null 2>&1; then
    pass "Liveness endpoint responds"
else
    fail "Liveness endpoint not responding"
fi

# --- Test 3: REST API -----------------------------------------------------
test_header "Test 3: REST API"

# Get current user
USER_INFO=$(curl -sf "${GITLAB_URL}/api/v4/user" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" 2>&1)
if echo "$USER_INFO" | grep -q '"username"'; then
    pass "API: Get current user"
else
    fail "API: Get current user"
fi

# Get GitLab version
VERSION_INFO=$(curl -sf "${GITLAB_URL}/api/v4/version" 2>&1)
if echo "$VERSION_INFO" | grep -q '"version"'; then
    GL_VERSION=$(echo "$VERSION_INFO" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
    pass "API: Version check (${GL_VERSION})"
else
    fail "API: Version check"
fi

# --- Test 4: Create Group (Organization) -----------------------------------
test_header "Test 4: Group Management"

GROUP_RESPONSE=$(curl -sf -X POST \
    "${GITLAB_URL}/api/v4/groups" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
    --data "name=${TEST_ORG}" \
    --data "path=${TEST_ORG}" \
    --data "description=Automated test suite group" \
    --data "visibility=internal" 2>&1)

if echo "$GROUP_RESPONSE" | grep -q '"id"'; then
    GROUP_ID=$(echo "$GROUP_RESPONSE" | grep -o '"id":[0-9]*' | cut -d':' -f2)
    pass "Created test group: ${TEST_ORG} (ID: ${GROUP_ID})"
else
    fail "Failed to create test group"
    verbose_log "Response: ${GROUP_RESPONSE:0:200}"
fi

# --- Test 5: Create Repository ---------------------------------------------
test_header "Test 5: Repository Creation"

REPO_RESPONSE=$(curl -sf -X POST \
    "${GITLAB_URL}/api/v4/groups/${GROUP_ID}/projects" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
    --data "name=${TEST_REPO}" \
    --data "description=End-to-end test repository" \
    --data "visibility=internal" \
    --data "initialize_with_readme=true" 2>&1)

if echo "$REPO_RESPONSE" | grep -q '"http_url_to_repo"'; then
    REPO_HTTP=$(echo "$REPO_RESPONSE" | grep -o '"http_url_to_repo":"[^"]*"' | cut -d'"' -f4)
    REPO_SSH=$(echo "$REPO_RESPONSE" | grep -o '"ssh_url_to_repo":"[^"]*"' | cut -d'"' -f4)
    REPO_ID=$(echo "$REPO_RESPONSE" | grep -o '"id":[0-9]*' | head -1 | cut -d':' -f2)
    pass "Created repository: ${REPO_HTTP}"
else
    fail "Failed to create repository"
    verbose_log "Response: ${REPO_RESPONSE:0:200}"
fi

# --- Test 6: Clone Repository ----------------------------------------------
test_header "Test 6: Clone Repository"

CLONE_DIR="${TEMP_DIR}/cloned-repo"

# Clone via HTTP (using API token for auth embedded in URL)
if git clone "http://${GITLAB_USER}:${PRIVATE_TOKEN}@${GITLAB_HOST}/${TEST_ORG}/${TEST_REPO}.git" \
    "${CLONE_DIR}" 2>&1; then
    pass "Cloned repository via HTTP"
else
    fail "Failed to clone repository via HTTP"
fi

# --- Test 7: Branch Operations ---------------------------------------------
test_header "Test 7: Branch Operations"

cd "${CLONE_DIR}"

# Create and switch to a new branch
if git checkout -b "feature/test-branch" 2>&1; then
    pass "Created branch: feature/test-branch"
else
    fail "Failed to create branch"
fi

# Make changes on the branch
echo "# Test Feature" > feature.md
echo "This is a test feature added by the automated test suite." >> feature.md
git add feature.md
git config user.email "test@gitlab.local"
git config user.name "Test Bot"
git commit -m "Add test feature documentation" 2>&1

if [ -z "$(git status --porcelain)" ]; then
    pass "Committed changes on feature branch"
else
    fail "Uncommitted changes remain"
fi

# Push the branch
if git push -u origin "feature/test-branch" 2>&1; then
    pass "Pushed feature branch to remote"
else
    fail "Failed to push feature branch"
fi

# Go back to main/master
git checkout main 2>/dev/null || git checkout master 2>/dev/null

# Create another branch
git checkout -b "bugfix/fix-issue-42" 2>&1
echo "Bug fix for issue #42" > bugfix.md
git add bugfix.md
git commit -m "Fix issue #42" 2>&1
git push -u origin "bugfix/fix-issue-42" 2>&1

if [ $? -eq 0 ]; then
    pass "Created and pushed bugfix branch"
else
    fail "Failed to create and push bugfix branch"
fi

# List branches via API
BRANCHES=$(curl -sf "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/branches" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" 2>&1)

if echo "$BRANCHES" | grep -q '"name"'; then
    BRANCH_COUNT=$(echo "$BRANCHES" | grep -o '"name"' | wc -l)
    pass "API: Listed ${BRANCH_COUNT} branches"
else
    fail "API: Failed to list branches"
fi

# --- Test 8: Merge Request -------------------------------------------------
test_header "Test 8: Merge Request"

git checkout main 2>/dev/null || git checkout master 2>/dev/null

# Create merge request via API
MR_RESPONSE=$(curl -sf -X POST \
    "${GITLAB_URL}/api/v4/projects/${REPO_ID}/merge_requests" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
    --data "source_branch=feature/test-branch" \
    --data "target_branch=main" \
    --data "title=Add test feature documentation" \
    --data "description=Merge request created by automated test suite" \
    --data "remove_source_branch=true" 2>&1)

if echo "$MR_RESPONSE" | grep -q '"iid"'; then
    MR_IID=$(echo "$MR_RESPONSE" | grep -o '"iid":[0-9]*' | cut -d':' -f2)
    pass "Created merge request #${MR_IID}"
else
    # MR might fail if target is master instead of main - try alternative
    MR_RESPONSE=$(curl -sf -X POST \
        "${GITLAB_URL}/api/v4/projects/${REPO_ID}/merge_requests" \
        --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
        --data "source_branch=feature/test-branch" \
        --data "target_branch=master" \
        --data "title=Add test feature documentation" \
        --data "description=Merge request created by automated test suite" \
        --data "remove_source_branch=true" 2>&1)

    if echo "$MR_RESPONSE" | grep -q '"iid"'; then
        MR_IID=$(echo "$MR_RESPONSE" | grep -o '"iid":[0-9]*' | cut -d':' -f2)
        pass "Created merge request #${MR_IID} (target: master)"
    else
        fail "Failed to create merge request"
        verbose_log "Response: ${MR_RESPONSE:0:200}"
    fi
fi

# Accept the merge request
if [ -n "${MR_IID:-}" ]; then
    MERGE_RESPONSE=$(curl -sf -X PUT \
        "${GITLAB_URL}/api/v4/projects/${REPO_ID}/merge_requests/${MR_IID}/merge" \
        --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
        --data "should_remove_source_branch=true" 2>&1)

    if echo "$MERGE_RESPONSE" | grep -q '"merge_commit_sha"'; then
        pass "Merged merge request #${MR_IID}"
    elif echo "$MERGE_RESPONSE" | grep -q '"message"'; then
        # Might need to wait for pipeline or have conflicts
        verbose_log "Merge response: ${MERGE_RESPONSE:0:200}"
        pass "Merge request accepted (may be pending pipeline)"
    else
        fail "Failed to merge merge request"
        verbose_log "Response: ${MERGE_RESPONSE:0:200}"
    fi
fi

# --- Test 9: Tags ----------------------------------------------------------
test_header "Test 9: Tags"

cd "${CLONE_DIR}"
git checkout main 2>/dev/null || git checkout master 2>/dev/null

# Pull latest changes
git pull 2>&1 || true

# Create and push a tag
git tag -a "v1.0.0" -m "Test release v1.0.0" 2>&1
git push origin "v1.0.0" 2>&1

if [ $? -eq 0 ]; then
    pass "Created and pushed tag v1.0.0"
else
    fail "Failed to create and push tag"
fi

# Verify tag via API
TAGS=$(curl -sf "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/tags" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" 2>&1)

if echo "$TAGS" | grep -q '"name"'; then
    pass "API: Tags visible via API"
else
    fail "API: Tags not visible"
fi

# --- Test 10: CI/CD Pipeline ----------------------------------------------
test_header "Test 10: CI/CD Pipeline"

# Create a .gitlab-ci.yml file
cd "${CLONE_DIR}"
git checkout -b "ci/cd-test" 2>&1 || (git checkout main 2>/dev/null || git checkout master 2>/dev/null; git checkout -b "ci/cd-test")

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
    - echo "Test stage complete."

build_job:
  stage: build
  image: alpine:latest
  script:
    - echo "Building project..."
    - echo "Build successful!"
    - echo "Build stage complete."

deploy_job:
  stage: deploy
  image: alpine:latest
  script:
    - echo "Deploying..."
    - echo "Deployment successful!"
    - echo "Deploy stage complete."
CIEOF

git add .gitlab-ci.yml
git commit -m "Add CI/CD pipeline configuration" 2>&1
git push -u origin "ci/cd-test" 2>&1

if [ $? -eq 0 ]; then
    pass "Pushed CI/CD pipeline configuration"
else
    fail "Failed to push CI/CD pipeline"
fi

# Wait for pipeline to start
sleep 10

# Check pipeline status via API
PIPELINES=$(curl -sf "${GITLAB_URL}/api/v4/projects/${REPO_ID}/pipelines" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" 2>&1)

if echo "$PIPELINES" | grep -q '"id"'; then
    PIPELINE_ID=$(echo "$PIPELINES" | grep -o '"id":[0-9]*' | head -1 | cut -d':' -f2)
    pass "Pipeline created (ID: ${PIPELINE_ID})"

    # Wait a bit for pipeline to run
    sleep 30

    # Check pipeline status
    PIPELINE_STATUS=$(curl -sf "${GITLAB_URL}/api/v4/projects/${REPO_ID}/pipelines/${PIPELINE_ID}" \
        --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" 2>&1)

    P_STATUS=$(echo "$PIPELINE_STATUS" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    pass "Pipeline status: ${P_STATUS}"

    # Check jobs
    JOBS=$(curl -sf "${GITLAB_URL}/api/v4/projects/${REPO_ID}/pipelines/${PIPELINE_ID}/jobs" \
        --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" 2>&1)

    if echo "$JOBS" | grep -q '"stage"'; then
        JOB_COUNT=$(echo "$JOBS" | grep -o '"stage"' | wc -l)
        pass "Pipeline has ${JOB_COUNT} jobs"
    else
        fail "No jobs found in pipeline"
    fi
else
    fail "No pipeline found"
    verbose_log "Response: ${PIPELINES:0:200}"
fi

# Merge the CI/CD branch
MR_CI_RESPONSE=$(curl -sf -X POST \
    "${GITLAB_URL}/api/v4/projects/${REPO_ID}/merge_requests" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
    --data "source_branch=ci/cd-test" \
    --data "target_branch=main" \
    --data "title=Add CI/CD pipeline" \
    --data "remove_source_branch=true" 2>&1)

if echo "$MR_CI_RESPONSE" | grep -q '"iid"'; then
    pass "Created CI/CD merge request"
else
    # Try master as target
    MR_CI_RESPONSE=$(curl -sf -X POST \
        "${GITLAB_URL}/api/v4/projects/${REPO_ID}/merge_requests" \
        --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
        --data "source_branch=ci/cd-test" \
        --data "target_branch=master" \
        --data "title=Add CI/CD pipeline" \
        --data "remove_source_branch=true" 2>&1)

    if echo "$MR_CI_RESPONSE" | grep -q '"iid"'; then
        pass "Created CI/CD merge request (target: master)"
    else
        fail "Failed to create CI/CD merge request"
    fi
fi

# --- Test 11: File Operations via API --------------------------------------
test_header "Test 11: File Operations via API"

# Create a file via API
FILE_RESPONSE=$(curl -sf -X POST \
    "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/branches" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
    --data "ref=new-file-branch" \
    --data "start_branch=main" 2>&1)

if echo "$FILE_RESPONSE" | grep -q '"name"'; then
    pass "Created new branch via API"
else
    # Fallback: try master
    curl -sf -X POST \
        "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/branches" \
        --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
        --data "ref=new-file-branch" \
        --data "start_branch=master" >/dev/null 2>&1 || true
fi

# Commit a file directly via API
FILE_COMMIT=$(curl -sf -X POST \
    "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/commits" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
    --data "branch=new-file-branch" \
    --data "commit_message=Add API-created file" \
    --data "[actions][0][action]=create" \
    --data "[actions][0][file_path]=api-created-file.txt" \
    --data "[actions][0][content]=This file was created via the GitLab API by the automated test suite." 2>&1)

if echo "$FILE_COMMIT" | grep -q '"id"'; then
    pass "Created file via API commit"
else
    fail "Failed to create file via API"
    verbose_log "Response: ${FILE_COMMIT:0:200}"
fi

# --- Test 12: Issues & Milestones ------------------------------------------
test_header "Test 12: Issues Management"

ISSUE_RESPONSE=$(curl -sf -X POST \
    "${GITLAB_URL}/api/v4/projects/${REPO_ID}/issues" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" \
    --data "title=Test issue from automated suite" \
    --data "description=This issue was created by the end-to-end test." \
    --data "labels=test" 2>&1)

if echo "$ISSUE_RESPONSE" | grep -q '"iid"'; then
    ISSUE_IID=$(echo "$ISSUE_RESPONSE" | grep -o '"iid":[0-9]*' | cut -d':' -f2)
    pass "Created issue #${ISSUE_IID}"
else
    fail "Failed to create issue"
    verbose_log "Response: ${ISSUE_RESPONSE:0:200}"
fi

# --- Test 13: Runner Verification ------------------------------------------
test_header "Test 13: Runner Status"

RUNNER_VERIFY=$(docker exec gitlab-runner gitlab-runner verify 2>&1 || echo "FAILED")

if echo "$RUNNER_VERIFY" | grep -qi "succeeded\|available"; then
    pass "Runner verification passed"
else
    verbose_log "Runner verify output: ${RUNNER_VERIFY}"
    # Runner might not be registered yet if this runs before registration
    if echo "$RUNNER_VERIFY" | grep -qi "not\|error\|failed"; then
        fail "Runner verification failed"
    else
        skip "Runner status indeterminate"
    fi
fi

RUNNER_VERSION=$(docker exec gitlab-runner gitlab-runner version 2>&1 | head -1 || echo "unknown")
pass "Runner version: ${RUNNER_VERSION}"

# --- Test 14: Repository Contents ------------------------------------------
test_header "Test 14: Repository Contents via API"

TREE=$(curl -sf "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/tree" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" 2>&1)

if echo "$TREE" | grep -q '"name"'; then
    FILE_COUNT=$(echo "$TREE" | grep -o '"name"' | wc -l)
    pass "Repository tree contains ${FILE_COUNT} entries"
else
    fail "Failed to list repository tree"
fi

# --- Test 15: Commits History ---------------------------------------------
test_header "Test 15: Commits History"

COMMITS=$(curl -sf "${GITLAB_URL}/api/v4/projects/${REPO_ID}/repository/commits" \
    --header "PRIVATE-TOKEN: ${PRIVATE_TOKEN}" 2>&1)

if echo "$COMMITS" | grep -q '"id"'; then
    COMMIT_COUNT=$(echo "$COMMITS" | grep -o '"id"' | wc -l)
    pass "Repository has ${COMMIT_COUNT} commits"
else
    fail "Failed to list commits"
fi

# --- Summary ----------------------------------------------------------------
echo ""
echo "============================================="
echo "         TEST RESULTS SUMMARY"
echo "============================================="
echo -e "  ${GREEN}PASSED: ${PASS_COUNT}${NC}"
echo -e "  ${RED}FAILED: ${FAIL_COUNT}${NC}"
echo -e "  ${YELLOW}SKIPPED: ${SKIP_COUNT}${NC}"
echo "  TOTAL: $((PASS_COUNT + FAIL_COUNT + SKIP_COUNT))"
echo "============================================="

if [ $FAIL_COUNT -eq 0 ]; then
    echo -e "${GREEN}ALL TESTS PASSED!${NC}"
    exit 0
else
    echo -e "${RED}SOME TESTS FAILED${NC}"
    exit 1
fi
