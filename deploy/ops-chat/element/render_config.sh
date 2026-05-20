#!/bin/sh
set -eu

base_url="${MATRIX_PUBLIC_BASEURL:-http://localhost:3302}"
server_name="${MATRIX_SERVER_NAME:-agentic-ops.local}"
public_url="${MATRIX_ELEMENT_PUBLIC_URL:-http://localhost:3301}"

sed \
  -e "s#__MATRIX_PUBLIC_BASEURL__#${base_url}#g" \
  -e "s#__MATRIX_SERVER_NAME__#${server_name}#g" \
  /app/config.json.template > /app/config.json

# Element Web's nginx image serves config from /tmp/element-web-config when
# runtime config mounting is enabled. Keep all known locations in sync so the
# browser never falls back to the stock matrix.org config.
mkdir -p /tmp/element-web-config /usr/share/nginx/html
if ! cmp -s /app/config.json /usr/share/nginx/html/config.json; then
  cp /app/config.json /usr/share/nginx/html/config.json
fi
cp /app/config.json /tmp/element-web-config/config.json

host_name="$(printf '%s' "${base_url}" | sed -E 's#^[a-zA-Z]+://([^/:]+).*#\1#')"
if [ -n "${host_name}" ] && [ "${host_name}" != "${base_url}" ]; then
  cp /app/config.json "/tmp/element-web-config/config.${host_name}.json"
fi

cat > /usr/share/nginx/html/agentic-ops-polyfills.js <<'EOF'
(function () {
  if (window.crypto && typeof window.crypto.randomUUID !== "function") {
    window.crypto.randomUUID = function () {
      var bytes = new Uint8Array(16);
      window.crypto.getRandomValues(bytes);
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      var hex = Array.from(bytes, function (b) {
        return b.toString(16).padStart(2, "0");
      }).join("");
      return (
        hex.slice(0, 8) + "-" +
        hex.slice(8, 12) + "-" +
        hex.slice(12, 16) + "-" +
        hex.slice(16, 20) + "-" +
        hex.slice(20)
      );
    };
  }
}());
EOF

for index_file in /app/index.html /usr/share/nginx/html/index.html; do
  if [ -f "${index_file}" ] && ! grep -q "agentic-ops-polyfills.js" "${index_file}"; then
    sed -i 's#<script src="bundles/#<script src="agentic-ops-polyfills.js"></script>\n    <script src="bundles/#' "${index_file}"
  fi
done

if [ -f /etc/nginx/tls/ops-chat.crt ] && [ -f /etc/nginx/tls/ops-chat.key ]; then
  cat > /etc/nginx/conf.d/default.conf <<EOF
server {
    listen 80;
    server_name _;
    return 301 ${public_url}\$request_uri;
}

server {
    listen 443 ssl;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    ssl_certificate /etc/nginx/tls/ops-chat.crt;
    ssl_certificate_key /etc/nginx/tls/ops-chat.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location /_matrix/ {
        proxy_pass http://ops-chat-synapse:8008/_matrix/;
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Forwarded-Host \$http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 90s;
    }

    location /_synapse/ {
        proxy_pass http://ops-chat-synapse:8008/_synapse/;
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Forwarded-Host \$http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 90s;
    }

    location /.well-known/matrix/client {
        default_type application/json;
        add_header Access-Control-Allow-Origin * always;
        return 200 '{"m.homeserver":{"base_url":"${public_url}"}}';
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
fi
