-- 0013_dod_integration_verdict — explicit delegated-integration truth on the authoritative DoD.

ALTER TABLE dod
    ADD COLUMN integration_ok boolean,
    ADD COLUMN integration_note text;
