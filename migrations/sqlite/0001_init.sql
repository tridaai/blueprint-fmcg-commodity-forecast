-- 0001: observations, grading truth, event registry, manifest.
-- Observations are INSERT-ONLY: the primary key makes a duplicate
-- write an error, never an overwrite.

CREATE TABLE observations (
    commodity TEXT NOT NULL,
    market    TEXT NOT NULL,
    obs_date  TEXT NOT NULL,
    driver    TEXT NOT NULL,
    value     REAL NOT NULL,
    PRIMARY KEY (commodity, market, obs_date, driver)
);

CREATE INDEX idx_obs_series ON observations (commodity, market, driver, obs_date);

-- The sealed future path. Only fmcg_forecast.truth may touch this
-- table; the forecast package is graded on never reading it.
CREATE TABLE truth_observations (
    commodity TEXT NOT NULL,
    market    TEXT NOT NULL,
    obs_date  TEXT NOT NULL,
    driver    TEXT NOT NULL,
    value     REAL NOT NULL,
    PRIMARY KEY (commodity, market, obs_date, driver)
);

CREATE TABLE events (
    event_id     TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    commodity    TEXT NOT NULL,
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    magnitude    REAL NOT NULL,
    decay_days   INTEGER NOT NULL,
    transmission TEXT NOT NULL,
    description  TEXT NOT NULL
);

CREATE TABLE generation_manifest (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    payload TEXT NOT NULL
);
