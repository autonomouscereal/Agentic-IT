#!/usr/bin/env bash
# generate-certs.sh - Generate self-signed TLS certificates for nginx proxy
# Creates a certificate valid for keycloak.internal and localhost

set -euo pipefail

CERT_DIR="${1:-/opt/agentic-it/gitlab-keycloak-integration/certs}"
DOMAIN="${DOMAIN:-keycloak.internal}"
PUBLIC_IP="${PUBLIC_IP:-192.168.50.222}"

mkdir -p "$CERT_DIR"

echo "=== Generating TLS Certificates ==="
echo "  Domain: ${DOMAIN}"
echo "  Public IP: ${PUBLIC_IP}"
echo "  Cert dir: ${CERT_DIR}"

# Generate CA private key and certificate
openssl genrsa -out "${CERT_DIR}/ca-key.pem" 4096 2>/dev/null
openssl req -x509 -new -nodes -key "${CERT_DIR}/ca-key.pem" \
    -sha256 -days 3650 \
    -subj "/C=US/ST=Local/L=Local/O=Internal CA/CN=Internal Root CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" \
    -out "${CERT_DIR}/ca-cert.pem" 2>/dev/null
echo "  [OK] CA certificate created"

# Generate server private key
openssl genrsa -out "${CERT_DIR}/server-key.pem" 4096 2>/dev/null

# Generate CSR with SAN
openssl req -new -key "${CERT_DIR}/server-key.pem" \
    -subj "/C=US/ST=Local/L=Local/O=Internal/CN=${DOMAIN}" \
    -out "${CERT_DIR}/server.csr" 2>/dev/null

# Create extensions file for SAN
cat > "${CERT_DIR}/ext.cnf" <<EOF
[v3_ca]
subjectAltName = @alt_names
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = ${DOMAIN}
DNS.2 = localhost
IP.1 = ${PUBLIC_IP}
IP.2 = 127.0.0.1
EOF

# Sign certificate with CA
openssl x509 -req -in "${CERT_DIR}/server.csr" \
    -CA "${CERT_DIR}/ca-cert.pem" -CAkey "${CERT_DIR}/ca-key.pem" \
    -CAcreateserial -out "${CERT_DIR}/server-cert.pem" \
    -days 3650 -sha256 -extfile "${CERT_DIR}/ext.cnf" -extensions v3_ca 2>/dev/null

# Clean up temp files
rm -f "${CERT_DIR}/server.csr" "${CERT_DIR}/ext.cnf"

# Set permissions
chmod 600 "${CERT_DIR}/ca-key.pem" "${CERT_DIR}/server-key.pem"
chmod 644 "${CERT_DIR}/ca-cert.pem" "${CERT_DIR}/server-cert.pem"

echo "  [OK] Server certificate created"
echo ""
echo "  Certificates:"
echo "    CA cert:  ${CERT_DIR}/ca-cert.pem"
echo "    Server cert:  ${CERT_DIR}/server-cert.pem"
echo "    Server key:   ${CERT_DIR}/server-key.pem"
echo ""
echo "  Valid for: ${DOMAIN}, localhost, ${PUBLIC_IP}, 127.0.0.1"
