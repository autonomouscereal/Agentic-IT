---
name: gitlab-manager
description: Deploy, manage, and test GitLab CE 17.x + GitLab Runner via Docker. Includes deployment scripts, E2E test suite (31 tests), management CLI, health monitoring, and backup utilities.
type: skill
---

# GitLab Manager Skill

Complete deployment, management, and testing toolkit for GitLab CE 17.x with GitLab Runner via Docker Compose.

## Quick Deploy

```bash
# On the target server, from /home/cereal/gitlab/:
bash scripts/deploy.sh --fresh
```

This generates secure credentials, pulls images, starts containers, waits for health, registers the runner, and prints login details.

## Architecture

| Component | Image | Ports | Purpose |
|-----------|-------|-------|---------|
| GitLab CE | `gitlab/gitlab-ce:17.11.3-ce.0` | 80 (HTTP), 2222 (SSH) | Git platform, CI/CD, issues, MRs |
| GitLab Runner | `gitlab/gitlab-runner:alpine-v17.11.0` | None (internal) | Executes CI/CD jobs via Docker executor |

Both containers communicate over a private Docker bridge network (`gitlab-net`). Data persists in named Docker volumes.

## File Structure

```
/home/cereal/gitlab/              # Server deployment directory
├── docker-compose.yml            # Service definitions
├── .env                          # Secrets (chmod 600) - NEVER commit
├── .gitlab-token                 # PAT for API auth (chmod 600)
├── scripts/
│   ├── deploy.sh                 # Deployment orchestrator
│   ├── manage.sh                 # Day-to-day management CLI
│   ├── health_check.sh           # Health monitoring
│   ├── backup.sh                 # Backup/restore
│   └── reset_password.sh         # Rails-based password reset
└── tests/
    └── test_all_v2.sh            # 31-test E2E suite (all pass)

C:/Users/cereal/.agents/skills/gitlab-manager/  # Local skill directory
├── SKILL.md                      # This file
├── docker-compose.yml            # Template (identical to server copy)
├── .env.example                  # Template - fill in and deploy
├── scripts/                      # All scripts above
└── tests/                        # All test scripts above
```

## Deployment Process

### Prerequisites
- Docker and Docker Compose V2 installed on target server
- At least 4GB RAM recommended (GitLab is resource-intensive)
- Ports 80 and 2222 available

### Step-by-step for a new environment

1. **Copy files**: Upload `docker-compose.yml`, all scripts, and `.env.example` to the target server's deployment directory (e.g., `/home/cereal/gitlab/`)

2. **Generate credentials**: The deploy script auto-generates a secure root password via OpenSSL if no `.env` exists. Alternatively, create one manually:
   ```bash
   openssl rand -base64 32 | tr -d '/+=' | head -c 32
   ```

3. **Run deployment**:
   ```bash
   bash scripts/deploy.sh --fresh
   ```

4. **Create a PAT**: After first login, create a Personal Access Token in the GitLab UI (User Settings > Access Tokens) with `api`, `read_api`, `write_repository` scopes. Save it to `.gitlab-token`

5. **Run E2E tests**: `bash tests/test_all_v2.sh` -- all 31 tests should pass

### Deploy Script Commands

| Command | Description |
|---------|-------------|
| `--fresh` | Full deployment (stop old, start new, register runner) |
| `--status` | Show container status and health |
| `--start` / `--stop` | Start/stop containers |
| `--reconfigure` | Run `gitlab-ctl reconfigure` inside container |
| `--update` | Pull new images and restart |
| `--credentials` | Display root password and PAT |

## Management Script

```bash
# List all groups
bash scripts/manage.sh groups

# Create group
bash scripts/manage.sh create-group "My Team" "my-team" internal

# List projects
bash scripts/manage.sh projects

# Create project in group (use group ID from list)
bash scripts/manage.sh create-project "my-app" 7

# List runners
bash scripts/manage.sh runners

# View container logs
bash scripts/manage.sh logs gitlab
bash scripts/manage.sh logs gitlab-runner

# Restart everything
bash scripts/manage.sh restart
```

## Health Monitoring

```bash
# Quick check
bash scripts/health_check.sh --brief

# Full report with resource usage
bash scripts/health_check.sh --verbose
```

**CRITICAL for GitLab 17.x**: Health endpoints (`/-/health`, `/-/readiness`, `/-/liveness`) only respond from **inside** the container (localhost). They return 404 when called from the host IP. Always use `docker exec gitlab curl http://localhost/-/health` for health checks.

## API Authentication

GitLab 17.x **removed** the `/api/v4/session` endpoint. All API calls must use a Personal Access Token (PAT):

```bash
curl -H "PRIVATE-TOKEN: <gitlab_pat_from_vault>" http://192.168.50.222/api/v4/user
```

Create PATs via the UI or API:
```bash
bash scripts/manage.sh create-pat 2027-01-01
```

## GitLab 17.x Breaking Changes

These were discovered through extensive testing and debugging:

| Change | Old API | New API |
|--------|---------|---------|
| Session auth removed | `POST /api/v4/session` | Use PAT with `PRIVATE-TOKEN` header |
| Project creation in groups | `POST /api/v4/groups/{id}/projects` (404) | `POST /api/v4/projects` with `namespace_id={id}` |
| Runner auth tokens | `POST /api/v4/runners/authentication_tokens` (CE: unavailable) | Use registration token from `GET /api/v4/application/settings/registration` |
| Health endpoints | Respond from host IP | Only respond from localhost inside container |
| Branch API parameter | `start_branch` | `branch` |
| File commit API | Form-encoded `--data` | JSON body with `Content-Type: application/json` |

