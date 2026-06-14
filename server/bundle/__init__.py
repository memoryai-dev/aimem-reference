"""AIMEM Bundle reference implementation.

This package implements draft-vu-aimem-bundle-00:
  - schema.py    — Bundle/Chunk/Edge/Entity dataclasses + validation
  - canonical.py — RFC 8785 canonical JSON for checksum
  - exporter.py  — DB rows → Bundle (Producer)
  - importer.py  — Bundle → DB rows (Consumer)
"""
from .schema import (
    Bundle,
    ChunkRecord,
    EdgeRecord,
    EntityRecord,
    ChunkEntityLink,
    BundleValidationError,
    BUNDLE_FORMAT,
    BUNDLE_VERSION,
    DNA_MEMORY_TYPES,
    VALID_MEMORY_TYPES,
    VALID_SCOPES,
    make_urn,
    parse_urn,
    compute_checksum,
    verify_checksum,
    encode_embedding,
    decode_embedding,
)
from .exporter import export_bundle
from .importer import import_bundle, ImportSummary

__all__ = [
    "Bundle",
    "ChunkRecord",
    "EdgeRecord",
    "EntityRecord",
    "ChunkEntityLink",
    "BundleValidationError",
    "BUNDLE_FORMAT",
    "BUNDLE_VERSION",
    "DNA_MEMORY_TYPES",
    "VALID_MEMORY_TYPES",
    "VALID_SCOPES",
    "make_urn",
    "parse_urn",
    "compute_checksum",
    "verify_checksum",
    "encode_embedding",
    "decode_embedding",
    "export_bundle",
    "import_bundle",
    "ImportSummary",
]
