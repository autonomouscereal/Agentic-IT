#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../credential-vault/scripts/load_secret.sh"
TOKEN="$(load_secret gitlab_manager_pat GITLAB_PAT GITLAB_PAT_FILE /home/gitlab/.gitlab-token)" || {
    echo "ERROR: No GitLab PAT found. Set GITLAB_PAT, GITLAB_PAT_FILE, or CREDMAN_PATH/GITLAB_PAT_VAULT_KEY." >&2
    exit 1
}
URL='http://127.0.0.1'

echo "=== Test: Create project at root level ==="
curl -s -w '\nHTTP_CODE:%{http_code}' -X POST "$URL/api/v4/projects" \
    -H "PRIVATE-TOKEN: $TOKEN" \
    -d 'name=debug-root-project' \
    -d 'visibility=internal' \
    -d 'initialize_with_readme=true'

echo ""
echo ""

echo "=== Test: Create project in group (encoded data) ==="
curl -s -w '\nHTTP_CODE:%{http_code}' -X POST "$URL/api/v4/groups/7/projects" \
    -H "PRIVATE-TOKEN: $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name":"debug-test-repo-3","visibility":"internal","initialize_with_readme":true}'

echo ""
echo ""

echo "=== Test: Check PAT scopes ==="
curl -s "$URL/api/v4/personal_access_tokens/self" \
    -H "PRIVATE-TOKEN: $TOKEN" 2>&1

echo ""
echo ""

echo "=== Test: List projects in group ==="
curl -s -w '\nHTTP_CODE:%{http_code}' "$URL/api/v4/groups/7/projects" \
    -H "PRIVATE-TOKEN: $TOKEN"

echo ""
echo ""

echo "=== Test: Check group details ==="
curl -s "$URL/api/v4/groups/7" \
    -H "PRIVATE-TOKEN: $TOKEN" 2>&1 | python3 -m json.tool 2>/dev/null | grep -E 'id|name|path|project_creation'
