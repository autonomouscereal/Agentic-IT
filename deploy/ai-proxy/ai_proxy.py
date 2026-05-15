"""
Reference AI proxy for the enterprise operations platform.

It exposes one routable endpoint for both current harness families:
- Claude Code / Anthropic Messages: /v1/messages
- Hermes / OpenAI-compatible clients: /v1/chat/completions

Secrets are supplied by the caller or runtime environment. Do not hardcode
provider tokens in this file.
"""
import json
import logging
import os
import time

from aiohttp import web
import httpx


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ai-proxy")

LISTEN_PORT = int(os.getenv("PROXY_PORT", "4001"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "300"))
LM_STUDIO_BASE = os.getenv("LM_STUDIO_BASE", "http://localhost:1234").rstrip("/")
LM_STUDIO_TOKEN = os.getenv("LM_STUDIO_TOKEN", "lmstudio")
ANTHROPIC_BASE = os.getenv("ANTHROPIC_BASE", "https://api.anthropic.com").rstrip("/")
NOUS_BASE = os.getenv("NOUS_BASE", "https://inference-api.nousresearch.com/v1").rstrip("/")
NOUS_API_KEY = os.getenv("NOUS_API_KEY", "")
CREDENTIALS_PATH = os.path.expanduser(os.getenv("CREDENTIALS_PATH", "~/.claude_credentials.json"))

LM_MODELS = [
    {"id": "qwen/qwen3.6-27b", "weight": 3},
    {"id": "qwen/qwen3.6-27b2", "weight": 1},
    {"id": "qwen/qwen3.6-27b3", "weight": 1},
]
NOUS_MODELS = [
    "deepseek/deepseek-v4-flash",
    "deepseek-v4-flash",
]
ANTHROPIC_MODELS = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-5-20251101",
]


class Lb:
    def __init__(self, models):
        self._pool = []
        for model in models:
            self._pool.extend([model["id"]] * model["weight"])
        self._idx = 0

    def next(self):
        value = self._pool[self._idx % len(self._pool)]
        self._idx += 1
        return value


lb = Lb(LM_MODELS)
known_lm = [m["id"] for m in LM_MODELS]


def get_client_auth(request):
    auth = request.headers.get("Authorization", "") or request.headers.get("x-api-key", "")
    return auth[7:] if auth.startswith("Bearer ") else auth


def auth_preview(token):
    if not token:
        return "(none)"
    return token[:12] + "..." if len(token) > 12 else token


def is_anthropic_model(model):
    value = (model or "").lower()
    base = value.split("/", 1)[0] if "/" in value else value
    return base.startswith("claude") or base == "anthropic"


def is_local_model(model):
    value = (model or "").lower()
    return value.startswith(("qwen/", "lmstudio/", "local/")) or any(value.endswith(m.lower()) for m in known_lm)


def strip_provider_prefix(model):
    if "/" in model:
        provider, rest = model.split("/", 1)
        if provider.lower() in ("anthropic", "lmstudio", "local"):
            return rest
    return model


def strip_thinking_from_messages(body):
    for msg in body.get("messages", []):
        content = msg.get("content", [])
        if isinstance(content, list):
            msg["content"] = [block for block in content if block.get("type") != "thinking"]
    return body


_oauth_token = None
_oauth_cache_ts = 0
_oauth_expires_at = 0
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_TOKEN_ENDPOINT = "https://console.anthropic.com/v1/oauth/token"


def _load_credentials():
    with open(CREDENTIALS_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _save_credentials(creds):
    with open(CREDENTIALS_PATH, "w", encoding="utf-8") as handle:
        json.dump(creds, handle)


async def _refresh_oauth_token():
    try:
        creds = _load_credentials()
        oauth = creds.get("claudeAiOauth", {})
        refresh_token = oauth.get("refreshToken", "")
        if not refresh_token:
            return None
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": OAUTH_CLIENT_ID,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(OAUTH_TOKEN_ENDPOINT, json=payload)
        resp.raise_for_status()
        data = resp.json()
        oauth["accessToken"] = data.get("access_token", "")
        oauth["refreshToken"] = data.get("refresh_token", refresh_token)
        oauth["expiresAt"] = int(time.time() * 1000 + data.get("expires_in", 7776000) * 1000)
        creds["claudeAiOauth"] = oauth
        _save_credentials(creds)
        return oauth["accessToken"]
    except Exception as exc:
        log.warning("OAuth refresh failed: %s", exc)
        return None


async def resolve_anthropic_token(token):
    global _oauth_token, _oauth_cache_ts, _oauth_expires_at
    if token and token != LM_STUDIO_TOKEN:
        return token
    now = time.monotonic()
    if _oauth_token and now - _oauth_cache_ts < 1800 and time.time() <= _oauth_expires_at:
        return _oauth_token
    try:
        creds = _load_credentials()
        oauth = creds.get("claudeAiOauth", {})
        expires_at = oauth.get("expiresAt", 0) / 1000
        if time.time() > expires_at:
            token = await _refresh_oauth_token()
        else:
            token = oauth.get("accessToken", "")
        if token:
            _oauth_token = token
            _oauth_cache_ts = now
            _oauth_expires_at = expires_at
        return token
    except Exception:
        return _oauth_token


def anthropic_headers(request, token):
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": request.headers.get(
            "anthropic-beta",
            "oauth-2025-04-20,claude-code-20250219",
        ),
        "anthropic-dangerous-direct-browser-access": "true",
        "x-app": "cli",
        "user-agent": request.headers.get("user-agent", "claude-cli"),
    }
    if token.startswith("sk-ant-oat"):
        headers["Authorization"] = f"Bearer {token}"
    else:
        headers["x-api-key"] = token
    sid = request.headers.get("x-claude-code-session-id", "")
    if sid:
        headers["x-claude-code-session-id"] = sid
    return headers


