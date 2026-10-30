-- 0012: forecast-ops analytics reports (R12).
-- An ops report is a computed artefact: the desk's track
-- record (accuracy trends, signal outcomes, transmission
-- error by event class, shock-window grades) computed in
-- code from the artefacts of record and re-performed by
-- the verifier. Content-addressed and insert-only like
-- every other artefact in this repo, so it shares their
-- payload-table shape.

CREATE TABLE ops_reports (
    report_id               TEXT PRIMARY KEY,
    analytics_pack_version  TEXT NOT NULL,
    payload                 TEXT NOT NULL
);

CREATE INDEX idx_ops_reports_pack
    ON ops_reports (analytics_pack_version);
