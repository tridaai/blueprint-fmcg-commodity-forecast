<p align="center">
  <img src="https://trida.ai/logos-rounded/trida-rounded.png" alt="Trida AI" width="96">
</p>

# Blueprint — Commodity Price Forecasting & Procurement Intelligence Agent

A working prototype of the forecasting desk a large food buyer in India actually
needs. The fictional buyer is **Verdanta Foods**, whose trading desk buys wheat,
basmati rice, soybean, groundnut, chili, cumin and coffee at national scale and
today works entirely by phone — no forecasting tool, no sentiment feed, no way to
ask "what happens to soybean if the tariff stays?" and get an answer it can defend.
This blueprint builds that answer as a governed agent: **the forecast is computed
by a stated statistical engine in code, every number carries its driver
contributions and its measured backtest accuracy, and the language model only
explains, structures sentiment and parses scenarios.** It is decision support for
a procurement desk — it never places a trade and never publishes a number a named
human has not approved.

> **Work in progress** — this blueprint is built and passing its automated test and eval gates, but it has not yet finished hands-on local testing, and its companion blog post is not yet published. Expect changes. This notice comes off when both are done.

## The laws (enforced in code, as the rounds land)

1. **Forecasts are computed, never narrated.** A stated statistical engine produces
   every figure: trend/seasonal baseline + per-driver contributions, each a
   recorded line. The LLM explains; it never originates a price.
2. **Every forecast carries its measured accuracy.** A rolling-origin backtest
   scores the engine per commodity and horizon; a degraded forecast is flagged,
   never hidden.
3. **Sentiment is a scored pack with provenance.** Each item is data — source,
   date, commodity, direction, strength — and the index is computed in code.
4. **Shocks are declared events, not silent adjustments.** The event registry
   holds each shock with its stated transmission; a shocked forecast shows the
   event as separate contribution lines.
5. **Scenarios are pinned forks.** A what-if parses into named, bounded levers;
   a scenario is a new run pinned to its base forecast, and becoming the desk's
   official view takes a named human approval act.
6. **Dashboards are assembled from artefacts only.** A prompt becomes a stated
   dashboard spec whose every figure traces to a computed artefact.
7. **Thin data means wide bands + named gaps.** Coffee-class commodities
   forecast with honest intervals and the missing drivers named — never fake
   precision.

## Product lineage

This blueprint follows the shapes of the group's own products — pattern
references, with all code here original to this repo:

- The data layer — mandi prices, arrivals, stocks, trade, weather, policy and
  sentiment in one ontology — is the **Farmioc DataStore** shape
  ([farmioc.com](https://farmioc.com)).
- The forecast + price surface for buyers is the **Farmioc PriceHub** shape,
  extended with contributions, sentiment and scenarios.
- Prompt-to-dashboard is the **AgentSQL** pattern (natural language → governed
  query → dashboard) on a **TridaPad**-shaped surface, from Trida Labs
  ([tridalabs.com](https://tridalabs.com)).

## The stack

Python 3.12 · FastAPI · Pydantic · LangGraph state machines (ingest → compute →
explain → scenario → human gate → publish) · PostgreSQL 16 as the system of
record (monthly range partitioning, Timescale-ready) with SQLite for the
offline dev/test profile · DuckDB for backtesting and analytical scans ·
numpy/pandas + statsmodels primitives under the stated in-repo forecast
engine · model port with an offline deterministic default and fail-closed
hosted profiles (Anthropic, Amazon Bedrock, NVIDIA NIM) · uv with exact pins
and a frozen `constraints.txt` · multi-stage non-root Docker.

## What Round 1 builds

- **A gold-by-construction dataset generator** — one deterministic, seeded pass
  builds ~3 years of daily series (2023-01-01 .. 2025-12-31) for seven
  commodities across 14 market series: modal price, arrivals, stock level,
  import/export flow and a weather index, with planted seasonality on each
  commodity's harvest calendar, two planted trend breaks, one planted tariff
  shock (soybean, Jun 2025), one planted export ban (basmati rice, Sep-Oct
  2024) and a planted chili drought. Everything planted is restated in a
  **generator manifest** the eval gate grades against.
- **The sealed grading truth** — the generator also emits the next 90 days of
  every series. Those rows live behind a separate truth store; the forecast
  package is structurally forbidden from reading them (graded by test + eval).
- **Coffee as the thin-data case** — reports Tue/Fri only, a planted three-week
  reporting disruption in Aug 2025, and no stock or trade-flow drivers at all:
  named gaps in the manifest, never zero-filled rows.
- **The store port** — insert-only observations (a duplicate write is an
  error, not an overwrite), the event registry and the manifest, behind one
  port with SQLite and Postgres dialects; numbered migrations with a runner.
- **The model port** — offline deterministic default; anthropic / bedrock /
  nim profiles that refuse loudly until configured.
- **A LangGraph ingest workflow** — generate → persist → verify as explicit
  graph state; re-loading the same seed verifies and stops.
- **The operations API** — `/series`, `/events`, `/manifest`, `/coverage`,
  `/catalogue`, `/health`, `/readiness`, with structured JSON logs and a
  request id on every response.

## Honest status

- **Built and gated in R1:** the spine, generator + manifest, store port +
  migration 0001 (both dialects), truth store, model port, ingest workflow,
  API reads, demo, harness, eval gate v1 (data integrity: planted shock/ban
  bands, seasonality, coverage completeness, coffee sparsity, truth
  isolation, manifest agreement — all zero-tolerance).
- **Not yet built:** the forecast engine itself (R2), backtesting + the
  accuracy ledger (R3), the sentiment pack (R4), event/scenario handling
  (R5-R6), prompt-to-dashboard (R7), the console (R13). The round map runs
  to R20 and continues past it until the production bar is met.
- **The dataset in this repo is generated in-repo for the blueprint** — gold
  by construction, so the engine can be graded against a known future.
- **Live models are stub-tested until configured:** hosted profiles fail
  closed; nothing here has called a hosted model.
- **Docker image build was not run** in the build sandbox (no daemon); the
  Dockerfile and compose file follow the portfolio's verified pattern and
  are reviewed statically.

## Quickstart

```bash
make install        # uv sync (or: make install-pip)
make demo           # generate the dataset, print the planted checks
make harness        # boot the API and exercise it over HTTP
make test           # pytest
make evals          # the eval gate
make serve          # the operations API on :8000
```

Configuration is environment-only (see `.env.example`): model-port profiles
first, SQLite unless `DATABASE_URL` points at Postgres.

## Layout

```
src/fmcg_forecast/
  catalogue.py     the seven commodities, markets, planted parameters
  generator.py     the gold-by-construction dataset generator
  models.py        observations, events, manifest
  store.py         store port: SQLite / Postgres, insert-only writes
  truth.py         the sealed grading-truth store (forecast may not read)
  migrations.py    numbered migration runner (both dialects)
  workflow.py      LangGraph ingest graph: generate -> persist -> verify
  modelport.py     offline default; anthropic/bedrock/nim fail-closed
  api.py           FastAPI read surfaces
  forecast/        the forecast engine package (lands R2, truth-isolated)
migrations/        0001 SQL, sqlite + postgres dialects
scripts/           demo.py, local_harness.py
evals/             the eval gate
docs/              architecture.md
```

Apache 2.0. A Trida AI blueprint — patterns are the point; the fictional
buyer's data is ours, generated for this repo.
