#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../credential-vault/scripts/load_secret.sh"
TOKEN="$(load_secret gitlab_manager_pat GITLAB_PAT GITLAB_PAT_FILE /home/gitlab/.gitlab-token)" || {
    echo "ERROR: No GitLab PAT found. Set GITLAB_PAT, GITLAB_PAT_FILE, or CREDMAN_PATH/GITLAB_PAT_VAULT_KEY." >&2
    exit 1
}
URL='http://127.0.0.1'

echo "=== Test: Create project with namespace_id ==="
curl -s -w '\nHTTP_CODE:%{http_code}' -X POST "$URL/api/v4/projects" \
    -H "PRIVATE-TOKEN: $TOKEN" \
    -d 'name=debug-namespace-project' \
    -d 'namespace_id=7' \
    -d 'visibility=internal' \
    -d 'initialize_with_readme=true'

echo ""
echo ""

echo "=== Test: Create project with namespace (path) ==="
curl -s -w '\nHTTP_CODE:%{http_code}' -X POST "$URL/api/v4/projects" \
    -H "PRIVATE-TOKEN: $TOKEN" \
    -d 'name=debug-namespace-project-2' \
    -d 'namespace=debug-test-group' \
    -d 'visibility=internal' \
    -d 'initialize_with_readme=true'

echo ""
echo ""

echo "=== Test: URL-encoded group path ==="
curl -s -w '\nHTTP_CODE:%{http_code}' -X POST "$URL/api/v4/groups/debug-test-group%2Fsubgroup/projects" \
    -H "PRIVATE-TOKEN: $TOKEN" \
    -d 'name=debug-subgroup-project' \
    -d 'visibility=internal'

echo ""
echo ""

echo "=== Test: Check if /api/v4/groups/7/projects works with GET ==="
curl -s -w '\nHTTP_CODE:%{http_code}' "$URL/api/v4/groups/7/projects" \
    -H "PRIVATE-TOKEN: $TOKEN"

echo ""
echo ""

echo "=== Test: Check app settings for groups ==="
curl -s "$URL/api/v4/application/settings" \
    -H "PRIVATE-TOKEN: $TOKEN" 2>&1 | python3 -m json.tool 2>/dev/null | grep -E 'group|project|namespace'
