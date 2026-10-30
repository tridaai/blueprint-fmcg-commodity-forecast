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
| Model port | `modelport.py` | Language only (Law 1): commentary drafting, sentiment extraction (`extract_sentiment`, R4), scenario intake (`parse_scenario`, R6) and dashboard intake (`parse_dashboard`, R7). Offline deterministic default (the pack's stated lexicon rule for extraction; the scenario pack's stated grammar for intake); hosted profiles refuse loudly until configured. |
| API | `api.py` | Read surfaces: `/series`, `/events`, `/manifest`, `/coverage/{commodity}`, `/catalogue`, `/health`, `/readiness`; forecast surface (R2): `/forecasts/run`, `/forecasts/{id}` + `/contributions`, `/verify`, `/approve`, `/approval`, `/commentary`; accuracy surface (R3): `/backtests/run`, `/backtests` + `/{id}`, `/accuracy`, `/accuracy/{commodity}/{market}/{horizon}`, `/forecasts/{id}/accuracy`; sentiment surface (R4): `/sentiment/run`, `/sentiment/manifest`, `/sentiment/items` + `/{id}`, `/sentiment/extractions`, `/sentiment/index/{commodity}` + `/{week}`, `/sentiment/verify`, `/forecasts/{id}/sentiment`; event registry (R5): `POST /market-events`, `POST /market-events/seed-historical`, `GET /market-events` + `/{id}` (verdict on its face), `/{id}/verify`, `/{id}/impact`, `/market-events/verify`, `/forecasts/{id}/events` — with the registry wired into API forecast runs; scenario studio (R6): `GET /scenarios/pack`, `POST /scenarios/requests` + `/structured`, `POST /scenarios`, `GET /scenarios` + `/{id}`, `/{id}/diff`, `/{id}/verify`, `POST /{id}/adopt`, `GET /{id}/adoption`, `GET /scenarios/adopted/{commodity}/{market}` — mirrored by the `fmcg-agent-scenarios` CLI; dashboards (R7): `GET /dashboards/pack`, `POST /dashboards/ask`, `GET /dashboards/specs` + `/{id}`, `POST /dashboards/specs/{id}/save`, `GET /dashboards/views`, `POST /dashboards/specs/{id}/assemble`, `GET /dashboards/assemblies/{id}` + `/html` + `/appendix` + `/verify`, `GET /board` + `/board/html` — mirrored by the `fmcg-agent-dashboards` CLI. JSON logs + request id on every response. |
| Forecast package | `forecast/` | The engine (R2). Its `__init__` states the isolation law it is graded on: the package reads observations through the store port only, never the truth store. |
| Forecast engine | `forecast/engine.py` | The stated method: OLS baseline (trend + day-of-year seasonality on log price); baseline residuals regressed on standardised driver inputs (arrivals = z(log arrivals), stock = z(level), trade = z(imports − exports), weather = raw); driver paths projected as last input × persistence^h; sequential (telescoping) attribution in the order arrivals → stock → trade → weather → sentiment → events, so the decomposition sums to the total to the paisa; intervals from rolling 365-observation residual quantiles, AR-propagated and widened by the sparsity multiplier √(calendar/observed days). Refuses an `as_of` inside the sealed window unless invoked via the backtest path; refuses thin history (< 250 observations or < 730 days span) by naming it. R4: accepts a sentiment input (the weekly index carried daily, with the pack's estimation floors riding on it) — estimated like any other driver when the floors are met, a named zero `not_estimable` line (also named in `missing_drivers`) when they are not, and byte-identical pre-R4 behaviour when no input is supplied. R5: event adjustments telescope separately in the order given, each event's own INR path recorded on the events line (`per_event`), and an adjustment's interval widening factor multiplies the band growth on exactly the days its path is non-zero; duplicate events and narrowing factors are refused. R6: driver shifts (`DriverShift`: add / add_clip) are applied to the built input paths before attribution — a shifted line records a `scenario_shift` marker in its input summary — and a sentiment start override replaces the sentiment path's first input (refused when no estimated sentiment line exists); a run with no shifts is byte-identical to the pre-R6 engine. |
| Forecast verifier | `forecast/verify.py` | Re-performs a stored artefact: re-adds every day, checks line paths against day values, horizon summaries against day rows, interval ordering, and the content address. Any tamper fails here. |
| Commentary | `forecast/commentary.py` | Builds the figure set from the artefact and verifies model drafts against it: every decimal figure in a draft must be an artefact figure, or the draft is refused wholesale. |
| Forecast service | `forecast/service.py` | The one workflow every surface shares: idempotent runs (content-addressed artefacts), the draft → official approval act (named approver + role; placeholders and repeat approvals refused), figure-verified commentary drafting, and — R3 — pinning the accuracy ledger's current records onto each run as a self-contained snapshot whose state (measured / degraded / unmeasured) no read path can suppress. |
| Accuracy pack | `backtest/pack.py` | The backtest grid and ledger rules as versioned data: first-of-month origins Jan–Oct 2025, horizons 7/30/90, ledger window of the most recent 6 origins, degraded bar at pooled MAPE > 5.0%. Fail-closed loader; every result and record names the pack version it was built under. |
| Backtest metrics | `backtest/metrics.py` | Pure computation: scored days (only days carrying a realised observation) summed per result — error, absolute error, absolute percentage, band coverage counted exactly — with MAE/MAPE/bias/coverage derived from the rounded sums by stated formulas; the ledger aggregation pools those sums over the window (day-weighted) and stamps `degraded`. |
| Backtest harness | `backtest/harness.py` | Rolling-origin runs through the engine's `via_backtest` seam over observed history (never the truth store), storing content-addressed results idempotently and recording refused origins (coffee, before it can state the method) as named skips; then the ledger rebuild. `score_sealed_boundary` scores a boundary forecast against rows a grader hands in — the eval gate composes the sealed check from it. |
| Backtest verifier | `backtest/verify.py` | Re-performs a stored result from its own scored days and a ledger record from the result artefacts of record; any tamper or drift fails. |
| Sentiment pack | `sentiment/pack.py` | Law 3 as versioned data: the 27-phrase lexicon (phrase, aspect, polarity, weight — read from the buying desk's side of the price), the classification rule (direction ladder with no classified zero, strength formula), the index formula parameters (14-day trailing window, 7-day half-life), the forecast estimation floors (≥200 aligned days, ≥500-day span, ≤28-day recency) and the commentary claim vocabulary. Fail-closed loader; every extraction and index names its pack version. |
| Sentiment corpus | `sentiment/corpus.py`, `sentiment/load.py`, `sentiment/grading.py` | The planted news/policy stream (583 items, deliberately uneven: rich for five commodities, 12 groundnut, 4 coffee) generated deterministically and loaded as a dataset artefact with a digest-stamped manifest. Each item's planted intent is written only to the grading store, whose table mirrors the truth store's isolation pattern: load path, tests and the eval gate may read it; the scoring modules may not — enforced by an AST scan. |
| Extraction | `sentiment/extract.py` | The pack's stated lexicon rule performed offline: word-boundary matching, longest-first, non-overlapping; score = Σ polarity × weight; no matches or a zero score is `unclassified` with the reason — never forced. Wraps readings in the content-addressed `SentimentExtraction` artefact. |
| Sentiment index | `sentiment/index.py` | Pure computation: per commodity × ISO week, the strength-weighted, age-decayed mean direction over the trailing window, with per-aspect sub-indices by the same rule. No classified item in the window → no index artefact at all (absent, never zero). |
| Sentiment verifier | `sentiment/verify.py` | Re-performs every stored extraction (content address + the offline rule over the headline) and every stored index (recompute from the named extractions); and verifies commentary sentiment claims — a claim verifies only when the items it cites exist, belong to the forecast's commodity, are classified, and their strength-weighted aggregate supports the claimed direction word. |
| Sentiment service | `sentiment/service.py` | The pipeline (extract all items idempotently — a stored artefact whose content address disagrees with a fresh computation is a conflict, never an overwrite — then compute every week's index), the reads, stored-artefact verification, and the forecast hand-off: the daily index series restricted to fully-ended weeks (no partial-week leakage) plus the strongest cited items behind the latest index, or `None` when a commodity has no corpus. |
| Event pack | `events/pack.py` | Law 4 as versioned data: the six event classes and the transmission channels each may claim, the estimation-basis vocabulary (announced measure / measured analogue / desk estimate), the path rule parameters (3-day ramp; post-window decay over the event's own stated days), the interval widening factor (×1.25), and the transmission measurement rule with its verification band ([0.5, 1.5] of the claim, sign agreeing). Fail-closed loader; every registered event names its pack version. |
| Event paths | `events/paths.py` | The pack's path rule performed: one declared event → a per-day log-price path (zero before the window, ramped peak inside it, linear decay after it, no decay while open-ended). The registry translates declarations into paths; the engine consumes paths, never declarations. |
| Event measurement | `events/measure.py` | Two distinct reads. Transmission measurement: per market, the ratio of ratios of mean modal price across the event's windows vs the same windows a year earlier (seasonality and trend differenced out), medianed across markets and judged against the claim by the pack's band — verified, unverified, or not_measurable with the reason named. Impact view: the engine's baseline method fitted on pre-window history only, projected through the window and decay tail, each observed day's log effect against that projection. Neither read creates or edits an event. |
| Event verifier | `events/verify.py` | Re-performs a stored declaration: content address, direction vs claimed sign, window order, channel and basis against the pack. A declaration altered after registration fails here even if it still parses. |
| Event service | `events/service.py` | The registry workflow: the analyst act (validation against the pack; placeholder declarers refused, as at the approval gate; content-addressed, idempotent, insert-only), historical seeding from the generator manifest (the planted tariff, ban and drought, claimed magnitudes as planted — the verifier checks them, never fits them), the reads (every event read carries its transmission verdict), and the forecast provider: adjustments for exactly the events whose path touches a run's window, in deterministic order, carrying the pack's widening factor. |
| Scenario pack | `scenarios/pack.py` | Law 5 as versioned data: the lever catalogue with stated bounds (arrivals ±40%, stock ±30 days, trade ±60%, weather ±0.5, sentiment within [−1, 1], extensions ≤ 90 days, hypothetical peaks ±35%), the lever → driver-input conversion rules, and the deterministic grammar stated as data. Fail-closed loader; every request and run names its pack version. |
| Scenario grammar | `scenarios/parse.py` | The pack's stated grammar performed offline (the model port's offline profile; the hosted profile is the same lever schema via structured outputs, fail-closed). Clause by clause, each clause becomes one lever or the parse is refused with the clause named — no silent reinterpretation, no improvisation. |
| Scenario shifts | `scenarios/shifts.py` | Lever values → driver-input shifts, computed in code from the store's history exactly as the pack states (level percents over the log-level standard deviation; stock days over the level standard deviation; trade percents over the mean net flow at the last observation; weather clipped to the index range; sentiment replacing the path start). The recorded conversion carries its basis statistics, so a shift re-performs from the store. |
| Scenario diff | `scenarios/diff.py` | The fork-vs-base difference in integer paise: per driver per day, plus the events difference; the parts re-add to the P50 difference on every day, and the baseline must be identical on both sides or the fork is not a fork. |
| Scenario verifier | `scenarios/verify.py` | Artefact-level re-performance of a stored run: content addresses, both forecasts through the forecast verifier, the diff identity, every shift recomputed from store + pack, every scenario event's path and transmission re-performed. (Not an engine re-run: the accuracy ledger may legitimately move between run and verify.) |
| Scenario service | `scenarios/service.py` | The studio workflow: parse (model port, pack-validated) and structured intake; the pinned fork — the base's event adjustments re-derived from the insert-only registry, scenario events appended in lever order, the engine re-run with the shifts — with the fork living on the run artefact, never in the desk's forecast record; the diff and labelled reads (base / scenario_draft / adopted_scenario / superseded_scenario); and the adoption act — named adopter + role, placeholders refused, supersession by link, state errors on re-adoption. The base artefact is never mutated. |
| Dashboard pack | `dashboards/pack.py` | Law 6 as versioned data: the panel catalogue (forecast / accuracy / sentiment / events / scenario-diff — each with its stated figures and source family), the head rule that picks a series' current forecast, the prompt grammar's vocabulary (commodity aliases, market words, the subjects the catalogue honestly cannot state and the named gap each becomes), and the morning board's section order. Fail-closed loader; every spec, assembly and board names its pack version. |
| Dashboard grammar | `dashboards/parse.py` | The pack's stated grammar performed offline (the model port's `parse_dashboard`). Clause by clause, each clause becomes one catalogue panel or a named gap panel — never dropped, never improvised; a scenario panel exists only when the prompt names the scenario (by id, or as a series' adopted scenario). |
| Dashboard lineage | `dashboards/lineage.py` | The provenance walk (F20-DR3) built from the store alone: figure -> artefact -> input facts -> source + date, terminating at stored facts — observation series (with row count and last date), sentiment items, event declarations, the dataset manifest. |
| Dashboard assembler | `dashboards/assemble.py` | Panel resolution: each spec panel re-resolves to the current head of its artefact family, figures are read from the artefacts, replaced bindings are named as superseded, missing data becomes a rendered gap; and the re-run diff (figure changes, binding supersessions, gap<->rendered flips) is computed against the previous assembly. |
| Dashboard verifier | `dashboards/verify.py` | Whole-dashboard re-performance before a page may exist or be trusted: panels re-resolve and compare figure for figure, the family verifiers re-perform the artefacts behind them, every figure's lineage walk is re-checked against the store (a figure without a complete walk cannot render), and the stored HTML re-renders byte-for-byte. One problem refuses the whole dashboard. |
| Dashboard renderer | `dashboards/render.py` | One static HTML file per dashboard / board — inline CSS, light theme, no JavaScript — a pure function of the stored artefacts: panels with artefact ids on every figure, the diff section, and the provenance appendix walking every figure to its facts. |
| Desk board | `dashboards/board.py` | The morning exception inbox (F20-OW1) computed from artefacts only: degraded series, pending approval / adoption gates, active declared events (verdict on the row's face), forecast changes between a series' two most recent run dates, and named data gaps — ranked by the pack's section order, every row linked to its artefact; a clean series does not appear. The board is itself a content-addressed artefact. |
| Dashboard service | `dashboards/service.py` | The surface workflow every caller shares: ask (model port, pack-validated, ask-time bindings recorded), saved views (names pointing at specs), assembly (re-resolve -> diff -> render -> verify -> store; an identical re-assembly returns the stored artefact), the appendix and verify reads, and the board. Mirrored by the `fmcg-agent-dashboards` CLI. |
| Signal pack | `signals/pack.py` | The buy-window decision as versioned data (R8, F20-PO2): the 30-day horizon, the rise/fall bars against spot, the wide-band bar, the degraded and unmeasured caps, and the decision table stated in order. Fail-closed loader; every signal names its pack version. |
| Signal engine | `signals/engine.py` | The pack's table performed over the pinned head forecast: spot from the store, drift and band from the forecast's own horizon summaries, the accuracy state from its pinned attachment (never re-derived), declared events overlapping the horizon from the registry. Reasoning lines are formatted from the numbers themselves, so re-performance reproduces them exactly. |
| Signal verifier | `signals/verify.py` | Recomputes the whole signal from the pinned forecast + store under the signal's own pack and compares field for field; runs the forecast verifier over the pinned artefact; and checks the hard rules on their own lines — a degraded or unmeasured series carrying buy_now is a problem even if everything else re-performs. |
| Signal service | `signals/service.py` | Compute (idempotent, content-addressed; pins the series' head under the dashboard pack's head rule), reads and re-performance. Mirrored by the `fmcg-agent-signals` CLI and the `/signals` API. |
| Planning pack | `planning/pack.py` | The planner's arithmetic as versioned data (R8, F20-PO3): quintals per tonne, the month price rule (mean daily P50/P90 over covered days, 4dp before valuing; beyond-horizon months named, never valued), FIFO stock allocation, the coverage-days rule, the three option shapes, and the ranking criteria — expected cost, then adverse cost, then name. The pinned signal is context only and never enters the ranking. |
| Planning engine | `planning/engine.py` | Pure computation over one desk-entered plan and one pinned price source (the official head forecast, or an adopted scenario's fork): month pricing, stock allocation, coverage days, paise-exact exposure, option schedules on both price bases, ranking, and the assessment's figures — each figure basis-tagged (desk / market / mixed) with its lineage walk. |
| Planning verifier | `planning/verify.py` | Re-performs the whole assessment and compares field for field (the pinned forecast/fork and the pinned signal are themselves re-performed); re-checks every figure's walk through the R7 lineage verifier; and enforces provenance separation on its own lines — a desk figure's walk is exactly the `desk_entered` terminal fact, a market figure's walk contains none, a mixed figure's carries exactly one. |
| Planning service | `planning/service.py` | The desk's workflow: plan entry as a named act (placeholder enterers refused, one line per calendar month, catalogue series), assessment on the official basis or — only where a scenario stands adopted — the scenario basis, reads and re-performance. Mirrored by the `fmcg-agent-planning` CLI and the `/planning` API. |

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
  R5 adds the governed registry beside it (migration 0005): the R1
  table stays the dataset manifest's record, while `market_events`
  holds declared shocks — analyst acts and manifest-seeded
  historical entries, linked back via `source_record_id` — each
  with its stated transmission (channel, peak log-price effect,
  named basis). A forecast's events line records each applied
  event's own log and INR paths, so the desk reads shocks as
  separate lines, and the transmission verdict (verified /
  unverified / not measurable) is computed from history at read
  time — it is never a stored field that could be edited off.
- The **truth** window (2026-01-01 .. 2026-03-31) continues the same
  latent process — same seasonality, trend and noise streams — so R3's
  backtests grade the engine against a future that behaves like the
  past it was built from, including no planted events in the window.
- A **sentiment item** is (item id, commodity, date, generic source
  label, headline) — data with provenance, insert-only. Its
  **extraction** and the weekly **index** derived from extractions
  are content-addressed artefacts (migration 0004); the item's
  planted intent is a separate grading-side record the product
  tables never join to. Sentiment items and the R5 event registry
  are different artefacts and are never merged: an item is a
  reading of the news stream, an event is a declared shock with a
  stated transmission.
- A **scenario** is three artefacts (migration 0006): the
  **request** (the typed text or structured lever set, parsed into
  bounded levers, content-addressed), the **run** (pinning base
  forecast + request + author, carrying the recorded shifts, any
  scenario-local events, and the full fork forecast — the fork is
  deliberately NOT a row in the forecasts table, so no read of
  the desk's forecast record can mistake it for one), and the
  **adoption** (the named act; lifecycle status lives in a store
  column outside the content hash, supersession is a link on the
  act). Scenario-local events reuse the `MarketEvent` artefact
  with `origin = "scenario"` and are stored only on the run —
  the registry table is never written by the studio.
- A **dashboard** is three artefacts plus the board (migration
  0007): the **spec** (the prompt, the asker, and the stated
  panel set with its ask-time artefact bindings — gap panels
  included, so an unanswerable ask is on the record, not
  dropped), the **view** (a name pointing at a spec; re-running
  the view is a fresh assembly, never a copy of an old page),
  the **assembly** (the panels as resolved against the store at
  assembly time, the computed diff against the previous
  assembly, and the rendered page — stored only after the
  verifier re-performs it whole), and the **desk board** (the
  morning exception rows for a date, content-addressed like
  everything else). Nothing on any of them is computed at read
  time except the board's HTML, which re-renders from the
  stored rows.
- A **signal** is one artefact (migration 0008): the call, the
  pinned forecast it was computed from, every input the pack's
  table read (spot, drift, band, accuracy state and its ledger
  records, overlapping declared events, named missing drivers)
  and the reasoning lines — content-addressed over all of it,
  so the call the desk read is the call that re-performs.
- A **plan** and its **assessment** are two artefacts
  (migration 0008): the plan is the desk's own statement
  (enterer, date, opening stock, tonnes by month) with
  `origin = "desk_entered"` on its face — the one artefact
  family in the repo that is not derived from market data, and
  the lineage vocabulary keeps it that way (its terminal fact
  class is `desk_entered`, distinct from every stored market
  fact). The assessment is content-addressed over the plan, the
  pinned price source (head forecast or adopted fork), the
  pinned signal and the planning pack version: month rows,
  coverage, exposure, ranked options and basis-tagged figures
  with their walks.

## The pipeline the rounds build

`ingest → compute → explain → scenario → human gate → publish`, as a
LangGraph state machine whose transitions are stored artefacts:

- **compute** (R2–R3): the stated forecast engine — trend/seasonal
  baseline + per-driver contributions — landed in R2; rolling-origin
  backtests and the accuracy ledger landed in R3 (Law 2): every
  forecast now pins the ledger's records for its series, degraded
  where the pooled MAPE crosses the pack's stated bar, unmeasured
  (named) where the harness has not covered the series yet.
- **explain** (R4, landed): sentiment as a scored pack with
  provenance — planted corpus, extraction through the model port,
  the weekly index computed in code, the forecast line earned
  against the pack's floors or named not-estimable, and commentary
  drafted by the model port around computed figures only, with
  sentiment directions admitted solely alongside the items whose
  stored extractions support them.
- **scenario** (R5–R6, landed): declared events landed in R5
  (Law 4) — the registry, transmission verification against
  measured history, per-event forecast lines and pack-stated
  interval widening. The studio landed in R6 (Law 5): the
  bounded lever catalogue as a versioned pack, typed what-ifs
  parsed through the model port into shown-back requests with
  named-clause refusals, pinned forks computed by the engine
  with levers applied to driver inputs (identity intact, base
  never mutated), the integer-paise diff, and adoption only by
  a named human act with supersession by link.
- **publish** (R7, landed): dashboards assembled from artefacts
  only (Law 6) — a plain-language prompt compiles through the
  model port to a stated spec (catalogue panels or named gap
  panels), assemblies re-resolve to current artefact heads and
  are verified whole (figures re-performed, every lineage walk
  re-checked to stored facts, HTML byte-exact) before they are
  stored, re-runs carry a computed diff, and the morning desk
  board ranks the day's exceptions — degraded series, pending
  gates, active events, forecast changes, named gaps — each row
  an artefact.
- **decide** (R8, landed): buy-window signals and coverage
  planning (F20-PO2/PO3). Each series' head forecast becomes one
  computed call under the signal pack — reasoning on the
  artefact's face, degraded and unmeasured series capped by
  rule, overlapping shocks named, the whole call re-performed
  by its verifier. The desk's own requirement plans enter as
  desk-entered artefacts with a lineage terminal class of their
  own (never market provenance), and assessments price them
  against the official forecast or an adopted scenario's fork —
  coverage, paise-exact exposure and options ranked only by the
  planning pack's criteria. The board gains a signals section;
  signals deliberately do not join the dashboard panel
  catalogue, which stays closed versioned data. No trade or
  purchase is ever placed — both artefact families state the
  scope line on their face.
- **alert** (R9, landed): alerting, subscriptions and
  escalation (F20-AL1/AL2/AL3). The desk's watch enters as
  desk-entered subscription artefacts, superseded by link.
  A sweep derives alerts from artefacts of record — struck
  signals, declared event windows, price crossings computed
  from the observation series under the alert pack's stated
  window and bar, and the accuracy ledger's degraded and
  coverage-collapsed records (one alert per open episode) —
  each alert content-addressed by (subscription, kind,
  trigger), so a crossing fires exactly once, and each
  carrying the trigger facts that decided its severity on
  its face. Acknowledgement and closure are attributed acts;
  state is a fold of the acts plus the pack's escalation
  windows, derived at read, so an unacknowledged alert's
  climb up the ladder is provable from the record. Daily
  digests carry exactly a subscriber's alerts for their
  date, and the verifier re-performs the whole set against
  a fresh derivation. Alerts stay out of the dashboard
  panel catalogue for the same reason signals did.
- **thin data & intake** (R10, landed): thin-data depth and
  assisted intake (Law 7 depth, F20-DI3). A versioned
  thin-data pack judges each forecast's own series —
  operating-day coverage by window on the catalogue
  reporting pattern with every missing date named,
  per-driver states with last-observed dates, per-horizon
  confidence tiers computed in code from coverage, measured
  accuracy and band width against the series' own realised
  volatility; caps only ever lower a tier, and a tier
  stated anywhere above the earned one is a graded
  contradiction. Assisted intake keeps desk-entered
  figures in pending tables no engine read can see; a
  named checker who is not the enterer confirms (landing
  exactly one observation through the store's insert path,
  both names riding the entry's lineage) or rejects
  (landing nothing); the chain re-performs, and an
  observation standing at a pending or rejected entry's
  key is graded leakage.
- **production data plane** (R11, landed): the connector
  framework, quarantine & correction workflow, and
  historical backfill & replay (F20-DI1/DI2/DI4). Sources
  are registry artefacts under a versioned ingest pack —
  built-ins plus named-act desk registrations, each pinned
  to the catalogue's canonical units, conversion living
  upstream of the port. File drops and API pushes are
  judged by one pure validation path: a clean row lands
  through the store's ordinary insert path and gains a
  provenance row naming its batch and source; a bad row
  quarantines with its exact planted reasons from the
  pack vocabulary; a batch that cannot name its source
  and as-of, or whose units disagree with the registry,
  is refused whole and the refusal is stored as an
  artefact. Batch content addresses exclude the receipt
  stamp, so re-delivery is the same artefact and lands
  nothing twice — replay is idempotent by construction.
  Corrections are insert-only overlays superseding by
  link; the stored observation is never rewritten, and
  the effective fact at a key is the fold of landed value
  and correction chain, a correction answering a
  quarantined row landing nothing. Backfill replay runs
  the engine at named origins through the harness's
  seams, stores results insert-if-absent, and rebuilds
  the series' ledger records in place — the same seam
  the grid used, so a backfilled series' accuracy is
  indistinguishable in kind from a gridded one; origins
  the data cannot support are skipped with the refusal
  named. The verifier re-performs every artefact family
  independently, and ingestion never touches a pending
  intake entry: the maker–checker gate and the connector
  path stay separate doors into the same store.
- **forecast-ops analytics** (R12, landed): the desk's
  track record as one re-performable artefact (F20-AM1).
  A versioned analytics pack states the trend windows and
  epsilon, the signal-outcome rule, the minimum class
  sample and the shock-window rule. Trends pool stored
  backtest results early-against-late by the ledger's own
  pooling, with the ledger record riding beside the trend
  and too-few-origins series named insufficient. Signal
  outcomes are struck at the accuracy grid's origins from
  raw engine runs carrying as-of accuracy attachments
  (earlier origins only — no outcome is judged with
  knowledge its origin lacked) and measured against the
  realised prices that followed; desk signals whose
  horizons have not landed are pending, named, never
  graded. Transmission error aggregates the events
  layer's own seasonally-matched measurements per class,
  with sample counts on the face and small samples named
  anecdote. Shock windows split each series × horizon's
  stored scored days at the event window plus its decay
  tail and re-derive both pools by the backtest metrics'
  own day formulas; an event the grid never graded is
  named, never absent. The report is struck from the
  artefact set at build time: when the set moves on, the
  older report's re-performance names the drift and a
  rebuild strikes the current record — nothing is edited
  in place.

## Failure posture

- Hosted model profiles fail closed; the offline profile is the only
  silent path and it is deterministic.
- Store writes are insert-only; a bad load fails loudly instead of
  corrupting history.
- Readiness is honest: without a loaded manifest the API reports
  `not_ready`, and unknown series return 404 rather than empty charts.
