-- 0006_human_authorization_proof — immutable evidence for authenticated terminal gate resolution.
-- A hold is immutable evidence but not a resolution: it leaves the approval pending.

ALTER TABLE approval
    ADD CONSTRAINT approval_company_id_id_uq UNIQUE (company_id, id);

CREATE TABLE human_authorization_proof (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    decision_id uuid NOT NULL,
    approval_id uuid NOT NULL,
    user_id text NOT NULL,
    method text NOT NULL CHECK (method IN ('session', 'api_key', 'step_up')),
    authenticated_at timestamptz NOT NULL,
    nonce text NOT NULL,
    decided_at timestamptz NOT NULL,
    request_id text NOT NULL,
    request_hash text NOT NULL,
    verdict text NOT NULL CHECK (verdict IN ('approve', 'deny', 'request_revision', 'hold')),
    PRIMARY KEY (company_id, decision_id),
    UNIQUE (company_id, nonce),
    FOREIGN KEY (company_id, approval_id) REFERENCES approval (company_id, id)
);

CREATE UNIQUE INDEX human_authorization_proof_terminal_approval_uq
    ON human_authorization_proof (company_id, approval_id)
    WHERE verdict IN ('approve', 'deny', 'request_revision');

ALTER TABLE human_authorization_proof ENABLE ROW LEVEL SECURITY;

ALTER TABLE human_authorization_proof FORCE ROW LEVEL SECURITY;

CREATE POLICY human_authorization_proof_company_isolation ON human_authorization_proof
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE FUNCTION human_authorization_proof_matches_approval()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    approval_status text;
    approval_user_id text;
    approval_decided_at timestamptz;
BEGIN
    SELECT status, decided_by_user_id, decided_at
      INTO approval_status, approval_user_id, approval_decided_at
      FROM approval
     WHERE company_id = NEW.company_id AND id = NEW.approval_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'human authorization proof approval is not visible in this company';
    END IF;

    IF NEW.authenticated_at > NEW.decided_at THEN
        RAISE EXCEPTION 'human authorization authenticated_at must be at or before decided_at';
    END IF;

    IF NEW.verdict = 'hold' AND approval_status <> 'pending' THEN
        RAISE EXCEPTION 'human authorization hold requires a pending approval';
    END IF;

    IF (NEW.verdict = 'approve' AND approval_status <> 'approved')
       OR (NEW.verdict = 'deny' AND approval_status <> 'denied')
       OR (NEW.verdict = 'request_revision' AND approval_status <> 'revision_requested') THEN
        RAISE EXCEPTION 'human authorization proof verdict does not match approval status';
    END IF;

    IF NEW.verdict <> 'hold' AND (approval_user_id IS DISTINCT FROM NEW.user_id
       OR approval_decided_at IS DISTINCT FROM NEW.decided_at) THEN
        RAISE EXCEPTION 'human authorization proof must match approval decision identity and time';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER human_authorization_proof_consistency
BEFORE INSERT ON human_authorization_proof
FOR EACH ROW EXECUTE FUNCTION human_authorization_proof_matches_approval();

CREATE FUNCTION human_authorization_proof_is_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'human authorization proof is immutable';
END;
$$;

CREATE TRIGGER human_authorization_proof_immutable
BEFORE UPDATE OR DELETE ON human_authorization_proof
FOR EACH ROW EXECUTE FUNCTION human_authorization_proof_is_immutable();
