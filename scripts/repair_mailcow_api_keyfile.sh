#!/usr/bin/env bash
set -euo pipefail

KEY_FILE="${MAILCOW_API_KEY_FILE:-/home/cereal/Mailcow/deploy/api-nginx/.api_key}"

mkdir -p "$(dirname "$KEY_FILE")"

docker exec mysql-mailcow sh -lc '
  mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -N -B \
    -e "SELECT api_key FROM api WHERE LENGTH(api_key) > 10 LIMIT 1" 2>/dev/null
' > "$KEY_FILE"

chmod 600 "$KEY_FILE"
test -s "$KEY_FILE"
echo "mailcow api key file repaired"
