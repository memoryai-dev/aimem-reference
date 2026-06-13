# Changelog

All notable changes to `aimem-reference` are documented here. Format:
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — semver.

## [0.1.0] — 2026-06-13

Initial public release.

### Added

- Reference Producer + Consumer for the AIMEM Bundle Format,
  draft-vu-aimem-bundle-01.
- FastAPI HTTP profile (export, export/stream, import) with Bearer
  auth and PostgreSQL row-level security.
- Pure-Python `server/bundle/` library: schema dataclasses, RFC 8785
  canonical JSON, exporter, importer with idempotency rules.
- Minimal 6-table Postgres schema (tenants, api_keys, chunks, edges,
  entities, chunk_entities, erasure_log).
- Conformance corpus of 28 test bundles (12 valid / 14 invalid / 2
  edge) with black-box runner.
- 26 pure-Python unit tests covering URN, canonical JSON, checksum,
  validation, embedding round-trip.
- Docker Compose recipe for one-command bring-up.

### Spec changes from draft-00

- Added Producer Namespace and `urn:aimem:` URN scheme for chunk
  identifiers.
- Inlined edge, entity, chunk_entity record schemas.
- Added `embedding_model` envelope field; required for any Bundle
  carrying embeddings.
- Replaced "out-of-band v1" signature mechanism with detached
  COSE_Sign1 over JSON-canonicalised body (RFC 8785 + RFC 9052).
- Added embedding privacy guidance.

[0.1.0]: https://github.com/memoryai-dev/aimem-reference/releases/tag/v0.1.0
