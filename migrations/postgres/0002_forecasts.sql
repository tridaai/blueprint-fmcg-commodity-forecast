-- 0002: forecast artefacts, approval acts, commentaries (R2).
-- A forecast payload is IMMUTABLE once stored: the decomposition a
-- desk approved must be the decomposition on record. The lifecycle
-- status (draft -> official) is a separate column flipped only by a
-- recorded approval act; approvals are insert-only, one per forecast.

CREATE TABLE forecasts (
    forecast_id    TEXT PRIMARY KEY,
    commodity      TEXT NOT NULL,
    market         TEXT NOT NULL,
    as_of          DATE NOT NULL,
    status         TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    payload        TEXT NOT NULL
);

CREATE INDEX idx_forecasts_series ON forecasts (commodity, market, as_of);

CREATE TABLE forecast_approvals (
    approval_id TEXT PRIMARY KEY,
    forecast_id TEXT NOT NULL UNIQUE,
    approver    TEXT NOT NULL,
    role        TEXT NOT NULL,
    decided_on  DATE NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE commentaries (
    forecast_id   TEXT PRIMARY KEY,
    model_profile TEXT NOT NULL,
    payload       TEXT NOT NULL
);
