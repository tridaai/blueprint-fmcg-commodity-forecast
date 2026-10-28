# Architecture — Commodity Price Forecasting & Procurement Intelligence Agent

## Shape

```
            ┌────────────┐   generate    ┌──────────────────┐
 seed ─────►│ generator  ├──────────────►│ history rows     │──► store port ──► API reads
            │ (planted,  │               │ (2023..2025)     │    (SQLite /
            │ manifested)│               ├──────────────────┐     Postgres)
            │            ├──────────────►│ sealed truth     │──► truth store ─► graders ONLY
            └────────────┘               │ (2026 Q1)        │
                                          └──────────────────┘
 LangGraph ingest graph:  generate → persist → verify
 Model port: offline default · anthropic / bedrock / nim (fail-closed)
 Forecast engine (R2): reads the store port ONLY — never the truth store
```

## Components

| Component | File | Responsibility |
|---|---|---|
| Catalogue | `catalogue.py` | The seven commodities, their markets and planted generation parameters. Stated constants; the manifest restates the planted structure. |
| Generator | `generator.py` | One deterministic seeded pass over the full timeline; plants seasonality, trend breaks, one tariff shock, one export ban, one weather anomaly, and coffee's sparse reporting. Emits history + sealed future + manifest. |
| Manifest | `models.py` | The contract for everything planted: events with dates/magnitudes, breaks, coverage in operating days, coffee's named gaps, and the history digest. The eval gate grades against it. |
| Store port | `store.py` | Insert-only observations, event registry, manifest. SQLite default; Postgres 16 via `DATABASE_URL` (monthly range partitioning, Timescale-ready). A duplicate observation write is an integrity error, never an overwrite. |
| Truth store | `truth.py` | The sealed future path. Written once by the load path; read by graders and the eval gate. The forecast package is forbidden from importing it — enforced by an AST scan in the tests and the eval gate. |
| Migrations | `migrations.py`, `migrations/{sqlite,postgres}/` | Numbered SQL files + a ledger table; idempotent runner shared by both stores. |
| Ingest workflow | `workflow.py` | LangGraph graph: `generate → persist → verify`. Idempotent at the workflow level (same seed + digest verifies and stops); the store stays insert-only underneath. |
| Model port | `modelport.py` | Language only (Law 1). Offline deterministic default; hosted profiles refuse loudly until configured. |
| API | `api.py` | Read surfaces: `/series`, `/events`, `/manifest`, `/coverage/{commodity}`, `/catalogue`, `/health`, `/readiness`. JSON logs + request id on every response. |
| Forecast package | `forecast/` | The engine lands in R2. Its `__init__` states the isolation law it is graded on. |

## Data design

- An **observation** is (commodity, market, date, driver) → value. Drivers:
  `modal_price` (INR/quintal), `arrivals`, `stock_level`, `import_flow`,
  `export_flow`, `weather_index`.
- Markets operate Mon–Sat; Sundays have no rows. Coffee reports Tue/Fri,
  has a planted three-week disruption window (Aug 2025), and does not
  report `stock_level`, `import_flow` or `export_flow` at all — the
  manifest names those as gaps (Law 7) and the store never zero-fills.
- The **event registry** is data (Law 4): each shock carries kind,
  window, signed magnitude, decay and transmission channel, so later
  rounds can render event contributions instead of absorbing them.
- The **truth** window (2026-01-01 .. 2026-03-31) continues the same
  latent process — same seasonality, trend and noise streams — so R3's
  backtests grade the engine against a future that behaves like the
  past it was built from, including no planted events in the window.

## The pipeline the rounds build

`ingest → compute → explain → scenario → human gate → publish`, as a
LangGraph state machine whose transitions are stored artefacts:

- **compute** (R2–R3): the stated forecast engine — trend/seasonal
  baseline + per-driver contributions — plus rolling-origin backtests
  and the accuracy ledger (Law 2).
- **explain** (R4): sentiment as a scored pack with provenance;
  commentary drafted by the model port around computed figures only.
- **scenario** (R5–R6): declared events and bounded lever forks,
  pinned to their base forecast (Laws 4–5).
- **publish** (R7+): dashboards assembled from artefacts only (Law 6),
  behind a named human approval act.

## Failure posture

- Hosted model profiles fail closed; the offline profile is the only
  silent path and it is deterministic.
- Store writes are insert-only; a bad load fails loudly instead of
  corrupting history.
- Readiness is honest: without a loaded manifest the API reports
  `not_ready`, and unknown series return 404 rather than empty charts.
