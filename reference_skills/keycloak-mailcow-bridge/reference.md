# API Reference - Keycloak-Mailcow Bridge

## Keycloak Admin REST API

### Authentication

```
POST {KEYCLOAK_URL}/realms/master/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=password&username={admin}&password={password}&client_id=admin-cli
```

Returns access token used for all Admin API calls.

### Realm Operations

```
POST   {KEYCLOAK_URL}/admin/realms              # Create realm
GET    {KEYCLOAK_URL}/admin/realms/{realm}      # Get realm
PUT    {KEYCLOAK_URL}/admin/realms/{realm}      # Update realm
DELETE {KEYCLOAK_URL}/admin/realms/{realm}      # Delete realm
```

### Client Operations

```
POST   {KEYCLOAK_URL}/admin/realms/{realm}/clients         # Create client
GET    {KEYCLOAK_URL}/admin/realms/{realm}/clients         # List clients
GET    {KEYCLOAK_URL}/admin/realms/{realm}/clients/{id}    # Get client
PUT    {KEYCLOAK_URL}/admin/realms/{realm}/clients/{id}    # Update client
```

**OIDC Client Configuration (mailcow-oidc):**
```json
{
  "clientId": "mailcow-oidc",
  "enabled": true,
  "surrogateAuthRequired": false,
  "standardFlowEnabled": true,
  "implicitFlowEnabled": false,
  "directAccessGrantsEnabled": true,
  "serviceAccountsEnabled": true,
  "publicClient": false,
  "redirectUris": ["http://localhost/*"],
  "webOrigins": ["+"],
  "protocol": "openid-connect",
  "attributes": {
    "post.logout.redirect.uris": "+"
  }
}
```

### User Operations

```
POST   {KEYCLOAK_URL}/admin/realms/{realm}/users              # Create user
GET    {KEYCLOAK_URL}/admin/realms/{realm}/users              # List users
GET    {KEYCLOAK_URL}/admin/realms/{realm}/users/{id}         # Get user
PUT    {KEYCLOAK_URL}/admin/realms/{realm}/users/{id}         # Update user
DELETE {KEYCLOAK_URL}/admin/realms/{realm}/users/{id}         # Delete user
```

**Create User with Custom Attributes:**
```json
{
  "username": "john.doe",
  "email": "john.doe@localhost",
  "enabled": true,
  "emailVerified": true,
  "attributes": {
    "mailcow_template": "default",
    "mailcow_password": "{BLF-CRYPT}$2a$05$..."
  }
}
```

**Set User Password:**
```
PUT {KEYCLOAK_URL}/admin/realms/{realm}/users/{id}/reset-password
Content-Type: application/json

[{"type": "password", "value": "password123", "temporary": false}]
```

### Group Operations

```
POST   {KEYCLOAK_URL}/admin/realms/{realm}/groups              # Create group
GET    {KEYCLOAK_URL}/admin/realms/{realm}/groups              # List groups
PUT    {KEYCLOAK_URL}/admin/realms/{realm}/groups/{id}         # Update group
```

### Role Operations

```
POST   {KEYCLOAK_URL}/admin/realms/{realm}/roles               # Create role
GET    {KEYCLOAK_URL}/admin/realms/{realm}/roles               # List roles
POST   {KEYCLOAK_URL}/admin/realms/{realm}/users/{id}/role-mappings/realm  # Assign realm role
```

### OIDC Protocol Mappers

**Add User Attribute Mapper to Client Scope:**
```
POST {KEYCLOAK_URL}/admin/realms/{realm}/client-scopes/{scope-id}/protocol-mappers/models
Content-Type: application/json

{
  "name": "mailcow_template",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-usermodel-attribute-mapper",
  "consentRequired": false,
  "config": {
    "user.attribute": "mailcow_template",
    "id.token.claim": "true",
    "access.token.claim": "true",
    "introspection.token.claim": "true",
    "userinfo.token.claim": "true",
    "claim.name": "mailcow_template",
    "jsonType.label": "String"
  }
}
```

### Service Account Roles

```
POST {KEYCLOAK_URL}/admin/realms/{realm}/clients/{client-id}/service-accounts/role-mappings
Content-Type: application/json

[{"id": "{role-id}", "name": "view-users"}]
```

