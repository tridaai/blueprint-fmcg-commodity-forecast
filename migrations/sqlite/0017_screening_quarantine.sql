-- 0017: screening quarantine records (R17).
-- One record per sentiment item the screening pack
-- flags as instruction-shaped, struck by the pipeline
-- before the item's headline can reach the model port.
-- The record carries the headline verbatim as evidence
-- and the rules that matched, and it is
-- content-addressed and insert-only like every other
-- record in this repo, so it shares the payload-table
-- shape. A quarantined item has no extraction and no
-- other footprint: this table is the whole of it.

CREATE TABLE screening_records (
    record_id  TEXT PRIMARY KEY,
    item_id    TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE INDEX idx_screening_records_item
    ON screening_records (item_id);
