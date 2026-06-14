# aimem-reference

**Reference implementation of the AIMEM Bundle Format** —
a vendor-neutral interchange format for AI agent memory.

This server is the *reference* Producer + Consumer cited in
[`draft-vu-aimem-bundle-00`](spec/draft-vu-aimem-bundle-00.md), an
IETF Independent Submission. It is intentionally minimal: it
implements only the **encoding and transport** layers defined by the
specification. The **reasoning layer** (recall ranking, sleep cycles,
neural graphs, etc.) is **out of scope** and left to production
implementers.

> **Production note.** This is not a production memory system.
> If you need real recall quality, run a production server like
> [MemoryAI](https://memoryai.dev/) and use this repo as the
> wire-compatibility test suite.

## What this gives you

- **Apache 2.0** licensed, including patent grant — fork freely.
- A working FastAPI server exposing the spec's HTTP Profile:
  - `GET  /v1/brain/export` — emit a Bundle for the authenticated tenant
  - `GET  /v1/brain/export/stream` — NDJSON variant for large brains
  - `POST /v1/brain/import` — ingest a Bundle into the authenticated tenant
- **PostgreSQL + pgvector** schema (6 tables) sufficient for the
  normative ChunkRecord / EdgeRecord / EntityRecord fields.
- **RFC 8785** canonical JSON checksum implementation.
- **Bearer token auth** with **PostgreSQL row-level security** for
  tenant isolation.
- **Conformance corpus** of 28 test bundles
  (`tests/conformance/corpus/{valid,invalid,edge}/`) usable as a
  black-box test suite against any implementation.
- **Pure-Python unit tests** (no DB) for the schema + canonical
  modules — `pytest tests/test_bundle.py`.

## Quick start (Docker)

```bash
git clone https://github.com/memoryai-dev/aimem-reference
cd aimem-reference
cp .env.example .env
# Edit .env: pick AIMEM_ADMIN_SECRET = output of `openssl rand -hex 32`

docker compose up -d
curl http://localhost:9420/healthz
# → {"status":"ok"}
```

## Quick start (local Python)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Pre-create extensions (only required once, as a superuser):
sudo -u postgres psql -d aimem -c "CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;"

export DATABASE_URL=postgresql://aimem:aimem@localhost/aimem
export AIMEM_ADMIN_SECRET=$(openssl rand -hex 32)
uvicorn server.main:app --host 0.0.0.0 --port 9420
```

## Provision a tenant + export

```bash
# 1. Provision (admin secret only)
curl -X POST http://localhost:9420/v1/admin/provision \
    -H "X-Admin-Secret: $AIMEM_ADMIN_SECRET" \
    -H "Content-Type: application/json" \
    -d '{"name":"example"}'
# → {"tenant_id":"...","api_key":"aimem_..."}

# 2. Export the (empty) brain
curl http://localhost:9420/v1/brain/export \
    -H "Authorization: Bearer aimem_..."
```

## Running the conformance suite

The corpus in `tests/conformance/corpus/` exercises every normative
requirement in the spec. To run it against any AIMEM-Bundle-claiming
endpoint:

```bash
python tests/conformance/conformance.py run \
    http://localhost:9420 aimem_<api-key>
```

A successful run reports `28 passed, 0 failed`.

## Running the unit tests

```bash
PYTHONPATH=. pytest tests/test_bundle.py -v
# → 26 passed
```

## Architecture (intentionally tiny)

```
server/
├── main.py                  # FastAPI app
├── db.py                    # asyncpg pool + RLS helpers
├── auth.py                  # Bearer token + SHA-256 hash
├── schema/
│   ├── 001_core.sql         # 6 tables
│   └── 002_rls.sql          # RLS policies
├── bundle/
│   ├── canonical.py         # RFC 8785 canonical JSON
│   ├── schema.py            # Bundle/Chunk/Edge/Entity dataclasses
│   ├── exporter.py          # DB rows → Bundle
│   └── importer.py          # Bundle → DB rows
└── routes/
    ├── meta.py              # /healthz, /.well-known/aimem-spec
    ├── brain.py             # /v1/brain/export|import
    └── admin.py             # /v1/admin/provision

spec/
└── draft-vu-aimem-bundle-00.md   # the specification

tests/
├── test_bundle.py           # 26 pure-python unit tests
└── conformance/
    ├── conformance.py       # corpus generator + black-box runner
    └── corpus/
        ├── valid/           # 12 bundles a Consumer MUST accept
        ├── invalid/         # 14 bundles a Consumer MUST reject
        └── edge/            # 2 boundary cases
```

## What this is NOT

- Not a recall engine. There is no ranking, no Hebbian graph, no
  neural reasoning, no decay schedule, no LLM call, no cluster
  synthesis. Production implementers ship those behind the same
  Bundle interface.
- Not a benchmark. It will not score well on retrieval quality
  benchmarks because *there is no retrieval*.
- Not a single-vendor format. The whole point is the format is
  vendor-neutral — anyone may implement it, including competitors.

## Contributing

Implementations from independent vendors are explicitly welcome. The
goal is for AIMEM Bundle to have multiple Consumer/Producer pairs in
the wild before the IETF draft advances. If you ship one, please:

1. File a GitHub issue with the URL of your implementation.
2. Run the conformance corpus against it and submit results.
3. Note any spec gaps you found while implementing.

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

The specification document under `spec/` is licensed
**CC BY 4.0** (per IETF `trust200902` boilerplate).
