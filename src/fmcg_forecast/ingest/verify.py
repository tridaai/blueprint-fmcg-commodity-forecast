"""Re-performance verification for the production data plane.

The verifier trusts nothing stored. For every batch it
recomputes the content digest from the stored candidate rows,
re-judges every row under the pack version the batch names,
re-applies the batch's key discipline against the store as it
stands — a fact this batch itself landed (its provenance says
so) is not a conflict with itself — and compares the outcome
field for field: the landed set against the provenance rows,
the quarantine set and reasons against the stored records,
the counts against the batch's face. A batch that was refused
whole must show the refusal the same re-judgement reaches,
and must have landed and quarantined nothing.

Corrections are graded as chains: content addresses recompute,
the links form exactly one chain per key (one head, no forks,
no cycles), every corrected value is inside the pack's range,
and a named quarantine record is really about the key it is
said to correct. Registry entries are graded against the
pack: units are the canonical units, drivers are real, and a
pack built-in stored differently from the pack's statement
is a problem.

The zero-tolerance invariants, stated plainly:

- no quarantined row stands in the observations table as a
  fact this batch landed;
- every connector-landed fact has exactly one provenance row
  naming a real batch and source;
- replaying a delivery lands nothing twice — the same
  content is the same artefact;
- a correction never rewrites history: the stored observation
  keeps its landed value, and the effective value is the fold.
"""

from __future__ import annotations

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.ingest.models import (
    IngestBatch,
    SourceRegistration,
    batch_content_id,
    candidates_digest,
    correction_content_id,
    quarantine_content_id,
)
from fmcg_forecast.ingest.models import natural_key as _natural_key
from fmcg_forecast.ingest.pack import IngestPack, builtin_registration, load_ingest_pack
from fmcg_forecast.ingest.validate import judge_row
from fmcg_forecast.models import DRIVER_UNITS
from fmcg_forecast.store import Store


def _registry(store: Store, pack: IngestPack) -> dict[str, SourceRegistration]:
    by_id = {
        b.source_id: builtin_registration(b, pack) for b in pack.builtin_sources
    }
    for stored in store.list_ingest_sources():
        by_id[stored.source_id] = stored
    return by_id


def _rejudge(
    store: Store, batch: IngestBatch, pack: IngestPack, registry: dict
) -> tuple[set[int], dict[int, list[str]], set[int], str]:
    """Re-perform a batch's judging from its stored rows.

    Returns (landed row indexes, quarantine reasons by row,
    duplicate row indexes, expected refusal reason).
    """
    rows = store.list_ingest_candidates(batch.batch_id)
    source = registry.get(batch.source_id)
    if source is None:
        return set(), {}, set(), "unknown_source"
    if batch.as_of is None:
        return set(), {}, set(), "batch_missing_provenance"
    if not rows:
        return set(), {}, set(), "empty_batch"
    if any(
        row.driver.strip() in source.units
        and row.unit.strip() != source.units[row.driver.strip()]
        for row in rows
    ):
        return set(), {}, set(), "unit_mismatch"

    verdicts: dict[int, list[str]] = {
        row.row_index: judge_row(
            row,
            source=source,
            as_of=batch.as_of,
            pack=pack,
            row_provenance_required=batch.connector_kind == "api_push",
        )
        for row in rows
    }
    by_key: dict[tuple, list] = {}
    for row in rows:
        key = _natural_key(row)
        if key is not None:
            by_key.setdefault(key, []).append(row)
    duplicates: set[int] = set()
    for group in by_key.values():
        if len(group) < 2:
            continue
        values = {r.parsed_value() for r in group}
        if len(values) == 1:
            for extra in group[1:]:
                if not verdicts[extra.row_index]:
                    duplicates.add(extra.row_index)
        else:
            for row in group:
                if "duplicate_conflicting" not in verdicts[row.row_index]:
                    verdicts[row.row_index].append("duplicate_conflicting")
    landed: set[int] = set()
    for row in rows:
        if verdicts[row.row_index] or row.row_index in duplicates:
            continue
        key = _natural_key(row)
        assert key is not None
        commodity, market, obs_date, driver = key
        standing = store.series(commodity, market, driver, obs_date, obs_date)
        if standing:
            provenance = store.get_provenance(commodity, market, obs_date, driver)
            if (
                provenance is not None
                and provenance.batch_id == batch.batch_id
                and provenance.row_index == row.row_index
            ):
                landed.add(row.row_index)
            elif standing[0].value == row.parsed_value():
                duplicates.add(row.row_index)
            else:
                verdicts[row.row_index].append("conflicts_with_landed")
            continue
        landed.add(row.row_index)
    for reasons in verdicts.values():
        reasons.sort(key=pack.quarantine_reasons.index)
    quarantine = {i: r for i, r in verdicts.items() if r}
    return landed, quarantine, duplicates, ""


