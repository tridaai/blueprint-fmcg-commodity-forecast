-- 0018: monitoring run ledger and boards (R18).
-- One run record per completed model-port call: the
-- profile and purpose, hashes of the canonical request
-- and response (never their text), character counts,
-- estimated tokens and the pack-priced cost. One board
-- per strike: the usage fold and the per-source
-- freshness verdicts as-of a stated instant. Both are
-- content-addressed and insert-only like every other
-- artefact in this repo, so they share the
-- payload-table shape.

CREATE TABLE model_runs (
    run_id   TEXT PRIMARY KEY,
    profile  TEXT NOT NULL,
    purpose  TEXT NOT NULL,
    payload  TEXT NOT NULL
);

CREATE INDEX idx_model_runs_profile
    ON model_runs (profile);

CREATE INDEX idx_model_runs_purpose
    ON model_runs (purpose);

CREATE TABLE monitoring_boards (
    board_id  TEXT PRIMARY KEY,
    payload   TEXT NOT NULL
);
