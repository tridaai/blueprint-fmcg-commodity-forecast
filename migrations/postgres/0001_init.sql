-- 0001: observations, grading truth, event registry, manifest.
-- Observations are INSERT-ONLY: the primary key makes a duplicate
-- write an error, never an overwrite. The observation tables are
-- range-partitioned by month on obs_date (Timescale-ready); a
-- default partition keeps every month writable out of the box.

CREATE TABLE observations (
    commodity TEXT NOT NULL,
    market    TEXT NOT NULL,
    obs_date  DATE NOT NULL,
    driver    TEXT NOT NULL,
    value     DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (commodity, market, driver, obs_date)
) PARTITION BY RANGE (obs_date);

CREATE TABLE observations_default PARTITION OF observations DEFAULT;

CREATE INDEX idx_obs_series ON observations (commodity, market, driver, obs_date);

-- The sealed future path. Only fmcg_forecast.truth may touch this
-- table; the forecast package is graded on never reading it.
CREATE TABLE truth_observations (
    commodity TEXT NOT NULL,
    market    TEXT NOT NULL,
    obs_date  DATE NOT NULL,
    driver    TEXT NOT NULL,
    value     DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (commodity, market, driver, obs_date)
) PARTITION BY RANGE (obs_date);

CREATE TABLE truth_observations_default PARTITION OF truth_observations DEFAULT;

CREATE TABLE events (
    event_id     TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    commodity    TEXT NOT NULL,
    start_date   DATE NOT NULL,
    end_date     DATE NOT NULL,
    magnitude    DOUBLE PRECISION NOT NULL,
    decay_days   INTEGER NOT NULL,
    transmission TEXT NOT NULL,
    description  TEXT NOT NULL
);

CREATE TABLE generation_manifest (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    payload TEXT NOT NULL
);
