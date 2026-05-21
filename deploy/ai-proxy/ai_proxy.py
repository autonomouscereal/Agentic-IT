"""
Reference AI proxy for the enterprise operations platform.

It exposes one routable endpoint for both current harness families:
- Claude Code / Anthropic Messages: /v1/messages
- Hermes / OpenAI-compatible clients: /v1/chat/completions
- Codex / OpenAI Responses clients: /v1/responses

Secrets are supplied by the caller or runtime environment. Do not hardcode
provider tokens in this file.
"""
import json
import logging
import os
import time
import uuid

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
PROXY_CONFIG_PATH = os.getenv("PROXY_CONFIG_PATH", "/runtime/proxy_config.json")
LM_STUDIO_BASE = os.getenv("LM_STUDIO_BASE", "http://host.docker.internal:1234").rstrip("/")
LM_STUDIO_TOKEN = os.getenv("LM_STUDIO_TOKEN", "lmstudio")
ANTHROPIC_BASE = os.getenv("ANTHROPIC_BASE", "https://api.anthropic.com").rstrip("/")
NOUS_BASE = os.getenv("NOUS_BASE", "https://inference-api.nousresearch.com/v1").rstrip("/")
NOUS_API_KEY = os.getenv("NOUS_API_KEY", "")
OPENROUTER_BASE = os.getenv("OPENROUTER_BASE", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENAI_BASE = os.getenv("OPENAI_BASE", "https://api.openai.com/v1").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CUSTOM_PROVIDER_BASE = os.getenv("CUSTOM_PROVIDER_BASE", "").rstrip("/")
CUSTOM_PROVIDER_API_KEY = os.getenv("CUSTOM_PROVIDER_API_KEY", "")
CREDENTIALS_PATH = os.path.expanduser(os.getenv("CREDENTIALS_PATH", "~/.claude_credentials.json"))
TRANSIENT_PROVIDER_STATUSES = {401, 403, 429, 500, 502, 503, 504}
PROVIDER_PREFIXES = {"anthropic", "lmstudio", "local", "openai", "custom", "openrouter", "nous"}


def _split_env(name, default=""):
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _default_config():
    local = _split_env("LOCAL_MODEL_ALIASES", "qwen/qwen3.6-27b")
    nous = _split_env("NOUS_MODEL_ALIASES", "deepseek/deepseek-v4-flash,deepseek-v4-flash")
    openrouter = _split_env("OPENROUTER_MODEL_ALIASES", "openrouter/free,deepseek/deepseek-v4-flash:free")
    anthropic = _split_env(
        "ANTHROPIC_MODEL_ALIASES",
        "claude-opus-4-7,claude-sonnet-4-6,claude-haiku-4-5-20251001,claude-opus-4-5-20251101",
    )
    openai = _split_env("OPENAI_MODEL_ALIASES", "")
    custom = _split_env("CUSTOM_MODEL_ALIASES", "")
    local_model = os.getenv("AI_PROXY_LOCAL_MODEL", local[0] if local else "qwen/qwen3.6-27b")
    external_provider = os.getenv("AI_PROXY_EXTERNAL_PROVIDER", "nous").strip() or "nous"
    external_model = os.getenv("AI_PROXY_EXTERNAL_MODEL", nous[0] if nous else "deepseek/deepseek-v4-flash")
    active_route = os.getenv("AI_PROXY_MODEL_ROUTE", os.getenv("AI_MODEL_ROUTE", "local")).strip().lower() or "local"
    return {
        "routing": {
            "active": active_route,
            "external_enabled": _env_bool("AI_PROXY_EXTERNAL_ENABLED", False),
            "profiles": {
                "local": {
                    "provider": "lmstudio",
                    "model": local_model,
                    "aliases": _split_env(
                        "AI_PROXY_LOCAL_ALIASES",
                        "default,agent-default,local/agent-default,deepseek/deepseek-v4-flash,deepseek-v4-flash",
                    ),
                    "fallbacks": _split_env("LMSTUDIO_FALLBACK_PROVIDERS", ""),
                },
                "external": {
                    "provider": external_provider,
                    "model": external_model,
                    "aliases": _split_env("AI_PROXY_EXTERNAL_ALIASES", "external/agent-default"),
                    "fallbacks": _split_env("AI_PROXY_EXTERNAL_FALLBACK_PROVIDERS", "openrouter,lmstudio"),
                },
            },
        },
        "local_models": [{"id": model, "weight": 1} for model in local],
        "providers": {
            "lmstudio": {
                "base_url": LM_STUDIO_BASE,
                "token_env": "LM_STUDIO_TOKEN",
                "models": local,
                "fallbacks": _split_env("LMSTUDIO_FALLBACK_PROVIDERS", ""),
            },
            "nous": {
                "base_url": NOUS_BASE,
                "token_env": "NOUS_API_KEY",
                "models": nous,
                "fallbacks": _split_env("NOUS_FALLBACK_PROVIDERS", "openrouter,lmstudio"),
            },
            "openrouter": {
                "base_url": OPENROUTER_BASE,
                "token_env": "OPENROUTER_API_KEY",
                "models": openrouter,
                "fallback_model": "openrouter/free",
                "fallbacks": _split_env("OPENROUTER_FALLBACK_PROVIDERS", "lmstudio"),
            },
            "anthropic": {
                "base_url": ANTHROPIC_BASE,
                "token_env": "ANTHROPIC_API_KEY",
                "models": anthropic,
                "fallbacks": _split_env("ANTHROPIC_FALLBACK_PROVIDERS", ""),
            },
            "openai": {
                "base_url": OPENAI_BASE,
                "token_env": "OPENAI_API_KEY",
                "models": openai,
                "fallbacks": _split_env("OPENAI_FALLBACK_PROVIDERS", ""),
            },
            "custom": {
                "base_url": CUSTOM_PROVIDER_BASE,
                "token_env": "CUSTOM_PROVIDER_API_KEY",
                "models": custom,
                "fallbacks": _split_env("CUSTOM_FALLBACK_PROVIDERS", ""),
            },
        },
    }


def load_proxy_config():
    config = _default_config()
    if PROXY_CONFIG_PATH and os.path.exists(PROXY_CONFIG_PATH):
        with open(PROXY_CONFIG_PATH, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            config.update({k: v for k, v in loaded.items() if k != "providers"})
            providers = dict(config.get("providers") or {})
            providers.update(loaded.get("providers") or {})
            config["providers"] = providers
    return config


CONFIG = load_proxy_config()
PROVIDERS = CONFIG.get("providers") or {}
LM_MODELS = CONFIG.get("local_models") or [{"id": "qwen/qwen3.6-27b", "weight": 1}]
NOUS_MODELS = (PROVIDERS.get("nous") or {}).get("models") or []
ANTHROPIC_MODELS = (PROVIDERS.get("anthropic") or {}).get("models") or []
OPENAI_MODELS = (PROVIDERS.get("openai") or {}).get("models") or []
OPENROUTER_MODELS = (PROVIDERS.get("openrouter") or {}).get("models") or []
CUSTOM_MODELS = (PROVIDERS.get("custom") or {}).get("models") or []
ROUTING = CONFIG.get("routing") or {}
ROUTE_PROFILES = ROUTING.get("profiles") or {}
ACTIVE_ROUTE = os.getenv("AI_PROXY_MODEL_ROUTE", os.getenv("AI_MODEL_ROUTE", ROUTING.get("active", "local"))).strip().lower() or "local"
EXTERNAL_ENABLED = _env_bool("AI_PROXY_EXTERNAL_ENABLED", bool(ROUTING.get("external_enabled")))


class Lb:
    def __init__(self, models):
        self._pool = []
        for model in models:
            self._pool.extend([model["id"]] * model["weight"])
        self._idx = 0

    def next(self):
        if not self._pool:
            return "qwen/qwen3.6-27b"
        value = self._pool[self._idx % len(self._pool)]
        self._idx += 1
        return value


lb = Lb(LM_MODELS)
known_lm = [m["id"] for m in LM_MODELS]


def provider_base(name, fallback=""):
    return ((PROVIDERS.get(name) or {}).get("base_url") or fallback).rstrip("/")


def provider_token(name, request_token=""):
    provider = PROVIDERS.get(name) or {}
    token_env = provider.get("token_env")
    configured = provider.get("api_key") or ""
    if token_env:
        configured = os.getenv(token_env, configured)
    if name == "lmstudio":
        configured = configured or LM_STUDIO_TOKEN
    if name == "nous":
        configured = configured or NOUS_API_KEY
    if name == "openrouter":
        configured = configured or OPENROUTER_API_KEY
    if name == "openai":
        configured = configured or OPENAI_API_KEY
    if name == "custom":
        configured = configured or CUSTOM_PROVIDER_API_KEY
    if name == "anthropic":
        configured = configured or os.getenv("ANTHROPIC_API_KEY", "")
    return request_token or configured


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


def provider_for_chat_model(model):
    return route_for_chat_model(model)[0]


def profile_route(name):
    profiles = ROUTE_PROFILES or {}
    if name in profiles:
        return profiles[name] or {}
    if name.startswith("external"):
        return profiles.get("external") or {}
    return profiles.get("local") or {}


def _explicit_provider(model):
    value = (model or "").strip()
    if "/" not in value:
        return "", value
    prefix, rest = value.split("/", 1)
    prefix = prefix.lower()
    if prefix in PROVIDER_PREFIXES:
        return prefix, rest
    return "", value


def _profile_aliases(profile):
    return {str(item).lower() for item in (profile.get("aliases") or [])}


def _provider_models(provider):
    return [str(item).lower() for item in ((PROVIDERS.get(provider) or {}).get("models") or [])]


def route_for_chat_model(model):
    """Return provider plus model after applying the active route profile.

    The route profile is the deployment policy. In government/on-prem
    environments it should normally be `local`, which maps generic/default
    aliases and lab external model names to the local model gateway. Explicit
    provider prefixes still work for controlled tests and migrations.
    """
    requested = (model or "").strip()
    value = requested.lower()
    explicit_provider, explicit_model = _explicit_provider(requested)
    if explicit_provider in ("local", "lmstudio"):
        local_profile = profile_route("local")
        aliases = _profile_aliases(local_profile)
        if value in aliases or explicit_model.lower() in {"default", "agent-default"}:
            return "lmstudio", local_profile.get("model") or lb.next()
        return "lmstudio", explicit_model or local_profile.get("model") or lb.next()
    if explicit_provider and explicit_provider in PROVIDERS:
        if explicit_provider == "openrouter" and requested.lower() in _provider_models("openrouter"):
            return "openrouter", requested
        return explicit_provider, explicit_model or requested

    local_profile = profile_route("local")
    external_profile = profile_route("external")
    if is_local_model(requested):
        return "lmstudio", strip_provider_prefix(requested)
    if ACTIVE_ROUTE.startswith("local"):
        if value in _profile_aliases(local_profile) or value in _provider_models("nous") or value in _provider_models("openrouter"):
            return "lmstudio", local_profile.get("model") or lb.next()
        if not EXTERNAL_ENABLED:
            return "lmstudio", local_profile.get("model") or lb.next()
    if value.startswith("openrouter/") or value in _provider_models("openrouter"):
        return "openrouter", requested
    if value.startswith("openai/") or value in _provider_models("openai"):
        return "openai", strip_provider_prefix(requested)
    if value.startswith("custom/") or value in _provider_models("custom"):
        return "custom", strip_provider_prefix(requested)
    if value in _provider_models("nous"):
        return "nous", requested
    if ACTIVE_ROUTE.startswith("external") and EXTERNAL_ENABLED:
        return external_profile.get("provider") or "nous", external_profile.get("model") or requested
    return "lmstudio", local_profile.get("model") or lb.next()


def is_local_model(model):
    value = (model or "").lower()
    return value.startswith(("qwen/", "lmstudio/", "local/")) or any(value.endswith(m.lower()) for m in known_lm)


def strip_provider_prefix(model):
    if "/" in model:
        provider, rest = model.split("/", 1)
        if provider.lower() in ("anthropic", "lmstudio", "local", "openai", "custom", "nous"):
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


def openrouter_headers(token):
    headers = bearer_headers(token)
    headers["HTTP-Referer"] = os.getenv("OPENROUTER_HTTP_REFERER", "http://agentic-operations.local")
    headers["X-Title"] = os.getenv("OPENROUTER_APP_TITLE", "Agentic Operations")
    return headers


def provider_headers(provider, token):
    if provider == "openrouter":
        return openrouter_headers(token)
    return bearer_headers(token)


def provider_fallback_model(provider, requested_model):
    config = PROVIDERS.get(provider) or {}
    configured = (config.get("fallback_model") or "").strip()
    if configured:
        return configured
    models = config.get("models") or []
    return models[0] if models else requested_model


def fallback_chain(primary):
    chain = [primary]
    profile = profile_route("external" if ACTIVE_ROUTE.startswith("external") else "local")
    configured_fallbacks = profile.get("fallbacks") if primary == profile.get("provider") else None
    for provider in configured_fallbacks or (PROVIDERS.get(primary) or {}).get("fallbacks") or []:
        if provider not in chain:
            chain.append(provider)
    return chain


def provider_unavailable(resp):
    return resp.status_code in TRANSIENT_PROVIDER_STATUSES


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
    token = provider_token("lmstudio", token)
    model = strip_provider_prefix(body.get("model", ""))
    if any(model.lower() == known.lower() for known in known_lm):
        body["model"] = model
    else:
        body["model"] = lb.next()
        log.info("LB -> %s", body["model"])
    url = f"{provider_base('lmstudio', LM_STUDIO_BASE)}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if body.get("stream"):
            async with client.stream("POST", url, json=body, headers=bearer_headers(token)) as resp:
                return await copy_response(resp, request)
        resp = await client.post(url, json=body, headers=bearer_headers(token))
        return await copy_response(resp, request)


async def try_openai_compatible_chat(request, body, token, provider, model_override=None):
    token = provider_token(provider, token)
    if not token:
        return None, {"provider": provider, "status": 401, "reason": "missing_authorization"}
    if model_override:
        body["model"] = model_override
    elif provider != "openrouter":
        body["model"] = strip_provider_prefix(body.get("model", ""))
    base = provider_base(
        provider,
        {
            "nous": NOUS_BASE,
            "openrouter": OPENROUTER_BASE,
            "openai": OPENAI_BASE,
        }.get(provider, CUSTOM_PROVIDER_BASE),
    )
    if not base:
        return None, {"provider": provider, "status": 503, "reason": "missing_base_url"}
    url = f"{base}/chat/completions"
    headers = provider_headers(provider, token)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if body.get("stream"):
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if provider_unavailable(resp):
                    await resp.aread()
                    return None, {"provider": provider, "status": resp.status_code, "reason": "provider_unavailable_or_limited"}
                return await copy_response(resp, request), None
        resp = await client.post(url, json=body, headers=headers)
        if provider_unavailable(resp):
            return None, {"provider": provider, "status": resp.status_code, "reason": "provider_unavailable_or_limited"}
        return await copy_response(resp, request), None


async def proxy_chat_with_fallbacks(request, body, token, primary):
    attempts = []
    requested_model = body.get("model", "")
    for provider in fallback_chain(primary):
        attempt_body = json.loads(json.dumps(body))
        if provider == "lmstudio":
            log.warning("provider fallback -> lmstudio after attempts=%s", attempts)
            return await proxy_lmstudio_chat(request, attempt_body, LM_STUDIO_TOKEN)
        model_override = None
        if provider != primary:
            model_override = provider_fallback_model(provider, requested_model)
            log.warning("provider fallback -> %s model=%s after attempts=%s", provider, model_override, attempts)
        response, error = await try_openai_compatible_chat(
            request,
            attempt_body,
            token if provider == primary else "",
            provider,
            model_override=model_override,
        )
        if response is not None:
            return response
        attempts.append(error)
    return web.json_response({
        "error": "All configured model providers are temporarily unavailable",
        "attempts": attempts,
    }, status=503)


async def proxy_nous_chat(request, body, token):
    return await proxy_chat_with_fallbacks(request, body, token, "nous")


async def proxy_openai_compatible_chat(request, body, token, provider):
    response, error = await try_openai_compatible_chat(request, body, token, provider)
    if response is not None:
        return response
    return web.json_response({"error": error}, status=error.get("status", 503))


def responses_text_from_content(content):
    if isinstance(content, str):
        return content
    parts = []
    for item in content or []:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.append(str(item.get("text") or item.get("input_text") or item.get("output_text") or ""))
    return "\n".join(part for part in parts if part)


def responses_input_to_chat_messages(body):
    messages = []
    instructions = str(body.get("instructions") or "").strip()
    if instructions:
        messages.append({"role": "system", "content": instructions})
    payload = body.get("input")
    if isinstance(payload, str):
        messages.append({"role": "user", "content": payload})
    elif isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "function_call_output":
                messages.append({
                    "role": "tool",
                    "tool_call_id": item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                    "content": str(item.get("output") or ""),
                })
                continue
            role = item.get("role") or ("assistant" if item_type in ("message", "output_text") else "user")
            text = responses_text_from_content(item.get("content") or item.get("text") or item.get("input_text"))
            if text:
                messages.append({"role": role, "content": text})
    if not messages:
        messages.append({"role": "user", "content": ""})
    return messages


def responses_tools_to_chat_tools(tools):
    chat_tools = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") != "function":
            continue
        function = tool.get("function") or {}
        name = tool.get("name") or function.get("name")
        if not name:
            continue
        chat_tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool.get("description") or function.get("description") or "",
                "parameters": tool.get("parameters") or function.get("parameters") or {"type": "object", "properties": {}},
            },
        })
    return chat_tools


