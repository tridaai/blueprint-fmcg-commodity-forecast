-- 0011: the production data plane (R11, F20-DI1/DI2/DI4).
-- A source registration is the registry artefact a feed
-- arrives under. A batch is one delivery, content-addressed
-- over its source and its exact candidate set, stored loaded
-- or refused whole with the refusal on its face. Candidate
-- rows keep every field's raw text so verdicts re-perform
-- years later. Quarantine records pin the rows that failed,
-- with their reasons, outside the observations table by
-- construction. Provenance binds each connector-landed
-- observation to its source and batch row. Corrections are
-- insert-only overlays that supersede by link, never edits.
-- A backfill replay records the results a replay stored and
-- the ledger records its series earned.

CREATE TABLE ingest_sources (
    source_id  TEXT PRIMARY KEY,
    payload    TEXT NOT NULL
);

CREATE TABLE ingest_batches (
    batch_id    TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    status      TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE INDEX idx_ingest_batches_source
    ON ingest_batches (source_id);

CREATE TABLE ingest_candidates (
    batch_id   TEXT NOT NULL,
    row_index  INTEGER NOT NULL,
    payload    TEXT NOT NULL,
    PRIMARY KEY (batch_id, row_index)
);

CREATE TABLE ingest_quarantine (
    quarantine_id  TEXT PRIMARY KEY,
    batch_id       TEXT NOT NULL,
    row_index      INTEGER NOT NULL,
    payload        TEXT NOT NULL
);

CREATE INDEX idx_ingest_quarantine_batch
    ON ingest_quarantine (batch_id);

CREATE TABLE observation_provenance (
    commodity   TEXT NOT NULL,
    market      TEXT NOT NULL,
    obs_date    TEXT NOT NULL,
    driver      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    row_index   INTEGER NOT NULL,
    PRIMARY KEY (commodity, market, obs_date, driver)
);

CREATE INDEX idx_observation_provenance_batch
    ON observation_provenance (batch_id);

CREATE TABLE ingest_corrections (
    correction_id  TEXT PRIMARY KEY,
    commodity      TEXT NOT NULL,
    market         TEXT NOT NULL,
    obs_date       TEXT NOT NULL,
    driver         TEXT NOT NULL,
    payload        TEXT NOT NULL
);

CREATE INDEX idx_ingest_corrections_key
    ON ingest_corrections (commodity, market, obs_date, driver);

CREATE TABLE backfill_replays (
    replay_id  TEXT PRIMARY KEY,
    commodity  TEXT NOT NULL,
    market     TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE INDEX idx_backfill_replays_series
    ON backfill_replays (commodity, market);
