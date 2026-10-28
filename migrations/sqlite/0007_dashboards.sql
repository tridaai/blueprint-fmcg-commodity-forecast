-- 0007: prompt-to-dashboard + the morning desk board (R7, Law 6).
-- A dashboard spec is the parse of a desk prompt into a stated
-- panel set; an assembly is one verified rendering of a spec
-- (figures re-performed from artefacts, lineage to stored facts,
-- a diff against the previous assembly, the static HTML). A
-- saved view is a name a spec is re-run by. A desk board is one
-- date's exception inbox. All four are content-addressed
-- payloads, insert-only like every other artefact table: a
-- re-ask, re-assembly or rebuild that lands on the same content
-- is a no-op, never a duplicate-write error, and a stored
-- payload is never rewritten.

CREATE TABLE dashboard_specs (
    spec_id   TEXT PRIMARY KEY,
    prompt    TEXT NOT NULL,
    asked_by  TEXT NOT NULL,
    payload   TEXT NOT NULL
);

CREATE TABLE dashboard_assemblies (
    assembly_id  TEXT PRIMARY KEY,
    spec_id      TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_dashboard_assemblies_spec ON dashboard_assemblies (spec_id, seq);

CREATE TABLE dashboard_views (
    view_id   TEXT PRIMARY KEY,
    spec_id   TEXT NOT NULL,
    name      TEXT NOT NULL,
    payload   TEXT NOT NULL
);

CREATE INDEX idx_dashboard_views_spec ON dashboard_views (spec_id);
CREATE INDEX idx_dashboard_views_name ON dashboard_views (name);

CREATE TABLE desk_boards (
    board_id    TEXT PRIMARY KEY,
    board_date  TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE INDEX idx_desk_boards_date ON desk_boards (board_date);
