#!/usr/bin/env bash
# health_check.sh - Comprehensive GitLab Health Monitoring
# GitLab 17.x: Health endpoints only respond from inside the container
#
# Usage: bash health_check.sh [--brief | --verbose]

set -uo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/home/cereal/gitlab}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

check_container_status() {
    echo "=== Container Status ==="
    cd "${DEPLOY_DIR}"
    docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
    echo ""
}

check_gitlab_health() {
    echo "=== GitLab Health (via docker exec) ==="

    local health
    health=$(docker exec gitlab curl -sf http://localhost/-/health 2>&1 || echo "FAILED")
    if [ "$health" != "FAILED" ]; then
        echo -e "  Overall Health: ${GREEN}UP${NC}"
    else
        echo -e "  Overall Health: ${RED}DOWN${NC}"
    fi

    local ready
    ready=$(docker exec gitlab curl -sf http://localhost/-/readiness 2>&1 || echo "FAILED")
    if [ "$ready" != "FAILED" ]; then
        echo -e "  Readiness:      ${GREEN}READY${NC}"
    else
        echo -e "  Readiness:      ${YELLOW}NOT READY${NC}"
    fi

    local alive
    alive=$(docker exec gitlab curl -sf http://localhost/-/liveness 2>&1 || echo "FAILED")
    if [ "$alive" != "FAILED" ]; then
        echo -e "  Liveness:       ${GREEN}ALIVE${NC}"
    else
        echo -e "  Liveness:       ${RED}DEAD${NC}"
    fi

    echo ""
}

check_runner_status() {
    echo "=== GitLab Runner Status ==="
    local runner_verify
    runner_verify=$(docker exec gitlab-runner gitlab-runner verify 2>&1 || echo "FAILED")
    echo "  Verify: ${runner_verify}"

    local runner_version
    runner_version=$(docker exec gitlab-runner gitlab-runner version 2>&1 | head -1 || echo "N/A")
    echo "  Version: ${runner_version}"
    echo ""
}

check_resource_usage() {
    echo "=== Resource Usage ==="
    echo "  GitLab:"
    docker stats gitlab --no-stream --format "    CPU: {{.CPUPerc}} | Mem: {{.MemUsage}}" 2>/dev/null
    echo "  Runner:"
    docker stats gitlab-runner --no-stream --format "    CPU: {{.CPUPerc}} | Mem: {{.MemUsage}}" 2>/dev/null
    echo ""
}

check_disk_usage() {
    echo "=== Disk Usage ==="
    echo "  Data:   $(docker exec gitlab du -sh /var/opt/gitlab 2>/dev/null | awk '{print $1}')"
    echo "  Config: $(docker exec gitlab du -sh /etc/gitlab 2>/dev/null | awk '{print $1}')"
    echo "  Logs:   $(docker exec gitlab du -sh /var/log/gitlab 2>/dev/null | awk '{print $1}')"
    echo ""
}

case "${1:-}" in
    --brief)   check_container_status; check_gitlab_health ;;
    --verbose) check_container_status; check_gitlab_health; check_runner_status; check_resource_usage; check_disk_usage ;;
    *)         check_container_status; check_gitlab_health; check_runner_status; check_resource_usage ;;
esac
