-- aimem-reference 002_rls.sql
--
-- Row-level security: each tenant sees only its own rows.
-- Implementation: session variable `app.tenant_id` carries the
-- authenticated tenant; bypass is via `app.bypass_rls = 'true'`
-- for administrative paths (provision, erasure cascade).

ALTER TABLE chunks         ENABLE ROW LEVEL SECURITY;
ALTER TABLE edges          ENABLE ROW LEVEL SECURITY;
ALTER TABLE entities       ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunk_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys       ENABLE ROW LEVEL SECURITY;

ALTER TABLE chunks         FORCE ROW LEVEL SECURITY;
ALTER TABLE edges          FORCE ROW LEVEL SECURITY;
ALTER TABLE entities       FORCE ROW LEVEL SECURITY;
ALTER TABLE chunk_entities FORCE ROW LEVEL SECURITY;
ALTER TABLE api_keys       FORCE ROW LEVEL SECURITY;

CREATE POLICY chunks_isolation ON chunks
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )
    WITH CHECK (
        current_setting('app.bypass_rls', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    );

CREATE POLICY edges_isolation ON edges
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )
    WITH CHECK (
        current_setting('app.bypass_rls', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    );

CREATE POLICY entities_isolation ON entities
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )
    WITH CHECK (
        current_setting('app.bypass_rls', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    );

CREATE POLICY chunk_entities_isolation ON chunk_entities
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )
    WITH CHECK (
        current_setting('app.bypass_rls', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    );

CREATE POLICY api_keys_isolation ON api_keys
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )
    WITH CHECK (
        current_setting('app.bypass_rls', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    );

INSERT INTO schema_version(version, name) VALUES (2, '002_rls')
    ON CONFLICT DO NOTHING;
