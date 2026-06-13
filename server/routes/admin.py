"""Admin route: provision tenants.

Gated by AIMEM_ADMIN_SECRET env var (constant-time compare). Returns the
raw API key ONCE — the client must save it; only the hash is persisted.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from ..auth import provision_tenant

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class ProvisionRequest(BaseModel):
    name: str


def _check_admin(secret: str | None) -> None:
    expected = os.environ.get("AIMEM_ADMIN_SECRET")
    if not expected:
        raise HTTPException(500, detail="AIMEM_ADMIN_SECRET not configured")
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad admin secret")


@router.post("/provision")
async def post_provision(
    body: ProvisionRequest,
    x_admin_secret: str | None = Header(default=None),
):
    _check_admin(x_admin_secret)
    tenant_id, raw_token = await provision_tenant(body.name)
    return {
        "tenant_id": tenant_id,
        "api_key": raw_token,
        "message": "Save the api_key now — it cannot be retrieved later.",
    }
