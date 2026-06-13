"""AIMEM Bundle schema — dataclasses + validation per draft-vu-aimem-bundle-01.

Pure-Python, no DB dependencies. Used by both exporter (build) and
importer (validate).
"""
from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from .canonical import canonical_json


# ── Constants from the spec ─────────────────────────────────────────────

BUNDLE_FORMAT = "aimem-bundle"
BUNDLE_FORMAT_LEGACY = "memoryai-bundle"  # accepted on import, never emitted
BUNDLE_VERSION = "1"

VALID_SCOPES = frozenset({"FULL", "DNA_ONLY", "SINCE"})

VALID_MEMORY_TYPES = frozenset({
    "fact", "preference", "decision", "identity",
    "pitfall", "procedure", "episodic", "goal",
})
DNA_MEMORY_TYPES = frozenset({
    "preference", "decision", "identity", "pitfall", "procedure",
})

VALID_ZONES = frozenset({"critical", "important", "standard"})

VALID_EDGE_TYPES = frozenset({"hebbian", "semantic", "temporal", "causal"})
VALID_ENTITY_KINDS = frozenset({
    "person", "organization", "place", "technology", "concept",
})

PRODUCER_NS_RE = re.compile(r"^[a-z0-9-]{1,63}$")
CHUNK_LOCAL_RE = re.compile(r"^[\x21-\x7E]+$")  # printable ASCII, no space
URN_RE = re.compile(r"^urn:aimem:([a-z0-9-]{1,63}):([\x21-\x7E]+)$")