### Workarounds

**Create project in a group:**
```bash
curl -X POST http://192.168.50.222/api/v4/projects \
  -H "PRIVATE-TOKEN: $TOKEN" \
  -d "name=my-project" -d "namespace_id=7" \
  -d "visibility=internal" -d "initialize_with_readme=true"
```

**Create file via API:**
```bash
curl -X POST http://192.168.50.222/api/v4/projects/$PID/repository/commits \
  -H "PRIVATE-TOKEN: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"branch":"feature","start_branch":"main","commit_message":"add file",
       "actions":[{"action":"create","file_path":"README.md","content":"Hello"}]}'
```

**Health check from host:**
```bash
docker exec gitlab curl -sf http://localhost/-/health
```

## E2E Test Suite

`tests/test_all_v2.sh` runs 31 tests across 14 categories:

| # | Category | Tests | What it validates |
|---|----------|-------|-------------------|
| 1 | Container Health | 3 | Both containers running, health status |
| 2 | Health Endpoints | 3 | Health/readiness/liveness via docker exec |
| 3 | API Auth & Version | 2 | PAT auth works, version endpoint |
| 4 | Group Management | 1 | Create group via API |
| 5 | Repository Creation | 1 | Create project with `namespace_id` |
| 6 | Clone Repository | 1 | HTTP clone with PAT auth |
| 7 | Branch Operations | 4 | Feature/bugfix branches, push, API listing |
| 8 | Merge Request | 2 | Create and merge MR |
| 9 | Tags | 2 | Create and push annotated tag |
| 10 | CI/CD Pipeline | 5 | Push `.gitlab-ci.yml`, pipeline creation, job execution |
| 11 | File API | 2 | Branch creation + file creation via commit API |
| 12 | Issues | 1 | Create issue via API |
| 13 | Runner | 2 | Runner verify alive, version check |
| 14 | Repository State | 2 | Tree listing, commit history |

The test suite is idempotent: it creates a unique test group per run and cleans it up on exit.

## Troubleshooting

### GitLab won't start / health check fails
```bash
# Check logs
cd /home/cereal/gitlab && docker compose logs --tail=100 gitlab

# First boot takes 3-7 minutes. Subsequent boots are faster.
# If stuck > 10 minutes, check RAM: GitLab needs 4GB+ for comfortable operation
```

### Runner not picking up jobs
```bash
# Verify runner is registered and alive
docker exec gitlab-runner gitlab-runner verify
docker exec gitlab-runner gitlab-runner list

# Check runner can reach GitLab
docker exec gitlab-runner curl -sf http://gitlab/-/health
```

### "You can only create or edit files when you are on a branch"
This GitLab error means the target branch has no commits. Always use `start_branch` pointing to a branch with commits (e.g., `main`):
```bash
curl -X POST .../repository/commits \
  -H "Content-Type: application/json" \
  -d '{"branch":"new-branch","start_branch":"main","commit_message":"msg",
       "actions":[{"action":"create","file_path":"f.txt","content":"data"}]}'
```

### Password reset
```bash
# Option 1: Rails runner (preferred)
bash scripts/reset_password.sh "NewSecurePassword123!"

# Option 2: Interactive rake
docker exec -it gitlab gitlab-rake 'gitlab:password:reset[root]'
```

### Port conflicts
If port 80 is in use, change `GITLAB_HTTP_PORT` in `.env` to another port (e.g., 8080).

## Backup and Restore

```bash
# Create backup
bash scripts/backup.sh --create

# List backups
bash scripts/backup.sh --list

# Restore specific backup
bash scripts/backup.sh --restore 20260430120000

# Backup config only
bash scripts/backup.sh --config-backup
```

## Re-deployment Checklist

To deploy this skill in a new environment:

1. [ ] Install Docker and Docker Compose V2 on target server
2. [ ] Ensure ports 80 and 2222 are free
3. [ ] Copy `docker-compose.yml` and all scripts to deployment directory
4. [ ] Set `GITLAB_HOSTNAME` in `.env` to the target server's IP
5. [ ] Run `bash scripts/deploy.sh --fresh`
6. [ ] Note the printed credentials
7. [ ] Create a PAT in the GitLab UI with `api`, `read_api`, `write_repository` scopes
8. [ ] Save PAT to `.gitlab-token` file
9. [ ] Run `bash tests/test_all_v2.sh` to verify all 31 tests pass
10. [ ] Change root password via the UI or `reset_password.sh`

## Resource Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 2GB | 4-8GB |
| CPU | 2 cores | 4 cores |
| Disk | 10GB | 20GB+ |
| Network | Private LAN | Private LAN |

## Security Notes

- Root password generated via OpenSSL (256-bit entropy)
- `.env` and `.gitlab-token` files set to `chmod 600`
- HTTP only (no TLS) -- appropriate for private LAN; add Let's Encrypt for external exposure
- Prometheus monitoring disabled by default (reduces attack surface)
- GitLab Pages disabled by default
- Container registry disabled by default
- Runner uses Docker executor (isolated job containers)
