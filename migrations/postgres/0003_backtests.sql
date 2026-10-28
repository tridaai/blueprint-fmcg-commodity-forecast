-- 0003: backtest results + the accuracy ledger (R3, Law 2).
-- Backtest results are insert-only artefacts, exactly like the
-- forecasts they score: a stored result is never rewritten. The
-- ledger holds ONE current accuracy record per (series, horizon);
-- rebuilding the ledger re-performs the aggregation from the result
-- artefacts of record and replaces the record — the record's own
-- content address changes whenever its inputs do.

CREATE TABLE backtest_results (
    result_id    TEXT PRIMARY KEY,
    commodity    TEXT NOT NULL,
    market       TEXT NOT NULL,
    origin       DATE NOT NULL,
    horizon_days INTEGER NOT NULL,
    forecast_id  TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_backtest_series ON backtest_results (commodity, market, horizon_days, origin);

CREATE TABLE accuracy_records (
    commodity    TEXT NOT NULL,
    market       TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    record_id    TEXT NOT NULL,
    payload      TEXT NOT NULL,
    PRIMARY KEY (commodity, market, horizon_days)
);
