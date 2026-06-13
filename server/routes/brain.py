"""Bundle export/import HTTP routes.

Implements the HTTP Profile in draft-vu-aimem-bundle-01 §4.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
import json as _json

from ..auth import AuthPrincipal, authenticate
from ..bundle import (
    Bundle, BundleValidationError,
    export_bundle, import_bundle,
)
from ..db import tenant_conn

router = APIRouter(prefix="/v1/brain", tags=["brain"])

AIMEM_MEDIA_TYPE = "application/aimem-bundle+json"


def _problem(status_code: int, code: str, detail: str) -> JSONResponse:
    """RFC 7807 problem details response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "type": f"https://aimem.dev/errors/{code}",
            "title": code,
            "status": status_code,
            "detail": detail,
        },
        media_type="application/problem+json",
    )


@router.get("/export")
async def get_export(
    scope: str = Query("FULL", regex=r"^(FULL|DNA_ONLY|SINCE)$"),
    since: str | None = Query(None),
    include_embeddings: bool = Query(False),
    embedding_model: str | None = Query(None),
    embedding_dim: int | None = Query(None),
    principal: AuthPrincipal = Depends(authenticate),
) -> JSONResponse:
    """GET /v1/brain/export — return AIMEM Bundle JSON."""
    if "bundle:export" not in principal.scopes:
        return _problem(status.HTTP_403_FORBIDDEN, "missing_scope", "bundle:export required")

    since_dt: datetime | None = None
    if scope == "SINCE":
        if not since:
            return _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "since_required", "scope=SINCE requires `since` query param",
            )
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            return _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "bad_since", f"`since` is not ISO-8601: {since!r}",
            )

    import os
    producer = os.environ.get("AIMEM_PRODUCER", "aimem-reference")

    async with tenant_conn(principal.tenant_id) as conn:
        bundle = await export_bundle(
            conn,
            producer=producer,
            tenant_id=principal.tenant_id,
            scope=scope,
            since=since_dt,
            include_embeddings=include_embeddings,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
        )

    return JSONResponse(
        content=bundle.to_json(),
        media_type=AIMEM_MEDIA_TYPE,
    )


@router.get("/export/stream")
async def get_export_stream(
    scope: str = Query("FULL", regex=r"^(FULL|DNA_ONLY|SINCE)$"),
    since: str | None = Query(None),
    include_embeddings: bool = Query(False),
    embedding_model: str | None = Query(None),
    embedding_dim: int | None = Query(None),
    principal: AuthPrincipal = Depends(authenticate),
) -> StreamingResponse:
    """GET /v1/brain/export/stream — NDJSON for large bundles.

    First line: envelope (without record arrays).
    Subsequent lines: {"_kind": "chunk"|"edge"|"entity"|"chunk_entity", ...}
    """
    if "bundle:export" not in principal.scopes:
        raise HTTPException(403, detail="bundle:export required")

    since_dt: datetime | None = None
    if scope == "SINCE":
        if not since:
            raise HTTPException(422, detail="since required for scope=SINCE")
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))

    import os
    producer = os.environ.get("AIMEM_PRODUCER", "aimem-reference")

    async def gen():
        async with tenant_conn(principal.tenant_id) as conn:
            bundle = await export_bundle(
                conn,
                producer=producer,
                tenant_id=principal.tenant_id,
                scope=scope,
                since=since_dt,
                include_embeddings=include_embeddings,
                embedding_model=embedding_model,
                embedding_dim=embedding_dim,
            )
        body = bundle.to_json()
        env = {k: v for k, v in body.items()
               if k not in ("chunks", "edges", "entities", "chunk_entities")}
        yield (_json.dumps(env, separators=(",", ":")) + "\n").encode("utf-8")
        for c in body["chunks"]:
            yield (_json.dumps({"_kind": "chunk", **c}, separators=(",", ":")) + "\n").encode("utf-8")
        for e in body["edges"]:
            yield (_json.dumps({"_kind": "edge", **e}, separators=(",", ":")) + "\n").encode("utf-8")
        for ent in body["entities"]:
            yield (_json.dumps({"_kind": "entity", **ent}, separators=(",", ":")) + "\n").encode("utf-8")
        for ce in body["chunk_entities"]:
            yield (_json.dumps({"_kind": "chunk_entity", **ce}, separators=(",", ":")) + "\n").encode("utf-8")

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.post("/import")
async def post_import(
    body: dict[str, Any],
    principal: AuthPrincipal = Depends(authenticate),
) -> JSONResponse:
    """POST /v1/brain/import — ingest an AIMEM Bundle into the caller's tenant."""
    if "bundle:import" not in principal.scopes:
        return _problem(status.HTTP_403_FORBIDDEN, "missing_scope", "bundle:import required")

    try:
        bundle = Bundle.from_json(body)
    except BundleValidationError as e:
        if e.code == "checksum_mismatch":
            return _problem(status.HTTP_409_CONFLICT, e.code, str(e))
        return _problem(status.HTTP_422_UNPROCESSABLE_ENTITY, e.code, str(e))

    async with tenant_conn(principal.tenant_id) as conn:
        summary = await import_bundle(
            conn, bundle, target_tenant_id=principal.tenant_id,
        )

    return JSONResponse(content=summary.to_json())
