-- 0004: the sentiment pack's artefacts (R4, Law 3).
-- Items are data with provenance (source, date, commodity, headline)
-- and are insert-only, like observations. Extractions and weekly
-- indices are content-addressed artefacts computed from the items;
-- they are never rewritten either — a re-extraction under a new
-- pack version is a new artefact, and the store keeps one current
-- extraction per item and one current index per (commodity, week).
-- The planted intent behind the corpus is grading-side data: it
-- gets a table here (exactly like the truth store's table in
-- 0001), but it is written and read ONLY through the corpus
-- grading store — the scoring path never imports that module,
-- and the isolation is graded structurally.

CREATE TABLE sentiment_items (
    item_id    TEXT PRIMARY KEY,
    commodity  TEXT NOT NULL,
    item_date  DATE NOT NULL,
    source     TEXT NOT NULL,
    headline   TEXT NOT NULL
);

CREATE INDEX idx_sentiment_items_commodity ON sentiment_items (commodity, item_date);

CREATE TABLE sentiment_extractions (
    extraction_id TEXT PRIMARY KEY,
    item_id       TEXT NOT NULL UNIQUE,
    commodity     TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE sentiment_indices (
    index_id   TEXT PRIMARY KEY,
    commodity  TEXT NOT NULL,
    week_start DATE NOT NULL,
    payload    TEXT NOT NULL,
    UNIQUE (commodity, week_start)
);

CREATE TABLE sentiment_corpus_manifest (
    id      INTEGER PRIMARY KEY,
    payload TEXT NOT NULL
);

-- Grading side only: the planted intent per item. Written by the
-- corpus load path, read by graders and the eval gate through the
-- grading store. No product surface reads this table.
CREATE TABLE sentiment_intent (
    item_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
