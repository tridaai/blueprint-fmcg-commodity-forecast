-- 0013: operator console (R13).
-- The review queue's rejection acts, the event triage acts
-- and the coverage pre-flight reports. Acts and reports are
-- content-addressed and insert-only like every other artefact
-- in this repo, so they share the payload-table shape. A
-- forecast's review state and an event's triage state are
-- folds of these acts, derived at read, never stored columns.

CREATE TABLE forecast_rejections (
    rejection_id  TEXT PRIMARY KEY,
    forecast_id   TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE INDEX idx_forecast_rejections_forecast
    ON forecast_rejections (forecast_id);

CREATE TABLE event_triage_acts (
    act_id    TEXT PRIMARY KEY,
    event_id  TEXT NOT NULL,
    payload   TEXT NOT NULL
);

CREATE INDEX idx_event_triage_acts_event
    ON event_triage_acts (event_id);

CREATE TABLE preflight_reports (
    report_id  TEXT PRIMARY KEY,
    commodity  TEXT NOT NULL,
    market     TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE INDEX idx_preflight_reports_series
    ON preflight_reports (commodity, market);
