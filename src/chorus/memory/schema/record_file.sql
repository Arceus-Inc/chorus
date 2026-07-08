-- record_file: files_touched fanned out, one row per (run_id, path) — the fingerprint pre-filter
-- (spec 07 §4/§6). Declarative; applied via migrations/.
CREATE TABLE record_file (
    run_id TEXT NOT NULL REFERENCES episodic_record(run_id),
    path   TEXT NOT NULL,
    PRIMARY KEY (run_id, path)
);

CREATE INDEX record_file_path_idx ON record_file(path);
