"""Pure-python tests — no DB, no HTTP, just bundle schema + canonical."""
import base64
import hashlib
import json

import pytest

from server.bundle import (
    Bundle, ChunkRecord, EdgeRecord, EntityRecord, ChunkEntityLink,
    BundleValidationError, make_urn, parse_urn,
    compute_checksum, verify_checksum,
    encode_embedding, decode_embedding,
    DNA_MEMORY_TYPES,
)
from server.bundle.canonical import canonical_json


PRODUCER = "test-producer"


def _h(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def _chunk(local: str, content: str, **kw) -> ChunkRecord:
    return ChunkRecord(
        id=make_urn(PRODUCER, local),
        content=content,
        content_hash=_h(content),
        memory_type=kw.pop("memory_type", "fact"),
        created_at=kw.pop("created_at", "2026-04-01T09:00:00Z"),
        **kw,
    )


# ── URN ─────────────────────────────────────────────────────────────────

def test_urn_roundtrip():
    urn = make_urn("memoryai-prod", "chunk-42")
    assert urn == "urn:aimem:memoryai-prod:chunk-42"
    p, l = parse_urn(urn)
    assert p == "memoryai-prod" and l == "chunk-42"


def test_urn_uppercase_producer_rejected():
    with pytest.raises(BundleValidationError):
        make_urn("MemoryAI", "x")


def test_urn_invalid_local_with_colon():
    with pytest.raises(BundleValidationError):
        make_urn("ok", "has:colon")


def test_urn_unparseable():
    with pytest.raises(BundleValidationError):
        parse_urn("not-a-urn")


# ── Canonical JSON (RFC 8785) ───────────────────────────────────────────

def test_canonical_sorts_keys():
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b == b'{"a":2,"b":1}'


def test_canonical_no_whitespace():
    out = canonical_json({"x": [1, 2, {"k": "v"}]})
    assert out == b'{"x":[1,2,{"k":"v"}]}'


def test_canonical_unicode_passthrough():
    out = canonical_json({"k": "Cha gọi tao là 'mày'"})
    # Must NOT escape non-ASCII (RFC 8785 emits as UTF-8)
    assert "Cha".encode() in out


# ── Checksum ────────────────────────────────────────────────────────────

def test_checksum_deterministic():
    body = {"format": "aimem-bundle", "version": "1", "x": [1, 2, 3]}
    cs1 = compute_checksum(body)
    cs2 = compute_checksum(body)
    assert cs1 == cs2
    assert cs1.startswith("sha256:") and len(cs1) == 71


def test_checksum_ignores_existing_field():
    body = {"x": 1, "checksum": "stale"}
    actual = compute_checksum(body)
    body["checksum"] = actual
    verify_checksum(body)  # no raise


def test_verify_checksum_mismatch_raises():
    body = {"x": 1, "checksum": "sha256:" + "0" * 64}
    with pytest.raises(BundleValidationError) as ei:
        verify_checksum(body)
    assert ei.value.code == "checksum_mismatch"


# ── Bundle build + validate ─────────────────────────────────────────────

def _bundle_with(**chunks_kw) -> Bundle:
    return Bundle(
        producer=PRODUCER,
        tenant_id="11111111-1111-1111-1111-111111111111",
        exported_at="2026-06-13T15:00:00Z",
        scope="FULL",
        chunks=[_chunk("c1", "hello", **chunks_kw)],
    )


def test_minimal_valid_bundle():
    b = _bundle_with()
    b.validate()


def test_bad_memory_type_rejected():
    b = _bundle_with(memory_type="wat")
    with pytest.raises(BundleValidationError) as ei:
        b.validate()
    assert ei.value.code == "invalid_memory_type"


def test_dna_types_accepted():
    for t in sorted(DNA_MEMORY_TYPES):
        b = _bundle_with(memory_type=t)
        b.validate()


def test_content_hash_mismatch():
    ch = _chunk("c1", "real content")
    ch.content = "modified after hash computed"
    b = Bundle(
        producer=PRODUCER, tenant_id="x", exported_at="2026-01-01T00:00:00Z",
        scope="FULL", chunks=[ch],
    )
    with pytest.raises(BundleValidationError) as ei:
        b.validate()
    assert ei.value.code == "hash_mismatch"


def test_duplicate_chunk_ids():
    b = Bundle(
        producer=PRODUCER, tenant_id="x", exported_at="2026-01-01T00:00:00Z",
        scope="FULL",
        chunks=[_chunk("dup", "a"), _chunk("dup", "b")],
    )
    with pytest.raises(BundleValidationError) as ei:
        b.validate()
    assert ei.value.code == "duplicate_chunk_id"


def test_edge_references_unknown_chunk():
    e = EdgeRecord(
        source_id=make_urn(PRODUCER, "exists"),
        target_id=make_urn(PRODUCER, "ghost"),
        edge_type="hebbian", weight=0.5, created_at="2026-04-01T00:00:00Z",
    )
    b = Bundle(
        producer=PRODUCER, tenant_id="x", exported_at="2026-01-01T00:00:00Z",
        scope="FULL", chunks=[_chunk("exists", "a")], edges=[e],
    )
    with pytest.raises(BundleValidationError) as ei:
        b.validate()
    assert ei.value.code == "edge_target_unknown"


def test_edge_weight_out_of_range():
    src = _chunk("a", "x")
    tgt = _chunk("b", "y")
    e = EdgeRecord(source_id=src.id, target_id=tgt.id,
                   edge_type="hebbian", weight=1.5,
                   created_at="2026-04-01T00:00:00Z")
    b = Bundle(producer=PRODUCER, tenant_id="x", exported_at="2026-01-01T00:00:00Z",
               scope="FULL", chunks=[src, tgt], edges=[e])
    with pytest.raises(BundleValidationError):
        b.validate()


def test_extension_edge_type_accepted():
    src = _chunk("a", "x")
    tgt = _chunk("b", "y")
    e = EdgeRecord(source_id=src.id, target_id=tgt.id,
                   edge_type="x-vendor-rel", weight=0.5,
                   created_at="2026-04-01T00:00:00Z")
    b = Bundle(producer=PRODUCER, tenant_id="x", exported_at="2026-01-01T00:00:00Z",
               scope="FULL", chunks=[src, tgt], edges=[e])
    b.validate()


# ── Round-trip ──────────────────────────────────────────────────────────

def test_to_json_includes_checksum():
    b = _bundle_with()
    out = b.to_json()
    assert "checksum" in out
    assert out["checksum"].startswith("sha256:")


def test_round_trip_via_json():
    b = _bundle_with(zone="important", tags=["a", "b"])
    out = b.to_json()
    raw = json.dumps(out)  # serialise to wire
    b2 = Bundle.from_json(json.loads(raw))
    assert b2.producer == b.producer
    assert b2.chunks[0].content == b.chunks[0].content
    assert b2.chunks[0].zone == "important"
    assert b2.chunks[0].tags == ["a", "b"]


def test_legacy_format_value_accepted():
    b = _bundle_with()
    out = b.to_json(with_checksum=False)
    out["format"] = "memoryai-bundle"
    out["checksum"] = compute_checksum(out)
    Bundle.from_json(out)  # no raise


def test_wrong_version_rejected():
    b = _bundle_with()
    out = b.to_json(with_checksum=False)
    out["version"] = "2"
    out["checksum"] = compute_checksum(out)
    with pytest.raises(BundleValidationError) as ei:
        Bundle.from_json(out)
    assert ei.value.code == "unsupported_version"


# ── Embedding ───────────────────────────────────────────────────────────

def test_embedding_roundtrip():
    vec = [0.1, -0.5, 1.0, 0.0]
    b64 = encode_embedding(vec)
    out = decode_embedding(b64, dim=4)
    assert all(abs(a - b) < 1e-6 for a, b in zip(vec, out))


def test_embedding_dim_mismatch():
    b64 = encode_embedding([1.0, 2.0])
    with pytest.raises(BundleValidationError):
        decode_embedding(b64, dim=4)


def test_bundle_with_embedding_validates():
    vec = [0.1, 0.2, 0.3, 0.4]
    ch = _chunk("e1", "with vec")
    ch.embedding = encode_embedding(vec)
    b = Bundle(
        producer=PRODUCER, tenant_id="x", exported_at="2026-01-01T00:00:00Z",
        scope="FULL", chunks=[ch],
        embedding_dim=4, embedding_model="test-emb",
    )
    b.validate()


def test_embedding_without_envelope_rejected():
    ch = _chunk("e1", "x")
    ch.embedding = encode_embedding([1.0, 2.0, 3.0, 4.0])
    b = Bundle(producer=PRODUCER, tenant_id="x", exported_at="2026-01-01T00:00:00Z",
               scope="FULL", chunks=[ch])
    with pytest.raises(BundleValidationError) as ei:
        b.validate()
    assert ei.value.code == "embedding_envelope_missing"
