#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../scripts/gitlab_token.sh"
TOKEN="$(load_gitlab_pat gitlab_manager_pat)" || {
    echo "ERROR: No GitLab PAT found. Set GITLAB_PAT, GITLAB_PAT_FILE, or CREDMAN_PATH/GITLAB_PAT_VAULT_KEY." >&2
    exit 1
}
URL='http://192.168.50.222'

echo "=== Test: Create group ==="
curl -s -w '\nHTTP_CODE:%{http_code}' -X POST "$URL/api/v4/groups" \
    -H "PRIVATE-TOKEN: $TOKEN" \
    -d 'name=debug-test-group' \
    -d 'path=debug-test-group' \
    -d 'visibility=internal'

echo ""
echo ""

# Get group by path
GRP_INFO=$(curl -s "$URL/api/v4/groups/debug-test-group" -H "PRIVATE-TOKEN: $TOKEN")
echo "GROUP INFO: $GRP_INFO"

GRP_ID=$(echo "$GRP_INFO" | grep -o '"id":[0-9]*' | cut -d: -f2)
echo "GRP_ID: $GRP_ID"

echo ""
echo "=== Test: Create project by ID ==="
curl -s -w '\nHTTP_CODE:%{http_code}' -X POST "$URL/api/v4/groups/$GRP_ID/projects" \
    -H "PRIVATE-TOKEN: $TOKEN" \
    -d 'name=debug-test-repo' \
    -d 'visibility=internal' \
    -d 'initialize_with_readme=true'

echo ""
echo ""
echo "=== Test: Create project by path ==="
curl -s -w '\nHTTP_CODE:%{http_code}' -X POST "$URL/api/v4/groups/debug-test-group/projects" \
    -H "PRIVATE-TOKEN: $TOKEN" \
    -d 'name=debug-test-repo-2' \
    -d 'visibility=internal' \
    -d 'initialize_with_readme=true'
