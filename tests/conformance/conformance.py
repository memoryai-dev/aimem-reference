"""Conformance corpus generator + black-box runner.

Builds a corpus of test bundles in valid/, invalid/, edge/ subdirectories
that any Consumer claiming AIMEM Bundle Format conformance must handle
correctly. Then runs them against an HTTP endpoint and reports pass/fail.

Usage:
    python conformance.py build      # regenerate corpus/
    python conformance.py run BASE_URL TOKEN
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

CORPUS_DIR = Path(__file__).parent / "corpus"
PRODUCER = "conformance-test"


def _hash(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def _checksum(body: dict) -> str:
    """Compute checksum the same way the spec mandates (RFC 8785)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from server.bundle.canonical import canonical_json
    body = {k: v for k, v in body.items() if k != "checksum"}
    return "sha256:" + hashlib.sha256(canonical_json(body)).hexdigest()


def _wrap(body_no_checksum: dict) -> dict:
    body_no_checksum["checksum"] = _checksum(body_no_checksum)
    return body_no_checksum


def _envelope(scope: str = "FULL", **extra) -> dict:
    env = {
        "format": "aimem-bundle",
        "version": "1",
        "producer": PRODUCER,
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "exported_at": "2026-06-13T15:00:00Z",
        "scope": scope,
        "chunks": [],
        "edges": [],
        "entities": [],
        "chunk_entities": [],
    }
    env.update(extra)
    return env


def _chunk(local: str, content: str, memory_type: str = "fact",
           created_at: str = "2026-04-01T09:00:00Z", **extra) -> dict:
    c = {
        "id": f"urn:aimem:{PRODUCER}:{local}",
        "content": content,
        "content_hash": _hash(content),
        "memory_type": memory_type,
        "created_at": created_at,
        "is_pinned": False,
        "tags": [],
    }
    c.update(extra)
    return c


# ── Corpus definitions ──────────────────────────────────────────────────

def build_valid() -> dict[str, dict]:
    """Bundles a Consumer MUST accept (HTTP 200)."""
    out: dict[str, dict] = {}

    # 1. Empty bundle
    out["minimal_empty"] = _wrap(_envelope())

    # 2. Single chunk
    out["single_chunk"] = _wrap(_envelope(chunks=[
        _chunk("c1", "Hello world.", memory_type="fact"),
    ]))

    # 3. All 8 memory types
    types = ["fact", "preference", "decision", "identity",
             "pitfall", "procedure", "episodic", "goal"]
    out["all_memory_types"] = _wrap(_envelope(chunks=[
        _chunk(f"c{i}", f"Sample {t} chunk.", memory_type=t)
        for i, t in enumerate(types)
    ]))

    # 4. DNA_ONLY scope
    dna_types = ["preference", "decision", "identity", "pitfall", "procedure"]
    out["dna_only_scope"] = _wrap(_envelope(scope="DNA_ONLY", chunks=[
        _chunk(f"d{i}", f"DNA {t}.", memory_type=t, zone="critical")
        for i, t in enumerate(dna_types)
    ]))

    # 5. SINCE scope
    out["since_scope"] = _wrap(_envelope(
        scope="SINCE", since="2026-04-01T00:00:00Z",
        chunks=[_chunk("s1", "After cutoff.", created_at="2026-04-15T00:00:00Z")],
    ))

    # 6. Pinned chunk
    out["pinned_chunk"] = _wrap(_envelope(chunks=[
        _chunk("p1", "Pinned forever.", is_pinned=True, zone="critical"),
    ]))

    # 7. Tags + zone
    out["tags_and_zones"] = _wrap(_envelope(chunks=[
        _chunk("t1", "Tagged and zoned.",
               tags=["a", "b", "c"], zone="important"),
    ]))

    # 8. Edges + entities + chunk_entities
    out["graph_complete"] = _wrap(_envelope(
        chunks=[
            _chunk("g1", "Alpha"),
            _chunk("g2", "Beta"),
        ],
        edges=[{
            "source_id": f"urn:aimem:{PRODUCER}:g1",
            "target_id": f"urn:aimem:{PRODUCER}:g2",
            "edge_type": "hebbian",
            "weight": 0.85,
            "created_at": "2026-04-15T08:00:00Z",
        }],
        entities=[{
            "id": f"urn:aimem:{PRODUCER}:e1",
            "name": "Alpha Inc",
            "kind": "organization",
            "created_at": "2026-04-15T08:00:00Z",
        }],
        chunk_entities=[{
            "chunk_id": f"urn:aimem:{PRODUCER}:g1",
            "entity_id": f"urn:aimem:{PRODUCER}:e1",
        }],
    ))

    # 9. x-prefixed extension edge_type
    out["extension_edge_type"] = _wrap(_envelope(
        chunks=[_chunk("x1", "A"), _chunk("x2", "B")],
        edges=[{
            "source_id": f"urn:aimem:{PRODUCER}:x1",
            "target_id": f"urn:aimem:{PRODUCER}:x2",
            "edge_type": "x-custom-rel",
            "weight": 0.5,
            "created_at": "2026-04-15T08:00:00Z",
        }],
    ))

    # 10. UTF-8 multi-byte content (Vietnamese, emoji, CJK)
    out["unicode_content"] = _wrap(_envelope(chunks=[
        _chunk("u1", "Cha gọi tao là 'mày' 🤖 中文测试 ñ é ü"),
    ]))

    # 11. Long content (just under limit)
    out["long_content"] = _wrap(_envelope(chunks=[
        _chunk("lc1", "x" * 60000),
    ]))

    # 12. Embedding included
    out["with_embedding"] = _wrap(_envelope(
        embedding_dim=4,
        embedding_model="conformance-fake-v1",
        chunks=[_chunk("emb1", "with embedding",
                       embedding="zczMPc3MTD6amZm+zczMPg==")],  # 4 floats
    ))

    return out


