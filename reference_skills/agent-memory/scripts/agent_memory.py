#!/usr/bin/env python3
"""
PostgreSQL-only async memory CLI for Codex, Claude Code, and local agents.

Design constraints:
- raw asyncpg only
- no ORM or validation-model database layer
- no SQLite/Chroma side database
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import asyncpg


VECTOR_DIMS = 384
DEFAULT_SPACE = os.getenv("AGENT_MEMORY_SPACE", "global").strip() or "global"
DEFAULT_DB = {
    "host": "192.168.50.222",
    "port": 25490,
    "database": "agent_memory",
    "user": "agent_memory",
}
BACKEND_DIR = Path(__file__).resolve().parent
LOG_DIR = Path(os.getenv("AGENT_MEMORY_LOG_DIR", str(BACKEND_DIR / "logs")))
SERVER_MANAGER_DIR = Path(
    os.getenv("SERVER_MANAGER_SKILL_DIR", r"C:\Users\cereal\.agents\skills\server-manager")
)


def json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def read_vault_secret(key: str) -> str:
    if not key:
        return ""
    candidate_dirs = [
        SERVER_MANAGER_DIR,
        Path(r"C:\Users\cereal\.agents\skills\server-manager"),
    ]
    try:
        import subprocess
    except Exception:
        return ""
    for directory in candidate_dirs:
        credman = directory / "credman.py"
        if not credman.exists():
            continue
        try:
            result = subprocess.run(
                [sys.executable, str(credman), "get", key],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            continue
    return ""


def db_config() -> dict[str, Any]:
    password = (
        os.getenv("MEMORY_DB_PASSWORD")
        or os.getenv("PGPASSWORD")
        or read_vault_secret(os.getenv("MEMORY_DB_VAULT_KEY", "agent_memory_pg"))
    )
    return {
        "host": os.getenv("MEMORY_DB_HOST", DEFAULT_DB["host"]),
        "port": int(os.getenv("MEMORY_DB_PORT", str(DEFAULT_DB["port"]))),
        "database": os.getenv("MEMORY_DB_NAME", DEFAULT_DB["database"]),
        "user": os.getenv("MEMORY_DB_USER", DEFAULT_DB["user"]),
        "password": password,
        "timeout": float(os.getenv("MEMORY_DB_CONNECT_TIMEOUT", "10")),
    }


def write_error_log(exc: Exception) -> None:
    record = {
        "created_at": datetime.now(UTC).isoformat(),
        "error": str(exc),
        "argv": sys.argv,
    }
    for directory in (LOG_DIR, Path("/tmp/agent-memory/logs"), Path.cwd() / "logs"):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "agent_memory_errors.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=json_default) + "\n")
            return
        except Exception:
            continue


async def connect() -> asyncpg.Connection:
    conn = await asyncpg.connect(**db_config())
    await conn.set_type_codec(
        "jsonb",
        encoder=lambda value: json.dumps(value, ensure_ascii=False, default=json_default),
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=lambda value: json.dumps(value, ensure_ascii=False, default=json_default),
        decoder=json.loads,
        schema="pg_catalog",
    )
    return conn


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_./:-]*", re.IGNORECASE)
ENTITY_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9_.:/-]{2,}|[a-z0-9]+(?:[-_/.:][a-z0-9]+)+)"
    r"(?:\s+(?:[A-Z][A-Za-z0-9_.:/-]{2,}|[a-z0-9]+(?:[-_/.:][a-z0-9]+)+)){0,4}\b"
)


def stem_token(token: str) -> list[str]:
    token = token.lower()
    variants = {token}
    for suffix in ("ingly", "edly", "ing", "ed", "ies", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            if suffix == "ies":
                variants.add(token[: -len(suffix)] + "y")
            else:
                variants.add(token[: -len(suffix)])
    return list(variants)


def stable_hash(text: str, salt: str = "") -> int:
    digest = hashlib.blake2b((salt + text).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False)


def add_feature(vec: list[float], feature: str, weight: float) -> None:
    h = stable_hash(feature)
    idx = h % VECTOR_DIMS
    sign = 1.0 if ((h >> 8) & 1) else -1.0
    vec[idx] += sign * weight


def cpu_embedding(text: str) -> list[float]:
    """Dependency-free CPU feature-hash embedding for local pgvector search."""
    normalized = text.lower()
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(normalized):
        if len(raw) > 96:
            raw = raw[:96]
        tokens.extend(stem_token(raw))

    vec = [0.0] * VECTOR_DIMS
    for token in tokens:
        add_feature(vec, "tok:" + token, 1.0)
        if len(token) >= 5:
            for i in range(len(token) - 2):
                add_feature(vec, "tri:" + token[i : i + 3], 0.35)

    for left, right in zip(tokens, tokens[1:]):
        add_feature(vec, "bi:" + left + " " + right, 0.8)

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [round(v / norm, 8) for v in vec]


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"


def summarize(content: str, limit: int = 280) -> str:
    one_line = re.sub(r"\s+", " ", content).strip()
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def normalize_space(space: str | None) -> str:
    value = (space or DEFAULT_SPACE or "global").strip().lower()
    value = re.sub(r"[^a-z0-9_.:/-]+", "-", value).strip("-")
    return value[:160] or "global"


def normalize_entity_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())[:240]


def extract_entities(content: str, tags: list[str] | None = None, metadata: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Extract lightweight concept candidates for the memory knowledge graph."""
    candidates: dict[str, dict[str, str]] = {}
    for item in (metadata or {}).get("entities", []) if isinstance(metadata, dict) else []:
        if isinstance(item, dict):
            name = normalize_entity_name(str(item.get("name") or ""))
            kind = str(item.get("kind") or "concept").strip().lower() or "concept"
        else:
            name = normalize_entity_name(str(item))
            kind = "concept"
        if name:
            candidates[name.lower()] = {"name": name, "kind": kind[:80]}

    for tag in tags or []:
        tag_text = normalize_entity_name(str(tag))
        if tag_text and len(tag_text) >= 4 and tag_text not in {"asyncpg", "memory"}:
            candidates.setdefault(tag_text.lower(), {"name": tag_text, "kind": "tag"})

    for match in ENTITY_RE.findall(content or ""):
        name = normalize_entity_name(match)
        lowered = name.lower()
        if len(name) < 4 or lowered in {"http", "https", "json", "true", "false", "null"}:
            continue
        candidates.setdefault(lowered, {"name": name, "kind": "concept"})
        if len(candidates) >= 32:
            break
    return list(candidates.values())[:32]


