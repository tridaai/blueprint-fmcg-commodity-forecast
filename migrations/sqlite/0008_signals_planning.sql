-- 0008: buy-window signals + coverage planning (R8, F20-PO2/PO3).
-- A buy signal is one series' computed buy-window call — buy_now /
-- phased / wait — derived in code from the pinned forecast artefact
-- under the versioned signal pack; a requirement plan is the desk's
-- OWN stated need (tonnes by month), desk-entered and labelled so
-- on every surface; a coverage assessment values a plan's uncovered
-- exposure at pinned forecast prices and ranks the pack's stated
-- purchase options. All three are content-addressed payloads,
-- insert-only like every other artefact table: a re-computation
-- that lands on the same content is a no-op, never a duplicate-
-- write error, and a stored payload is never rewritten.

CREATE TABLE buy_signals (
    signal_id    TEXT PRIMARY KEY,
    commodity    TEXT NOT NULL,
    market       TEXT NOT NULL,
    forecast_id  TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_buy_signals_forecast ON buy_signals (forecast_id);
CREATE INDEX idx_buy_signals_series ON buy_signals (commodity, market);

CREATE TABLE requirement_plans (
    plan_id     TEXT PRIMARY KEY,
    commodity   TEXT NOT NULL,
    market      TEXT NOT NULL,
    entered_by  TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE INDEX idx_requirement_plans_series ON requirement_plans (commodity, market);

CREATE TABLE coverage_assessments (
    assessment_id  TEXT PRIMARY KEY,
    plan_id        TEXT NOT NULL,
    forecast_id    TEXT NOT NULL,
    payload        TEXT NOT NULL
);

CREATE INDEX idx_coverage_assessments_plan ON coverage_assessments (plan_id);
