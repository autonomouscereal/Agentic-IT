# Keycloak Manager - Troubleshooting Guide

## Common Issues and Solutions

### Container Won't Start

#### "The '--optimized' flag was used for first ever server start"

**Symptom:** Keycloak container immediately exits with code 2.

**Cause:** Keycloak 26.x requires a build step before `start --optimized` can be used.

**Fix:** Use `command: start` in docker-compose.yml for the first boot. The build happens automatically on first start.

#### Port Already in Use

**Symptom:** Container starts but immediately crashes or fails to bind.

**Check:**
```bash
ss -tlnp | grep -E '(8080|5432|9000)'
```

**Fix:** Stop the process using the port or change the port configuration.

### Health Check Fails

#### Health Endpoint Returns 404 on Port 8080

**Symptom:** `curl http://localhost:8080/health` returns 404.

**Cause:** In Keycloak 26.x, health and metrics endpoints moved to the management port 9000.

**Fix:** Use port 9000: `curl http://localhost:9000/health`

#### Health Check Times Out

**Symptom:** Deploy script times out waiting for Keycloak readiness.

**Check:**
```bash
docker logs keycloak --tail 50
```

**Common causes:**
- PostgreSQL not ready yet (check `docker logs keycloak-db`)
- Database connection failed (verify credentials in `.env`)
- JVM heap too small for available memory

### Authentication Issues

#### Cannot Login as Admin

**Symptom:** 401 Unauthorized on admin API calls.

**Check:**
1. Verify `.env` file exists and has correct permissions: `ls -la .env`
2. Verify admin credentials match what was generated
3. Check that `KC_BOOTSTRAP_ADMIN_USERNAME` and `KC_BOOTSTRAP_ADMIN_PASSWORD` are set

**Note:** Bootstrap credentials only work on first boot. If you need to reset admin password, use `--generate-secrets --recreate`.

#### Token Expired

**Symptom:** API calls work initially but start failing after ~5 minutes.

**Cause:** Access tokens expire after 5 minutes by default.

**Fix:** Re-authenticate using `get_token()` before each batch of operations.

### API Errors

#### 404 on Password Endpoints

**Symptom:** `POST /reset-password` or `PUT /set-password` returns 404.

**Cause:** Keycloak 26.x removed these endpoints.

**Fix:** Use `PUT /users/{id}` with `credentials` array in body:
```json
{
  "username": "user",
  "email": "user@example.com",
  "credentials": [{"type": "password", "value": "NewPass123!", "temporary": false}]
}
```

#### 201 with Empty Response Body

**Symptom:** `create_group()` returns `None` despite success.

**Cause:** Keycloak returns 201 with no body for group creation.

**Fix:** The admin script handles this by searching for the group by name after creation.

#### KeyError on Role Mappings

**Symptom:** `get_user_roles()` crashes with `KeyError: 'list object has no attribute get'`.

**Cause:** Keycloak 26.x returns role mappings as a list directly, not wrapped in a dict.

**Fix:** The admin script handles both dict and list response formats.

### Database Issues

#### PostgreSQL Connection Refused

**Symptom:** Keycloak logs show database connection errors.

**Check:**
```bash
docker logs keycloak-db --tail 20
docker logs keycloak --tail 20
```

**Fix:**
1. Ensure PostgreSQL container is healthy: `docker ps | grep keycloak-db`
2. Verify `KC_DB_URL` points to `localhost:5432` (not Docker service name with `network_mode: host`)
3. Check that `KC_DB_USERNAME` and `KC_DB_PASSWORD` match `.env` values

#### Database Migration Fails

**Symptom:** Keycloak crashes during schema initialization.

**Fix:** Use `--recreate` flag to stop and recreate containers with a clean state. **WARNING:** This deletes all data.

### Deployment Script Issues

#### "No .env file found" on Subsequent Runs

**Symptom:** Script regenerates secrets even though deployment exists.

**Cause:** `.env` file was deleted or in wrong directory.

**Fix:** Ensure `.env` file exists in the same directory as `docker-compose.yml`.

#### Docker Pull Fails

**Symptom:** `Failed to pull images` error.

**Check:** Network connectivity, Docker daemon status, available disk space.

**Fix:**
```bash
docker info  # Check daemon status
df -h /var/lib/docker  # Check disk space
```

### Performance Issues

#### Keycloak Slow to Respond

**Check:**
```bash
docker stats --no-stream keycloak
```

**Fix:**
1. Increase `JAVA_OPTS_KC_HEAP` in docker-compose.yml
2. Ensure memory reservation is not too restrictive
3. Check PostgreSQL query performance

#### Out of Memory

**Symptom:** Container killed with OOM.

**Fix:** Increase memory limits in docker-compose.yml or reduce `JAVA_OPTS_KC_HEAP`.

---

## Diagnostic Commands

### Quick Status Check

```bash
# Container status
docker compose ps

# Keycloak logs
docker logs keycloak --tail 30

# PostgreSQL logs
docker logs keycloak-db --tail 30

# Disk usage
docker system df

# Memory usage
docker stats --no-stream
```

### Network Diagnostics

```bash
# Check port binding
ss -tlnp | grep -E '(8080|5432|9000)'

# Test Keycloak HTTP
curl -s http://localhost:8080 | head -5

# Test health endpoint
curl -s http://localhost:9000/health

# Test PostgreSQL connectivity
docker exec keycloak-db pg_isready -U keycloak_user -d keycloak
```

### Reset Deployment

```bash
# Full stop and recreate (WARNING: deletes all data)
cd /opt/agentic-it/keycloak-manager
python3 scripts/deploy.py --recreate --generate-secrets
```

---

## Known Keycloak 26.x Behavior

1. **First boot takes longer** - Keycloak needs to build and initialize the Quarkus runtime
2. **Bootstrap admin only works once** - Subsequent restarts ignore `KC_BOOTSTRAP_ADMIN_PASSWORD`
3. **Health port is separate** - Management interface runs on port 9000, not 8080
4. **`network_mode: host` requires localhost DB URL** - Docker service names don't resolve in host network mode
5. **Fine-Grained Admin Permissions (FGAP)** - Enabled by default in newer versions; may require additional configuration for admin API access
