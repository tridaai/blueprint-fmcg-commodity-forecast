"""The data-plane service: registry, load, correct, replay.

The rules live here and in the pack, nowhere else:

- a batch travels under a registered source or it is refused
  whole, with the refusal stored as an artefact — refused is
  a recorded outcome, not an exception in a log;
- every row of an accepted batch is judged by the one
  validation path: clean rows land (with a provenance row
  each), bad rows quarantine with their reasons named, exact
  repeats count as duplicates and land nothing twice;
- a landed key is never overwritten: the same value again is
  a duplicate, a different value quarantines as a conflict,
  and the governed way to change a figure is a correction;
- a correction is an insert-only artefact that supersedes
  the previous correction for its key by link — the chain
  the service derives, never a link a caller forges;
- a backfill replay runs the backtest harness's own seams
  (the engine at an origin, the pack's scoring, the ledger's
  aggregation) for one series, so backfilled origins earn the
  same ledger a catalogue series earns, by the same rules.
"""

from __future__ import annotations

import math
from datetime import date, datetime

from fmcg_forecast.backtest import metrics
from fmcg_forecast.backtest.pack import AccuracyPack, load_accuracy_pack
from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.forecast.engine import ForecastError, run_engine
from fmcg_forecast.ingest.models import (
    BackfillReplay,
    CandidateRow,
    Correction,
    IngestBatch,
    ProvenanceRow,
    QuarantineRecord,
    SourceRegistration,
    batch_content_id,
    candidates_digest,
    correction_content_id,
    natural_key as _natural_key,
    quarantine_content_id,
    replay_content_id,
)
from fmcg_forecast.ingest.pack import (
    CONNECTOR_KINDS,
    IngestPack,
    builtin_registration,
    load_ingest_pack,
)
from fmcg_forecast.ingest.validate import judge_row
from fmcg_forecast.models import DRIVER_UNITS, Observation
from fmcg_forecast.store import Store

_PLACEHOLDER_NAMES = {"", "tbd", "test", "user", "admin", "someone", "n/a", "na"}


def _require_named(value: str, field: str) -> str:
    cleaned = (value or "").strip()
    if cleaned.lower() in _PLACEHOLDER_NAMES or len(cleaned) < 2:
        raise IngestValidationError(
            f"{field} must be a named human — a data-plane act by "
            f"{value!r} cannot be attributed, so it is refused"
        )
    return cleaned


class IngestValidationError(ValueError):
    """A caller-side breach of the stated rules."""


class IngestNotFoundError(LookupError):
    """No artefact with that id."""