class BundleValidationError(ValueError):
    """Raised when a Bundle fails normative validation."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"[{code}] {detail}")


# ── URN helpers ─────────────────────────────────────────────────────────

def make_urn(producer: str, local: str) -> str:
    """Construct an AIMEM URN from producer namespace + local id."""
    if not PRODUCER_NS_RE.match(producer):
        raise BundleValidationError(
            "invalid_producer",
            f"producer namespace {producer!r} must match {PRODUCER_NS_RE.pattern}",
        )
    if not CHUNK_LOCAL_RE.match(local) or ":" in local:
        raise BundleValidationError(
            "invalid_local_id",
            f"local id {local!r} must be printable ASCII without colon or whitespace",
        )
    if len(local) > 256:
        raise BundleValidationError(
            "invalid_local_id",
            f"local id length {len(local)} exceeds 256",
        )
    return f"urn:aimem:{producer}:{local}"


def parse_urn(urn: str) -> tuple[str, str]:
    """Parse `urn:aimem:<producer>:<local>` -> (producer, local)."""
    m = URN_RE.match(urn)
    if not m:
        raise BundleValidationError(
            "invalid_urn", f"id {urn!r} is not a valid AIMEM URN",
        )
    return m.group(1), m.group(2)


# ── Records ─────────────────────────────────────────────────────────────

@dataclass
class ChunkRecord:
    id: str
    content: str
    content_hash: str
    memory_type: str
    created_at: str
    zone: str | None = None
    is_pinned: bool = False
    tags: list[str] = field(default_factory=list)
    embedding: str | None = None  # base64 of float32 little-endian

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "content": self.content,
            "content_hash": self.content_hash,
            "memory_type": self.memory_type,
            "created_at": self.created_at,
            "is_pinned": self.is_pinned,
            "tags": list(self.tags),
        }
        if self.zone is not None:
            out["zone"] = self.zone
        if self.embedding is not None:
            out["embedding"] = self.embedding
        return out

    def validate(self) -> None:
        parse_urn(self.id)  # raises if bad
        if not self.content:
            raise BundleValidationError("empty_content", f"chunk {self.id} has empty content")
        if len(self.content) > 65536:
            raise BundleValidationError(
                "content_too_long",
                f"chunk {self.id} content length {len(self.content)} exceeds 65536",
            )
        if not self.content_hash.startswith("sha256:") or len(self.content_hash) != 71:
            raise BundleValidationError(
                "bad_hash_format", f"chunk {self.id}: content_hash must be 'sha256:<64-hex>'",
            )
        actual = "sha256:" + hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if actual != self.content_hash:
            raise BundleValidationError(
                "hash_mismatch",
                f"chunk {self.id}: content_hash claim {self.content_hash} != computed {actual}",
            )
        if self.memory_type not in VALID_MEMORY_TYPES:
            raise BundleValidationError(
                "invalid_memory_type",
                f"chunk {self.id}: memory_type {self.memory_type!r} not in {sorted(VALID_MEMORY_TYPES)}",
            )
        if self.zone is not None and self.zone not in VALID_ZONES:
            raise BundleValidationError(
                "invalid_zone",
                f"chunk {self.id}: zone {self.zone!r} not in {sorted(VALID_ZONES)}",
            )
        for t in self.tags:
            if not isinstance(t, str) or not (1 <= len(t) <= 64):
                raise BundleValidationError(
                    "invalid_tag",
                    f"chunk {self.id}: tag {t!r} must be string of 1-64 codepoints",
                )


@dataclass
class EdgeRecord:
    source_id: str
    target_id: str
    edge_type: str
    weight: float
    created_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type,
            "weight": self.weight,
            "created_at": self.created_at,
        }

    def validate(self, known_chunk_urns: set[str]) -> None:
        parse_urn(self.source_id)
        parse_urn(self.target_id)
        if self.source_id not in known_chunk_urns:
            raise BundleValidationError(
                "edge_source_unknown",
                f"edge source {self.source_id} not present in chunks[]",
            )
        if self.target_id not in known_chunk_urns:
            raise BundleValidationError(
                "edge_target_unknown",
                f"edge target {self.target_id} not present in chunks[]",
            )
        if not (self.edge_type in VALID_EDGE_TYPES or self.edge_type.startswith("x-")):
            raise BundleValidationError(
                "invalid_edge_type",
                f"edge_type {self.edge_type!r} not standard and not x-prefixed",
            )
        if not (0.0 <= float(self.weight) <= 1.0):
            raise BundleValidationError(
                "edge_weight_out_of_range",
                f"edge weight {self.weight} not in [0,1]",
            )


@dataclass
class EntityRecord:
    id: str
    name: str
    kind: str
    created_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name,
            "kind": self.kind, "created_at": self.created_at,
        }

    def validate(self) -> None:
        parse_urn(self.id)
        if not self.name:
            raise BundleValidationError("empty_entity_name", f"entity {self.id}: name is empty")
        if not (self.kind in VALID_ENTITY_KINDS or self.kind.startswith("x-")):
            raise BundleValidationError(
                "invalid_entity_kind",
                f"entity {self.id}: kind {self.kind!r} not standard and not x-prefixed",
            )


@dataclass
class ChunkEntityLink:
    chunk_id: str
    entity_id: str

    def to_json(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "entity_id": self.entity_id}

    def validate(self, known_chunks: set[str], known_entities: set[str]) -> None:
        if self.chunk_id not in known_chunks:
            raise BundleValidationError(
                "ce_chunk_unknown",
                f"chunk_entities link references unknown chunk {self.chunk_id}",
            )
        if self.entity_id not in known_entities:
            raise BundleValidationError(
                "ce_entity_unknown",
                f"chunk_entities link references unknown entity {self.entity_id}",
            )


# ── Bundle envelope ─────────────────────────────────────────────────────

@dataclass
class Bundle:
    producer: str
    tenant_id: str
    exported_at: str
    scope: str
    chunks: list[ChunkRecord] = field(default_factory=list)
    edges: list[EdgeRecord] = field(default_factory=list)
    entities: list[EntityRecord] = field(default_factory=list)
    chunk_entities: list[ChunkEntityLink] = field(default_factory=list)
    since: str | None = None
    embedding_dim: int | None = None
    embedding_model: str | None = None
    format: str = BUNDLE_FORMAT
    version: str = BUNDLE_VERSION

    def to_json(self, *, with_checksum: bool = True) -> dict[str, Any]:
        body: dict[str, Any] = {
            "format": self.format,
            "version": self.version,
            "producer": self.producer,
            "tenant_id": self.tenant_id,
            "exported_at": self.exported_at,
            "scope": self.scope,
            "chunks": [c.to_json() for c in self.chunks],
            "edges": [e.to_json() for e in self.edges],
            "entities": [e.to_json() for e in self.entities],
            "chunk_entities": [ce.to_json() for ce in self.chunk_entities],
        }
        if self.since is not None:
            body["since"] = self.since
        if self.embedding_dim is not None:
            body["embedding_dim"] = self.embedding_dim
        if self.embedding_model is not None:
            body["embedding_model"] = self.embedding_model
        if with_checksum:
            body["checksum"] = compute_checksum(body)
        return body

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Bundle":
        """Parse + validate a Bundle JSON dict. Raises BundleValidationError."""
        validate_envelope(data)
        verify_checksum(data)

        chunks = [_chunk_from_json(c) for c in data.get("chunks", [])]
        edges = [
            EdgeRecord(
                source_id=e["source_id"], target_id=e["target_id"],
                edge_type=e["edge_type"], weight=float(e["weight"]),
                created_at=e["created_at"],
            )
            for e in data.get("edges", [])
        ]
        entities = [
            EntityRecord(
                id=ent["id"], name=ent["name"],
                kind=ent["kind"], created_at=ent["created_at"],
            )
            for ent in data.get("entities", [])
        ]
        chunk_entities = [
            ChunkEntityLink(chunk_id=ce["chunk_id"], entity_id=ce["entity_id"])
            for ce in data.get("chunk_entities", [])
        ]

        b = cls(
            producer=data["producer"],
            tenant_id=data["tenant_id"],
            exported_at=data["exported_at"],
            scope=data["scope"],
            chunks=chunks,
            edges=edges,
            entities=entities,
            chunk_entities=chunk_entities,
            since=data.get("since"),
            embedding_dim=data.get("embedding_dim"),
            embedding_model=data.get("embedding_model"),
            format=data.get("format", BUNDLE_FORMAT),
            version=data.get("version", BUNDLE_VERSION),
        )
        b.validate()
        return b

    def validate(self) -> None:
        """Run all per-record validations + cross-record reference checks."""
        for c in self.chunks:
            c.validate()
        chunk_urns = {c.id for c in self.chunks}
        if len(chunk_urns) != len(self.chunks):
            raise BundleValidationError("duplicate_chunk_id", "chunks[] contains duplicate ids")
        for e in self.edges:
            e.validate(chunk_urns)
        for ent in self.entities:
            ent.validate()
        entity_urns = {e.id for e in self.entities}
        for ce in self.chunk_entities:
            ce.validate(chunk_urns, entity_urns)

        # If any chunk has an embedding, envelope must declare dim+model.
        has_emb = any(c.embedding is not None for c in self.chunks)
        if has_emb:
            if self.embedding_dim is None or self.embedding_model is None:
                raise BundleValidationError(
                    "embedding_envelope_missing",
                    "chunks contain embeddings but envelope lacks embedding_dim/embedding_model",
                )
            for c in self.chunks:
                if c.embedding is None:
                    continue
                raw = base64.b64decode(c.embedding)
                if len(raw) != self.embedding_dim * 4:
                    raise BundleValidationError(
                        "embedding_dim_mismatch",
                        f"chunk {c.id}: decoded embedding {len(raw)} bytes != "
                        f"declared dim {self.embedding_dim} × float32 (4 bytes)",
                    )


def _chunk_from_json(c: dict[str, Any]) -> ChunkRecord:
    return ChunkRecord(
        id=c["id"],
        content=c["content"],
        content_hash=c["content_hash"],
        memory_type=c["memory_type"],
        created_at=c["created_at"],
        zone=c.get("zone"),
        is_pinned=bool(c.get("is_pinned", False)),
        tags=list(c.get("tags", [])),
        embedding=c.get("embedding"),
    )


def validate_envelope(data: dict[str, Any]) -> None:
    """Check envelope-level required fields. Does NOT verify checksum."""
    if not isinstance(data, dict):
        raise BundleValidationError("not_object", "Bundle root must be a JSON object")
    fmt = data.get("format")
    if fmt not in (BUNDLE_FORMAT, BUNDLE_FORMAT_LEGACY):
        raise BundleValidationError(
            "bad_format",
            f"format {fmt!r} not 'aimem-bundle' (or legacy 'memoryai-bundle')",
        )
    if data.get("version") != BUNDLE_VERSION:
        raise BundleValidationError(
            "unsupported_version",
            f"version {data.get('version')!r} not {BUNDLE_VERSION!r}",
        )
    for k in ("producer", "tenant_id", "exported_at", "scope"):
        if k not in data:
            raise BundleValidationError("missing_field", f"envelope missing required field {k!r}")
    if not PRODUCER_NS_RE.match(data["producer"]):
        raise BundleValidationError(
            "invalid_producer", f"producer {data['producer']!r} fails namespace pattern",
        )
    if data["scope"] not in VALID_SCOPES:
        raise BundleValidationError(
            "invalid_scope", f"scope {data['scope']!r} not in {sorted(VALID_SCOPES)}",
        )
    if data["scope"] == "SINCE" and "since" not in data:
        raise BundleValidationError(
            "since_missing", "scope=SINCE requires 'since' field in envelope",
        )


# ── Checksum ────────────────────────────────────────────────────────────

def compute_checksum(body_without_checksum: dict[str, Any]) -> str:
    """Return 'sha256:<hex>' over RFC-8785-canonicalised body."""
    body = {k: v for k, v in body_without_checksum.items() if k != "checksum"}
    canonical = canonical_json(body)
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def verify_checksum(data: dict[str, Any]) -> None:
    claimed = data.get("checksum")
    if not isinstance(claimed, str) or not claimed.startswith("sha256:"):
        raise BundleValidationError("missing_checksum", "envelope missing or malformed checksum")
    actual = compute_checksum(data)
    if actual != claimed:
        raise BundleValidationError(
            "checksum_mismatch",
            f"checksum mismatch: claimed={claimed} actual={actual}",
        )


# ── Embedding helpers ───────────────────────────────────────────────────

def encode_embedding(vec: list[float]) -> str:
    """Encode a float32 vector to base64 little-endian."""
    import struct
    raw = b"".join(struct.pack("<f", float(x)) for x in vec)
    return base64.b64encode(raw).decode("ascii")


def decode_embedding(b64: str, dim: int) -> list[float]:
    """Decode base64 little-endian float32 → list[float] of length `dim`."""
    import struct
    raw = base64.b64decode(b64)
    if len(raw) != dim * 4:
        raise BundleValidationError(
            "embedding_dim_mismatch",
            f"decoded {len(raw)} bytes != dim {dim} × 4",
        )
    return list(struct.unpack(f"<{dim}f", raw))
