# Keycloak Manager - API Reference

## Keycloak 26.6.0 Admin REST API Endpoints

All admin API calls require a Bearer token obtained from the authentication endpoint.

### Authentication

| Endpoint | Method | Description |
|---|---|---|
| `/realms/master/protocol/openid-connect/token` | POST | Obtain access token |

**Request body (form-encoded):**
```
grant_type=password
client_id=admin
username=admin
password=<admin_password>
```

**Response:** JSON with `access_token`, `refresh_token`, `expires_in`.

### User Management

| Endpoint | Method | Description |
|---|---|---|
| `/admin/realms/{realm}/users` | GET | List all users |
| `/admin/realms/{realm}/users` | POST | Create user |
| `/admin/realms/{realm}/users/{id}` | GET | Get user by ID |
| `/admin/realms/{realm}/users/{id}` | PUT | Update user (including password via credentials array) |
| `/admin/realms/{realm}/users/{id}` | DELETE | Delete user |

**Set password (Keycloak 26.x):** Use PUT `/users/{id}` with `credentials` array in body:
```json
{
  "username": "user@example.com",
  "email": "user@example.com",
  "credentials": [{"type": "password", "value": "NewPass123!", "temporary": false}]
}
```

**Query parameters for listing:** `username`, `email`, `first`, `max`, `exact`

### Group Management

| Endpoint | Method | Description |
|---|---|---|
| `/admin/realms/{realm}/groups` | GET | List all groups |
| `/admin/realms/{realm}/groups` | POST | Create top-level group |
| `/admin/realms/{realm}/groups/{id}` | GET | Get group by ID |
| `/admin/realms/{realm}/groups/{id}` | PUT | Update group |
| `/admin/realms/{realm}/groups/{id}` | DELETE | Delete group |
| `/admin/realms/{realm}/groups/{id}/children` | POST | Create subgroup |
| `/admin/relms/{realm}/groups/{id}/members` | GET | Get group members |

### Role Management

| Endpoint | Method | Description |
|---|---|---|
| `/admin/realms/{realm}/roles` | GET | List realm roles |
| `/admin/realms/{realm}/roles` | POST | Create realm role |
| `/admin/realms/{realm}/roles/{name}` | DELETE | Delete realm role |
| `/admin/realms/{realm}/users/{id}/role-mappings` | GET | Get user role mappings |
| `/admin/realms/{realm}/users/{id}/role-mappings` | POST | Assign roles to user |
| `/admin/realms/{realm}/users/{id}/role-mappings` | DELETE | Remove roles from user |

### Realm Management

| Endpoint | Method | Description |
|---|---|---|
| `/admin/realms` | GET | List all realms |
| `/admin/realms` | POST | Create realm |
| `/admin/realms/{realm}` | GET | Get realm details |

### Health & Metrics

| Endpoint | Port | Description |
|---|---|---|
| `/health` | 9000 | Liveness and readiness health check |
| `/metrics` | 9000 | Prometheus-style metrics |

---

## Python Module API

### `keycloak_admin.py` Functions

#### Authentication

```python
from keycloak_admin import get_token, load_credentials

# Load credentials from .env file
username, password = load_credentials()

# Get access token
token = get_token(base_url, username, password)
```

#### User Operations

```python
from keycloak_admin import (
    create_user, list_users, update_user, delete_user,
    set_user_password, get_user
)

# Create user
user = create_user(token, base_url, realm, username, email=email, password=password)

# List users
users = list_users(token, base_url, realm, username="john")

# Update user
update_user(token, base_url, realm, user_id, email="new@example.com")

# Set password
set_user_password(token, base_url, realm, username, "NewPassword123!")

# Delete user
delete_user(token, base_url, realm, user_id)
```

#### Group Operations

```python
from keycloak_admin import (
    create_group, list_groups, update_group, delete_group,
    add_user_to_group, remove_user_from_group, get_group_members
)

# Create group
group = create_group(token, base_url, realm, "Engineering")

# Create subgroup
subgroup = create_group(token, base_url, realm, "Backend", parent_id=group["id"])

# List groups
groups = list_groups(token, base_url, realm, search="Engineering")

# Add user to group
add_user_to_group(token, base_url, realm, user_id, group_id)
```

#### Role Operations

```python
from keycloak_admin import (
    create_role, list_roles, delete_role,
    assign_roles_to_user, remove_roles_from_user, get_user_roles
)

# Create role
create_role(token, base_url, realm, "developer", description="Developer role")

# Assign roles
assign_roles_to_user(token, base_url, realm, username, ["developer", "admin"])

# Get user roles
roles = get_user_roles(token, base_url, realm, username)
```

---

## Docker Compose Configuration Reference

### Services

| Service | Image | Ports | Description |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5432 | Database backend |
| `keycloak` | `quay.io/keycloak/keycloak:26.6.0` | 8080, 9000 | Identity management |

### Volumes

| Volume | Container Path | Description |
|---|---|---|
| `pgdata` | `/var/lib/postgresql/data` | PostgreSQL persistent data |

### Environment Variables

**PostgreSQL:**
- `POSTGRES_DB` - Database name (default: `keycloak`)
- `POSTGRES_USER` - Database user (default: `keycloak_user`)
- `POSTGRES_PASSWORD` - Database password (required, from `.env`)
- `PGDATA` - Data directory path
- `POSTGRES_INITDB_ARGS` - Initialization arguments

**Keycloak:**
- `KC_BOOTSTRAP_ADMIN_USERNAME` - Admin username (default: `admin`)
- `KC_BOOTSTRAP_ADMIN_PASSWORD` - Admin password (required, from `.env`)
- `KC_DB` - Database vendor (`postgres`)
- `KC_DB_URL` - JDBC connection string
- `KC_DB_USERNAME` / `KC_DB_PASSWORD` - Database credentials
- `KC_HOSTNAME` - Server hostname
- `KC_HOSTNAME_STRICT` - Strict hostname validation
- `KC_HOSTNAME_STRICT_HTTPS` - Strict HTTPS validation
- `KC_HTTP_ENABLED` - Allow HTTP (default: `true`)
- `KC_HEALTH_ENABLED` - Enable health endpoints (default: `true`)
- `KC_METRICS_ENABLED` - Enable metrics (default: `true`)
- `KC_LOG_LEVEL` - Logging level (default: `INFO`)
- `KC_CACHE` - Cache mode (`local` for single instance)
- `KC_TRANSACTION_XA_ENABLED` - XA transactions (default: `false`)
- `JAVA_OPTS_KC_HEAP` - JVM heap settings (default: `--Xms512m -Xmx1024m`)

---

## Keycloak 26.x Breaking Changes

### Admin REST API

1. **Password management endpoints removed:** The `/reset-password` and `/set-password` sub-endpoints no longer exist. Use `PUT /users/{id}` with a `credentials` array in the request body instead.

2. **Health endpoints on management port:** Health and metrics are now served on port 9000 (management interface), not the main HTTP port 8080.

3. **Role mappings response format:** The `/users/{id}/role-mappings` endpoint may return a list directly rather than a dict with `realmMappings` key - code should handle both formats.

4. **Group creation response:** `POST /groups` returns 201 with an empty body. Use the Location header or search by name to retrieve the created group.

### Environment Variables

- All configuration uses `KC_*` prefix (Quarkus-based), not the legacy `KEYCLOAK_*` prefix
- Admin user bootstrap uses `KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD` (not `KEYCLOAK_ADMIN`)

### Startup

- `start --optimized` requires a prior build step; use plain `start` for first boot
- Subsequent restarts will use the optimized build automatically
