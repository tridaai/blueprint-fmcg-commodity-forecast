-- 0015: desk policy pack, approval chains, annotations (R15).
-- The runtime-versioned desk policy versions, the chain
-- decisions and their acts, the decision log, and the
-- artefact comments and follow-up tasks. Artefacts are
-- content-addressed and insert-only like every other
-- record in this repo, so they share the payload-table
-- shape. A policy version's lifecycle status is a
-- separate column flipped only when its pack-change
-- chain completes, the way a forecast's status is
-- flipped only by its approval act. A decision's state
-- is never a stored column at all: it is a fold over
-- its acts, derived at read.

CREATE TABLE policy_versions (
    version_id  TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE INDEX idx_policy_versions_status
    ON policy_versions (status);

CREATE TABLE decisions (
    decision_id  TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_decisions_target
    ON decisions (kind, target_id);

CREATE TABLE decision_acts (
    act_id       TEXT PRIMARY KEY,
    decision_id  TEXT NOT NULL,
    decided_on   TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_decision_acts_decision
    ON decision_acts (decision_id, decided_on, act_id);

CREATE TABLE decision_logs (
    log_id     TEXT PRIMARY KEY,
    struck_on  TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE TABLE artefact_comments (
    comment_id   TEXT PRIMARY KEY,
    target_kind  TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_artefact_comments_target
    ON artefact_comments (target_kind, target_id);

CREATE TABLE follow_up_tasks (
    task_id      TEXT PRIMARY KEY,
    target_kind  TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_follow_up_tasks_target
    ON follow_up_tasks (target_kind, target_id);

CREATE TABLE task_acts (
    act_id   TEXT PRIMARY KEY,
    task_id  TEXT NOT NULL,
    acted_on TEXT NOT NULL,
    payload  TEXT NOT NULL
);

CREATE INDEX idx_task_acts_task
    ON task_acts (task_id, acted_on, act_id);
