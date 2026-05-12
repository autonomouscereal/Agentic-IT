from fastapi import APIRouter, Body, Query
import re
from html.parser import HTMLParser
from urllib.parse import urlparse
import aiohttp
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services import ticket_service
from services.event_logger import log_event

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag in ("p", "div", "section", "article", "br", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if tag in ("p", "div", "section", "article", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)

    def text(self):
        body = " ".join(self.parts)
        body = re.sub(r"\s*\n\s*", "\n", body)
        body = re.sub(r"[ \t]{2,}", " ", body)
        return body.strip()


def _safe_url(url):
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        return False
    return bool(parsed.netloc)


@router.get("")
async def list_articles(
    category: str = Query(None),
    enabled_only: bool = Query(True),
    q: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    where = []
    params = []
    idx = 1
    if enabled_only:
        where.append("enabled = true")
    if category:
        where.append(f"category ILIKE ${idx}")
        params.append(f"%{category}%")
        idx += 1
    if q:
        where.append(f"(title ILIKE ${idx} OR body ILIKE ${idx})")
        params.append(f"%{q}%")
        idx += 1
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    rows = await fetchall(
        f"SELECT * FROM knowledge_articles {where_sql} ORDER BY updated_at DESC LIMIT ${idx}",
        *params, limit,
    )
    return {"articles": rows, "total": len(rows)}


@router.get("/{article_id}")
async def get_article(article_id: int):
    row = await fetchrow("SELECT * FROM knowledge_articles WHERE id = $1", article_id)
    if not row:
        return {"error": "Knowledge article not found"}
    return row


@router.post("")
async def create_article(
    title: str = Body(...),
    body: str = Body(...),
    category: str = Body(None),
    source: str = Body("dashboard"),
    tags: list = Body([]),
    external_ref: str = Body(None),
):
    return await ticket_service.create_knowledge_article(title, body, category, source, tags, external_ref)


@router.post("/import-url")
async def import_article_url(
    url: str = Body(...),
    title: str = Body(None),
    category: str = Body("imported"),
    tags: list = Body([]),
    source: str = Body("dashboard-url-import"),
):
    if not _safe_url(url):
        return {"error": "Only http and https URLs can be imported"}
    timeout = aiohttp.ClientTimeout(total=20)
    headers = {"User-Agent": "SOC-Dashboard-KB-Importer/1.0"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as response:
                if response.status >= 400:
                    return {"error": f"Fetch failed with HTTP {response.status}"}
                content_type = response.headers.get("content-type", "")
                raw = await response.text(errors="ignore")
    except Exception as exc:
        return {"error": f"Fetch failed: {exc}"}

    body = raw
    if "html" in content_type or "<html" in raw[:500].lower():
        parser = _TextExtractor()
        parser.feed(raw)
        body = parser.text()
    body = body[:200000]
    article_title = title or url
    result = await ticket_service.create_knowledge_article(
        article_title,
        body,
        category,
        source,
        tags,
        url,
    )
    await log_event("knowledge", "info", source, "knowledge_url_imported",
                    f"article_{result.get('id')}", {"url": url, "bytes": len(body)})
    return {**result, "url": url, "bytes": len(body)}


@router.put("/{article_id}")
async def update_article(
    article_id: int,
    title: str = Body(None),
    body: str = Body(None),
    category: str = Body(None),
    tags: list = Body(None),
    enabled: bool = Body(None),
):
    values = {
        "title": title,
        "body": body,
        "category": category,
        "tags": json_dumps(tags) if tags is not None else None,
        "enabled": enabled,
    }
    fields = []
    params = []
    idx = 1
    for key, value in values.items():
        if value is not None:
            fields.append(f"{key} = ${idx}")
            params.append(value)
            idx += 1
    if not fields:
        return {"error": "No fields to update"}
    fields.append("updated_at = NOW()")
    params.append(article_id)
    await execute(f"UPDATE knowledge_articles SET {', '.join(fields)} WHERE id = ${idx}", *params)
    await log_event("knowledge", "info", "dashboard", "knowledge_article_updated",
                    f"article_{article_id}", {"fields": [f.split(' = ')[0] for f in fields[:-1]]})
    return {"status": "updated", "id": article_id}