def build_invalid() -> dict[str, dict]:
    """Bundles a Consumer MUST reject (HTTP 4xx)."""
    out: dict[str, dict] = {}

    # Each entry: (bundle, expected_http_status)
    out["missing_format"] = {**_wrap(_envelope())}
    del out["missing_format"]["format"]

    out["wrong_format"] = _wrap(_envelope())
    out["wrong_format"]["format"] = "vendor-bundle"

    out["wrong_version"] = _wrap(_envelope())
    out["wrong_version"]["version"] = "2"

    out["bad_scope"] = _wrap(_envelope(scope="EVERYTHING"))

    out["since_missing"] = _wrap(_envelope(scope="SINCE"))

    out["bad_producer_uppercase"] = _wrap(_envelope())
    out["bad_producer_uppercase"]["producer"] = "BAD-PRODUCER"

    # Bad checksum (recompute then tamper)
    bad_checksum = _wrap(_envelope(chunks=[_chunk("bc1", "real content")]))
    bad_checksum["chunks"][0]["content"] = "tampered"  # leave checksum stale
    out["checksum_mismatch"] = bad_checksum  # checksum doesn't cover this change

    # Bad chunk URN (not urn:aimem:)
    bad_urn = _envelope(chunks=[
        {**_chunk("bu1", "x"), "id": "not-a-urn"},
    ])
    out["bad_chunk_urn"] = _wrap(bad_urn)

    # content_hash mismatch with content
    bad_hash = _envelope(chunks=[_chunk("bh1", "real")])
    bad_hash["chunks"][0]["content_hash"] = "sha256:" + "0" * 64
    out["bad_content_hash"] = _wrap(bad_hash)

    # Unknown memory_type
    bad_type = _envelope(chunks=[
        {**_chunk("bt1", "x"), "memory_type": "unknown_type"},
    ])
    out["bad_memory_type"] = _wrap(bad_type)

    # Edge weight out of range
    bad_weight = _envelope(
        chunks=[_chunk("bw1", "a"), _chunk("bw2", "b")],
        edges=[{
            "source_id": f"urn:aimem:{PRODUCER}:bw1",
            "target_id": f"urn:aimem:{PRODUCER}:bw2",
            "edge_type": "hebbian",
            "weight": 1.5,
            "created_at": "2026-04-15T08:00:00Z",
        }],
    )
    out["edge_weight_too_high"] = _wrap(bad_weight)

    # Edge references unknown chunk
    bad_edge = _envelope(
        chunks=[_chunk("be1", "a")],
        edges=[{
            "source_id": f"urn:aimem:{PRODUCER}:be1",
            "target_id": f"urn:aimem:{PRODUCER}:nonexistent",
            "edge_type": "hebbian",
            "weight": 0.5,
            "created_at": "2026-04-15T08:00:00Z",
        }],
    )
    out["edge_target_unknown"] = _wrap(bad_edge)

    # Duplicate chunk id
    dup = _envelope(chunks=[
        _chunk("dup", "first"),
        _chunk("dup", "second"),
    ])
    out["duplicate_chunk_id"] = _wrap(dup)

    # Embedding without envelope dim/model
    no_emb_meta = _envelope(chunks=[
        {**_chunk("ne1", "x"), "embedding": "zczMPQ=="},  # 1 float
    ])
    out["embedding_without_envelope"] = _wrap(no_emb_meta)

    return out


