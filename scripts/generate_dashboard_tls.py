#!/usr/bin/env python3
"""Generate runtime-only CA-signed TLS assets for the dashboard proxy."""
import argparse
import ipaddress
import os
import socket
import stat
import subprocess
import tempfile
from pathlib import Path


def local_names():
    values = {"localhost"}
    try:
        values.add(socket.gethostname())
        values.add(socket.getfqdn())
    except Exception:
        pass
    for name in os.getenv("DASHBOARD_TLS_EXTRA_DNS", "").split(","):
        name = name.strip()
        if name:
            values.add(name)
    return sorted(v for v in values if v)


def local_ips():
    values = {"127.0.0.1"}
    for name in os.getenv("DASHBOARD_TLS_EXTRA_IPS", "").split(","):
        name = name.strip()
        if name:
            values.add(name)
    try:
        output = subprocess.run(
            ["hostname", "-I"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        for item in output.split():
            try:
                values.add(str(ipaddress.ip_address(item)))
            except ValueError:
                pass
    except Exception:
        pass
    return sorted(values)


def build_openssl_config(common_name, dns_names, ip_addresses):
    alt_names = []
    for idx, name in enumerate(dns_names, start=1):
        alt_names.append(f"DNS.{idx} = {name}")
    for idx, ip in enumerate(ip_addresses, start=1):
        alt_names.append(f"IP.{idx} = {ip}")
    return f"""[req]
default_bits = 3072
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = v3_req

[dn]
CN = {common_name}
O = Agentic Operations
OU = Runtime TLS

[v3_req]
subjectAltName = @alt_names
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
basicConstraints = critical, CA:false

[alt_names]
{os.linesep.join(alt_names)}
"""


def build_ca_config(common_name):
    return f"""[req]
default_bits = 4096
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_ca

[dn]
CN = {common_name} Root CA
O = Agentic Operations
OU = Runtime Local CA

[v3_ca]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:true, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
"""


def write_temp_config(text):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(text)
        return handle.name


def ensure_ca(out_dir, common_name, days, rotate_ca=False):
    ca_cert = out_dir / "dashboard-ca.crt"
    ca_key = out_dir / "dashboard-ca.key"
    if ca_cert.exists() and ca_key.exists() and not rotate_ca:
        return ca_cert, ca_key, "existing"
    config_path = write_temp_config(build_ca_config(common_name))
    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-nodes",
                "-newkey",
                "rsa:4096",
                "-days",
                str(max(days, 3650)),
                "-keyout",
                str(ca_key),
                "-out",
                str(ca_cert),
                "-config",
                config_path,
            ],
            check=True,
        )
    finally:
        try:
            os.unlink(config_path)
        except OSError:
            pass
    return ca_cert, ca_key, "created"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="runtime/tls")
    parser.add_argument("--common-name", default=os.getenv("DASHBOARD_TLS_COMMON_NAME", "agentic-operations.local"))
    parser.add_argument("--days", type=int, default=int(os.getenv("DASHBOARD_TLS_DAYS", "825")))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--rotate-ca", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    cert_path = out_dir / "dashboard.crt"
    key_path = out_dir / "dashboard.key"
    ca_cert_path = out_dir / "dashboard-ca.crt"
    ca_key_path = out_dir / "dashboard-ca.key"
    ca_hint_path = out_dir / "README.txt"
    if cert_path.exists() and key_path.exists() and ca_cert_path.exists() and ca_key_path.exists() and not args.force and not args.rotate_ca:
        print({"status": "exists", "cert": str(cert_path), "ca_cert": str(ca_cert_path), "key": str(key_path), "secret_printed": False})
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    dns_names = local_names()
    ip_addresses = local_ips()
    if args.common_name not in dns_names:
        dns_names.insert(0, args.common_name)
    config = build_openssl_config(args.common_name, dns_names, ip_addresses)
    ca_cert, ca_key, ca_status = ensure_ca(out_dir, args.common_name, args.days, args.rotate_ca)
    csr_path = out_dir / "dashboard.csr"

    config_path = write_temp_config(config)
    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-newkey",
                "rsa:3072",
                "-nodes",
                "-keyout",
                str(key_path),
                "-out",
                str(csr_path),
                "-config",
                config_path,
            ],
            check=True,
        )
        subprocess.run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(csr_path),
                "-CA",
                str(ca_cert),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(cert_path),
                "-days",
                str(args.days),
                "-sha256",
                "-extfile",
                config_path,
                "-extensions",
                "v3_req",
            ],
            check=True,
        )
    finally:
        try:
            os.unlink(config_path)
        except OSError:
            pass
        try:
            csr_path.unlink()
        except OSError:
            pass

    try:
        key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        ca_key.chmod(stat.S_IRUSR | stat.S_IWUSR)
        cert_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        ca_cert.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        pass

    ca_hint_path.write_text(
        "This directory contains runtime-generated dashboard TLS assets.\n"
        "Import dashboard-ca.crt into an operator workstation trust store for demos.\n"
        "dashboard.key and dashboard-ca.key are secret runtime material and must never be committed.\n",
        encoding="utf-8",
    )
    print({
        "status": "created",
        "ca_status": ca_status,
        "cert": str(cert_path),
        "ca_cert": str(ca_cert),
        "key": str(key_path),
        "dns_names": dns_names,
        "ip_addresses": ip_addresses,
        "secret_printed": False,
    })


if __name__ == "__main__":
    main()