def verify_batch(store: Store, batch: IngestBatch, pack: IngestPack | None = None) -> list[str]:
    pack = pack or load_ingest_pack(batch.pack_version)
    problems: list[str] = []
    rows = store.list_ingest_candidates(batch.batch_id)
    if candidates_digest(rows) != batch.content_digest:
        problems.append(
            "content digest mismatch: the stored candidate rows "
            "do not recompute to the batch's stated digest — the "
            "delivery was altered after it was recorded"
        )
    expected_id = batch_content_id(
        batch.source_id, batch.connector_kind, batch.as_of,
        batch.content_digest, batch.pack_version,
    )
    if expected_id != batch.batch_id:
        problems.append(
            f"content id mismatch: stored {batch.batch_id}, "
            f"recomputed {expected_id}"
        )
    if batch.rows_received != len(rows):
        problems.append(
            f"row count mismatch: the batch states "
            f"{batch.rows_received} received, {len(rows)} candidate "
            "rows are stored"
        )
    registry = _registry(store, pack)
    landed, quarantine, duplicates, refusal = _rejudge(store, batch, pack, registry)

    stored_quarantine = {
        r.row_index: r for r in store.list_quarantine_records(batch_id=batch.batch_id)
    }
    stored_provenance = {
        p.row_index: p for p in store.list_provenance(batch_id=batch.batch_id)
    }

    if batch.status == "refused":
        if not refusal:
            problems.append(
                "refusal mismatch: the batch is stored refused, "
                "but re-judgement accepts the delivery"
            )
        elif batch.refusal_reason != refusal:
            problems.append(
                f"refusal mismatch: the batch states "
                f"{batch.refusal_reason!r}, re-judgement reaches "
                f"{refusal!r}"
            )
        if batch.rows_loaded or batch.rows_quarantined or batch.rows_duplicate:
            problems.append("a refused batch states non-zero outcome counts")
        if stored_quarantine or stored_provenance:
            problems.append(
                "a refused batch landed or quarantined rows — a "
                "whole-batch refusal touches nothing"
            )
        return problems

    if refusal:
        problems.append(
            f"refusal mismatch: the batch is stored loaded, but "
            f"re-judgement refuses it whole ({refusal})"
        )
        return problems
    if batch.rows_loaded != len(landed):
        problems.append(
            f"landed count mismatch: the batch states "
            f"{batch.rows_loaded}, re-judgement lands {len(landed)}"
        )
    if batch.rows_quarantined != len(quarantine):
        problems.append(
            f"quarantine count mismatch: the batch states "
            f"{batch.rows_quarantined}, re-judgement quarantines "
            f"{len(quarantine)}"
        )
    if batch.rows_duplicate != len(duplicates):
        problems.append(
            f"duplicate count mismatch: the batch states "
            f"{batch.rows_duplicate}, re-judgement counts "
            f"{len(duplicates)}"
        )
    if set(stored_provenance) != landed:
        problems.append(
            "provenance mismatch: the provenance rows for this "
            "batch are not exactly the rows re-judgement lands — "
            "a landed fact without provenance, or provenance "
            "without a landing"
        )
    for index, provenance in stored_provenance.items():
        if provenance.source_id != batch.source_id:
            problems.append(
                f"provenance source mismatch on row {index}: "
                f"{provenance.source_id} is not the batch's source "
                f"{batch.source_id}"
            )
    if set(stored_quarantine) != set(quarantine):
        problems.append(
            "quarantine set mismatch: the stored quarantine "
            "records are not exactly the rows re-judgement "
            "quarantines"
        )
    for index, record in stored_quarantine.items():
        if quarantine_content_id(record) != record.quarantine_id:
            problems.append(
                f"quarantine {record.quarantine_id}: content id "
                "mismatch — the record was altered after it was "
                "recorded"
            )
        if record.reasons != quarantine.get(index):
            problems.append(
                f"quarantine {record.quarantine_id}: reasons "
                f"{record.reasons} do not re-perform — "
                f"re-judgement reaches {quarantine.get(index)}"
            )
        candidate = next((r for r in rows if r.row_index == index), None)
        if candidate is None or record.candidate != candidate:
            problems.append(
                f"quarantine {record.quarantine_id}: the pinned "
                "candidate is not the batch's stored row"
            )
    # The leakage invariant, checked against the table itself:
    # a quarantined row's fact may stand only under another
    # batch's provenance or a non-connector path — never under
    # this batch's.
    for index in stored_quarantine:
        row = next((r for r in rows if r.row_index == index), None)
        if row is None:
            continue
        key = _natural_key(row)
        if key is None:
            continue
        provenance = store.get_provenance(*key)
        if provenance is not None and provenance.batch_id == batch.batch_id:
            problems.append(
                f"quarantine leakage: row {index} is quarantined "
                "but its fact stands under this batch's provenance "
                "— a quarantined row reached an engine input"
            )
    return problems


