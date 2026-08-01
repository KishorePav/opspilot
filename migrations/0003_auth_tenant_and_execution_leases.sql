ALTER TABLE investigation_runs
    ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'legacy';

CREATE INDEX IF NOT EXISTS investigation_runs_tenant_idx
    ON investigation_runs (tenant_id, created_at);

ALTER TABLE remediation_executions
    ADD COLUMN IF NOT EXISTS lease_owner text NOT NULL DEFAULT 'legacy-unowned',
    ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS fencing_token bigint NOT NULL DEFAULT 1
        CHECK (fencing_token >= 1),
    ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 1
        CHECK (attempt_count >= 1);

CREATE INDEX IF NOT EXISTS remediation_executions_recovery_idx
    ON remediation_executions (status, lease_expires_at)
    WHERE status = 'executing';
