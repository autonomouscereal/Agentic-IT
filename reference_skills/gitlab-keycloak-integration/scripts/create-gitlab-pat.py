#!/usr/bin/env python3
"""Create a Rails runner script to generate a GitLab root PAT."""
ruby_code = """
# Delete any existing oidc-setup token
user = User.find_by(username: 'root')
old_token = user.personal_access_tokens.find_by(name: 'oidc-setup')
old_token&.destroy

token = user.personal_access_tokens.create(
  name: 'oidc-setup',
  scopes: [:api, :read_user, :read_api, :write_api, :read_repository, :write_repository],
  expires_at: Date.new(2027, 12, 31)
)

if token && token.token
  puts "PAT: #{token.token}"
else
  puts "ERROR: Failed to create token"
  exit 1
end
"""

with open("/opt/agentic-it/create-pat.rake", "w") as f:
    f.write(ruby_code)
print("Wrote create-pat.rake")
