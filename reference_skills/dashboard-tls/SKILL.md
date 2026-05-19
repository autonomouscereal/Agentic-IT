---
name: dashboard-tls
description: >
  Deploy, repair, and validate the Agentic Operations dashboard HTTPS edge.
  Use when configuring dashboard-tls-proxy, generating runtime local-CA
  certificates, importing the demo CA into an operator workstation trust store,
  checking Secure/HttpOnly cookies, or troubleshooting dashboard certificate
  warnings and HTTPS reachability.
---

# Dashboard TLS

The dashboard HTTPS edge is `dashboard-tls-proxy`, an nginx sidecar that
terminates TLS on `DASHBOARD_HTTPS_PORT` and proxies to the internal FastAPI
service at `api:8000`. Direct FastAPI HTTP is loopback-only for local scripts,
containers, and agents.

Do not bind the dashboard to standard port `443` by default. Real environments
often reserve `443` for an existing enterprise ingress, reverse proxy, load
balancer, or another product.

## Files

- Compose service: `docker-compose.yml`, service `dashboard-tls-proxy`
- Nginx config: `deploy/dashboard-tls-proxy/nginx.conf`
- Cert generator: `scripts/generate_dashboard_tls.py`
- HTTPS smoke: `scripts/smoke_dashboard_https.py`
- Windows trust helper: `scripts/install_dashboard_ca_windows.ps1`
- Runtime certs: `runtime/tls/dashboard-ca.crt`, `dashboard-ca.key`,
  `dashboard.crt`, `dashboard.key`

Runtime keys must never be committed, copied into docs, or pasted into chat.
Only `dashboard-ca.crt` should be copied to an operator workstation.

## Generate Or Rotate

From the deployed dashboard directory:

```bash
python3 scripts/generate_dashboard_tls.py --out-dir runtime/tls --common-name agentic-operations.local
docker compose up -d dashboard-tls-proxy
python3 scripts/smoke_dashboard_https.py https://localhost:${DASHBOARD_HTTPS_PORT:-25443}
```

Use `--force` to refresh the server certificate using the existing local CA.
Use `--rotate-ca` only when intentionally replacing the trust root; after
rotation, reinstall `dashboard-ca.crt` on operator workstations.

## Trust On Windows Demo Workstation

Download only the CA cert:

```powershell
python "C:\Users\cereal\.agents\skills\server-manager\ssh_client.py" --server ai --download /home/cereal/SOC_TESTING/soc-dashboard/runtime/tls/dashboard-ca.crt "D:\IT AGENT PROJECT\runtime\trusted-ca"
.\scripts\install_dashboard_ca_windows.ps1 -CertPath "D:\IT AGENT PROJECT\runtime\trusted-ca\dashboard-ca.crt"
```

CurrentUser trust is enough for Chrome/Edge in the demo user profile and does
not require local administrator rights. Restart the browser if it had cached a
certificate error.

## Validation

Run:

```bash
python3 scripts/smoke_dashboard_https.py https://localhost:25443
```

From the operator workstation, verify normal TLS validation without
`--insecure`:

```powershell
python - <<'PY'
import urllib.request
with urllib.request.urlopen("https://192.168.50.222:25443/nginx-health", timeout=10) as resp:
    print(resp.status, resp.read().decode())
PY
```

Then run the login smoke over HTTPS:

```powershell
python scripts\smoke_dashboard_login.py https://192.168.50.222:25443 --username demo_account_1 --password-file <temp-vault-password-file>
```

Expected browser behavior:

- `https://SERVER:25443/` redirects to `/login?next=/`
- no certificate warning after `dashboard-ca.crt` is trusted
- `dashboard_session` is `Secure` and `HttpOnly`
- API/static/health requests without credentials still fail closed
