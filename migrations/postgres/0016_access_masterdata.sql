-- 0016: access grants, the read audit, master data (R16).
-- Principal grants as chained acts over a name, the
-- access entries every governed read strikes, the
-- audit logs folded from them, and the versioned
-- master data states. Artefacts are content-addressed
-- and insert-only like every other record in this
-- repo, so they share the payload-table shape. A
-- grant's standing and an entry's sequence are folds
-- and counts over the record, never stored columns:
-- the sequence rides in the payload and in its content
-- address, and the index columns only order the fold.

CREATE TABLE principal_grants (
    grant_id  TEXT PRIMARY KEY,
    subject   TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    payload   TEXT NOT NULL
);

CREATE INDEX idx_principal_grants_subject
    ON principal_grants (subject, seq);

CREATE TABLE access_entries (
    entry_id  TEXT PRIMARY KEY,
    seq       INTEGER NOT NULL,
    payload   TEXT NOT NULL
);

CREATE INDEX idx_access_entries_seq
    ON access_entries (seq);

CREATE TABLE access_logs (
    log_id     TEXT PRIMARY KEY,
    struck_on  TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE TABLE master_data_versions (
    version_id  TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    payload     TEXT NOT NULL
);

CREATE INDEX idx_master_data_versions_seq
    ON master_data_versions (seq);