def verify_source(store: Store, registration: SourceRegistration, pack: IngestPack) -> list[str]:
    problems: list[str] = []
    for driver, unit in registration.units.items():
        if DRIVER_UNITS.get(driver) != unit:
            problems.append(
                f"source {registration.source_id}: unit for "
                f"{driver} is {unit!r}, not the canonical "
                f"{DRIVER_UNITS.get(driver)!r}"
            )
    for driver in registration.drivers:
        if driver not in DRIVER_UNITS:
            problems.append(
                f"source {registration.source_id}: driver "
                f"{driver!r} is not a driver the store carries"
            )
    builtin = next(
        (b for b in pack.builtin_sources if b.source_id == registration.source_id),
        None,
    )
    stored = store.get_ingest_source(registration.source_id)
    if builtin is not None and stored is None:
        expected = builtin_registration(builtin, pack)
        if registration.model_dump(mode="json") != expected.model_dump(mode="json"):
            problems.append(
                f"source {registration.source_id}: the registry "
                "view differs from the pack's built-in statement"
            )
    return problems


def verify_corrections(store: Store, pack: IngestPack) -> list[str]:
    problems: list[str] = []
    keys: dict[tuple, list] = {}
    for correction in store.list_corrections():
        key = (
            correction.commodity,
            correction.market,
            correction.obs_date,
            correction.driver,
        )
        keys.setdefault(key, []).append(correction)
        if correction_content_id(correction) != correction.correction_id:
            problems.append(
                f"correction {correction.correction_id}: content "
                "id mismatch — the artefact was altered after it "
                "was recorded"
            )
        spec = BY_NAME.get(correction.commodity)
        if spec is None or correction.market not in {m.market for m in spec.markets}:
            problems.append(
                f"correction {correction.correction_id}: "
                f"{correction.commodity}/{correction.market} is "
                "not a catalogue series"
            )
        rule = next(
            (r for r in pack.value_rules if r.driver == correction.driver), None
        )
        if rule is not None:
            below = (
                correction.corrected_value <= rule.min_value
                if rule.min_exclusive
                else correction.corrected_value < rule.min_value
            )
            if below or correction.corrected_value > rule.max_value:
                problems.append(
                    f"correction {correction.correction_id}: the "
                    f"corrected value is outside the pack's range "
                    f"for {correction.driver}"
                )
        if correction.corrects_quarantine_id is not None:
            record = store.get_quarantine_record(correction.corrects_quarantine_id)
            if record is None:
                problems.append(
                    f"correction {correction.correction_id}: the "
                    f"named quarantine record "
                    f"{correction.corrects_quarantine_id} does not exist"
                )
            elif _natural_key(record.candidate) != (
                correction.commodity,
                correction.market,
                correction.obs_date,
                correction.driver,
            ):
                problems.append(
                    f"correction {correction.correction_id}: the "
                    "named quarantine record is about a different fact"
                )
    for key, chain in keys.items():
        heads = [c for c in chain if c.supersedes_correction_id is None]
        if len(heads) != 1:
            problems.append(
                f"correction chain {key}: {len(heads)} heads — a "
                "chain has exactly one first correction"
            )
        pointed = {
            c.supersedes_correction_id for c in chain if c.supersedes_correction_id
        }
        ids = {c.correction_id for c in chain}
        if not pointed <= ids:
            problems.append(
                f"correction chain {key}: a supersedes link points "
                "outside the chain"
            )
        tails = ids - pointed
        if len(tails) != 1:
            problems.append(
                f"correction chain {key}: {len(tails)} tails — a "
                "fork in the chain means two corrections claim the "
                "same predecessor"
            )
    return problems


