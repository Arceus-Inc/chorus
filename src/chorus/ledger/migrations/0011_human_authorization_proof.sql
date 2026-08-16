-- 0011_human_authorization_proof — immutable evidence for authenticated terminal gate resolution.
-- A hold is immutable evidence but not a resolution: it leaves the approval pending.
-- 0009 already unique-indexes approval(company_id, id); the composite FK below reuses that index.

CREATE TABLE human_authorization_proof (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    decision_id uuid NOT NULL,
    approval_id uuid NOT NULL,
    user_id text NOT NULL CHECK (btrim(user_id) <> ''),
    method text NOT NULL CHECK (method IN ('session', 'api_key', 'step_up')),
    authenticated_at timestamptz NOT NULL,
    nonce text NOT NULL CHECK (btrim(nonce) <> ''),
    decided_at timestamptz NOT NULL,
    request_id text NOT NULL CHECK (btrim(request_id) <> ''),
    request_hash text NOT NULL CHECK (btrim(request_hash) <> ''),
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

-- Deferred so authenticated resolution can UPDATE approval then INSERT the proof in one
-- transaction (the existing BEFORE INSERT trigger requires the approval to already be
-- terminal). Direct repo status bypass commits without a proof and is refused here.
-- The function runs as the invoker so FORCE RLS still scopes the proof lookup.
CREATE FUNCTION approval_authorization_requires_terminal_proof()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    expected_verdict text;
    proof_count integer;
BEGIN
    expected_verdict := CASE NEW.status
        WHEN 'approved' THEN 'approve'
        WHEN 'denied' THEN 'deny'
        WHEN 'revision_requested' THEN 'request_revision'
    END;

    SELECT COUNT(*) INTO proof_count
      FROM human_authorization_proof
     WHERE company_id = NEW.company_id
       AND approval_id = NEW.id
       AND verdict = expected_verdict
       AND user_id IS NOT DISTINCT FROM NEW.decided_by_user_id
       AND decided_at IS NOT DISTINCT FROM NEW.decided_at;

    IF proof_count <> 1 THEN
        RAISE EXCEPTION 'authorization approval requires a matching terminal proof';
    END IF;

    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER approval_authorization_requires_terminal_proof
AFTER UPDATE OF status ON approval
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
WHEN (
    NEW.gate_kind = 'authorization'
    AND NEW.status IN ('approved', 'denied', 'revision_requested')
)
EXECUTE FUNCTION approval_authorization_requires_terminal_proof();