## Mailcow REST API

### Authentication

All requests require:
```
X-API-Key: {api_key}
Content-Type: application/json
```

### API Endpoints

```
GET  /api/v1/get/{category}/{object}     # Retrieve resources
POST /api/v1/add/{category}              # Create resources
POST /api/v1/edit/{category}             # Update resources
POST /api/v1/delete/{category}           # Delete resources
```

### Identity Provider Configuration

**Get Current IDP Config:**
```
GET /api/v1/get/iam
```

**Configure Keycloak as IDP:**
```
POST /api/v1/edit/iam
Content-Type: application/json

{
  "items": [],
  "attr": {
    "authsource": "keycloak",
    "keycloak_server_url": "http://localhost:8080",
    "keycloak_realm": "mailcow",
    "keycloak_client_id": "mailcow-oidc",
    "keycloak_client_secret": "{client_secret}",
    "keycloak_redirect_url": "http://localhost",
    "keycloak_version": "26",
    "keycloak_mappers": ["default"],
    "keycloak_templates": [1],
    "keycloak_periodic_full_sync": true,
    "keycloak_import_users": true,
    "keycloak_sync_interval": 30,
    "keycloak_mailpassword_flow": true
  }
}
```

### Mailbox Operations

**List Mailboxes:**
```
GET /api/v1/get/mailbox/all
```

**Create Mailbox:**
```
POST /api/v1/add/mailbox
Content-Type: application/json

{
  "username": "user@localhost",
  "password": "<from vault: keycloak_admin>",
  "domain": "localhost",
  "quota": 3,
  "active": 1
}
```

**Update Mailbox Auth Source:**
```
POST /api/v1/edit/mailbox
Content-Type: application/json

{
  "items": ["user@localhost"],
  "attr": {
    "authsource": "keycloak"
  }
}
```

### Alias Operations (Distribution Groups)

**Create Alias:**
```
POST /api/v1/add/alias
Content-Type: application/json

{
  "alias": "security-team@localhost",
  "goto": "admin@localhost,user1@localhost",
  "active": 1,
  "description": "Security team distribution group"
}
```

### Mailbox Templates

**List Templates:**
```
GET /api/v1/get/mailbox/template/all
```

## OIDC Protocol Details

### Authorization Code Flow

1. Mailcow redirects user to Keycloak:
   ```
   GET {KEYCLOAK_URL}/realms/mailcow/protocol/openid-connect/auth?
     response_type=code&
     client_id=mailcow-oidc&
     redirect_uri={redirect_url}&
     scope=openid+profile+email&
     state={csrf_token}
   ```

2. User authenticates at Keycloak

3. Keycloak redirects back with authorization code:
   ```
   GET {redirect_url}?code={auth_code}&state={csrf_token}
   ```

4. Mailcow exchanges code for tokens:
   ```
   POST {KEYCLOAK_URL}/realms/mailcow/protocol/openid-connect/token
   Content-Type: application/x-www-form-urlencoded

   grant_type=authorization_code&
   code={auth_code}&
   redirect_uri={redirect_url}&
   client_id=mailcow-oidc&
   client_secret={client_secret}
   ```

5. Mailcow fetches user info:
   ```
   GET {KEYCLOAK_URL}/realms/mailcow/protocol/openid-connect/userinfo
   Authorization: Bearer {access_token}
   ```

### Discovery Endpoint

```
GET {KEYCLOAK_URL}/realms/mailcow/.well-known/openid-configuration
```

Returns OIDC provider metadata including authorization, token, and userinfo endpoints.

## Sync Protocol

### Sync State File Format

```json
{
  "last_sync": "2026-05-01T12:00:00Z",
  "keycloak_users": {
    "john.doe": {
      "email": "john.doe@localhost",
      "mailcow_template": "default",
      "groups": ["mailcow-user"],
      "synced_at": "2026-05-01T12:00:00Z"
    }
  },
  "mailcow_mailboxes": {
    "john.doe@localhost": {
      "authsource": "keycloak",
      "quota": 5368709120,
      "synced_at": "2026-05-01T12:00:00Z"
    }
  }
}
```