class IngestService:
    def __init__(self, store: Store, pack: IngestPack | None = None):
        self.store = store
        self.pack = pack or load_ingest_pack()

    # -- source registry ---------------------------------------------

    def list_sources(self) -> list[SourceRegistration]:
        builtins = [
            builtin_registration(b, self.pack) for b in self.pack.builtin_sources
        ]
        by_id = {s.source_id: s for s in builtins}
        for stored in self.store.list_ingest_sources():
            by_id[stored.source_id] = stored
        return [by_id[k] for k in sorted(by_id)]

    def get_source(self, source_id: str) -> SourceRegistration | None:
        for source in self.list_sources():
            if source.source_id == source_id:
                return source
        return None

    def register_source(
        self,
        source_id: str,
        kind: str,
        display: str,
        owner: str,
        cadence: str,
        drivers: list[str],
        licence_note: str,
        registered_by: str,
        registered_by_role: str,
        registered_at: datetime,
    ) -> SourceRegistration:
        registered_by = _require_named(registered_by, "registered_by")
        _require_named(registered_by_role, "registered_by_role")
        owner = _require_named(owner, "owner")
        source_id = (source_id or "").strip()
        if not source_id or any(c.isspace() for c in source_id):
            raise IngestValidationError(
                "source_id must be a non-empty slug — it is the "
                "name every provenance row will carry"
            )
        if kind not in CONNECTOR_KINDS:
            raise IngestValidationError(
                f"connector kind {kind!r} is not one of "
                f"{', '.join(CONNECTOR_KINDS)}"
            )
        if not drivers:
            raise IngestValidationError("a source must carry at least one driver")
        for driver in drivers:
            if driver not in DRIVER_UNITS:
                raise IngestValidationError(
                    f"driver {driver!r} is not a driver the store carries"
                )
        if not (display or "").strip() or not (cadence or "").strip():
            raise IngestValidationError("display and cadence must be stated")
        if not (licence_note or "").strip():
            raise IngestValidationError(
                "licence_note must be stated — a source without a "
                "licence note is not registered"
            )
        existing = self.get_source(source_id)
        registration = SourceRegistration(
            source_id=source_id,
            kind=kind,
            display=display.strip(),
            owner=owner,
            cadence=cadence.strip(),
            drivers=list(drivers),
            units={d: DRIVER_UNITS[d] for d in drivers},
            licence_note=licence_note.strip(),
            registered_by=registered_by,
            registered_at=registered_at,
            pack_version=self.pack.version,
        )
        if existing is not None:
            if existing.model_dump(mode="json") == registration.model_dump(mode="json"):
                return existing  # the same act, re-entered
            raise IngestValidationError(
                f"source {source_id!r} is already registered with "
                "different terms — a source id names one contract"
            )
        self.store.insert_ingest_source(registration)
        return registration

    # -- batch loading -------------------------------------------------

    def load_batch(
        self,
        source_id: str,
        connector_kind: str,
        rows: list[CandidateRow],
        *,
        as_of: date | None,
        received_by: str,
        received_at: datetime,
    ) -> IngestBatch:
        received_by = _require_named(received_by, "received_by")
        if connector_kind not in CONNECTOR_KINDS:
            raise IngestValidationError(
                f"connector kind {connector_kind!r} is not one of "
                f"{', '.join(CONNECTOR_KINDS)}"
            )
        digest = candidates_digest(rows)
        batch_id = batch_content_id(
            source_id, connector_kind, as_of, digest, self.pack.version
        )
        existing = self.store.get_ingest_batch(batch_id)
        if existing is not None:
            return existing  # the same delivery, replayed: nothing lands twice

        source = self.get_source(source_id)
        refusal = ""
        if source is None:
            refusal = "unknown_source"
        elif as_of is None:
            refusal = "batch_missing_provenance"
        elif not rows:
            refusal = "empty_batch"
        elif source is not None and any(
            row.driver.strip() in source.units
            and row.unit.strip() != source.units[row.driver.strip()]
            for row in rows
        ):
            refusal = "unit_mismatch"

        if refusal:
            batch = IngestBatch(
                batch_id=batch_id,
                source_id=source_id,
                connector_kind=connector_kind,
                received_by=received_by,
                received_at=received_at,
                as_of=as_of,
                pack_version=self.pack.version,
                status="refused",
                refusal_reason=refusal,
                rows_received=len(rows),
                rows_loaded=0,
                rows_quarantined=0,
                rows_duplicate=0,
                content_digest=digest,
            )
            self.store.insert_ingest_batch(batch)
            self.store.insert_ingest_candidates(batch_id, rows)
            return batch

        assert source is not None and as_of is not None
        verdicts: dict[int, list[str]] = {
            row.row_index: judge_row(
                row,
                source=source,
                as_of=as_of,
                pack=self.pack,
                row_provenance_required=connector_kind == "api_push",
            )
            for row in rows
        }
        # In-batch key discipline: one key, one value per batch.
        by_key: dict[tuple, list[CandidateRow]] = {}
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
        # Landed-key discipline: never overwrite a standing fact.
        landed_rows: list[CandidateRow] = []
        for row in rows:
            if verdicts[row.row_index] or row.row_index in duplicates:
                continue
            key = _natural_key(row)
            assert key is not None
            commodity, market, obs_date, driver = key
            standing = self.store.series(commodity, market, driver, obs_date, obs_date)
            if standing:
                if standing[0].value == row.parsed_value():
                    duplicates.add(row.row_index)
                else:
                    verdicts[row.row_index].append("conflicts_with_landed")
                continue
            landed_rows.append(row)
        for reasons in verdicts.values():
            reasons.sort(key=self.pack.quarantine_reasons.index)

        if landed_rows:
            self.store.insert_observations(
                [
                    Observation(
                        commodity=r.commodity.strip(),
                        market=r.market.strip(),
                        obs_date=r.parsed_date(),  # type: ignore[arg-type]
                        driver=r.driver.strip(),  # type: ignore[arg-type]
                        value=r.parsed_value(),  # type: ignore[arg-type]
                    )
                    for r in landed_rows
                ]
            )
            self.store.insert_provenance(
                [
                    ProvenanceRow(
                        commodity=r.commodity.strip(),
                        market=r.market.strip(),
                        obs_date=r.parsed_date(),  # type: ignore[arg-type]
                        driver=r.driver.strip(),
                        source_id=source_id,
                        batch_id=batch_id,
                        row_index=r.row_index,
                    )
                    for r in landed_rows
                ]
            )
        quarantined = [r for r in rows if verdicts[r.row_index]]
        for row in quarantined:
            record = QuarantineRecord(
                quarantine_id="QRN-pending",
                batch_id=batch_id,
                row_index=row.row_index,
                reasons=verdicts[row.row_index],
                candidate=row,
                pack_version=self.pack.version,
            )
            record = record.model_copy(
                update={"quarantine_id": quarantine_content_id(record)}
            )
            self.store.insert_quarantine_record(record)
        batch = IngestBatch(
            batch_id=batch_id,
            source_id=source_id,
            connector_kind=connector_kind,
            received_by=received_by,
            received_at=received_at,
            as_of=as_of,
            pack_version=self.pack.version,
            status="loaded",
            refusal_reason="",
            rows_received=len(rows),
            rows_loaded=len(landed_rows),
            rows_quarantined=len(quarantined),
            rows_duplicate=len(duplicates),
            content_digest=digest,
        )
        self.store.insert_ingest_batch(batch)
        self.store.insert_ingest_candidates(batch_id, rows)
        return batch

    def load_file_drop(
        self,
        source_id: str,
        text: str,
        *,
        as_of: date | None,
        received_by: str,
        received_at: datetime,
        connector_kind: str = "file_drop",
    ) -> IngestBatch:
        from fmcg_forecast.ingest.connectors import parse_file_drop

        return self.load_batch(
            source_id,
            connector_kind,
            parse_file_drop(text),
            as_of=as_of,
            received_by=received_by,
            received_at=received_at,
        )

    def load_api_push(
        self,
        source_id: str,
        payload: list[dict],
        *,
        as_of: date | None,
        received_by: str,
        received_at: datetime,
    ) -> IngestBatch:
        from fmcg_forecast.ingest.connectors import parse_api_push

        return self.load_batch(
            source_id,
            "api_push",
            parse_api_push(payload),
            as_of=as_of,
            received_by=received_by,
            received_at=received_at,
        )

    def get_batch(self, batch_id: str) -> IngestBatch:
        batch = self.store.get_ingest_batch(batch_id)
        if batch is None:
            raise IngestNotFoundError(f"no ingest batch {batch_id}")
        return batch

    def batch_view(self, batch_id: str) -> dict:
        from fmcg_forecast.ingest.verify import verify_batch

        batch = self.get_batch(batch_id)
        view = batch.model_dump(mode="json")
        view["candidates"] = [
            r.model_dump(mode="json")
            for r in self.store.list_ingest_candidates(batch_id)
        ]
        view["quarantine"] = [
            r.model_dump(mode="json")
            for r in self.store.list_quarantine_records(batch_id=batch_id)
        ]
        view["provenance"] = [
            p.model_dump(mode="json")
            for p in self.store.list_provenance(batch_id=batch_id)
        ]
        view["problems"] = verify_batch(self.store, batch)
        return view

    def list_batches(self, source_id: str | None = None) -> list[IngestBatch]:
        return self.store.list_ingest_batches(source_id)

    def list_quarantine(
        self, batch_id: str | None = None
    ) -> list[QuarantineRecord]:
        return self.store.list_quarantine_records(batch_id=batch_id)

    # -- corrections -----------------------------------------------------

    def correct(
        self,
        commodity: str,
        market: str,
        obs_date: date,
        driver: str,
        corrected_value: float,
        *,
        reason: str,
        corrected_by: str,
        corrected_by_role: str,
        corrected_at: datetime,
        corrects_quarantine_id: str | None = None,
    ) -> Correction:
        corrected_by = _require_named(corrected_by, "corrected_by")
        _require_named(corrected_by_role, "corrected_by_role")
        spec = BY_NAME.get(commodity)
        if spec is None or market not in {m.market for m in spec.markets}:
            raise IngestValidationError(
                f"{commodity}/{market} is not a catalogue series"
            )
        if driver not in spec.drivers:
            raise IngestValidationError(
                f"{commodity} does not report {driver} — there is "
                "no figure of that kind to correct"
            )
        rule = next(r for r in self.pack.value_rules if r.driver == driver)
        below = (
            corrected_value <= rule.min_value
            if rule.min_exclusive
            else corrected_value < rule.min_value
        )
        if not math.isfinite(corrected_value) or below or corrected_value > rule.max_value:
            raise IngestValidationError(
                f"corrected value {corrected_value!r} is outside the "
                f"pack's range for {driver} — a correction states a "
                "plausible figure, not a new error"
            )
        if not (reason or "").strip():
            raise IngestValidationError(
                "a correction must state its reason — an unexplained "
                "change to a figure of record is refused"
            )
        landed = self.store.series(commodity, market, driver, obs_date, obs_date)
        if corrects_quarantine_id is not None:
            record = self.store.get_quarantine_record(corrects_quarantine_id)
            if record is None:
                raise IngestNotFoundError(
                    f"no quarantine record {corrects_quarantine_id}"
                )
            key = _natural_key(record.candidate)
            if key != (commodity, market, obs_date, driver):
                raise IngestValidationError(
                    "the named quarantine record is about a different "
                    "fact — a correction answers the row it names"
                )
        elif not landed:
            raise IngestValidationError(
                "nothing to correct: no landed fact stands at that "
                "key and no quarantine record is named — a "
                "correction answers a figure of record"
            )
        chain = self.correction_chain(commodity, market, obs_date, driver)
        correction = Correction(
            correction_id="COR-pending",
            commodity=commodity,
            market=market,
            obs_date=obs_date,
            driver=driver,
            corrected_value=corrected_value,
            reason=reason.strip(),
            corrected_by=corrected_by,
            corrected_by_role=corrected_by_role,
            corrected_at=corrected_at,
            supersedes_correction_id=chain[-1].correction_id if chain else None,
            corrects_quarantine_id=corrects_quarantine_id,
            pack_version=self.pack.version,
        )
        correction = correction.model_copy(
            update={"correction_id": correction_content_id(correction)}
        )
        if self.store.get_correction(correction.correction_id) is None:
            self.store.insert_correction(correction)
        return correction

    def correction_chain(
        self, commodity: str, market: str, obs_date: date, driver: str
    ) -> list[Correction]:
        """The key's corrections in chain order, head link first."""
        records = self.store.list_corrections(commodity, market, obs_date, driver)
        by_supersedes: dict[str | None, Correction] = {}
        for record in records:
            by_supersedes.setdefault(record.supersedes_correction_id, record)
        ordered: list[Correction] = []
        cursor: str | None = None
        seen: set[str] = set()
        while cursor in by_supersedes and by_supersedes[cursor].correction_id not in seen:
            current = by_supersedes[cursor]
            ordered.append(current)
            seen.add(current.correction_id)
            cursor = current.correction_id
        if len(ordered) != len(records):
            # A broken chain (fork or dangling link) never folds
            # silently: fall back to recorded order and let the
            # verifier name the break.
            return sorted(records, key=lambda c: (c.corrected_at, c.correction_id))
        return ordered

    def effective_fact(
        self, commodity: str, market: str, obs_date: date, driver: str
    ) -> dict:
        landed_rows = self.store.series(commodity, market, driver, obs_date, obs_date)
        landed_value = landed_rows[0].value if landed_rows else None
        chain = self.correction_chain(commodity, market, obs_date, driver)
        provenance = self.store.get_provenance(commodity, market, obs_date, driver)
        if chain:
            effective = chain[-1].corrected_value
            state = "corrected" if landed_rows else "quarantine_corrected"
        elif landed_rows:
            effective = landed_value
            state = "landed"
        else:
            effective = None
            state = "absent"
        return {
            "commodity": commodity,
            "market": market,
            "obs_date": obs_date.isoformat(),
            "driver": driver,
            "unit": DRIVER_UNITS.get(driver, ""),
            "landed": bool(landed_rows),
            "landed_value": landed_value,
            "effective_value": effective,
            "state": state,
            "provenance": provenance.model_dump(mode="json") if provenance else None,
            "corrections": [c.model_dump(mode="json") for c in chain],
        }

    # -- backfill replay (F20-DI4) ---------------------------------------

    def replay_backtests(
        self,
        commodity: str,
        market: str,
        origins: list[date],
        *,
        replayed_by: str,
        replayed_at: datetime,
        pack: AccuracyPack | None = None,
    ) -> BackfillReplay:
        replayed_by = _require_named(replayed_by, "replayed_by")
        pack = pack or load_accuracy_pack()
        manifest = self.store.get_manifest()
        if manifest is None:
            raise IngestValidationError(
                "dataset not loaded — a replay runs against the "
                "loaded record, manifest first"
            )
        spec = BY_NAME.get(commodity)
        if spec is None or market not in {m.market for m in spec.markets}:
            raise IngestValidationError(
                f"{commodity}/{market} is not a catalogue series"
            )
        origins = sorted(set(origins))
        max_horizon = max(pack.horizons_days)
        from datetime import timedelta

        realised_all = {
            r.obs_date: float(r.value)
            for r in self.store.series(commodity, market, "modal_price")
        }
        result_ids: list[str] = []
        stored = 0
        already = 0
        skipped: list[dict] = []
        for origin in origins:
            try:
                forecast = run_engine(
                    self.store, manifest, commodity, market, origin,
                    via_backtest=True,
                )
            except ForecastError as exc:
                skipped.append(
                    {"origin": origin.isoformat(), "reason": str(exc)}
                )
                continue
            realised = {
                d: v
                for d, v in realised_all.items()
                if origin < d <= origin + timedelta(days=max_horizon)
            }
            for horizon in pack.horizons_days:
                result = metrics.build_result(forecast, horizon, realised, pack)
                result_ids.append(result.result_id)
                if self.store.get_backtest_result(result.result_id) is not None:
                    already += 1
                    continue
                self.store.insert_backtest_result(result)
                stored += 1
        ledger_ids: list[str] = []
        for horizon in pack.horizons_days:
            results = self.store.list_backtest_results(commodity, market, horizon)
            if not results:
                continue
            record = metrics.aggregate_results(results, pack)
            self.store.save_accuracy_record(record)
            ledger_ids.append(record.record_id)
        replay = BackfillReplay(
            replay_id="RPL-pending",
            commodity=commodity,
            market=market,
            origins=origins,
            accuracy_pack_version=pack.version,
            results_stored=stored,
            results_already_on_record=already,
            skipped=skipped,
            result_ids=sorted(result_ids),
            ledger_record_ids=sorted(ledger_ids),
            replayed_by=replayed_by,
            replayed_at=replayed_at,
        )
        replay = replay.model_copy(
            update={"replay_id": replay_content_id(replay)}
        )
        if self.store.get_backfill_replay(replay.replay_id) is None:
            self.store.insert_backfill_replay(replay)
        return replay

    def get_replay(self, replay_id: str) -> BackfillReplay:
        replay = self.store.get_backfill_replay(replay_id)
        if replay is None:
            raise IngestNotFoundError(f"no backfill replay {replay_id}")
        return replay

    def list_replays(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[BackfillReplay]:
        return self.store.list_backfill_replays(commodity, market)

    # -- verification ------------------------------------------------------

    def verify_batch(self, batch_id: str) -> list[str]:
        from fmcg_forecast.ingest.verify import verify_batch

        return verify_batch(self.store, self.get_batch(batch_id))

    def verify_all(self) -> list[str]:
        from fmcg_forecast.ingest.verify import verify_all

        return verify_all(self.store, self.pack)
