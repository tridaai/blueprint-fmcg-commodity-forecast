"""The monitoring service: wrap the port, read the
ledger, strike the board.

One service owns the layer's three acts:

- **wrap** a model port in the recording port, bound
  to this store — the act that turns a deployment's
  model calls into ledger entries;
- **read** the run ledger, whole or filtered by
  profile and purpose;
- **strike** a board as-of an instant (now, unless an
  as-of is stated): fold the run records, the ingest
  registry and the batch artefacts through the engine
  and store the board. Striking is idempotent — a
  board whose content address already stands is
  returned as it stands, never re-struck over itself.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fmcg_forecast.ingest.pack import load_ingest_pack
from fmcg_forecast.ingest.service import IngestService
from fmcg_forecast.modelport import ModelPort
from fmcg_forecast.monitoring.engine import build_board
from fmcg_forecast.monitoring.models import MonitoringBoard, RunRecord
from fmcg_forecast.monitoring.pack import MonitoringPack, load_monitoring_pack
from fmcg_forecast.monitoring.port import RecordingModelPort
from fmcg_forecast.store import Store


class MonitoringService:
    def __init__(self, store: Store, pack: MonitoringPack | None = None):
        self.store = store
        self.pack = pack or load_monitoring_pack()

    # -- the recording port -------------------------------------------

    def wrap(self, model: ModelPort) -> RecordingModelPort:
        """Ledger a model port's completed calls in this store."""
        if isinstance(model, RecordingModelPort):
            return model
        return RecordingModelPort(model, self.store, self.pack)

    # -- the run ledger -------------------------------------------------

    def list_runs(
        self,
        profile: str | None = None,
        purpose: str | None = None,
    ) -> list[RunRecord]:
        return self.store.list_model_runs(profile=profile, purpose=purpose)

    # -- boards ---------------------------------------------------------

    def strike_board(self, as_of: datetime | None = None) -> MonitoringBoard:
        """Fold the standing artefacts into a board and store it.

        An as-of in the past is a legitimate read — the
        board folds only what had landed by then — and
        the same store at the same as-of always strikes
        the same board.
        """
        struck_at = as_of or datetime.now(timezone.utc)
        registrations = IngestService(self.store).list_sources()
        board = build_board(
            struck_at=struck_at,
            records=self.store.list_model_runs(),
            registrations=registrations,
            batches=self.store.list_ingest_batches(),
            ingest_pack_version=load_ingest_pack().version,
            pack=self.pack,
        )
        standing = self.store.get_monitoring_board(board.board_id)
        if standing is not None:
            return standing
        self.store.insert_monitoring_board(board)
        return board

    def get_board(self, board_id: str) -> MonitoringBoard | None:
        return self.store.get_monitoring_board(board_id)

    def list_boards(self) -> list[MonitoringBoard]:
        return self.store.list_monitoring_boards()
