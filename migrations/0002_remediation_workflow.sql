CREATE TABLE IF NOT EXISTS investigation_runs (
    run_id text PRIMARY KEY,
    incident_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('completed', 'failed')),
    request jsonb NOT NULL CHECK (jsonb_typeof(request) = 'object'),
    result jsonb CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
    failure jsonb CHECK (failure IS NULL OR jsonb_typeof(failure) = 'object'),
    created_by jsonb NOT NULL CHECK (jsonb_typeof(created_by) = 'object'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    CHECK (
        (status = 'completed' AND result IS NOT NULL AND failure IS NULL) OR
        (status = 'failed' AND result IS NULL AND failure IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS remediation_proposals (
    proposal_id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES investigation_runs(run_id),
    plan_version integer NOT NULL CHECK (plan_version = 1),
    plan_digest character(64) NOT NULL CHECK (plan_digest ~ '^[a-f0-9]{64}$'),
    action jsonb NOT NULL CHECK (jsonb_typeof(action) = 'object'),
    dry_run jsonb NOT NULL CHECK (jsonb_typeof(dry_run) = 'object'),
    status text NOT NULL CHECK (
        status IN ('awaiting_approval', 'approved', 'rejected', 'executing', 'completed', 'failed')
    ),
    created_by jsonb NOT NULL CHECK (jsonb_typeof(created_by) = 'object'),
    approval jsonb CHECK (approval IS NULL OR jsonb_typeof(approval) = 'object'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    version integer NOT NULL CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS remediation_proposals_run_idx
    ON remediation_proposals (run_id, created_at);

CREATE TABLE IF NOT EXISTS remediation_executions (
    execution_id text PRIMARY KEY,
    proposal_id text NOT NULL UNIQUE REFERENCES remediation_proposals(proposal_id),
    run_id text NOT NULL REFERENCES investigation_runs(run_id),
    idempotency_key text NOT NULL UNIQUE,
    plan_digest character(64) NOT NULL CHECK (plan_digest ~ '^[a-f0-9]{64}$'),
    requested_by jsonb NOT NULL CHECK (jsonb_typeof(requested_by) = 'object'),
    status text NOT NULL CHECK (status IN ('executing', 'completed', 'failed')),
    outcome jsonb CHECK (outcome IS NULL OR jsonb_typeof(outcome) = 'object'),
    error_code text,
    created_at timestamptz NOT NULL,
    completed_at timestamptz,
    CHECK (
        (status = 'executing' AND outcome IS NULL AND error_code IS NULL AND completed_at IS NULL) OR
        (status = 'completed' AND outcome IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL) OR
        (status = 'failed' AND outcome IS NULL AND error_code IS NOT NULL AND completed_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS workflow_audit_events (
    event_id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES investigation_runs(run_id),
    sequence_no integer NOT NULL CHECK (sequence_no >= 1),
    event_type text NOT NULL,
    actor jsonb NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    previous_hash character(64) CHECK (
        previous_hash IS NULL OR previous_hash ~ '^[a-f0-9]{64}$'
    ),
    event_hash character(64) NOT NULL CHECK (event_hash ~ '^[a-f0-9]{64}$'),
    occurred_at timestamptz NOT NULL,
    UNIQUE (run_id, sequence_no)
);

CREATE INDEX IF NOT EXISTS workflow_audit_events_run_idx
    ON workflow_audit_events (run_id, sequence_no);

CREATE OR REPLACE FUNCTION reject_workflow_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'workflow audit events are append-only';
END;
$$;

DROP TRIGGER IF EXISTS workflow_audit_events_immutable ON workflow_audit_events;
CREATE TRIGGER workflow_audit_events_immutable
BEFORE UPDATE OR DELETE ON workflow_audit_events
FOR EACH ROW EXECUTE FUNCTION reject_workflow_audit_mutation();
