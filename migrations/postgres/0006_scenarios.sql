-- 0006: the scenario studio (R6, Law 5).
-- Scenario requests are parses of desk what-ifs into the bounded
-- lever catalogue; scenario runs are pinned forks (base forecast,
-- lever set, the fork artefact itself). Both are content-addressed
-- payloads, insert-only like every other artefact table. A run's
-- lifecycle status (draft -> adopted -> superseded) is state about
-- the artefact, held in its own column and flipped only by a
-- recorded adoption act in scenario_adoptions — the payload itself
-- is never rewritten. The fork forecast lives inside the run's
-- payload: it never enters the forecasts table, so the desk's
-- forecast record carries bases only.

CREATE TABLE scenario_requests (
    request_id   TEXT PRIMARY KEY,
    commodity    TEXT NOT NULL,
    market       TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_scenario_requests_series ON scenario_requests (commodity, market);

CREATE TABLE scenarios (
    scenario_id      TEXT PRIMARY KEY,
    base_forecast_id TEXT NOT NULL,
    commodity        TEXT NOT NULL,
    market         TEXT NOT NULL,
    status           TEXT NOT NULL,
    payload          TEXT NOT NULL
);

CREATE INDEX idx_scenarios_series ON scenarios (commodity, market, status);
CREATE INDEX idx_scenarios_base ON scenarios (base_forecast_id);

CREATE TABLE scenario_adoptions (
    adoption_id  TEXT PRIMARY KEY,
    scenario_id  TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_scenario_adoptions_scenario ON scenario_adoptions (scenario_id);
