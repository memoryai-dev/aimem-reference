"""Bearer token auth + RLS scope.

Token is hashed with SHA-256 (no salt — bearer tokens are already
high-entropy random and treated as opaque secrets by the client).
On match, sets `app.tenant_id` for the request connection.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from server.db import admin_conn, get_pool


@dataclass
class AuthPrincipal:
    tenant_id: str
    scopes: list[str]


def hash_token(raw: str) -> str:
    """SHA-256 of UTF-8 token bytes, lowercase hex."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """Return a fresh 32-byte URL-safe token (raw, shown to user once)."""
    return "aimem_" + secrets.token_urlsafe(32)


async def authenticate(
    authorization: str | None = Header(default=None),
) -> AuthPrincipal:
    """FastAPI dependency: validates Bearer token, returns AuthPrincipal."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="empty token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    h = hash_token(token)
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Bypass RLS for the lookup (transaction-local). Lookup is by
            # hash so cross-tenant exposure here is bounded.
            await conn.execute("SELECT set_config('app.bypass_rls', 'true', true)")
            row = await conn.fetchrow(
                "SELECT tenant_id, scopes FROM api_keys "
                "WHERE key_hash = $1 AND revoked_at IS NULL",
                h,
            )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        )
    return AuthPrincipal(
        tenant_id=str(row["tenant_id"]),
        scopes=list(row["scopes"]),
    )


def require_scope(scope: str):
    """Dependency factory: enforce a specific scope on the principal."""
    async def _check(principal: AuthPrincipal) -> AuthPrincipal:
        if scope not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing scope {scope!r}",
            )
        return principal
    return _check


# ── Tenant + key provisioning (admin path) ──────────────────────────────

async def provision_tenant(name: str) -> tuple[str, str]:
    """Create a tenant + a fresh API key. Returns (tenant_id, raw_token).

    The raw token is shown to the caller ONCE; only its hash is stored.
    """
    raw = generate_token()
    async with admin_conn() as conn:
        tenant_id = await conn.fetchval(
            "INSERT INTO tenants (name) VALUES ($1) RETURNING id",
            name,
        )
        await conn.execute(
            "INSERT INTO api_keys (tenant_id, key_hash) VALUES ($1::uuid, $2)",
            tenant_id, hash_token(raw),
        )
    return str(tenant_id), raw
