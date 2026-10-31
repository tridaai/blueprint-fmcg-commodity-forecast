-- 0019: the integration surface (R19).
-- Scoped integration tokens (the secret itself is
-- never stored, only its SHA-256), token revocation
-- acts, webhook subscriptions (their shared secret is
-- server-side configuration, redacted on every read),
-- webhook delivery attempts (one artefact per attempt,
-- the delivered state a fold over them), board-pack
-- exports (the whole file set on the artefact, each
-- file hashed into its own manifest) and export jobs
-- with their completion acts. All content-addressed
-- and insert-only like every other artefact in this
-- repo, so they share the payload-table shape.

CREATE TABLE integration_tokens (
    token_id  TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    payload   TEXT NOT NULL
);

CREATE TABLE token_acts (
    act_id    TEXT PRIMARY KEY,
    token_id  TEXT NOT NULL,
    payload   TEXT NOT NULL
);

CREATE INDEX idx_token_acts_token
    ON token_acts (token_id);

CREATE TABLE webhook_subscriptions (
    subscription_id  TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    payload          TEXT NOT NULL
);

CREATE TABLE webhook_deliveries (
    delivery_id        TEXT PRIMARY KEY,
    subscription_id    TEXT NOT NULL,
    source_artefact_id TEXT NOT NULL,
    payload            TEXT NOT NULL
);

CREATE INDEX idx_webhook_deliveries_pair
    ON webhook_deliveries (subscription_id, source_artefact_id);

CREATE TABLE board_packs (
    pack_id  TEXT PRIMARY KEY,
    payload  TEXT NOT NULL
);

CREATE TABLE export_jobs (
    job_id   TEXT PRIMARY KEY,
    payload  TEXT NOT NULL
);

CREATE TABLE export_job_acts (
    act_id   TEXT PRIMARY KEY,
    job_id   TEXT NOT NULL,
    payload  TEXT NOT NULL
);

CREATE INDEX idx_export_job_acts_job
    ON export_job_acts (job_id);
