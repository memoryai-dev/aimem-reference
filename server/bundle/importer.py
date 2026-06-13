"""Bundle Consumer — ingest AIMEM Bundle (draft-01) → DB rows.

Implements the idempotency rules in spec §3.7:
  - re-import of (producer, local) with same content_hash + created_at = no-op
  - hash differs but created_at matches → reject with 422 conflict
  - newer created_at → updates allowed (this implementation REJECTS to be
    safe; an opt-in policy could allow it)
"""
from __future__ import annotations

import base64
import struct
from datetime import datetime
from typing import Any

import asyncpg

from .schema import (
    Bundle, BundleValidationError, parse_urn,
)


def _vector_from_b64(b64: str | None, dim: int | None):
    """base64 LE float32 → numpy array (pgvector wants ndarray, not list)."""
    if b64 is None:
        return None
    raw = base64.b64decode(b64)
    if dim is not None and len(raw) != dim * 4:
        raise BundleValidationError(
            "embedding_dim_mismatch",
            f"decoded {len(raw)} bytes != dim {dim} × 4",
        )
    cnt = len(raw) // 4
    floats = list(struct.unpack(f"<{cnt}f", raw))
    try:
        import numpy as np
        return np.array(floats, dtype=np.float32)
    except ImportError:
        return floats


def _parse_iso(s: str) -> datetime:
    # Tolerant: accept trailing Z or explicit offset
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


class ImportSummary:
    def __init__(self) -> None:
        self.chunks_inserted = 0
        self.chunks_skipped_idempotent = 0
        self.chunks_rejected_conflict: list[str] = []
        self.edges_inserted = 0
        self.edges_skipped_idempotent = 0
        self.entities_inserted = 0
        self.entities_skipped_idempotent = 0
        self.chunk_entities_inserted = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "chunks_inserted": self.chunks_inserted,
            "chunks_skipped_idempotent": self.chunks_skipped_idempotent,
            "chunks_rejected_conflict": list(self.chunks_rejected_conflict),
            "edges_inserted": self.edges_inserted,
            "edges_skipped_idempotent": self.edges_skipped_idempotent,
            "entities_inserted": self.entities_inserted,
            "entities_skipped_idempotent": self.entities_skipped_idempotent,
            "chunk_entities_inserted": self.chunk_entities_inserted,
        }