def build_edge() -> dict[str, dict]:
    """Edge cases — endpoint-specific behaviour, not strict accept/reject."""
    out: dict[str, dict] = {}

    # Legacy "memoryai-bundle" format value (Consumer SHOULD accept)
    legacy = _envelope()
    legacy["format"] = "memoryai-bundle"
    out["legacy_format_value"] = _wrap(legacy)

    # Empty arrays explicitly null
    out["large_chunk_count"] = _wrap(_envelope(chunks=[
        _chunk(f"big{i}", f"Chunk {i}", memory_type="fact",
               created_at=f"2026-04-{(i % 28) + 1:02d}T00:00:00Z")
        for i in range(200)
    ]))

    return out


# ── File I/O ────────────────────────────────────────────────────────────

def write_corpus() -> None:
    for kind, builder in [
        ("valid", build_valid),
        ("invalid", build_invalid),
        ("edge", build_edge),
    ]:
        out_dir = CORPUS_DIR / kind
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, bundle in builder().items():
            path = out_dir / f"{name}.json"
            path.write_text(json.dumps(bundle, indent=2, sort_keys=True))
    total = sum(1 for _ in CORPUS_DIR.rglob("*.json"))
    print(f"Wrote {total} bundles to {CORPUS_DIR}")


def run_corpus(base_url: str, token: str) -> int:
    """Black-box test: POST every corpus bundle to base_url/v1/brain/import.
    Returns nonzero on any failure.
    """
    headers = {"Authorization": f"Bearer {token}"}
    fails = []
    passes = 0

    for valid_path in sorted((CORPUS_DIR / "valid").glob("*.json")):
        body = json.loads(valid_path.read_text())
        r = httpx.post(f"{base_url}/v1/brain/import", json=body, headers=headers, timeout=10.0)
        if r.status_code == 200:
            passes += 1
            print(f"  ✓ valid/{valid_path.stem}")
        else:
            fails.append((valid_path.name, "valid", r.status_code, r.text[:100]))
            print(f"  ✗ valid/{valid_path.stem} → {r.status_code}")

    for invalid_path in sorted((CORPUS_DIR / "invalid").glob("*.json")):
        body = json.loads(invalid_path.read_text())
        r = httpx.post(f"{base_url}/v1/brain/import", json=body, headers=headers, timeout=10.0)
        if 400 <= r.status_code < 500:
            passes += 1
            print(f"  ✓ invalid/{invalid_path.stem} → {r.status_code}")
        else:
            fails.append((invalid_path.name, "invalid", r.status_code, r.text[:100]))
            print(f"  ✗ invalid/{invalid_path.stem} → {r.status_code} (expected 4xx)")

    for edge_path in sorted((CORPUS_DIR / "edge").glob("*.json")):
        body = json.loads(edge_path.read_text())
        r = httpx.post(f"{base_url}/v1/brain/import", json=body, headers=headers, timeout=30.0)
        # Edge cases: just record outcome.
        print(f"  · edge/{edge_path.stem} → {r.status_code}")
        passes += 1

    print()
    print(f"Total: {passes} passed, {len(fails)} failed")
    return 1 if fails else 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    pr = sub.add_parser("run")
    pr.add_argument("base_url")
    pr.add_argument("token")
    args = p.parse_args()

    if args.cmd == "build":
        write_corpus()
        return 0
    elif args.cmd == "run":
        return run_corpus(args.base_url, args.token)
    return 1


if __name__ == "__main__":
    sys.exit(main())
