import os
import secrets
import base64
from pathlib import Path


CONFIG_DIR = Path("/config")
DATA_DIR = Path("/data")


def env(name, default=""):
    return os.getenv(name, default)


def render_template(name, target, values):
    text = (CONFIG_DIR / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    Path(target).write_text(text, encoding="utf-8")


def _oidc_endpoint_lines(public_issuer, backchannel_base):
    if not backchannel_base:
        return "    discover: true"
    public = public_issuer.rstrip("/")
    backchannel = backchannel_base.rstrip("/")
    return "\n".join(
        [
            "    discover: false",
            f'    authorization_endpoint: "{public}/protocol/openid-connect/auth"',
            f'    token_endpoint: "{backchannel}/protocol/openid-connect/token"',
            f'    userinfo_endpoint: "{backchannel}/protocol/openid-connect/userinfo"',
            f'    jwks_uri: "{backchannel}/protocol/openid-connect/certs"',
        ]
    )


def _valid_signing_key(text):
    parts = (text or "").strip().split()
    if len(parts) != 3 or parts[0] != "ed25519":
        return False
    seed = parts[2]
    padded = seed + ("=" * ((4 - len(seed) % 4) % 4))
    try:
        return len(base64.b64decode(padded, validate=True)) == 32
    except Exception:
        return False


def _new_signing_key():
    seed = base64.b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    return f"ed25519 auto {seed}\n"


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.chmod(0o777)
    media_dir = DATA_DIR / "media_store"
    media_dir.mkdir(parents=True, exist_ok=True)
    media_dir.chmod(0o777)
    signing_key = DATA_DIR / "homeserver.signing.key"
    if not signing_key.exists() or not _valid_signing_key(signing_key.read_text(encoding="utf-8", errors="ignore")):
        signing_key.write_text(_new_signing_key(), encoding="utf-8")
    signing_key.chmod(0o644)

    oidc_issuer = env("MATRIX_OIDC_ISSUER", "http://host.docker.internal:8080/realms/agentic-ops")
    values = {
        "MATRIX_SERVER_NAME": env("MATRIX_SERVER_NAME", "agentic-ops.local"),
        "MATRIX_PUBLIC_BASEURL": env("MATRIX_PUBLIC_BASEURL", "http://localhost:3302"),
        "MATRIX_ELEMENT_PUBLIC_URL": env("MATRIX_ELEMENT_PUBLIC_URL", "http://localhost:3301"),
        "MATRIX_DB_PASSWORD": env("MATRIX_DB_PASSWORD"),
        "MATRIX_REGISTRATION_SHARED_SECRET": env("MATRIX_REGISTRATION_SHARED_SECRET"),
        "MATRIX_AS_TOKEN": env("MATRIX_AS_TOKEN"),
        "MATRIX_HS_TOKEN": env("MATRIX_HS_TOKEN"),
        "MATRIX_OIDC_ENABLED": "true" if env("MATRIX_OIDC_ENABLED", "true").lower() in ("1", "true", "yes", "on") else "false",
        "MATRIX_OIDC_ISSUER": oidc_issuer,
        "MATRIX_OIDC_ENDPOINTS": _oidc_endpoint_lines(oidc_issuer, env("MATRIX_OIDC_BACKCHANNEL_BASEURL")),
        "MATRIX_OIDC_CLIENT_ID": env("MATRIX_OIDC_CLIENT_ID", "agentic-ops-chat"),
        "MATRIX_OIDC_CLIENT_SECRET": env("MATRIX_OIDC_CLIENT_SECRET"),
        "MATRIX_BOT_LOCALPART": env("MATRIX_BOT_LOCALPART", "agentic-ops"),
    }
    render_template("homeserver.yaml.template", DATA_DIR / "homeserver.yaml", values)
    render_template("ops-chat-appservice.yaml.template", DATA_DIR / "ops-chat-appservice.yaml", values)
    log_config = DATA_DIR / "log.config"
    if not log_config.exists():
        log_config.write_text(
            """
version: 1
formatters:
  precise:
    format: '%(asctime)s - %(name)s - %(lineno)d - %(levelname)s - %(request)s - %(message)s'
handlers:
  console:
    class: logging.StreamHandler
    formatter: precise
loggers:
  synapse.storage.SQL:
    level: INFO
root:
  level: INFO
  handlers: [console]
disable_existing_loggers: false
""".strip() + "\n",
            encoding="utf-8",
        )
    log_config.chmod(0o666)


if __name__ == "__main__":
    main()