def response_usage_from_chat(chat_payload):
    usage = chat_payload.get("usage") or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
    normalized = {
        "input_tokens": input_tokens or 0,
        "output_tokens": output_tokens or 0,
        "total_tokens": total_tokens or 0,
    }
    if usage.get("output_tokens_details"):
        normalized["output_tokens_details"] = usage.get("output_tokens_details")
    elif usage.get("completion_tokens_details"):
        normalized["output_tokens_details"] = usage.get("completion_tokens_details")
    if usage.get("input_tokens_details"):
        normalized["input_tokens_details"] = usage.get("input_tokens_details")
    elif usage.get("prompt_tokens_details"):
        normalized["input_tokens_details"] = usage.get("prompt_tokens_details")
    return normalized


def response_payload_from_chat(chat_payload, model):
    choice = (chat_payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = message.get("content") or ""
    output = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        output.append({
            "type": "function_call",
            "id": f"fc_{uuid.uuid4().hex[:24]}",
            "call_id": call.get("id") or f"call_{uuid.uuid4().hex[:24]}",
            "name": function.get("name"),
            "arguments": function.get("arguments") or "{}",
            "status": "completed",
        })
    if text or not output:
        output.append({
            "type": "message",
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "status": "completed",
            "role": "assistant",
            "content": [{
                "type": "output_text",
                "text": text,
                "annotations": [],
            }],
        })
    return {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": model,
        "output": output,
        "output_text": text,
        "usage": response_usage_from_chat(chat_payload),
    }


async def sse_response_payload(request, payload):
    response = web.StreamResponse(
        status=200,
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
    )
    await response.prepare(request)

    async def send(data):
        event_type = data.get("type") if isinstance(data, dict) else ""
        prefix = f"event: {event_type}\n" if event_type else ""
        await response.write(f"{prefix}data: {json.dumps(data)}\n\n".encode("utf-8"))

    await send({"type": "response.created", "response": payload})
    for output_index, item in enumerate(payload.get("output") or []):
        await send({"type": "response.output_item.added", "output_index": output_index, "item": item})
        if item.get("type") == "message":
            for idx, part in enumerate(item.get("content") or []):
                await send({"type": "response.content_part.added", "item_id": item.get("id"), "output_index": output_index, "content_index": idx, "part": part})
                if part.get("type") == "output_text" and part.get("text"):
                    await send({"type": "response.output_text.delta", "item_id": item.get("id"), "output_index": output_index, "content_index": idx, "delta": part.get("text")})
                    await send({"type": "response.output_text.done", "item_id": item.get("id"), "output_index": output_index, "content_index": idx, "text": part.get("text")})
                await send({"type": "response.content_part.done", "item_id": item.get("id"), "output_index": output_index, "content_index": idx, "part": part})
        await send({"type": "response.output_item.done", "output_index": output_index, "item": item})
    await send({"type": "response.completed", "response": payload})
    await response.write(b"data: [DONE]\n\n")
    await response.write_eof()
    return response


async def proxy_responses(request, body, token):
    requested_model = body.get("model", "")
    provider, routed_model = route_for_chat_model(requested_model)
    chat_body = {
        "model": routed_model,
        "messages": responses_input_to_chat_messages(body),
        "temperature": body.get("temperature", 0),
        "stream": False,
    }
    chat_tools = responses_tools_to_chat_tools(body.get("tools"))
    if chat_tools:
        chat_body["tools"] = chat_tools
    if token == LM_STUDIO_TOKEN or provider == "lmstudio":
        chat_response = await proxy_lmstudio_chat(request, chat_body, token)
    elif provider in ("nous", "openrouter"):
        chat_response = await proxy_chat_with_fallbacks(request, chat_body, token, provider)
    else:
        chat_response = await proxy_openai_compatible_chat(request, chat_body, token, provider)
    if getattr(chat_response, "status", 500) >= 400:
        return chat_response
    try:
        chat_payload = json.loads((chat_response.body or b"{}").decode("utf-8"))
    except Exception as exc:
        return web.json_response({"error": f"Invalid upstream chat response: {exc}"}, status=502)
    payload = response_payload_from_chat(chat_payload, requested_model or routed_model)
    if body.get("stream"):
        return await sse_response_payload(request, payload)
    return web.json_response(payload)


async def handler(request):
    path = request.match_info.get("path", request.path)
    if path == "health" and request.method == "GET":
        return web.json_response({
            "status": "ok",
            "port": LISTEN_PORT,
            "config_path": PROXY_CONFIG_PATH,
            "routing": {
                "active": ACTIVE_ROUTE,
                "external_enabled": EXTERNAL_ENABLED,
                "local_model": (profile_route("local") or {}).get("model"),
                "external_provider": (profile_route("external") or {}).get("provider"),
                "external_model": (profile_route("external") or {}).get("model"),
            },
            "providers": sorted([name for name, provider in PROVIDERS.items() if provider.get("models")]),
        })
    models = []
    for model in LM_MODELS:
        models.append({"id": f"lmstudio/{model['id']}", "object": "model", "display_name": model["id"]})
    for model in NOUS_MODELS:
        models.append({"id": model, "object": "model", "display_name": model})
    for model in ANTHROPIC_MODELS:
        models.append({"id": f"anthropic/{model}", "object": "model", "display_name": model})
    for model in OPENAI_MODELS:
        models.append({"id": f"openai/{model}", "object": "model", "display_name": model})
    for model in OPENROUTER_MODELS:
        models.append({"id": model, "object": "model", "display_name": model})
    for model in CUSTOM_MODELS:
        models.append({"id": f"custom/{model}", "object": "model", "display_name": model})
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
    if path == "api/route" and request.method == "POST":
        body = await request.json()
        provider, routed_model = route_for_chat_model(body.get("model") or "")
        return web.json_response({
            "requested_model": body.get("model") or "",
            "provider": provider,
            "model": routed_model,
            "routing": {
                "active": ACTIVE_ROUTE,
                "external_enabled": EXTERNAL_ENABLED,
            },
            "fallback_chain": fallback_chain(provider),
        })
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
        provider, routed_model = route_for_chat_model(model)
        body["model"] = routed_model
        if token == LM_STUDIO_TOKEN or provider == "lmstudio":
            return await proxy_lmstudio_chat(request, body, token)
        if provider in ("nous", "openrouter"):
            return await proxy_chat_with_fallbacks(request, body, token, provider)
        return await proxy_openai_compatible_chat(request, body, token, provider)
    if path == "v1/responses" and request.method == "POST":
        body = await request.json()
        model = body.get("model", "")
        token = get_client_auth(request)
        log.info("responses -> model=%s auth=%s ua=%s", model, auth_preview(token), request.headers.get("user-agent", ""))
        return await proxy_responses(request, body, token)
    return web.json_response({"error": f"Not found: {path}"}, status=404)


def create_app():
    app = web.Application(client_max_size=20 * 1024 * 1024)
    app.router.add_route("*", "/{path:.*}", handler)
    return app


if __name__ == "__main__":
    log.info("AI Proxy on 0.0.0.0:%s", LISTEN_PORT)
    log.info("Config: %s", PROXY_CONFIG_PATH)
    log.info("LM Studio: %s", provider_base("lmstudio", LM_STUDIO_BASE))
    log.info("Nous: %s", provider_base("nous", NOUS_BASE))
    web.run_app(create_app(), host="0.0.0.0", port=LISTEN_PORT, print=lambda msg: log.info(msg))
