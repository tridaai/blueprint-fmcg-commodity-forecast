"""Re-performance verification for the monitoring layer.

Every check trusts nothing stored:

- a run record re-performs: its content address
  re-derives, its purpose is in the pack's closed
  vocabulary, its token figures are exactly the pack's
  estimator over its character counts, and its cost is
  exactly the pack's pricing of those tokens under its
  profile — an unrated profile's record must carry
  cost None, and a rated record the exact integer;
- a board re-performs: the engine folds the standing
  run records, registry and batches at the board's
  as-of and the fold must equal the stored board field
  for field — usage rows, totals, freshness verdicts,
  the breach and never-loaded lists. A board struck
  before the artefact set moved on (a source
  registered since, a batch landed since) names that
  drift rather than passing silently; the remedy is a
  newly struck board, never an edit to the old one.

The ledger's privacy rule is structural, not checked
here: a run record has no field that could hold prompt
or response text — hashes and counts are all it stores.
"""

from __future__ import annotations

from fmcg_forecast.ingest.pack import load_ingest_pack
from fmcg_forecast.ingest.service import IngestService
from fmcg_forecast.monitoring.engine import build_board, estimate_tokens, price_call
from fmcg_forecast.monitoring.models import board_content_id, run_content_id
from fmcg_forecast.monitoring.pack import MonitoringPack, load_monitoring_pack
from fmcg_forecast.store import Store


def verify_monitoring(
    store: Store, pack: MonitoringPack | None = None
) -> list[str]:
    pack = pack or load_monitoring_pack()
    problems: list[str] = []

    records = store.list_model_runs()
    for record in records:
        if run_content_id(record) != record.run_id:
            problems.append(
                f"content id mismatch on {record.run_id} — the "
                "run record was altered after it was struck"
            )
        if record.pack_version != pack.version:
            problems.append(
                f"run {record.run_id} was priced under pack "
                f"{record.pack_version}, cannot re-perform under "
                f"{pack.version}"
            )
            continue
        if record.purpose not in pack.purposes:
            problems.append(
                f"run {record.run_id} names purpose "
                f"{record.purpose!r}, outside the pack's closed "
                "vocabulary"
            )
        if record.request_tokens != estimate_tokens(record.request_chars, pack):
            problems.append(
                f"run {record.run_id} states {record.request_tokens} "
                f"request tokens for {record.request_chars} "
                "characters — the pack's estimator gives "
                f"{estimate_tokens(record.request_chars, pack)}"
            )
        if record.response_tokens != estimate_tokens(record.response_chars, pack):
            problems.append(
                f"run {record.run_id} states {record.response_tokens} "
                f"response tokens for {record.response_chars} "
                "characters — the pack's estimator gives "
                f"{estimate_tokens(record.response_chars, pack)}"
            )
        cost, basis = price_call(
            record.profile, record.request_tokens, record.response_tokens, pack
        )
        if record.cost_nano_usd != cost or record.cost_basis != basis:
            problems.append(
                f"run {record.run_id} states cost "
                f"{record.cost_nano_usd} ({record.cost_basis}) — "
                f"the pack prices its tokens at {cost} ({basis})"
            )

    registrations = IngestService(store).list_sources()
    batches = store.list_ingest_batches()
    ingest_pack_version = load_ingest_pack().version
    for board in store.list_monitoring_boards():
        if board_content_id(board) != board.board_id:
            problems.append(
                f"content id mismatch on board {board.board_id} — "
                "the board was altered after it was struck"
            )
        if board.monitoring_pack_version != pack.version:
            problems.append(
                f"board {board.board_id} was struck under "
                f"monitoring pack {board.monitoring_pack_version}, "
                f"cannot re-perform under {pack.version}"
            )
            continue
        rebuilt = build_board(
            struck_at=board.struck_at,
            records=records,
            registrations=registrations,
            batches=batches,
            ingest_pack_version=ingest_pack_version,
            pack=pack,
        )
        if rebuilt.model_dump(mode="json") != board.model_dump(mode="json"):
            problems.append(
                f"board {board.board_id} does not re-perform — "
                "the fold of the standing records, registry and "
                "batches at its as-of differs from the stored "
                "board (the artefact set has moved on since it "
                "was struck, or the board was altered)"
            )
    return problems
