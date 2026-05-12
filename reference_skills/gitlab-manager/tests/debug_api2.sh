#!/bin/bash
TOKEN='glpat-MrwXKrPG4tyEaGnpYzpu'
URL='http://192.168.50.222'

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
