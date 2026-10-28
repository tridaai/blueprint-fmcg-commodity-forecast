-- 0005: the governed event registry (R5, Law 4).
-- Market events are declared shocks, stored as content-addressed
-- payloads like the forecast artefacts: the declaration a desk
-- approved must be the declaration on record, so the table is
-- insert-only and a correction lands as a new declaration, never
-- an edit. This registry is distinct from the R1 `events` table,
-- which holds the dataset manifest's planted records; R5 seeds
-- its historical entries FROM those records and links back to
-- them via source_record_id.

CREATE TABLE market_events (
    event_id     TEXT PRIMARY KEY,
    commodity    TEXT NOT NULL,
    event_class  TEXT NOT NULL,
    window_start DATE NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_market_events_commodity ON market_events (commodity, window_start);
