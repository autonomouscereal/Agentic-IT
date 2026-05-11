---
name: keycloak-manager
description: >-
  Deploy, manage, and test Keycloak 26.6.0 + PostgreSQL 16 via Docker on any Linux server.
  Includes deployment scripts, E2E test suite (26 tests), admin API CLI, health monitoring,
  and secret management. Supports user/group/role CRUD, role mappings, and group memberships.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(python ssh_client.py *)
  - Bash(find *)
  - Bash(docker *)
---

# Keycloak Manager

Complete deployment, management, and testing solution for Keycloak 26.6.0 with PostgreSQL 16 on Linux servers via Docker Compose with `network_mode: host`.

## Architecture

| Component | File | Purpose |
|---|---|---|
| Docker Compose | `docker-compose.yml` | Keycloak 26.6.0 + PostgreSQL 16 deployment config |
| Deployment Script | `scripts/deploy.py` | Secret generation, image pull, service startup, health waiting |
| Admin API Client | `scripts/keycloak_admin.py` | Full Keycloak Admin REST API client (pure Python, zero deps) |
| E2E Test Suite | `scripts/test_keycloak.py` | 26 tests covering health, auth, users, groups, roles, integration |
| Environment Template | `.env.example` | Secret template - copy to `.env` before deploying |

## Prerequisites

- **Docker 29.x** with Compose plugin installed on target server
- **Ports 8080, 5432, 9000** must be available (Keycloak HTTP, PostgreSQL, Health/Metrics)
- **Python 3.x** available on the server (for script execution)
- **server-manager** skill configured with SSH access to the target server

## Quick Deployment

### Step 1: Copy files to server

```bash
python "${CLAUDE_SKILL_DIR_SERVER_MANAGER}/ssh_client.py" --server ai --upload-dir "${CLAUDE_SKILL_DIR}" "/home/cereal/keycloak-manager"
```

### Step 2: Generate secrets and deploy

```bash
python "${CLAUDE_SKILL_DIR_SERVER_MANAGER}/ssh_client.py" --server ai --execute "cd /home/cereal/keycloak-manager && python3 scripts/deploy.py"
```

This will:
1. Generate cryptographically secure passwords using `secrets.token_urlsafe(48)`
2. Write `.env` file with 600 permissions
3. Pull Docker images
4. Start PostgreSQL and Keycloak containers
5. Wait for Keycloak to be ready (up to 300s timeout)

**SAVE THE PRINTED PASSWORDS** - they cannot be recovered.

### Step 3: Run E2E tests

```bash
python "${CLAUDE_SKILL_DIR_SERVER_MANAGER}/ssh_client.py" --server ai --execute "cd /home/cereal/keycloak-manager && python3 scripts/test_keycloak.py"
```

Expected: **26/26 tests passing**.

## Admin API CLI Reference

All commands executed via SSH on the server:

### User Operations

```bash
# Create user
python3 scripts/keycloak_admin.py user create --username john.doe --email john@example.com --password "Pass123!"

# List users
python3 scripts/keycloak_admin.py user list

# Update user
python3 scripts/keycloak_admin.py user update --username john.doe --email newemail@example.com

# Set password
python3 scripts/keycloak_admin.py user password --username john.doe --password "NewPass456!"

# Delete user
python3 scripts/keycloak_admin.py user delete --username john.doe
```

### Group Operations

```bash
# Create group
python3 scripts/keycloak_admin.py group create --name "Engineering"

# List groups
python3 scripts/keycloak_admin.py group list

# Create subgroup
python3 scripts/keycloak_admin.py group create --name "Backend" --parent-name "Engineering"

# Delete group
python3 scripts/keycloak_admin.py group delete --name "Engineering"
```

### Role Operations

```bash
# Create role
python3 scripts/keycloak_admin.py role create --name "developer" --description "Developer role"

# List roles
python3 scripts/keycloak_admin.py role list

# Assign role to user
python3 scripts/keycloak_admin.py role assign --username john.doe --roles developer

# Remove role from user
python3 scripts/keycloak_admin.py role unassign --username john.doe --roles developer

# Get user roles
python3 scripts/keycloak_admin.py role user-roles --username john.doe
```

### Health & Status

```bash
# Health check
python3 scripts/keycloak_admin.py health

# Deployment status
python3 scripts/deploy.py --status
```

## Deployment Script Flags

| Flag | Description |
|---|---|
| `--status` | Show running container status |
| `--stop` | Stop all Keycloak services |
| `--logs` | Show last 50 log lines |
| `--fresh` | Stop existing containers before deploying |
| `--recreate` | Full stop + redeploy cycle |
| `--generate-secrets` | Regenerate all secrets (WARNING: invalidates existing credentials) |

## Configuration

### docker-compose.yml

All secrets are loaded from `.env` file. Key environment variables:

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | *(required)* | PostgreSQL database password |
| `KC_BOOTSTRAP_ADMIN_PASSWORD` | *(required)* | Keycloak admin password |
| `POSTGRES_DB` | `keycloak` | Database name |
| `POSTGRES_USER` | `keycloak_user` | Database user |
| `KC_HOSTNAME` | `localhost` | Keycloak hostname |
| `KC_LOG_LEVEL` | `INFO` | Logging level |
| `KC_CACHE` | `local` | Cache mode (`local` for single instance) |

### Memory Limits

- PostgreSQL: 1G limit, 256M reservation
- Keycloak: 2G limit, 750M reservation

### Healthchecks

- PostgreSQL: `pg_isready` every 10s
- Keycloak: Management port 9000 health endpoint

## Security Model

1. **No hardcoded secrets** - All passwords generated via `secrets.token_urlsafe(48)`
2. **`.env` file** - 600 permissions (owner read/write only)
3. **Secrets generated on-server** - Never leave the target machine
4. **`network_mode: host`** - Direct host networking (no Docker network isolation)
5. **SSL verification disabled** - Appropriate for internal self-signed deployments

## File Structure

```
keycloak-manager/
├── SKILL.md              # This file - main skill documentation
├── docker-compose.yml    # Docker Compose deployment config
├── .env.example          # Environment variable template
├── .env.windows.example  # Windows-specific environment template
├── reference.md          # Detailed API reference
├── troubleshooting.md    # Common issues and solutions
└── scripts/
    ├── deploy.py         # Deployment automation
    ├── keycloak_admin.py # Admin REST API client
    └── test_keycloak.py  # E2E test suite
```

## Keycloak URLs

| Interface | URL |
|---|---|
| Admin Console | `http://server_ip:8080/admin` |
| Login Page | `http://server_ip:8080/realms/master/account` |
| Health Endpoint | `http://server_ip:9000/health` |
| Metrics Endpoint | `http://server_ip:9000/metrics` |
| Admin REST API | `http://server_ip:8080/admin/realms/{realm}/...` |

## When to Use

Use this skill when you need to:
- Deploy Keycloak on a new server
- Manage Keycloak users, groups, or roles via CLI
- Test Keycloak functionality
- Troubleshoot Keycloak deployment issues
- Regenerate secrets or recreate containers

## Model

**Agent model:** `qwen/qwen3.6-27b`
