"""Bundle Producer — read tenant rows → emit AIMEM Bundle (draft-01).

Only reads from the database; never mutates. Pure mapping from rows to
schema.ChunkRecord/EdgeRecord/EntityRecord/ChunkEntityLink.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

import asyncpg

from .schema import (
    Bundle, ChunkRecord, EdgeRecord, EntityRecord, ChunkEntityLink,
    DNA_MEMORY_TYPES, make_urn,
)


def _iso(ts: datetime) -> str:
    """ISO-8601 UTC with trailing Z."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _vector_to_b64(v: Any) -> str | None:
    """asyncpg pgvector returns a list[float]-like; encode to base64 LE float32."""
    if v is None:
        return None
    import struct
    return base64.b64encode(b"".join(struct.pack("<f", float(x)) for x in v)).decode("ascii")


async def export_bundle(
    conn: asyncpg.Connection,
    *,
    producer: str,
    tenant_id: str,
    scope: str = "FULL",
    since: datetime | None = None,
    include_embeddings: bool = False,
    embedding_model: str | None = None,
    embedding_dim: int | None = None,
) -> Bundle:
    """Read tenant data from the DB and assemble a Bundle.

    The connection MUST already be tenant-scoped (RLS app.tenant_id set)
    or admin-bypass; this function does not set session vars itself.
    """
    if scope not in ("FULL", "DNA_ONLY", "SINCE"):
        raise ValueError(f"scope {scope!r} not in FULL|DNA_ONLY|SINCE")
    if scope == "SINCE" and since is None:
        raise ValueError("scope=SINCE requires `since` argument")

    # ── Build chunk filter ─────────────────────────────────────────────
    where = ["tenant_id = $1::uuid", "deleted_at IS NULL"]
    args: list[Any] = [tenant_id]
    if scope == "DNA_ONLY":
        where.append(f"(memory_type = ANY($2::text[]) OR is_pinned = TRUE)")
        args.append(sorted(DNA_MEMORY_TYPES))
    elif scope == "SINCE":
        where.append(f"created_at >= ${len(args)+1}::timestamptz")
        args.append(since)

    chunk_cols = "id, content, content_hash, memory_type, zone, is_pinned, tags, created_at, source_producer, source_local"
    if include_embeddings:
        chunk_cols += ", embedding"

    chunk_rows = await conn.fetch(
        f"SELECT {chunk_cols} FROM chunks WHERE {' AND '.join(where)} "
        f"ORDER BY created_at ASC, id ASC",
        *args,
    )

    chunks: list[ChunkRecord] = []
    chunk_id_to_urn: dict[int, str] = {}
    for row in chunk_rows:
        # Re-export preserves the originating producer's URN if the chunk
        # was imported from elsewhere. Native chunks get a URN built from
        # this Producer's namespace.
        if row["source_producer"] and row["source_local"]:
            urn = make_urn(row["source_producer"], row["source_local"])
        else:
            urn = make_urn(producer, f"chunk-{row['id']}")
        chunk_id_to_urn[row["id"]] = urn
        emb_b64 = None
        if include_embeddings and row.get("embedding") is not None:
            emb_b64 = _vector_to_b64(row["embedding"])
        chunks.append(ChunkRecord(
            id=urn,
            content=row["content"],
            content_hash=row["content_hash"],
            memory_type=row["memory_type"],
            zone=row["zone"],
            is_pinned=bool(row["is_pinned"]),
            tags=list(row["tags"] or []),
            created_at=_iso(row["created_at"]),
            embedding=emb_b64,
        ))

    # ── Edges (only between chunks present in the bundle) ──────────────
    edges: list[EdgeRecord] = []
    if chunks:
        chunk_ids = list(chunk_id_to_urn.keys())
        edge_rows = await conn.fetch(
            "SELECT source_id, target_id, edge_type, weight, created_at "
            "FROM edges WHERE tenant_id = $1::uuid "
            "  AND source_id = ANY($2::bigint[]) "
            "  AND target_id = ANY($2::bigint[])",
            tenant_id, chunk_ids,
        )
        for er in edge_rows:
            edges.append(EdgeRecord(
                source_id=chunk_id_to_urn[er["source_id"]],
                target_id=chunk_id_to_urn[er["target_id"]],
                edge_type=er["edge_type"],
                weight=float(er["weight"]),
                created_at=_iso(er["created_at"]),
            ))

    # ── Entities + chunk_entities (only those linked to exported chunks) ─
    entities: list[EntityRecord] = []
    chunk_entities: list[ChunkEntityLink] = []
    entity_id_to_urn: dict[int, str] = {}
    if chunks:
        chunk_ids = list(chunk_id_to_urn.keys())
        ce_rows = await conn.fetch(
            "SELECT chunk_id, entity_id FROM chunk_entities "
            "WHERE tenant_id = $1::uuid AND chunk_id = ANY($2::bigint[])",
            tenant_id, chunk_ids,
        )
        ent_ids = sorted({r["entity_id"] for r in ce_rows})
        if ent_ids:
            ent_rows = await conn.fetch(
                "SELECT id, name, kind, source_producer, source_local, created_at "
                "FROM entities WHERE tenant_id = $1::uuid AND id = ANY($2::bigint[])",
                tenant_id, ent_ids,
            )
            for ent in ent_rows:
                if ent["source_producer"] and ent["source_local"]:
                    eu = make_urn(ent["source_producer"], ent["source_local"])
                else:
                    eu = make_urn(producer, f"entity-{ent['id']}")
                entity_id_to_urn[ent["id"]] = eu
                entities.append(EntityRecord(
                    id=eu, name=ent["name"], kind=ent["kind"],
                    created_at=_iso(ent["created_at"]),
                ))
        for ce in ce_rows:
            if ce["entity_id"] in entity_id_to_urn:
                chunk_entities.append(ChunkEntityLink(
                    chunk_id=chunk_id_to_urn[ce["chunk_id"]],
                    entity_id=entity_id_to_urn[ce["entity_id"]],
                ))

    # ── Embedding envelope fields ──────────────────────────────────────
    if include_embeddings and any(c.embedding is not None for c in chunks):
        if embedding_dim is None or embedding_model is None:
            # Try to infer from the first chunk's chunks_emb model column.
            # The minimal schema stores embedding_model per row; a Producer
            # MUST refuse export if rows have heterogeneous models.
            pass  # validated by Bundle.validate() below
        bundle_emb_dim = embedding_dim
        bundle_emb_model = embedding_model
    else:
        bundle_emb_dim = None
        bundle_emb_model = None

    bundle = Bundle(
        producer=producer,
        tenant_id=str(tenant_id),
        exported_at=_iso(datetime.now(timezone.utc)),
        scope=scope,
        chunks=chunks,
        edges=edges,
        entities=entities,
        chunk_entities=chunk_entities,
        since=_iso(since) if since else None,
        embedding_dim=bundle_emb_dim,
        embedding_model=bundle_emb_model,
    )
    bundle.validate()
    return bundle