async def _execute_ddl(conn: asyncpg.Connection, sql: str) -> None:
    try:
        await conn.execute(sql)
    except (
        asyncpg.DuplicateObjectError,
        asyncpg.DuplicateTableError,
        asyncpg.UniqueViolationError,
        asyncpg.ObjectInUseError,
    ):
        return


async def init_db_async() -> dict[str, Any]:
    conn = await connect()
    try:
        await _execute_ddl(conn, "CREATE EXTENSION IF NOT EXISTS vector")
        await _execute_ddl(conn, "CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await _execute_ddl(
            conn,
            """
            CREATE TABLE IF NOT EXISTS agent_memory_spaces (
                space TEXT PRIMARY KEY,
                description TEXT,
                parent_space TEXT REFERENCES agent_memory_spaces(space) ON DELETE SET NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        )
        await conn.execute(
            """
            INSERT INTO agent_memory_spaces (space, description)
            VALUES ('global', 'Default shared memory space for unscoped legacy events.')
            ON CONFLICT (space) DO NOTHING
            """
        )
        await _execute_ddl(
            conn,
            """
            CREATE TABLE IF NOT EXISTS agent_memory_events (
                id BIGSERIAL PRIMARY KEY,
                event_uid TEXT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                space TEXT NOT NULL DEFAULT 'global',
                session_id TEXT,
                agent TEXT NOT NULL,
                event_type TEXT NOT NULL,
                memory_kind TEXT NOT NULL DEFAULT 'event',
                role TEXT,
                source TEXT,
                content TEXT NOT NULL,
                summary TEXT,
                tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
                embedding VECTOR(384),
                search_vector TSVECTOR GENERATED ALWAYS AS (
                    to_tsvector('english', coalesce(content, '') || ' ' || coalesce(summary, ''))
                ) STORED
            )
            """,
        )
        await _execute_ddl(conn, "ALTER TABLE agent_memory_events ADD COLUMN IF NOT EXISTS space TEXT NOT NULL DEFAULT 'global'")
        await _execute_ddl(conn, "ALTER TABLE agent_memory_events ADD COLUMN IF NOT EXISTS memory_kind TEXT NOT NULL DEFAULT 'event'")
        await _execute_ddl(
            conn,
            """
            CREATE TABLE IF NOT EXISTS agent_memory_entities (
                id BIGSERIAL PRIMARY KEY,
                space TEXT NOT NULL DEFAULT 'global',
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'concept',
                summary TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        )
        await _execute_ddl(
            conn,
            """
            CREATE TABLE IF NOT EXISTS agent_memory_entity_mentions (
                event_id BIGINT NOT NULL REFERENCES agent_memory_events(id) ON DELETE CASCADE,
                entity_id BIGINT NOT NULL REFERENCES agent_memory_entities(id) ON DELETE CASCADE,
                weight REAL NOT NULL DEFAULT 1.0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (event_id, entity_id)
            )
            """,
        )
        await _execute_ddl(
            conn,
            """
            CREATE TABLE IF NOT EXISTS agent_memory_entity_edges (
                id BIGSERIAL PRIMARY KEY,
                space TEXT NOT NULL DEFAULT 'global',
                source_entity_id BIGINT NOT NULL REFERENCES agent_memory_entities(id) ON DELETE CASCADE,
                target_entity_id BIGINT NOT NULL REFERENCES agent_memory_entities(id) ON DELETE CASCADE,
                relation TEXT NOT NULL DEFAULT 'related_to',
                description TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        )
        await _execute_ddl(
            conn,
            """
            CREATE TABLE IF NOT EXISTS agent_memory_event_links (
                id BIGSERIAL PRIMARY KEY,
                source_event_id BIGINT NOT NULL REFERENCES agent_memory_events(id) ON DELETE CASCADE,
                target_event_id BIGINT NOT NULL REFERENCES agent_memory_events(id) ON DELETE CASCADE,
                link_type TEXT NOT NULL DEFAULT 'related_to',
                description TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        )
        ddl = [
            """
            CREATE INDEX IF NOT EXISTS agent_memory_events_space_created_idx
            ON agent_memory_events (space, created_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_events_space_kind_idx
            ON agent_memory_events (space, memory_kind, created_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_events_created_idx
            ON agent_memory_events (created_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_events_agent_type_idx
            ON agent_memory_events (agent, event_type, created_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_events_tags_idx
            ON agent_memory_events USING GIN (tags)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_events_search_idx
            ON agent_memory_events USING GIN (search_vector)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_events_content_trgm_idx
            ON agent_memory_events USING GIN (content gin_trgm_ops)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_events_embedding_idx
            ON agent_memory_events USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 100)
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS agent_memory_entities_space_name_kind_uidx
            ON agent_memory_entities (space, lower(name), kind)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_entities_space_idx
            ON agent_memory_entities (space, kind, updated_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_entities_name_trgm_idx
            ON agent_memory_entities USING GIN (name gin_trgm_ops)
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS agent_memory_entity_edges_uidx
            ON agent_memory_entity_edges (space, source_entity_id, target_entity_id, relation)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_entity_edges_source_idx
            ON agent_memory_entity_edges (source_entity_id, relation)
            """,
            """
            CREATE INDEX IF NOT EXISTS agent_memory_event_links_source_idx
            ON agent_memory_event_links (source_event_id, link_type)
            """,
        ]
        for sql in ddl:
            await _execute_ddl(conn, sql)
        return {"ok": True, "message": "agent_memory_events schema ready", "driver": "asyncpg"}
    finally:
        await conn.close()


def make_uid(
    agent: str,
    event_type: str,
    session_id: str,
    content: str,
    metadata: dict[str, Any],
    space: str = "",
    memory_kind: str = "event",
) -> str:
    seed = json.dumps(
        {
            "space": normalize_space(space),
            "agent": agent,
            "event_type": event_type,
            "memory_kind": memory_kind,
            "session_id": session_id,
            "content": content,
            "metadata": metadata,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=json_default,
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


async def ensure_space_async(
    space: str,
    *,
    description: str = "",
    parent_space: str = "",
    metadata: dict[str, Any] | None = None,
    conn: asyncpg.Connection | None = None,
) -> str:
    normalized = normalize_space(space)
    if normalized == parent_space:
        parent_space = ""
    own_conn = conn is None
    conn = conn or await connect()
    try:
        if parent_space:
            await ensure_space_async(parent_space, conn=conn)
        await conn.execute(
            """
            INSERT INTO agent_memory_spaces (space, description, parent_space, metadata)
            VALUES ($1, $2, $3, $4::JSONB)
            ON CONFLICT (space) DO UPDATE SET
                description = COALESCE(NULLIF(EXCLUDED.description, ''), agent_memory_spaces.description),
                parent_space = COALESCE(EXCLUDED.parent_space, agent_memory_spaces.parent_space),
                metadata = agent_memory_spaces.metadata || EXCLUDED.metadata,
                updated_at = NOW()
            """,
            normalized,
            description or None,
            normalize_space(parent_space) if parent_space else None,
            metadata or {},
        )
        return normalized
    finally:
        if own_conn:
            await conn.close()


async def upsert_entity_async(
    space: str,
    name: str,
    *,
    kind: str = "concept",
    summary: str = "",
    metadata: dict[str, Any] | None = None,
    conn: asyncpg.Connection | None = None,
) -> int | None:
    name = normalize_entity_name(name)
    if not name:
        return None
    own_conn = conn is None
    conn = conn or await connect()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_memory_entities (space, name, kind, summary, metadata)
            VALUES ($1, $2, $3, $4, $5::JSONB)
            ON CONFLICT (space, lower(name), kind) DO UPDATE SET
                summary = COALESCE(NULLIF(EXCLUDED.summary, ''), agent_memory_entities.summary),
                metadata = agent_memory_entities.metadata || EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
            """,
            normalize_space(space),
            name,
            (kind or "concept")[:80],
            summary or None,
            metadata or {},
        )
        return row["id"] if row else None
    finally:
        if own_conn:
            await conn.close()


async def mention_entities_async(
    event_id: int,
    space: str,
    entities: list[dict[str, str]],
    *,
    conn: asyncpg.Connection | None = None,
) -> list[int]:
    own_conn = conn is None
    conn = conn or await connect()
    mentioned: list[int] = []
    try:
        for entity in entities:
            entity_id = await upsert_entity_async(
                space,
                entity.get("name", ""),
                kind=entity.get("kind") or "concept",
                conn=conn,
            )
            if not entity_id:
                continue
            await conn.execute(
                """
                INSERT INTO agent_memory_entity_mentions (event_id, entity_id, weight)
                VALUES ($1, $2, 1.0)
                ON CONFLICT (event_id, entity_id) DO UPDATE SET weight = GREATEST(agent_memory_entity_mentions.weight, 1.0)
                """,
                event_id,
                entity_id,
            )
            mentioned.append(entity_id)
        return mentioned
    finally:
        if own_conn:
            await conn.close()


async def add_event_async(
    *,
    agent: str,
    event_type: str,
    content: str,
    space: str = "",
    memory_kind: str = "event",
    role: str = "",
    source: str = "",
    session_id: str = "",
    summary: str = "",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await init_db_async()
    space = normalize_space(space)
    metadata = metadata or {}
    tags = tags or []
    summary = summary or summarize(content)
    event_uid = make_uid(agent, event_type, session_id, content, metadata, space, memory_kind)
    embedding = vector_literal(cpu_embedding(content + "\n" + summary))

    conn = await connect()
    try:
        await ensure_space_async(space, conn=conn)
        row = await conn.fetchrow(
            """
            INSERT INTO agent_memory_events (
                event_uid, space, session_id, agent, event_type, memory_kind, role, source,
                content, summary, tags, metadata, embedding
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::TEXT[], $12::JSONB, $13::VECTOR)
            ON CONFLICT (event_uid) DO UPDATE SET
                metadata = agent_memory_events.metadata || EXCLUDED.metadata,
                space = COALESCE(NULLIF(EXCLUDED.space, 'global'), agent_memory_events.space)
            RETURNING id, created_at, (xmax = 0) AS inserted
            """,
            event_uid,
            space,
            session_id or None,
            agent,
            event_type,
            memory_kind or "event",
            role or None,
            source or None,
            content,
            summary,
            tags,
            metadata,
            embedding,
        )
        entities = extract_entities(content + "\n" + summary, tags, metadata)
        mentioned = await mention_entities_async(row["id"], space, entities, conn=conn)
        return {
            "ok": True,
            "id": row["id"],
            "created_at": row["created_at"],
            "inserted": bool(row["inserted"]),
            "event_uid": event_uid,
            "space": space,
            "memory_kind": memory_kind or "event",
            "entities": len(mentioned),
        }
    finally:
        await conn.close()


async def search_events_async(
    query: str,
    *,
    limit: int = 10,
    space: str = "",
    all_spaces: bool = False,
    agent: str = "",
    event_type: str = "",
    memory_kind: str = "",
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    await init_db_async()
    qvec = vector_literal(cpu_embedding(query))
    filters = []
    params: list[Any] = [query, qvec, query]
    idx = 4
    if space and not all_spaces:
        filters.append(f"space = ${idx}")
        params.append(normalize_space(space))
        idx += 1
    if agent:
        filters.append(f"agent = ${idx}")
        params.append(agent)
        idx += 1
    if event_type:
        filters.append(f"event_type = ${idx}")
        params.append(event_type)
        idx += 1
    if memory_kind:
        filters.append(f"memory_kind = ${idx}")
        params.append(memory_kind)
        idx += 1
    if tags:
        filters.append(f"tags && ${idx}::TEXT[]")
        params.append(tags)
        idx += 1
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params.append(limit)

    conn = await connect()
    try:
        rows = await conn.fetch(
            f"""
            WITH q AS (
                SELECT
                    plainto_tsquery('english', $1) AS tsq,
                    $2::VECTOR AS emb,
                    $3 AS raw_query
            )
            SELECT
                id, created_at, space, session_id, agent, event_type, memory_kind, role, source,
                summary, tags, metadata,
                left(content, 2400) AS content,
                1 - (embedding <=> (SELECT emb FROM q)) AS semantic_score,
                ts_rank_cd(search_vector, (SELECT tsq FROM q)) AS text_score,
                similarity(content, (SELECT raw_query FROM q)) AS trigram_score,
                (
                    (1 - (embedding <=> (SELECT emb FROM q))) * 0.68
                    + ts_rank_cd(search_vector, (SELECT tsq FROM q)) * 0.22
                    + similarity(content, (SELECT raw_query FROM q)) * 0.10
                ) AS score
            FROM agent_memory_events
            {where}
            ORDER BY score DESC, created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def audit_events_async(
    limit: int = 20,
    session_id: str = "",
    agent: str = "",
    space: str = "",
    all_spaces: bool = False,
) -> list[dict[str, Any]]:
    await init_db_async()
    filters = []
    params: list[Any] = []
    idx = 1
    if session_id:
        filters.append(f"session_id = ${idx}")
        params.append(session_id)
        idx += 1
    if agent:
        filters.append(f"agent = ${idx}")
        params.append(agent)
        idx += 1
    if space and not all_spaces:
        filters.append(f"space = ${idx}")
        params.append(normalize_space(space))
        idx += 1
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params.append(limit)

    conn = await connect()
    try:
        rows = await conn.fetch(
            f"""
            SELECT id, created_at, space, session_id, agent, event_type, memory_kind, role, source,
                   summary, tags, metadata, left(content, 2400) AS content
            FROM agent_memory_events
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def status_async() -> dict[str, Any]:
    await init_db_async()
    conn = await connect()
    try:
        total = await conn.fetchval("SELECT count(*) AS total FROM agent_memory_events")
        breakdown_rows = await conn.fetch(
            """
            SELECT space, agent, event_type, count(*) AS count
            FROM agent_memory_events
            GROUP BY space, agent, event_type
            ORDER BY space, agent, event_type
            """
        )
        space_rows = await conn.fetch(
            """
            SELECT s.space, s.description, s.parent_space, count(e.id) AS events
            FROM agent_memory_spaces s
            LEFT JOIN agent_memory_events e ON e.space = s.space
            GROUP BY s.space, s.description, s.parent_space
            ORDER BY s.space
            """
        )
        graph_counts = await conn.fetchrow(
            """
            SELECT
                (SELECT count(*) FROM agent_memory_entities) AS entities,
                (SELECT count(*) FROM agent_memory_entity_edges) AS entity_edges,
                (SELECT count(*) FROM agent_memory_event_links) AS event_links
            """
        )
        span = await conn.fetchrow(
            """
            SELECT max(created_at) AS newest, min(created_at) AS oldest
            FROM agent_memory_events
            """
        )
        return {
            "ok": True,
            "driver": "asyncpg",
            "total": total,
            "span": dict(span) if span else {},
            "spaces": [dict(row) for row in space_rows],
            "graph": dict(graph_counts) if graph_counts else {},
            "breakdown": [dict(row) for row in breakdown_rows],
        }
    finally:
        await conn.close()


async def list_spaces_async() -> list[dict[str, Any]]:
    await init_db_async()
    conn = await connect()
    try:
        rows = await conn.fetch(
            """
            SELECT s.*, count(e.id) AS event_count
            FROM agent_memory_spaces s
            LEFT JOIN agent_memory_events e ON e.space = s.space
            GROUP BY s.space, s.description, s.parent_space, s.metadata, s.created_at, s.updated_at
            ORDER BY s.updated_at DESC, s.space
            """
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def search_entities_async(query: str = "", *, space: str = "", all_spaces: bool = False, limit: int = 20) -> list[dict[str, Any]]:
    await init_db_async()
    filters = []
    params: list[Any] = []
    idx = 1
    if query:
        filters.append(f"(name ILIKE ${idx} OR summary ILIKE ${idx})")
        params.append(f"%{query}%")
        idx += 1
    if space and not all_spaces:
        filters.append(f"space = ${idx}")
        params.append(normalize_space(space))
        idx += 1
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params.append(limit)
    conn = await connect()
    try:
        rows = await conn.fetch(
            f"""
            SELECT e.*, count(m.event_id) AS mentions
            FROM agent_memory_entities e
            LEFT JOIN agent_memory_entity_mentions m ON m.entity_id = e.id
            {where}
            GROUP BY e.id
            ORDER BY mentions DESC, e.updated_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def relate_entities_async(
    *,
    source: str,
    target: str,
    relation: str = "related_to",
    space: str = "",
    description: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await init_db_async()
    space = normalize_space(space)
    conn = await connect()
    try:
        await ensure_space_async(space, conn=conn)
        source_id = await upsert_entity_async(space, source, conn=conn)
        target_id = await upsert_entity_async(space, target, conn=conn)
        if not source_id or not target_id:
            return {"ok": False, "error": "source and target are required"}
        row = await conn.fetchrow(
            """
            INSERT INTO agent_memory_entity_edges (
                space, source_entity_id, target_entity_id, relation, description, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6::JSONB)
            ON CONFLICT (space, source_entity_id, target_entity_id, relation) DO UPDATE SET
                description = COALESCE(NULLIF(EXCLUDED.description, ''), agent_memory_entity_edges.description),
                metadata = agent_memory_entity_edges.metadata || EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
            """,
            space,
            source_id,
            target_id,
            relation or "related_to",
            description or None,
            metadata or {},
        )
        return {"ok": True, "id": row["id"], "space": space, "source_entity_id": source_id, "target_entity_id": target_id}
    finally:
        await conn.close()


async def graph_neighbors_async(entity: str, *, space: str = "", all_spaces: bool = False, limit: int = 30) -> list[dict[str, Any]]:
    await init_db_async()
    filters = ["lower(src.name) = lower($1)"]
    params: list[Any] = [entity]
    idx = 2
    if space and not all_spaces:
        filters.append(f"edge.space = ${idx}")
        params.append(normalize_space(space))
        idx += 1
    where = "WHERE " + " AND ".join(filters)
    params.append(limit)
    conn = await connect()
    try:
        rows = await conn.fetch(
            f"""
            SELECT edge.id, edge.space, src.name AS source, edge.relation,
                   dst.name AS target, edge.description, edge.metadata, edge.updated_at
            FROM agent_memory_entity_edges edge
            JOIN agent_memory_entities src ON src.id = edge.source_entity_id
            JOIN agent_memory_entities dst ON dst.id = edge.target_entity_id
            {where}
            ORDER BY edge.updated_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


def init_db() -> dict[str, Any]:
    return asyncio.run(init_db_async())


def add_event(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(add_event_async(**kwargs))


def search_events(query: str, **kwargs: Any) -> list[dict[str, Any]]:
    return asyncio.run(search_events_async(query, **kwargs))


def audit_events(limit: int = 20, session_id: str = "", agent: str = "", space: str = "", all_spaces: bool = False) -> list[dict[str, Any]]:
    return asyncio.run(audit_events_async(limit, session_id, agent, space, all_spaces))


def status() -> dict[str, Any]:
    return asyncio.run(status_async())


def list_spaces() -> list[dict[str, Any]]:
    return asyncio.run(list_spaces_async())


def search_entities(query: str = "", **kwargs: Any) -> list[dict[str, Any]]:
    return asyncio.run(search_entities_async(query, **kwargs))


def relate_entities(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(relate_entities_async(**kwargs))


def graph_neighbors(entity: str, **kwargs: Any) -> list[dict[str, Any]]:
    return asyncio.run(graph_neighbors_async(entity, **kwargs))


def read_content(args: argparse.Namespace) -> str:
    if getattr(args, "content_file", ""):
        return Path(args.content_file).read_text(encoding="utf-8")
    if getattr(args, "stdin", False):
        return sys.stdin.read()
    return getattr(args, "content", "") or ""


def parse_json_arg(value: str, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        try:
            return json.loads(value.replace('\\"', '"'))
        except json.JSONDecodeError:
            pass
    stripped = value.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        pairs = stripped[1:-1].split(",")
        parsed: dict[str, Any] = {}
        for pair in pairs:
            if ":" not in pair:
                return default
            key, raw_val = pair.split(":", 1)
            key = key.strip().strip("'\"")
            raw_val = raw_val.strip().strip("'\"")
            if not key:
                return default
            lowered = raw_val.lower()
            if lowered == "true":
                parsed[key] = True
            elif lowered == "false":
                parsed[key] = False
            elif lowered == "null":
                parsed[key] = None
            else:
                try:
                    parsed[key] = int(raw_val)
                except ValueError:
                    try:
                        parsed[key] = float(raw_val)
                    except ValueError:
                        parsed[key] = raw_val
        return parsed
    return default


def print_result(data: Any, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=json_default))
        return
    if isinstance(data, list):
        for item in data:
            created = item.get("created_at")
            score = item.get("score")
            score_text = f" score={score:.3f}" if isinstance(score, float) else ""
            space_text = f" space={item.get('space')}" if item.get("space") else ""
            print(f"[{item.get('id')}] {created}{space_text} {item.get('agent')}/{item.get('event_type')}{score_text}")
            print(f"  {item.get('summary')}")
            print()
        return
    print(json.dumps(data, indent=2, ensure_ascii=False, default=json_default))


async def self_test_async() -> dict[str, Any]:
    await init_db_async()
    sentinel = "AGENT_MEMORY_SELF_TEST_20260512 asyncpg cpu embedder postgres semantic audit trace"
    space_a = "self-test-alpha"
    space_b = "self-test-beta"
    added = await add_event_async(
        agent="self_test",
        event_type="diagnostic",
        space=space_a,
        memory_kind="test",
        role="system",
        source="agent_memory.py",
        session_id="self-test",
        content=sentinel,
        tags=["self_test", "memory", "asyncpg"],
        metadata={"test": True, "driver": "asyncpg", "entities": [{"name": "Agent Memory Spaces", "kind": "concept"}]},
    )
    await add_event_async(
        agent="self_test",
        event_type="diagnostic",
        space=space_b,
        memory_kind="test",
        role="system",
        source="agent_memory.py",
        session_id="self-test",
        content="AGENT_MEMORY_SELF_TEST_20260512 beta isolated unrelated context marker",
        tags=["self_test", "beta"],
        metadata={"test": True, "entities": ["Memory Space Isolation"]},
    )
    relation = await relate_entities_async(
        source="Agent Memory Spaces",
        target="Memory Space Isolation",
        relation="mitigates",
        space=space_a,
        description="Spaces prevent unrelated ideas and workflows from merging in default retrieval.",
        metadata={"test": True},
    )
    results = await search_events_async("asyncpg semantic audit trace memory self test", space=space_a, limit=5)
    beta_results = await search_events_async("beta isolated unrelated context marker", space=space_a, limit=5)
    graph = await graph_neighbors_async("Agent Memory Spaces", space=space_a, limit=5)
    found = any(sentinel in r.get("content", "") for r in results)
    isolated = not any("beta isolated" in r.get("content", "") for r in beta_results)
    return {"ok": found and isolated and bool(graph), "added": added, "relation": relation, "isolated": isolated, "top_results": results, "graph": graph}


def self_test() -> dict[str, Any]:
    return asyncio.run(self_test_async())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PostgreSQL-only async agent memory")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize schema")
    sub.add_parser("status", help="Show memory status")
    sub.add_parser("self-test", help="Run an insert/search test")

    add = sub.add_parser("add", help="Add a memory event")
    add.add_argument("--agent", default=os.getenv("AGENT_MEMORY_AGENT", "agent"))
    add.add_argument("--event-type", default="observation")
    add.add_argument("--space", default=os.getenv("AGENT_MEMORY_SPACE", DEFAULT_SPACE))
    add.add_argument("--memory-kind", default="event")
    add.add_argument("--role", default="")
    add.add_argument("--source", default="")
    add.add_argument("--session-id", default=os.getenv("AGENT_MEMORY_SESSION_ID", ""))
    add.add_argument("--summary", default="")
    add.add_argument("--tags", default="")
    add.add_argument("--metadata", default="")
    add.add_argument("--content", default="")
    add.add_argument("--content-file", default="")
    add.add_argument("--stdin", action="store_true")

    search = sub.add_parser("search", help="Search memory")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--space", default=os.getenv("AGENT_MEMORY_SPACE", ""))
    search.add_argument("--all-spaces", action="store_true")
    search.add_argument("--agent", default="")
    search.add_argument("--event-type", default="")
    search.add_argument("--memory-kind", default="")
    search.add_argument("--tags", default="")

    audit = sub.add_parser("audit", help="Show recent audit records")
    audit.add_argument("--limit", type=int, default=20)
    audit.add_argument("--space", default=os.getenv("AGENT_MEMORY_SPACE", ""))
    audit.add_argument("--all-spaces", action="store_true")
    audit.add_argument("--session-id", default="")
    audit.add_argument("--agent", default="")

    spaces = sub.add_parser("spaces", help="List or upsert memory spaces")
    spaces.add_argument("--space", default="")
    spaces.add_argument("--description", default="")
    spaces.add_argument("--parent-space", default="")
    spaces.add_argument("--metadata", default="")

    entities = sub.add_parser("entities", help="List/search graph entities")
    entities.add_argument("--query", default="")
    entities.add_argument("--space", default=os.getenv("AGENT_MEMORY_SPACE", ""))
    entities.add_argument("--all-spaces", action="store_true")
    entities.add_argument("--limit", type=int, default=20)

    relate = sub.add_parser("relate", help="Create an entity relationship")
    relate.add_argument("--space", default=os.getenv("AGENT_MEMORY_SPACE", DEFAULT_SPACE))
    relate.add_argument("--source", required=True)
    relate.add_argument("--target", required=True)
    relate.add_argument("--relation", default="related_to")
    relate.add_argument("--description", default="")
    relate.add_argument("--metadata", default="")

    graph = sub.add_parser("graph", help="Show graph neighbors for an entity")
    graph.add_argument("entity")
    graph.add_argument("--space", default=os.getenv("AGENT_MEMORY_SPACE", ""))
    graph.add_argument("--all-spaces", action="store_true")
    graph.add_argument("--limit", type=int, default=30)

    return parser


async def run_cli(args: argparse.Namespace) -> int:
    if args.command == "init":
        print_result(await init_db_async(), args.json)
    elif args.command == "status":
        print_result(await status_async(), args.json)
    elif args.command == "self-test":
        result = await self_test_async()
        print_result(result, args.json)
        return 0 if result["ok"] else 2
    elif args.command == "add":
        content = read_content(args)
        if not content.strip():
            raise SystemExit("content is required")
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        metadata = parse_json_arg(args.metadata, {})
        print_result(
            await add_event_async(
                agent=args.agent,
                event_type=args.event_type,
                space=args.space,
                memory_kind=args.memory_kind,
                role=args.role,
                source=args.source,
                session_id=args.session_id,
                summary=args.summary,
                tags=tags,
                metadata=metadata,
                content=content,
            ),
            args.json,
        )
    elif args.command == "search":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        print_result(
            await search_events_async(
                args.query,
                limit=args.limit,
                space=args.space,
                all_spaces=args.all_spaces,
                agent=args.agent,
                event_type=args.event_type,
                memory_kind=args.memory_kind,
                tags=tags,
            ),
            args.json,
        )
    elif args.command == "audit":
        print_result(await audit_events_async(args.limit, args.session_id, args.agent, args.space, args.all_spaces), args.json)
    elif args.command == "spaces":
        metadata = parse_json_arg(args.metadata, {})
        if args.space:
            await init_db_async()
            space = await ensure_space_async(
                args.space,
                description=args.description,
                parent_space=args.parent_space,
                metadata=metadata,
            )
            print_result({"ok": True, "space": space}, args.json)
        else:
            print_result(await list_spaces_async(), args.json)
    elif args.command == "entities":
        print_result(
            await search_entities_async(args.query, space=args.space, all_spaces=args.all_spaces, limit=args.limit),
            args.json,
        )
    elif args.command == "relate":
        print_result(
            await relate_entities_async(
                source=args.source,
                target=args.target,
                relation=args.relation,
                space=args.space,
                description=args.description,
                metadata=parse_json_arg(args.metadata, {}),
            ),
            args.json,
        )
    elif args.command == "graph":
        print_result(
            await graph_neighbors_async(args.entity, space=args.space, all_spaces=args.all_spaces, limit=args.limit),
            args.json,
        )
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(run_cli(args))
    except BrokenPipeError:
        return 1
    except Exception as exc:
        write_error_log(exc)
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
