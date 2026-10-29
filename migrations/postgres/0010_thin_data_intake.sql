-- 0010: thin-data assessments and assisted intake (R10).
-- A thin-data assessment is a computed artefact pinned to one
-- forecast: its window evidence, its driver states and its
-- per-horizon confidence tiers, content-addressed and
-- insert-only like every other artefact in this repo.
-- An intake entry is a phoned-in figure recorded by a named
-- assistant: it is not a fact, and it lives in its own table
-- so no engine read can see it while it is pending. A check
-- act is the second person's confirm or reject decision,
-- attributed and insert-only. Only a confirmed entry lands an
-- observation, through the ordinary insert path into the
-- observations table created in 0001.

CREATE TABLE thin_assessments (
    assessment_id  TEXT PRIMARY KEY,
    forecast_id    TEXT NOT NULL,
    commodity      TEXT NOT NULL,
    market         TEXT NOT NULL,
    payload        TEXT NOT NULL
);

CREATE INDEX idx_thin_assessments_forecast
    ON thin_assessments (forecast_id);

CREATE INDEX idx_thin_assessments_series
    ON thin_assessments (commodity, market);

CREATE TABLE intake_entries (
    entry_id   TEXT PRIMARY KEY,
    commodity  TEXT NOT NULL,
    market     TEXT NOT NULL,
    obs_date   TEXT NOT NULL,
    driver     TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE INDEX idx_intake_entries_series
    ON intake_entries (commodity, market);

CREATE TABLE intake_check_acts (
    act_id    TEXT PRIMARY KEY,
    entry_id  TEXT NOT NULL,
    payload   TEXT NOT NULL
);

CREATE INDEX idx_intake_check_acts_entry
    ON intake_check_acts (entry_id);
