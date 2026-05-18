# Keycloak OIDC Integration - Configured 2026-04-30
gitlab_rails["omniauth_providers"] = [
  {
    "name" => "openid_connect",
    "label" => "Keycloak",
    "icon" => "/assets/images/provider/keycloak.png",
    "args" => {
      "name" => "openid_connect",
      "scope" => ["openid", "profile", "email"],
      "response_type" => "code",
      "issuer" => "https://192.168.50.222:8443/realms/gitlab",
      "discovery" => true,
      "client_auth_method" => "query",
      "uid_field" => "sub",
      "allow_validate_issuer" => false,
      "pkce" => true,
      "client_options" => {
        "identifier" => "gitlab",
        "secret" => "<client-secret-from-keycloak-or-vault>",
        "redirect_uri" => "http://192.168.50.222/users/auth/openid_connect/callback"
      }
    }
  }
]

# OIDC Authentication Settings
gitlab_rails["omniauth_enabled"] = true
gitlab_rails["omniauth_allow_single_sign_on"] = true
gitlab_rails["omniauth_block_auto_created_users"] = true
gitlab_rails["omniauth_auto_link_users"] = true