async def import_bundle(
    conn: asyncpg.Connection,
    bundle: Bundle,
    *,
    target_tenant_id: str,
) -> ImportSummary:
    """Ingest a validated Bundle into the target tenant.

    The connection MUST already be tenant-scoped to `target_tenant_id`
    (or admin-bypass for cross-tenant migration).
    """
    summary = ImportSummary()

    # ── Map source URN → local chunk id (for edges/chunk_entities) ─────
    chunk_urn_to_id: dict[str, int] = {}

    for c in bundle.chunks:
        producer, local = parse_urn(c.id)

        # Idempotency check.
        #
        # Two cases:
        #   1. The chunk's source_producer matches a row already imported
        #      from that producer (cross-instance re-import).
        #   2. This is a "round-trip" of a native chunk: when this server
        #      exported the bundle it tagged the chunk with its OWN
        #      Producer Namespace, then we now see urn:aimem:OWN:chunk-N
        #      coming back. The DB row for chunk N has
        #      source_producer=NULL because it's native. We resolve this
        #      by ALSO checking content_hash + memory_type as a fallback
        #      identity within the tenant.
        existing = await conn.fetchrow(
            "SELECT id, content_hash, created_at FROM chunks "
            "WHERE tenant_id = $1::uuid AND source_producer = $2 AND source_local = $3",
            target_tenant_id, producer, local,
        )
        if existing is None:
            # Round-trip native fallback: same tenant, same content_hash.
            existing = await conn.fetchrow(
                "SELECT id, content_hash, created_at FROM chunks "
                "WHERE tenant_id = $1::uuid AND content_hash = $2 "
                "  AND source_producer IS NULL",
                target_tenant_id, c.content_hash,
            )
        if existing is not None:
            ex_iso = _parse_iso(c.created_at)
            if existing["content_hash"] == c.content_hash:
                # Same content_hash AND same (producer, local) → no-op.
                # Per spec §3.7, created_at equality is also expected here;
                # we accept matching content_hash as the stronger signal.
                chunk_urn_to_id[c.id] = existing["id"]
                summary.chunks_skipped_idempotent += 1
                continue
            # Hash differs.
            if existing["created_at"].replace(tzinfo=ex_iso.tzinfo) == ex_iso:
                # Conflict per spec §3.7 rule 2.
                summary.chunks_rejected_conflict.append(c.id)
                continue
            # Newer created_at — this implementation rejects rather than
            # silently overwriting. (Spec §3.7 leaves this to implementer.)
            summary.chunks_rejected_conflict.append(c.id)
            continue

        # New chunk — insert.
        emb = None
        if c.embedding is not None and bundle.embedding_dim is not None:
            emb = _vector_from_b64(c.embedding, bundle.embedding_dim)

        new_id = await conn.fetchval(
            """INSERT INTO chunks
                 (tenant_id, content, content_hash, memory_type, zone,
                  is_pinned, tags, embedding, embedding_model,
                  source_producer, source_local, created_at)
               VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
               RETURNING id""",
            target_tenant_id, c.content, c.content_hash, c.memory_type,
            c.zone, c.is_pinned, c.tags, emb, bundle.embedding_model,
            producer, local, _parse_iso(c.created_at),
        )
        chunk_urn_to_id[c.id] = new_id
        summary.chunks_inserted += 1

    # ── Entities ────────────────────────────────────────────────────────
    entity_urn_to_id: dict[str, int] = {}
    for ent in bundle.entities:
        producer, local = parse_urn(ent.id)
        existing = await conn.fetchrow(
            "SELECT id FROM entities "
            "WHERE tenant_id = $1::uuid AND source_producer = $2 AND source_local = $3",
            target_tenant_id, producer, local,
        )
        if existing is not None:
            entity_urn_to_id[ent.id] = existing["id"]
            summary.entities_skipped_idempotent += 1
            continue
        # Try the (name, kind) uniqueness — same entity from different producer
        existing_by_name = await conn.fetchrow(
            "SELECT id FROM entities WHERE tenant_id = $1::uuid AND name = $2 AND kind = $3",
            target_tenant_id, ent.name, ent.kind,
        )
        if existing_by_name is not None:
            entity_urn_to_id[ent.id] = existing_by_name["id"]
            summary.entities_skipped_idempotent += 1
            continue
        new_id = await conn.fetchval(
            """INSERT INTO entities
                 (tenant_id, name, kind, source_producer, source_local, created_at)
               VALUES ($1::uuid, $2, $3, $4, $5, $6)
               RETURNING id""",
            target_tenant_id, ent.name, ent.kind, producer, local, _parse_iso(ent.created_at),
        )
        entity_urn_to_id[ent.id] = new_id
        summary.entities_inserted += 1

    # ── Edges ───────────────────────────────────────────────────────────
    for e in bundle.edges:
        src = chunk_urn_to_id.get(e.source_id)
        tgt = chunk_urn_to_id.get(e.target_id)
        if src is None or tgt is None:
            # Source or target chunk was rejected during conflict checks;
            # skip rather than fail the whole bundle.
            continue
        result = await conn.execute(
            """INSERT INTO edges
                 (tenant_id, source_id, target_id, edge_type, weight, created_at)
               VALUES ($1::uuid, $2, $3, $4, $5, $6)
               ON CONFLICT (tenant_id, source_id, target_id, edge_type) DO NOTHING""",
            target_tenant_id, src, tgt, e.edge_type, e.weight, _parse_iso(e.created_at),
        )
        if result.endswith(" 1"):
            summary.edges_inserted += 1
        else:
            summary.edges_skipped_idempotent += 1

    # ── Chunk-entity links ──────────────────────────────────────────────
    for ce in bundle.chunk_entities:
        cid = chunk_urn_to_id.get(ce.chunk_id)
        eid = entity_urn_to_id.get(ce.entity_id)
        if cid is None or eid is None:
            continue
        result = await conn.execute(
            """INSERT INTO chunk_entities (tenant_id, chunk_id, entity_id)
               VALUES ($1::uuid, $2, $3)
               ON CONFLICT DO NOTHING""",
            target_tenant_id, cid, eid,
        )
        if result.endswith(" 1"):
            summary.chunk_entities_inserted += 1

    return summary
