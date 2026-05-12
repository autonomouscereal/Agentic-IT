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
DEFAULT_DB = {
    "host": "192.168.50.222",
    "port": 25490,
    "database": "agent_memory",
    "user": "agent_memory",
}
BACKEND_DIR = Path(__file__).resolve().parent
LOG_DIR = BACKEND_DIR / "logs"
SERVER_MANAGER_DIR = Path(
    os.getenv("SERVER_MANAGER_SKILL_DIR", r"C:\Users\cereal\.claude\skills\server-manager")
)


def json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def read_vault_secret(key: str) -> str:
    if not key:
        return ""
    credman = SERVER_MANAGER_DIR / "credman.py"
    if not credman.exists():
        return ""
    try:
        import subprocess

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
        return ""
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
            CREATE TABLE IF NOT EXISTS agent_memory_events (
                id BIGSERIAL PRIMARY KEY,
                event_uid TEXT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                session_id TEXT,
                agent TEXT NOT NULL,
                event_type TEXT NOT NULL,
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
        ddl = [
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
        ]
        for sql in ddl:
            await _execute_ddl(conn, sql)
        return {"ok": True, "message": "agent_memory_events schema ready", "driver": "asyncpg"}
    finally:
        await conn.close()


def make_uid(agent: str, event_type: str, session_id: str, content: str, metadata: dict[str, Any]) -> str:
    seed = json.dumps(
        {
            "agent": agent,
            "event_type": event_type,
            "session_id": session_id,
            "content": content,
            "metadata": metadata,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=json_default,
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


async def add_event_async(
    *,
    agent: str,
    event_type: str,
    content: str,
    role: str = "",
    source: str = "",
    session_id: str = "",
    summary: str = "",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await init_db_async()
    metadata = metadata or {}
    tags = tags or []
    summary = summary or summarize(content)
    event_uid = make_uid(agent, event_type, session_id, content, metadata)
    embedding = vector_literal(cpu_embedding(content + "\n" + summary))

    conn = await connect()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_memory_events (
                event_uid, session_id, agent, event_type, role, source,
                content, summary, tags, metadata, embedding
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::TEXT[], $10::JSONB, $11::VECTOR)
            ON CONFLICT (event_uid) DO UPDATE SET
                metadata = agent_memory_events.metadata || EXCLUDED.metadata
            RETURNING id, created_at, (xmax = 0) AS inserted
            """,
            event_uid,
            session_id or None,
            agent,
            event_type,
            role or None,
            source or None,
            content,
            summary,
            tags,
            metadata,
            embedding,
        )
        return {
            "ok": True,
            "id": row["id"],
            "created_at": row["created_at"],
            "inserted": bool(row["inserted"]),
            "event_uid": event_uid,
        }
    finally:
        await conn.close()


async def search_events_async(
    query: str,
    *,
    limit: int = 10,
    agent: str = "",
    event_type: str = "",
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    await init_db_async()
    qvec = vector_literal(cpu_embedding(query))
    filters = []
    params: list[Any] = [query, qvec, query]
    idx = 4
    if agent:
        filters.append(f"agent = ${idx}")
        params.append(agent)
        idx += 1
    if event_type:
        filters.append(f"event_type = ${idx}")
        params.append(event_type)
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
                id, created_at, session_id, agent, event_type, role, source,
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


async def audit_events_async(limit: int = 20, session_id: str = "", agent: str = "") -> list[dict[str, Any]]:
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
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params.append(limit)

    conn = await connect()
    try:
        rows = await conn.fetch(
            f"""
            SELECT id, created_at, session_id, agent, event_type, role, source,
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
            SELECT agent, event_type, count(*) AS count
            FROM agent_memory_events
            GROUP BY agent, event_type
            ORDER BY agent, event_type
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
            "breakdown": [dict(row) for row in breakdown_rows],
        }
    finally:
        await conn.close()


def init_db() -> dict[str, Any]:
    return asyncio.run(init_db_async())


def add_event(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(add_event_async(**kwargs))


def search_events(query: str, **kwargs: Any) -> list[dict[str, Any]]:
    return asyncio.run(search_events_async(query, **kwargs))


def audit_events(limit: int = 20, session_id: str = "", agent: str = "") -> list[dict[str, Any]]:
    return asyncio.run(audit_events_async(limit, session_id, agent))


def status() -> dict[str, Any]:
    return asyncio.run(status_async())


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
            print(f"[{item.get('id')}] {created} {item.get('agent')}/{item.get('event_type')}{score_text}")
            print(f"  {item.get('summary')}")
            print()
        return
    print(json.dumps(data, indent=2, ensure_ascii=False, default=json_default))


async def self_test_async() -> dict[str, Any]:
    await init_db_async()
    sentinel = "AGENT_MEMORY_SELF_TEST_20260512 asyncpg cpu embedder postgres semantic audit trace"
    added = await add_event_async(
        agent="self_test",
        event_type="diagnostic",
        role="system",
        source="agent_memory.py",
        session_id="self-test",
        content=sentinel,
        tags=["self_test", "memory", "asyncpg"],
        metadata={"test": True, "driver": "asyncpg"},
    )
    results = await search_events_async("asyncpg semantic audit trace memory self test", limit=5)
    found = any(sentinel in r.get("content", "") for r in results)
    return {"ok": found, "added": added, "top_results": results}


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
    search.add_argument("--agent", default="")
    search.add_argument("--event-type", default="")
    search.add_argument("--tags", default="")

    audit = sub.add_parser("audit", help="Show recent audit records")
    audit.add_argument("--limit", type=int, default=20)
    audit.add_argument("--session-id", default="")
    audit.add_argument("--agent", default="")

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
                agent=args.agent,
                event_type=args.event_type,
                tags=tags,
            ),
            args.json,
        )
    elif args.command == "audit":
        print_result(await audit_events_async(args.limit, args.session_id, args.agent), args.json)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(run_cli(args))
    except Exception as exc:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "agent_memory_errors.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "created_at": datetime.now(UTC).isoformat(),
                        "error": str(exc),
                        "argv": sys.argv,
                    },
                    ensure_ascii=False,
                    default=json_default,
                )
                + "\n"
            )
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
