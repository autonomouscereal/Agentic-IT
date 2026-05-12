import asyncpg
import os
import json

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5433")),
            database=os.getenv("DB_NAME", "soc_dashboard"),
            user=os.getenv("DB_USER", "soc_user"),
            password=os.getenv("DB_PASSWORD", ""),
            min_size=2,
            max_size=10,
        )
    return _pool

async def execute(query, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)

async def fetchrow(query, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None

async def fetchall(query, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(r) for r in rows]

async def fetchval(query, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)

async def executemany(query, args_list):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(query, args_list)

def json_dumps(obj):
    return json.dumps(obj, default=str)

def json_loads(s):
    return json.loads(s) if s else None
