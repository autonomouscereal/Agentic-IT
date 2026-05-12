#!/usr/bin/env bash
# manage.sh - GitLab 17.x Management Script
# Common operations: groups, projects, users, PATs, pipelines
#
# Usage: bash manage.sh <command> [options]

set -uo pipefail

GITLAB_HOST="${GITLAB_HOST:-192.168.50.222}"
GITLAB_URL="http://${GITLAB_HOST}"
TOKEN_FILE="${TOKEN_FILE:-/home/cereal/gitlab/.gitlab-token}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

load_token() {
    if [ -f "$TOKEN_FILE" ]; then
        TOKEN=$(cat "$TOKEN_FILE")
    elif [ -f "/home/cereal/gitlab/.env" ]; then
        TOKEN=$(grep '^GITLAB_PAT=' /home/cereal/gitlab/.env 2>/dev/null | cut -d'=' -f2-)
    else
        echo -e "${RED}ERROR: No PAT found. Create one in GitLab UI or set TOKEN_FILE.${NC}"
        exit 1
    fi
}

api() {
    curl -sf --max-time 15 -H "PRIVATE-TOKEN: ${TOKEN}" "$@" 2>&1
}

# ─── Group Commands ─────────────────────────────────────────────────────────
list_groups() {
    echo "=== Groups ==="
    # Try admin endpoint first, fall back to user-visible groups
    local resp
    resp=$(api "${GITLAB_URL}/api/v4/groups?per_page=50" 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "${resp:-}" ]; then
        resp=$(api "${GITLAB_URL}/api/v4/groups?per_page=50&all_available=true" 2>/dev/null)
    fi
    echo "$resp" | python3 -c "
import sys, json
try:
    groups = json.load(sys.stdin)
    for g in groups:
        print(f\"  {g['id']:>4} | {g['name']:<30} | {g.get('projects_count',0)} projects\")
except:
    print('  No groups found or insufficient permissions')
" 2>/dev/null || echo "  Failed to list groups"
}

create_group() {
    local name="$1" path="$2" visibility="${3:-internal}"
    local resp
    resp=$(api -X POST "${GITLAB_URL}/api/v4/groups" \
        --data "name=${name}" --data "path=${path}" --data "visibility=${visibility}")
    local gid
    gid=$(echo "$resp" | grep -o '"id":[0-9]*' | cut -d: -f2)
    [ -n "${gid:-}" ] && echo -e "${GREEN}Created group '${name}' (ID: ${gid})${NC}" || echo -e "${RED}Failed: ${resp:0:200}${NC}"
}

delete_group() {
    local group_id="$1"
    api -X DELETE "${GITLAB_URL}/api/v4/groups/${group_id}" >/dev/null 2>&1
    echo -e "${GREEN}Deleted group ${group_id}${NC}"
}

# ─── Project Commands ───────────────────────────────────────────────────────
list_projects() {
    echo "=== Projects ==="
    api "${GITLAB_URL}/api/v4/projects?per_page=50&order_by=created_at&sort=desc" | python3 -c "
import sys, json
projects = json.load(sys.stdin)
for p in projects:
    print(f\"  {p['id']:>4} | {p['path_with_namespace']:<40} | {p['visibility']}\")
" 2>/dev/null || echo "  Failed to list projects"
}

create_project() {
    local name="$1" namespace_id="$2"
    local resp
    resp=$(api -X POST "${GITLAB_URL}/api/v4/projects" \
        --data "name=${name}" --data "namespace_id=${namespace_id}" \
        --data "visibility=internal" --data "initialize_with_readme=true")
    local pid
    pid=$(echo "$resp" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
    [ -n "${pid:-}" ] && echo -e "${GREEN}Created project '${name}' (ID: ${pid})${NC}" || echo -e "${RED}Failed: ${resp:0:200}${NC}"
}

delete_project() {
    local project_id="$1"
    api -X DELETE "${GITLAB_URL}/api/v4/projects/${project_id}" >/dev/null 2>&1
    echo -e "${GREEN}Deleted project ${project_id}${NC}"
}

# ─── PAT Commands ───────────────────────────────────────────────────────────
create_pat() {
    local expiry="${1:-2027-01-01}"
    local resp
    resp=$(api -X POST "${GITLAB_URL}/api/v4/personal_access_tokens" \
        --data "name=manage-script" \
        --data "expires_at=${expiry}" \
        --data "scopes=api,read_api,write_repository")
    local new_token
    new_token=$(echo "$resp" | grep -o '"token":"glpat-[A-Za-z0-9_\-]*"' | cut -d'"' -f4)
    if [ -n "${new_token:-}" ]; then
        echo "$new_token" > "$TOKEN_FILE"
        chmod 600 "$TOKEN_FILE"
        echo -e "${GREEN}New PAT created and saved to ${TOKEN_FILE}${NC}"
        echo "  Token: ${new_token}"
    else
        echo -e "${RED}Failed: ${resp:0:200}${NC}"
    fi
}

# ─── Pipeline Commands ──────────────────────────────────────────────────────
list_pipelines() {
    local project_id="$1"
    echo "=== Pipelines for project ${project_id} ==="
    api "${GITLAB_URL}/api/v4/projects/${project_id}/pipelines?per_page=10" | python3 -c "
import sys, json
pipes = json.load(sys.stdin)
for p in pipes:
    print(f\"  #{p['id']:>5} | {p['ref']:<20} | {p['status']:<10} | {p['created_at']}\")
" 2>/dev/null || echo "  Failed to list pipelines"
}

# ─── Runner Commands ────────────────────────────────────────────────────────
list_runners() {
    echo "=== Registered Runners ==="
    api "${GITLAB_URL}/api/v4/runners" | python3 -c "
import sys, json
runners = json.load(sys.stdin)
for r in runners:
    tags = ','.join(r.get('tags', []))
    print(f\"  {r['id']:>3} | {r['description']:<25} | {r['status']:<10} | tags: {tags}\")
" 2>/dev/null || echo "  Failed to list runners"
}

# ─── Main ────────────────────────────────────────────────────────────────────
load_token

case "${1:-help}" in
    # Groups
    groups|list-groups)       list_groups ;;
    create-group)            create_group "${2:-}" "${3:-}" "${4:-internal}" ;;
    delete-group)            delete_group "${2:-}" ;;

    # Projects
    projects|list-projects)   list_projects ;;
    create-project)          create_project "${2:-}" "${3:-}" ;;
    delete-project)          delete_project "${2:-}" ;;

    # PAT
    create-pat)              create_pat "${2:-2027-01-01}" ;;

    # Pipelines
    pipelines)               list_pipelines "${2:-}" ;;

    # Runners
    runners|list-runners)    list_runners ;;

    # Container shortcuts
    restart)
        cd /home/cereal/gitlab && docker compose restart
        echo -e "${GREEN}Containers restarted${NC}"
        ;;
    logs)
        cd /home/cereal/gitlab && docker compose logs --tail=50 "${2:-gitlab}"
        ;;
    down)
        cd /home/cereal/gitlab && docker compose down
        echo -e "${GREEN}Containers stopped and removed${NC}"
        ;;

    help|*)
        echo "GitLab 17.x Management Script"
        echo ""
        echo "Commands:"
        echo "  groups / list-groups       List all groups"
        echo "  create-group NAME PATH     Create a group"
        echo "  delete-group ID            Delete a group"
        echo "  projects / list-projects   List all projects"
        echo "  create-project NAME GRP_ID Create a project in a group"
        echo "  delete-project ID          Delete a project"
        echo "  create-pat [EXPIRY]        Generate new PAT"
        echo "  pipelines PROJECT_ID       List pipelines"
        echo "  runners / list-runners     List registered runners"
        echo "  restart                   Restart containers"
        echo "  logs [service]            Show container logs"
        echo "  down                      Stop and remove containers"
        echo ""
        echo "Token file: ${TOKEN_FILE}"
        ;;
esac
