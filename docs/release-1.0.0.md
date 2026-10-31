# Release 1.0.0 — Commodity Price Forecasting & Procurement Intelligence Agent

Version 1.0.0 is the twentieth round of this blueprint and closes
its twenty-round map. It is a release-hardening release: no new
features — the version set everywhere it lives, the full changelog,
a docs sweep that corrects the documentation to what actually
ships, a migration review, and a double full-gate freeze.

## What a deployer gets

A governed forecasting desk for a large food buyer (the fictional
Verdanta Foods), in one service:

- **Computed forecasts, never narrated ones.** A stated statistical
  engine (trend + seasonality baseline, per-driver contributions)
  produces every figure; baseline + contributions + events equals
  the total to the paisa, and a re-performance verifier re-adds
  every stored forecast. The language model only explains,
  structures sentiment and parses scenarios — it never originates
  a price, and commentary figures must resolve to the artefact or
  the draft is refused.
- **Measured accuracy on every forecast.** Rolling-origin
  backtests and a pooled accuracy ledger pin each forecast's state
  — measured, degraded, unmeasured — where no read path can
  suppress it.
- **Sentiment as a scored pack with provenance**, screened by an
  injection quarantine before any item reaches the model port, with
  the corpus's integrity digest re-performed by the verifier.
- **Declared shocks, pinned scenarios, human gates.** Events are
  registry artefacts with measured transmissions; scenarios are
  forks that never mutate their base; a forecast becomes the
  desk's official view only through a named approval act, under
  approval chains the desk's own policy pack states as data.
- **Dashboards from artefacts only**, every figure walked to its
  stored facts; buy-window signals and coverage planning with
  paise-exact exposure; alerting with an escalation fold; a
  production data plane with quarantine and correction overlays;
  governed access with existence-hiding reads and a gapless audit
  log; a run ledger pricing every model call at stated reference
  rates (unrated profiles read None, never zero); and an
  integration surface of scoped tokens, signed webhooks and
  checksum-manifested board-pack exports.

## How to run it

```bash
make install        # uv sync (or: make install-pip)
make demo           # generate the dataset, walk the desk end to end
make harness        # boot the API and exercise it over HTTP
make test           # pytest
make evals          # the eval gate
make serve          # the operations API on :8000
```

Configuration is environment-only (see `.env.example`): SQLite by
default, PostgreSQL 16 when `DATABASE_URL` points at it; the
offline model profile by default, hosted profiles (Anthropic,
Amazon Bedrock, NVIDIA NIM) fail closed until configured.

## Freeze figures (release tree)

The complete gate set ran twice — Freeze A on the tree before this
document was committed, Freeze B on the exact 1.0.0 tree — with
identical figures:

- **pytest: 396 passed, 0 failed** — with `FMCG_TEST_DATABASE_URL`
  live on a fresh Postgres database, so the in-suite parity leg
  ran and the cross-profile gap is 0.
- **Eval gate: PASS — 107 zero-tolerance counters, all at zero.**
- **Demo: exit 0.**
- **Local harness: 120 PASS / 0 FAIL.**
- **Production smoke: PASS** — the Postgres profile serves end to
  end, with every round's parity walk at gap 0.

## Migration review

Both dialect sets were re-performed against the repo's own
runner: 19 files per dialect, identical names, gapless numbering
0001–0019, zero semicolon-discipline violations (semicolons only
at statement ends and inside the full-line comments the runner
strips), clean application in order on fresh SQLite and Postgres
databases, and an idempotent re-run applying 0. Verdict: CLEAN.
Thirteen of the nineteen files are byte-identical across dialects;
the other six carry dialect-specific DDL by design (partitioning
and types).

## Honest limits

- **No hosted model has ever been called.** Hosted profiles are
  stub-tested and fail closed; the offline deterministic profile
  is the only path ever exercised end to end. Live verification
  needs a configured key.
- **Pinned but unused:** pandas, statsmodels and DuckDB are in the
  pinned manifest and imported nowhere — the numerics are numpy
  and the scans run through the store port. They stay pinned so
  the frozen set stays stable.
- **Insert-only is a service discipline, not a storage
  guarantee:** forged artefacts are detected by re-performance,
  not prevented.
- **The dataset is generated in-repo**, gold by construction, so
  the engine can be graded against a known future; a deployment
  feeds real mandi data through the R11 data plane.
- **The Docker image build was not run** (no daemon in the build
  sandbox); the Dockerfile and compose file follow the portfolio's
  verified pattern and are reviewed statically.
- Screening (R17) covers sentiment item headlines; desk-entered
  request text is bounded by the scenario/dashboard grammars
  instead, and obfuscation past the pack's stated normalisation
  (e.g. leetspeak) is a stated, pinned limit.

## What a deployment still has to do

- Configure a hosted model profile (key + profile choice) and run
  a live verification pass before trusting hosted drafting.
- Wire real data feeds into the ingest registry (file drops and
  API pushes are the shipped doors) and re-run backfill replay so
  real series earn their accuracy ledgers.
- Put authentication in front of the API: named principals in this
  repo are stated identity claims judged by the access pack, not
  an identity provider — SSO or signed tokens compose at the edge.
- Build and run the Docker image in the target environment and
  point the webhook delivery port at the real receivers.

## Why the work-in-progress notice stays

The README keeps its work-in-progress blockquote at 1.0.0:
hands-on developer testing and the companion blog post are still
outstanding. The notice comes off when both are done — the code
freeze does not depend on them, and neither is claimed here.
