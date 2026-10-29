-- 0009: alerting, subscriptions and escalation (R9, F20-AL1/AL2/AL3).
-- A subscription is the desk's own stated watch — desk-entered,
-- content-addressed, superseded by link and never silently edited.
-- A price crossing is a computed artefact: the pinned pair of
-- observations whose stated-window move crossed the alert pack's
-- bar, content-addressed over the pair and the pack version. An
-- alert is derived, never authored: it is content-addressed over
-- the subscription and the triggering artefact it pins, so the
-- same trigger under the same subscription can only ever raise
-- one alert. Alert acts (acknowledge, close) are attributed,
-- insert-only records — an alert's state is the fold of its acts
-- plus the escalation clock, never a stored status. A digest is
-- one subscriber's alerts for one day, content-addressed over the
-- exact alert set it carries. All five tables are insert-only
-- payload tables in the repo's standing idiom.

CREATE TABLE alert_subscriptions (
    subscription_id  TEXT PRIMARY KEY,
    subscriber       TEXT NOT NULL,
    payload          TEXT NOT NULL
);

CREATE INDEX idx_alert_subscriptions_subscriber
    ON alert_subscriptions (subscriber);

CREATE TABLE price_crossings (
    crossing_id  TEXT PRIMARY KEY,
    commodity    TEXT NOT NULL,
    market       TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_price_crossings_series
    ON price_crossings (commodity, market);

CREATE TABLE alerts (
    alert_id         TEXT PRIMARY KEY,
    subscription_id  TEXT NOT NULL,
    commodity        TEXT NOT NULL,
    market           TEXT NOT NULL,
    kind             TEXT NOT NULL,
    payload          TEXT NOT NULL
);

CREATE INDEX idx_alerts_subscription ON alerts (subscription_id);
CREATE INDEX idx_alerts_series ON alerts (commodity, market);

CREATE TABLE alert_acts (
    act_id    TEXT PRIMARY KEY,
    alert_id  TEXT NOT NULL,
    payload   TEXT NOT NULL
);

CREATE INDEX idx_alert_acts_alert ON alert_acts (alert_id);

CREATE TABLE alert_digests (
    digest_id        TEXT PRIMARY KEY,
    subscription_id  TEXT NOT NULL,
    digest_date      TEXT NOT NULL,
    payload          TEXT NOT NULL
);

CREATE INDEX idx_alert_digests_subscription
    ON alert_digests (subscription_id);
