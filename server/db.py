"""asyncpg pool + RLS session helpers."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg
from pgvector.asyncpg import register_vector


_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    """Per-connection setup: register pgvector type codec.

    Safe-skip if extension is not installed (e.g. tests that never use
    embeddings); register_vector raises in that case and we ignore.
    """
    try:
        await register_vector(conn)
    except Exception:
        pass


async def init_db() -> asyncpg.Pool:
    """Create the global pool. Call once at app startup."""
    global _pool
    if _pool is not None:
        return _pool
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required")
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=int(os.environ.get("AIMEM_POOL_MIN", "2")),
        max_size=int(os.environ.get("AIMEM_POOL_MAX", "10")),
        command_timeout=30.0,
        timeout=10.0,
        init=_init_conn,
    )
    # Run migrations
    async with _pool.acquire() as conn:
        await _run_migrations(conn)
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("init_db() must be called first")
    return _pool


# ── RLS session helpers ─────────────────────────────────────────────────

@asynccontextmanager
async def tenant_conn(tenant_id: str) -> AsyncIterator[asyncpg.Connection]:
    """Acquire a connection scoped to one tenant (RLS enforced)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.tenant_id', $1, true), "
                "       set_config('app.bypass_rls', '', true)",
                str(tenant_id),
            )
            yield conn


@asynccontextmanager
async def admin_conn() -> AsyncIterator[asyncpg.Connection]:
    """Acquire an RLS-bypass connection — use ONLY for tenant provisioning,
    erasure cascade, and migrations. Never expose to user routes.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.bypass_rls', 'true', true)"
            )
            yield conn


# ── Migrations ──────────────────────────────────────────────────────────

async def _run_migrations(conn: asyncpg.Connection) -> None:
    """Apply server/schema/*.sql migrations in numeric order."""
    from pathlib import Path
    schema_dir = Path(__file__).parent / "schema"
    if not schema_dir.exists():
        return

    # Bypass RLS for DDL; the migration files create the policies themselves.
    await conn.execute("SELECT set_config('app.bypass_rls', 'true', false)")

    # Ensure schema_version exists first (file 001 also creates it,
    # but we need to read it before running 001).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INT PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    rows = await conn.fetch("SELECT version FROM schema_version")
    applied = {r["version"] for r in rows}

    for path in sorted(schema_dir.glob("*.sql")):
        try:
            version = int(path.stem.split("_")[0])
        except ValueError:
            continue
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        async with conn.transaction():
            await conn.execute(sql)
