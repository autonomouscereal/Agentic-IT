# IAM Bridge - API Reference

## Keycloak Admin API (26.x)

### Base URL
`http://localhost:8080/admin`

### Authentication
Obtain bearer token via the master realm:
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
| `GET` | `/admin/realms/{realm}/users/{id}/groups` | Get user's groups |
| `GET` | `/admin/realms/{realm}/clients/{id}/protocol-mappers/models` | List mappers |
| `POST` | `/admin/realms/{realm}/clients/{id}/protocol-mappers/models` | Create mapper |

### OIDC Client Configuration

```json
{
  "clientId": "itop-oidc-client",
  "enabled": true,
  "clientAuthenticatorType": "client-secret",
  "redirectUris": ["http://localhost:25432/env-production/combodo-hybridauth/callback.php"],
  "protocol": "openid-connect",
  "standardFlowEnabled": true,
  "serviceAccountsEnabled": true
}
```

### SAML Client Configuration

```json
{
  "clientId": "itop-saml-client",
  "enabled": true,
  "protocol": "saml",
  "publicClient": true,
  "attributes": {
    "saml.assertion.consume.bs": "false",
    "saml.client.signature": "false",
    "saml_force_post_binding": "true"
  }
}
```

### Health Check
```
GET http://localhost:9000/health
Response: {"status": "UP"}
```

## iTop REST API (v1.4)

### Base URL
`http://localhost:25432/webservices/rest.php`

### Authentication
Basic auth via `Authorization` header. All requests also include `user` and `password` in the JSON payload.

### Request Format
```
POST /webservices/rest.php
Content-Type: application/x-www-form-urlencoded

version=1.4&json_output=1&json_data=<base64_encoded_json>
```

### Operations

| Operation | Description |
|-----------|-------------|
| `core/check_credentials` | Verify authentication |
| `core/get` | Query objects by key or OQL |
| `core/create` | Create a new object |
| `core/update` | Update an existing object |
| `core/delete` | Delete an object |

### Get Request Payload

```json
{
  "class": "Person",
  "key": "John Doe"
}
```

Or with OQL:
```json
{
  "class": "UserLocal",
  "key": "SELECT UserLocal WHERE login = \"admin\""
}
```

### Create Request Payload

```json
{
  "class": "Person",
  "comment": "Bridge setup",
  "fields": {
    "name": "John Doe",
    "first_name": "John",
    "email": "john@example.com",
    "org_id": 1
  }
}
```

### iTop Classes

| Class | Description | Required Fields |
|-------|-------------|-----------------|
| `Person` | Contact person | `name`, `first_name`, `email`, `org_id` |
| `UserLocal` | Local user account | `contactid`, `login`, `profile_list` |
| `ExternalUser` | External (Keycloak) user | `contactid`, `login` |
| `Team` | Team/group | `name`, `org_id` |
| `Organization` | Organization | `name` |
| `Incident` | Support ticket | `title`, `description`, `impact`, `urgency`, `org_id`, `caller_id` |

### Profile IDs (Default)

| Profile | Default ID |
|---------|------------|
| Administrator | 1 |
| Configuration Manager | 2 |
| Portal power user | 3 |
| Portal user | 4 |

### UserLocal Profile Assignment

```json
{
  "profile_list": [{"profileid": "1"}]
}
```

### Important iTop API Quirks

- **`output_fields` crashes with OQL queries** - omit when using OQL keys
- **Person class does NOT have `last_name`** - use `name` for full name
- **UserLocal requires `profile_list`** - at least one profile must be assigned
- **Response keys are formatted as `Class::id`** - e.g., `UserLocal::2`

## Sync Bridge Protocol

### Sync State File Format

```json
{
  "synced_users": {
    "bridge_sync_username": "keycloak-user-uuid"
  },
  "synced_groups": {
    "itop-team-1": "itop-team-support-team"
  },
  "last_sync": "2026-04-30T12:00:00Z"
}
```

### Sync Cycle Flow

1. Check Keycloak reachability (port 9000 health endpoint)
2. Check iTop reachability (index.php)
3. Authenticate to Keycloak (admin token)
4. Authenticate to iTop (check_credentials)
5. Sync Keycloak -> iTop (user provisioning)
6. Sync iTop -> Keycloak (team feedback)
7. Save sync state

### Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| Keycloak down | Skip Keycloak-side sync, iTop continues normally |
| iTop down | Skip iTop-side sync, Keycloak continues normally |
| Both down | Log error, wait for next cycle |
| Auth failure | Skip that service, continue with the other |
