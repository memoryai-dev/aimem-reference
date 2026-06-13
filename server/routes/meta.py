"""Health check + spec discovery."""
from __future__ import annotations

from fastapi import APIRouter

from ..bundle import BUNDLE_FORMAT, BUNDLE_VERSION

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/.well-known/aimem-spec")
async def spec_discovery():
    """Discovery doc: tells callers which spec version this server speaks."""
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "draft": "draft-vu-aimem-bundle-01",
        "spec_url": "https://github.com/memoryai-dev/aimem-reference/blob/main/spec/draft-vu-aimem-bundle-01.md",
        "endpoints": {
            "export": "GET /v1/brain/export",
            "export_stream": "GET /v1/brain/export/stream",
            "import": "POST /v1/brain/import",
        },
        "media_type": "application/aimem-bundle+json",
    }
