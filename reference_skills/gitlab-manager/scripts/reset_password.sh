#!/usr/bin/env bash
# reset_password.sh - Reset GitLab root password via Rails runner
set -euo pipefail

NEW_PASS="${1:-GitLabAdmin2026!SecurePass}"

docker exec -i gitlab gitlab-rails runner "
user = User.find_by(username: 'root')
if user.nil?
  puts 'ERROR: root user not found'
  exit 1
end
user.password = '${NEW_PASS}'
user.password_confirmation = '${NEW_PASS}'
if user.save!
  puts 'SUCCESS: Root password updated'
else
  puts 'ERROR: Failed to save password'
  exit 1
end
"
