-- aimem-reference 001_core.sql
--
-- Minimal schema for AIMEM Bundle Producer/Consumer reference.
-- Implements ONLY the fields normatively required by
-- draft-vu-aimem-bundle-01. Production implementers are expected to
-- extend this schema with their own reasoning-layer columns
-- (decay scores, attention weights, brain layers, etc.) — those are
-- intentionally out of scope here.
--
-- Extensions: pgvector (for embedding column), pg_trgm (optional FTS).
-- These require a superuser; if you cannot grant superuser to the
-- application role, run the CREATE EXTENSION statements separately as
-- the postgres user, then this migration is a no-op for them.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        BEGIN
            CREATE EXTENSION vector;
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'pgvector not pre-installed and current role lacks superuser; '
                         'install with: sudo -u postgres psql -d <db> -c "CREATE EXTENSION vector"';
        END;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        BEGIN
            CREATE EXTENSION pg_trgm;
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'pg_trgm not pre-installed and current role lacks superuser';
        END;
    END IF;
END$$;

-- ─── Tenants ────────────────────────────────────────────────────────────
-- A tenant is the principal who owns a Bundle (per draft §2 Terminology).
CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    forgotten_at TIMESTAMPTZ        -- non-NULL = right-to-erasure executed
);

-- ─── API keys ───────────────────────────────────────────────────────────
-- Bearer token authentication. Token is hashed with SHA-256; the raw
-- token is shown ONCE at provision time and never stored.
CREATE TABLE IF NOT EXISTS api_keys (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash     TEXT NOT NULL UNIQUE,
    scopes       TEXT[] NOT NULL DEFAULT ARRAY['bundle:export', 'bundle:import'],
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash) WHERE revoked_at IS NULL;

-- ─── Chunks ─────────────────────────────────────────────────────────────
-- Atomic memory record (draft §3.2 ChunkRecord).
-- The set of columns matches exactly the normative ChunkRecord fields;
-- implementers MAY add columns for fields outside the spec scope, but
-- those additions MUST NOT appear in exported Bundles.
CREATE TABLE IF NOT EXISTS chunks (
    -- Local serial id used for foreign keys inside the implementation.
    -- The exported URN id is computed at export time as
    --   urn:aimem:<producer>:chunk-<id>
    -- so it survives across re-imports while remaining database-friendly.
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Content + integrity
    content         TEXT NOT NULL CHECK (char_length(content) > 0),
    content_hash    TEXT NOT NULL,        -- 'sha256:<hex>'

    -- Classification (draft §3.2)
    memory_type     TEXT NOT NULL CHECK (memory_type IN (
                        'fact','preference','decision','identity',
                        'pitfall','procedure','episodic','goal'
                    )),
    zone            TEXT CHECK (zone IN ('critical','important','standard')),
    is_pinned       BOOLEAN NOT NULL DEFAULT FALSE,
    tags            TEXT[] NOT NULL DEFAULT '{}',

    -- Embedding (optional, see draft §3.5)
    -- pgvector lets dim be variable per-row but all rows in one tenant
    -- SHOULD share embedding_model declared at envelope level.
    embedding       vector,                 -- NULL when not embedded
    embedding_model TEXT,                   -- e.g. 'text-embedding-3-small'

    -- Cross-instance import provenance
    -- When this chunk was originally created by a DIFFERENT producer and
    -- imported here, source_producer + source_local hold the originator's
    -- URN parts so re-export preserves identity.
    source_producer TEXT,                   -- NULL = native
    source_local    TEXT,

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,            -- soft delete

    -- Hard uniqueness so re-import is idempotent
    UNIQUE(tenant_id, source_producer, source_local)
);
CREATE INDEX IF NOT EXISTS idx_chunks_tenant_active
    ON chunks(tenant_id, created_at DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_chunks_tenant_type
    ON chunks(tenant_id, memory_type)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_chunks_tags
    ON chunks USING gin(tags);
CREATE INDEX IF NOT EXISTS idx_chunks_fts
    ON chunks USING gin(to_tsvector('simple', content));
CREATE INDEX IF NOT EXISTS idx_chunks_content_hash
    ON chunks(tenant_id, content_hash);

-- ─── Edges ──────────────────────────────────────────────────────────────
-- Co-activation graph between chunks (draft §3.3 EdgeRecord).
-- This is a directed adjacency; bidirectional relations are encoded as
-- two rows.
CREATE TABLE IF NOT EXISTS edges (
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_id   BIGINT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    target_id   BIGINT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    edge_type   TEXT NOT NULL CHECK (
                    edge_type IN ('hebbian','semantic','temporal','causal')
                    OR edge_type LIKE 'x-%'
                ),
    weight      REAL NOT NULL CHECK (weight >= 0.0 AND weight <= 1.0),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, source_id, target_id, edge_type)
);
CREATE INDEX IF NOT EXISTS idx_edges_target
    ON edges(tenant_id, target_id);

-- ─── Entities ───────────────────────────────────────────────────────────
-- Named entities extracted from chunks (draft §3.4 EntityRecord).
CREATE TABLE IF NOT EXISTS entities (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (
                        kind IN ('person','organization','place','technology','concept')
                        OR kind LIKE 'x-%'
                    ),
    source_producer TEXT,
    source_local    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, source_producer, source_local),
    UNIQUE(tenant_id, name, kind)
);
CREATE INDEX IF NOT EXISTS idx_entities_tenant
    ON entities(tenant_id, kind);

-- ─── Chunk ↔ Entity links ───────────────────────────────────────────────
-- Many-to-many bridge (draft §3.4.1 chunk_entities).
CREATE TABLE IF NOT EXISTS chunk_entities (
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    chunk_id    BIGINT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    entity_id   BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (tenant_id, chunk_id, entity_id)
);

-- ─── Erasure audit log ──────────────────────────────────────────────────
-- Records that an erasure occurred without retaining what was erased
-- (draft §6.2 Right to erasure).
CREATE TABLE IF NOT EXISTS erasure_log (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    UUID NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    chunks_purged INT,
    notes        TEXT
);

-- ─── Schema version tracking ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_version (
    version    INT PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO schema_version(version, name) VALUES (1, '001_core')
    ON CONFLICT DO NOTHING;
