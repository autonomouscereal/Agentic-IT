"""Small Wazuh API/indexer client for dashboard-gated agent lookups."""
import os
import ssl
import aiohttp


WAZUH_API_URL = os.getenv("WAZUH_API_URL", "").rstrip("/")
WAZUH_API_USER = os.getenv("WAZUH_API_USER", "")
WAZUH_API_PASSWORD = os.getenv("WAZUH_API_PASSWORD", "")
WAZUH_INDEXER_URL = os.getenv("WAZUH_INDEXER_URL", "").rstrip("/")
WAZUH_INDEXER_USER = os.getenv("WAZUH_INDEXER_USER", "")
WAZUH_INDEXER_PASSWORD = os.getenv("WAZUH_INDEXER_PASSWORD", "")
VERIFY_TLS = os.getenv("WAZUH_VERIFY_TLS", "false").lower() in ("1", "true", "yes", "on")


class WazuhConfigError(RuntimeError):
    pass


def _ssl_context():
    if VERIFY_TLS:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def _json_response(response):
    text = await response.text()
    try:
        data = await response.json(content_type=None)
    except Exception:
        data = {"raw": text[:2000]}
    if response.status >= 400:
        return {"error": "wazuh_request_failed", "status_code": response.status, "body": data}
    return data


def configured():
    return bool(WAZUH_API_URL and WAZUH_API_USER and WAZUH_API_PASSWORD)


async def authenticate():
    if not configured():
        raise WazuhConfigError("WAZUH_API_URL/WAZUH_API_USER/WAZUH_API_PASSWORD are not configured")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{WAZUH_API_URL}/security/user/authenticate",
            params={"raw": "true"},
            auth=aiohttp.BasicAuth(WAZUH_API_USER, WAZUH_API_PASSWORD),
            ssl=_ssl_context(),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            text = (await response.text()).strip()
            if response.status >= 400:
                return {"error": "wazuh_auth_failed", "status_code": response.status, "body": text[:500]}
            return {"token": text}


async def api_get(path, params=None):
    auth = await authenticate()
    if auth.get("error"):
        return auth
    token = auth["token"]
    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as session:
        async with session.get(
            f"{WAZUH_API_URL}{path}",
            params=params or {},
            ssl=_ssl_context(),
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            return await _json_response(response)


async def manager_status():
    return await api_get("/manager/status")


async def rule(rule_id):
    return await api_get("/rules", {"rule_ids": str(rule_id)})


async def search_alerts(rule_id=None, source_ip=None, limit=10):
    if not (WAZUH_INDEXER_URL and WAZUH_INDEXER_USER and WAZUH_INDEXER_PASSWORD):
        return {
            "error": "wazuh_indexer_not_configured",
            "detail": "Set WAZUH_INDEXER_URL/WAZUH_INDEXER_USER/WAZUH_INDEXER_PASSWORD for raw alert lookup.",
        }
    must = []
    if rule_id:
        must.append({"term": {"rule.id": str(rule_id)}})
    if source_ip:
        must.append({
            "bool": {
                "should": [
                    {"term": {"data.srcip": source_ip}},
                    {"term": {"srcip": source_ip}},
                    {"term": {"source.ip": source_ip}},
                    {"term": {"agent.ip": source_ip}},
                ],
                "minimum_should_match": 1,
            }
        })
    query = {"bool": {"must": must}} if must else {"match_all": {}}
    payload = {
        "size": max(1, min(int(limit or 10), 50)),
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": query,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{WAZUH_INDEXER_URL}/wazuh-alerts-*/_search",
            json=payload,
            auth=aiohttp.BasicAuth(WAZUH_INDEXER_USER, WAZUH_INDEXER_PASSWORD),
            ssl=_ssl_context(),
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            data = await _json_response(response)
    if data.get("error"):
        return data
    hits = ((data.get("hits") or {}).get("hits") or [])[: max(1, min(int(limit or 10), 50))]
    return {
        "total": (data.get("hits") or {}).get("total"),
        "alerts": [
            {
                "id": hit.get("_id"),
                "index": hit.get("_index"),
                "score": hit.get("_score"),
                "source": hit.get("_source") or {},
            }
            for hit in hits
        ],
    }
