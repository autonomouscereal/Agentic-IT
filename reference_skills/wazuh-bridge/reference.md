# Wazuh Bridge - API Reference

## Keycloak Admin API (26.x)

### Base URL
`http://localhost:8080/admin`

### Authentication
```
POST /realms/master/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

username=admin&password=<pw>&grant_type=password&client_id=admin-cli
```

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/admin/realms` | List all realms |
| `POST` | `/admin/realms` | Create a realm |
| `GET` | `/admin/realms/{realm}/clients` | List clients in realm |
| `POST` | `/admin/realms/{realm}/clients` | Create a client |
| `GET` | `/admin/realms/{realm}/groups` | List groups |
| `POST` | `/admin/realms/{realm}/groups` | Create a group |
| `GET` | `/admin/realms/{realm}/roles` | List realm roles |
| `POST` | `/admin/realms/{realm}/roles` | Create a role |
| `GET` | `/admin/realms/{realm}/users` | List users |
| `POST` | `/admin/realms/{realm}/users` | Create a user |
| `DELETE` | `/admin/realms/{realm}/users/{id}` | Delete a user |
| `GET` | `/admin/realms/{realm}/users/{id}/groups` | Get user groups |

### Health Check
```
GET http://localhost:9000/health
Response: {"status": "UP"}
```

## Wazuh Security API (4.14.x)

### Base URL
`https://192.168.50.222:26500`

### Authentication
```
GET /security/user/authenticate?raw=true
Authorization: Basic base64(username:password)
Response: raw JWT token string
```

### Security Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/security/users` | List API users |
| `POST` | `/security/users` | Create API user |
| `PUT` | `/security/users/{id}/password` | Change user password |
| `GET` | `/security/roles` | List RBAC roles |
| `POST` | `/security/roles` | Create RBAC role |
| `GET` | `/security/policies` | List RBAC policies |
| `POST` | `/security/policies` | Create RBAC policy |
| `GET` | `/security/rules` | List RBAC rules |
| `POST` | `/security/role-mappings` | Create role mapping |
| `GET` | `/security/role-mappings` | List role mappings |

### Manager Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/manager/status` | Process status |
| `GET` | `/manager/info` | Version, type, max agents |
| `PUT` | `/manager/restart` | Restart manager |

### Create User Payload

```json
{"username": "analyst", "password": "<from vault: wazuh_api>"}
```

### Default Wazuh Roles

| Role | Description |
|------|-------------|
| `administrator` | Full API access |
| `readonly` | Read-only access |
| `agents_admin` | Agent management |
| `agents_readonly` | Agent read-only |
| `cluster_admin` | Cluster/manager management |
| `cluster_readonly` | Cluster read-only |
| `users_admin` | User management |

### RBAC Policy Structure

```yaml
policy:
  actions:
    - agent:read
    - security:read
  resources:
    - agent:id:*
    - '*:*:*'
  effect: allow
```

### RBAC Resources

| Resource | Description | Example |
|----------|-------------|---------|
| `*:*` | Any resource | |
| `agent:id` | Agent by ID | `agent:id:001` |
| `agent:group` | Agent group | `agent:group:web` |
| `user:id` | Security user | `user:id:1` |
| `role:id` | Security role | `role:id:1` |
| `policy:id` | Security policy | `policy:id:1` |
| `node:id` | Cluster node | `node:id:master` |

### RBAC Actions

| Action | Description |
|--------|-------------|
| `agent:read` | Read agent information |
| `agent:create` | Create/enroll agents |
| `agent:delete` | Delete agents |
| `security:read` | Read security config |
| `security:create` | Create security objects |
| `security:create_user` | Create API users |
| `security:update` | Update security objects |
| `security:delete` | Delete security objects |
| `manager:read` | Read manager info |
| `manager:restart` | Restart manager |
| `cluster:read` | Read cluster info |
| `cluster:status` | Cluster status |

## Sync Bridge Protocol

### Sync State File Format

```json
{
  "synced_users": {
    "username": "keycloak-user-uuid"
  },
  "last_sync": "2026-05-01T12:00:00Z"
}
```

### Sync Cycle Flow

1. Check Keycloak reachability (port 9000 health)
2. Check Wazuh reachability (manager status)
3. Authenticate to Keycloak (admin token)
4. Authenticate to Wazuh (JWT token)
5. For each Keycloak user in wazuh realm:
   - New user → create in Wazuh
   - Existing user → check group membership
   - Deleted user → disable in Wazuh
6. Save sync state

### Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| Keycloak down | Skip sync, log warning |
| Wazuh down | Skip sync, log warning |
| Both down | Log error, wait for next cycle |
| Auth failure | Skip that service |
