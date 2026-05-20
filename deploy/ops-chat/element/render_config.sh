#!/bin/sh
set -eu

base_url="${MATRIX_PUBLIC_BASEURL:-http://localhost:3302}"
server_name="${MATRIX_SERVER_NAME:-agentic-ops.local}"

sed \
  -e "s#__MATRIX_PUBLIC_BASEURL__#${base_url}#g" \
  -e "s#__MATRIX_SERVER_NAME__#${server_name}#g" \
  /app/config.json.template > /app/config.json