def bearer_headers(token):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


async def copy_response(resp, request):
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        sse = web.StreamResponse(
            status=resp.status_code,
            headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
        )
        await sse.prepare(request)
        async for chunk in resp.aiter_bytes():
            if chunk:
                await sse.write(chunk)
        return sse
    content_type = resp.headers.get("content-type", "application/json")
    return web.Response(body=resp.content, status=resp.status_code, content_type=content_type.split(";")[0])


async def proxy_anthropic_messages(request, body, token):
    token = await resolve_anthropic_token(token)
    if not token:
        return web.json_response({"error": "No Anthropic authorization available"}, status=401)
    body["model"] = strip_provider_prefix(body.get("model", ""))
    strip_thinking_from_messages(body)
    url = f"{ANTHROPIC_BASE}/{request.match_info.get('path', request.path)}"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if body.get("stream"):
            async with client.stream("POST", url, json=body, headers=anthropic_headers(request, token)) as resp:
                return await copy_response(resp, request)
        resp = await client.post(url, json=body, headers=anthropic_headers(request, token))
        return await copy_response(resp, request)


async def proxy_lmstudio_chat(request, body, token):
    if not token:
        token = LM_STUDIO_TOKEN
    model = strip_provider_prefix(body.get("model", ""))
    if any(model.lower() == known.lower() for known in known_lm):
        body["model"] = model
    else:
        body["model"] = lb.next()
        log.info("LB -> %s", body["model"])
    url = f"{LM_STUDIO_BASE}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if body.get("stream"):
            async with client.stream("POST", url, json=body, headers=bearer_headers(token)) as resp:
                return await copy_response(resp, request)
        resp = await client.post(url, json=body, headers=bearer_headers(token))
        return await copy_response(resp, request)


async def proxy_nous_chat(request, body, token):
    token = token or NOUS_API_KEY
    if not token:
        return web.json_response({"error": "No Nous authorization available"}, status=401)
    url = f"{NOUS_BASE}/chat/completions"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if body.get("stream"):
            async with client.stream("POST", url, json=body, headers=bearer_headers(token)) as resp:
                return await copy_response(resp, request)
        resp = await client.post(url, json=body, headers=bearer_headers(token))
        return await copy_response(resp, request)


async def handler(request):
    path = request.match_info.get("path", request.path)
    if path == "health" and request.method == "GET":
        return web.json_response({"status": "ok", "port": LISTEN_PORT})
    models = []
    for model in LM_MODELS:
        models.append({"id": f"lmstudio/{model['id']}", "object": "model", "display_name": model["id"]})
    for model in NOUS_MODELS:
        models.append({"id": model, "object": "model", "display_name": model})
    for model in ANTHROPIC_MODELS:
        models.append({"id": f"anthropic/{model}", "object": "model", "display_name": model})
    if path in ("v1/models", "api/v1/models") and request.method == "GET":
        return web.json_response({"object": "list", "data": models})
    if path.startswith("v1/models/") and request.method == "GET":
        model_id = path.split("v1/models/", 1)[1]
        return web.json_response({"id": model_id, "object": "model", "display_name": model_id})
    if path == "api/tags" and request.method == "GET":
        return web.json_response({"models": [{"name": item["id"]} for item in models]})
    if path in ("v1/props", "props") and request.method == "GET":
        return web.json_response({"properties": {}})
    if path == "version" and request.method == "GET":
        return web.json_response({"version": "soc-ai-proxy"})
    if path == "api/show" and request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        model_id = body.get("model") or body.get("name") or ""
        return web.json_response({"model": model_id, "details": {}, "capabilities": ["completion", "tools"]})
    if path.startswith("v1/messages") and request.method == "POST":
        body = await request.json()
        model = body.get("model", "")
        token = get_client_auth(request)
        log.info("messages -> model=%s auth=%s ua=%s", model, auth_preview(token), request.headers.get("user-agent", ""))
        if is_anthropic_model(model) and token != LM_STUDIO_TOKEN:
            return await proxy_anthropic_messages(request, body, token)
        # LM Studio in this lab exposes an Anthropic-compatible messages path.
        url = f"{LM_STUDIO_BASE}/v1/messages"
        body["model"] = strip_provider_prefix(model) if is_local_model(model) else lb.next()
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            if body.get("stream"):
                async with client.stream("POST", url, json=body, headers=bearer_headers(token or LM_STUDIO_TOKEN)) as resp:
                    return await copy_response(resp, request)
            resp = await client.post(url, json=body, headers=bearer_headers(token or LM_STUDIO_TOKEN))
            return await copy_response(resp, request)
    if path == "v1/chat/completions" and request.method == "POST":
        body = await request.json()
        model = body.get("model", "")
        token = get_client_auth(request)
        log.info("chat -> model=%s auth=%s ua=%s", model, auth_preview(token), request.headers.get("user-agent", ""))
        if token == LM_STUDIO_TOKEN or is_local_model(model):
            return await proxy_lmstudio_chat(request, body, token)
        return await proxy_nous_chat(request, body, token)
    return web.json_response({"error": f"Not found: {path}"}, status=404)


def create_app():
    app = web.Application(client_max_size=20 * 1024 * 1024)
    app.router.add_route("*", "/{path:.*}", handler)
    return app


if __name__ == "__main__":
    log.info("AI Proxy on 0.0.0.0:%s", LISTEN_PORT)
    log.info("LM Studio: %s", LM_STUDIO_BASE)
    log.info("Nous: %s", NOUS_BASE)
    web.run_app(create_app(), host="0.0.0.0", port=LISTEN_PORT, print=lambda msg: log.info(msg))