def verify_replay(store: Store, replay) -> list[str]:
    """Re-perform a backfill replay's ledger claim from results."""
    from fmcg_forecast.backtest import metrics
    from fmcg_forecast.backtest.pack import load_accuracy_pack
    from fmcg_forecast.ingest.models import replay_content_id

    problems: list[str] = []
    if replay_content_id(replay) != replay.replay_id:
        problems.append(
            f"replay {replay.replay_id}: content id mismatch — "
            "the artefact was altered after it was recorded"
        )
    pack = load_accuracy_pack(replay.accuracy_pack_version)
    stored_ids = []
    for result_id in replay.result_ids:
        if store.get_backtest_result(result_id) is None:
            problems.append(
                f"replay {replay.replay_id}: result {result_id} "
                "is named but does not stand in the store"
            )
        else:
            stored_ids.append(result_id)
    if replay.results_stored + replay.results_already_on_record != len(replay.result_ids):
        problems.append(
            f"replay {replay.replay_id}: stored + already-on-record "
            "does not equal the named result count"
        )
    expected_records = []
    for horizon in pack.horizons_days:
        results = store.list_backtest_results(
            replay.commodity, replay.market, horizon
        )
        if results:
            expected_records.append(metrics.aggregate_results(results, pack).record_id)
    if sorted(expected_records) != replay.ledger_record_ids:
        problems.append(
            f"replay {replay.replay_id}: the ledger records do "
            "not re-perform from the stored results — the series' "
            "ledger is not the aggregation of its results"
        )
    return problems


def verify_all(store: Store, pack: IngestPack | None = None) -> list[str]:
    pack = pack or load_ingest_pack()
    problems: list[str] = []
    registry = _registry(store, pack)
    for registration in registry.values():
        for problem in verify_source(store, registration, pack):
            problems.append(problem)
    for batch in store.list_ingest_batches():
        for problem in verify_batch(store, batch, pack):
            problems.append(f"{batch.batch_id}: {problem}")
    for problem in verify_corrections(store, pack):
        problems.append(problem)
    for replay in store.list_backfill_replays():
        for problem in verify_replay(store, replay):
            problems.append(problem)
    # Provenance integrity, the other direction: every
    # provenance row names a batch that exists and a source
    # that is registered.
    for provenance in store.list_provenance():
        if store.get_ingest_batch(provenance.batch_id) is None:
            problems.append(
                f"provenance for {provenance.commodity}/"
                f"{provenance.market}/{provenance.driver} on "
                f"{provenance.obs_date} names missing batch "
                f"{provenance.batch_id}"
            )
        if provenance.source_id not in registry:
            problems.append(
                f"provenance for {provenance.commodity}/"
                f"{provenance.market}/{provenance.driver} on "
                f"{provenance.obs_date} names unregistered source "
                f"{provenance.source_id}"
            )
    return problems
