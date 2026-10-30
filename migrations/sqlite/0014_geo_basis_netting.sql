-- 0014: geospatial basis and netting (R14).
-- The desk-entered cost lines, the basis readings, the
-- landed comparisons and the market maps. Entries and
-- artefacts are content-addressed and insert-only like
-- every other record in this repo, so they share the
-- payload-table shape. A market's standing cost line is
-- a fold over its entries, derived at read, never a
-- stored column.

CREATE TABLE cost_line_entries (
    entry_id   TEXT PRIMARY KEY,
    commodity  TEXT NOT NULL,
    market     TEXT NOT NULL,
    line       TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE INDEX idx_cost_line_entries_series
    ON cost_line_entries (commodity, market, line);

CREATE TABLE basis_readings (
    reading_id  TEXT PRIMARY KEY,
    commodity   TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE INDEX idx_basis_readings_series
    ON basis_readings (commodity, as_of);

CREATE TABLE landed_comparisons (
    comparison_id  TEXT PRIMARY KEY,
    commodity      TEXT NOT NULL,
    as_of          TEXT NOT NULL,
    payload        TEXT NOT NULL
);

CREATE INDEX idx_landed_comparisons_series
    ON landed_comparisons (commodity, as_of);

CREATE TABLE market_maps (
    map_id     TEXT PRIMARY KEY,
    commodity  TEXT NOT NULL,
    as_of      TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE INDEX idx_market_maps_series
    ON market_maps (commodity, as_of);
